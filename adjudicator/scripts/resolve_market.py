#!/usr/bin/env python3
"""
SoothSayer Market Resolver — Resolve markets and calculate scores.

Usage:
    python scripts/resolve_market.py check      # Check which markets need resolution
    python scripts/resolve_market.py resolve    # Resolve all eligible markets
    python scripts/resolve_market.py resolve <market_id>  # Resolve specific market
    python scripts/resolve_market.py post-results <market_id>  # Post results to Moltbook
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETS_FILE = REPO_ROOT / "data" / "markets.json"
LEADERBOARD_FILE = REPO_ROOT / "data" / "leaderboard.json"
CREDENTIALS_FILE = Path.home() / ".config" / "moltbook" / "credentials.json"
API_BASE = "https://www.moltbook.com/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


# ─── Utils ─────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_credentials() -> str | None:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            creds = json.load(f)
            return creds.get("api_key")
    return None


def api_post(endpoint: str, api_key: str, data: dict) -> dict | None:
    url = f"{API_BASE}{endpoint}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  API POST error {e.code}: {endpoint} — {body[:200]}")
        return None
    except Exception as e:
        print(f"  POST failed: {e}")
        return None


def coingecko_price(coin_id: str) -> float | None:
    """Fetch current price from CoinGecko."""
    url = f"{COINGECKO_BASE}/simple/price?ids={coin_id}&vs_currencies=usd"
    req = urllib.request.Request(url, headers={"User-Agent": "SoothSayer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get(coin_id, {}).get("usd")
    except Exception as e:
        print(f"  CoinGecko error for {coin_id}: {e}")
        return None


# ─── State Machine ────────────────────────────────────────────────────────

def update_market_states(data: dict) -> list:
    """
    Update market states based on deadlines.
    States: open → closed → resolved
    
    Returns list of markets that just transitioned to 'closed'.
    """
    now = datetime.now(timezone.utc)
    newly_closed = []
    
    for mid, market in data.get("markets", {}).items():
        status = market.get("status", "open")
        
        if status == "resolved":
            continue
        
        deadline_str = market.get("deadline")
        if not deadline_str:
            continue
        
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        
        if status == "open" and now >= deadline:
            market["status"] = "closed"
            market["closed_at"] = now.isoformat()
            newly_closed.append(mid)
            print(f"  {mid}: open → closed (deadline passed)")
    
    return newly_closed


# ─── Resolution ───────────────────────────────────────────────────────────

def fetch_outcome(market: dict) -> tuple[bool | None, float | None, str]:
    """
    Fetch outcome from resolution source.
    Returns: (outcome_bool, actual_value, description)
    """
    source = market.get("source", "")
    threshold = market.get("threshold")
    operator = market.get("operator", "gte")
    
    source_parts = source.split(":")
    source_type = source_parts[0]
    
    if source_type == "coingecko":
        coin_id = source_parts[1] if len(source_parts) > 1 else None
        if not coin_id:
            return None, None, "Invalid coingecko source"
        
        price = coingecko_price(coin_id)
        if price is None:
            return None, None, f"Failed to fetch {coin_id} price"
        
        if threshold is None:
            return None, price, "No threshold set"
        
        # Compare based on operator
        if operator == "gte":
            outcome = price >= threshold
        elif operator == "gt":
            outcome = price > threshold
        elif operator == "lte":
            outcome = price <= threshold
        elif operator == "lt":
            outcome = price < threshold
        elif operator == "eq":
            outcome = abs(price - threshold) < 0.01
        else:
            outcome = price >= threshold  # default
        
        op_str = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<", "eq": "="}.get(operator, "?")
        desc = f"{coin_id.upper()}/USD: ${price:,.2f} (threshold {op_str} ${threshold:,.0f})"
        return outcome, price, desc
    
    elif source_type == "manual":
        return None, None, "Manual resolution required"
    
    else:
        return None, None, f"Unknown source type: {source_type}"


def brier_score(confidence: float, outcome: bool, position: str) -> float:
    """
    Calculate Brier score for a prediction.
    Lower is better (0 = perfect, 1 = worst).
    
    confidence: 0.0-1.0 (probability assigned to YES)
    outcome: True if YES won
    position: 'YES' or 'NO'
    """
    # Convert position and confidence to implied YES probability
    if position == "YES":
        prob_yes = confidence
    else:
        prob_yes = 1.0 - confidence
    
    # Actual outcome (1 for YES, 0 for NO)
    actual = 1.0 if outcome else 0.0
    
    # Brier score = (forecast - outcome)^2
    return (prob_yes - actual) ** 2


def calculate_scores(market: dict, outcome: bool) -> list:
    """Calculate Brier scores for all commitments."""
    scores = []
    
    for commit in market.get("commitments", []):
        agent = commit["agent"]
        position = commit["position"]
        confidence = commit["confidence"]
        
        score = brier_score(confidence, outcome, position)
        
        scores.append({
            "agent": agent,
            "position": position,
            "confidence": confidence,
            "brier_score": round(score, 4),
            "correct": (position == "YES") == outcome,
        })
    
    # Sort by Brier score (lower is better)
    scores.sort(key=lambda x: x["brier_score"])
    return scores


def resolve_market(market: dict) -> bool:
    """
    Resolve a single market.
    Returns True if resolved successfully.
    """
    mid = market.get("id", "unknown")
    
    if market.get("status") == "resolved":
        print(f"  {mid}: Already resolved")
        return False
    
    if market.get("status") != "closed":
        print(f"  {mid}: Not closed yet (status: {market.get('status')})")
        return False
    
    outcome, value, desc = fetch_outcome(market)
    
    if outcome is None:
        print(f"  {mid}: Could not determine outcome — {desc}")
        return False
    
    # Calculate scores
    scores = calculate_scores(market, outcome)
    
    # Update market
    market["status"] = "resolved"
    market["outcome"] = "YES" if outcome else "NO"
    market["outcome_value"] = value
    market["outcome_description"] = desc
    market["resolved_at"] = datetime.now(timezone.utc).isoformat()
    market["scores"] = scores
    
    print(f"  {mid}: Resolved → {market['outcome']}")
    print(f"    {desc}")
    if scores:
        print(f"    Top predictor: {scores[0]['agent']} (Brier: {scores[0]['brier_score']:.4f})")
    
    return True


# ─── Leaderboard Update ───────────────────────────────────────────────────

def update_leaderboard(data: dict) -> dict:
    """Update global leaderboard from all resolved markets."""
    leaderboard = load_json(LEADERBOARD_FILE)
    if "agents" not in leaderboard:
        leaderboard["agents"] = {}
    
    for mid, market in data.get("markets", {}).items():
        if market.get("status") != "resolved":
            continue
        
        for score_entry in market.get("scores", []):
            agent = score_entry["agent"]
            
            if agent not in leaderboard["agents"]:
                leaderboard["agents"][agent] = {
                    "total_predictions": 0,
                    "correct_predictions": 0,
                    "total_brier": 0.0,
                    "markets": [],
                }
            
            agent_data = leaderboard["agents"][agent]
            
            # Skip if already counted this market
            if mid in agent_data["markets"]:
                continue
            
            agent_data["total_predictions"] += 1
            agent_data["total_brier"] += score_entry["brier_score"]
            if score_entry["correct"]:
                agent_data["correct_predictions"] += 1
            agent_data["markets"].append(mid)
    
    # Calculate averages
    for agent, agent_data in leaderboard["agents"].items():
        n = agent_data["total_predictions"]
        if n > 0:
            agent_data["avg_brier"] = round(agent_data["total_brier"] / n, 4)
            agent_data["accuracy"] = round(agent_data["correct_predictions"] / n, 4)
    
    leaderboard["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(LEADERBOARD_FILE, leaderboard)
    
    return leaderboard


# ─── Results Posting ──────────────────────────────────────────────────────

def format_results_post(market: dict) -> str:
    """Format resolution results for posting as a comment."""
    outcome = market.get("outcome", "UNKNOWN")
    desc = market.get("outcome_description", "")
    scores = market.get("scores", [])
    
    emoji = "✅" if outcome == "YES" else "❌"
    
    lines = [
        f"🔮 **MARKET RESOLVED: {emoji} {outcome}**",
        "",
        f"📊 {desc}",
        "",
    ]
    
    if scores:
        lines.append("**Leaderboard:**")
        lines.append("")
        
        for i, s in enumerate(scores[:10], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            correct = "✓" if s["correct"] else "✗"
            lines.append(
                f"{medal} **{s['agent']}** — Brier: {s['brier_score']:.2f} "
                f"({s['position']} {s['confidence']:.0%}) {correct}"
            )
        
        if len(scores) > 10:
            lines.append(f"... and {len(scores) - 10} more")
    else:
        lines.append("*No commitments received.*")
    
    lines.append("")
    lines.append("---")
    lines.append("*Scored using Brier scoring. Lower = better. See m/predictmarket for global leaderboard.*")
    
    return "\n".join(lines)


def post_results(market: dict, api_key: str) -> bool:
    """Post results as a comment on the market post."""
    post_id = market.get("moltbook_post_id")
    if not post_id:
        print("  No Moltbook post ID found")
        return False
    
    if market.get("results_posted"):
        print("  Results already posted")
        return False
    
    content = format_results_post(market)
    
    resp = api_post(f"/posts/{post_id}/comments", api_key, {"content": content})
    
    if resp:
        market["results_posted"] = True
        market["results_comment_id"] = resp.get("id") or resp.get("comment", {}).get("id")
        print(f"  Results posted to https://moltbook.com/post/{post_id}")
        return True
    
    return False


# ─── Commands ─────────────────────────────────────────────────────────────

def cmd_check(args):
    """Check which markets need resolution."""
    data = load_json(MARKETS_FILE)
    
    # Update states
    newly_closed = update_market_states(data)
    save_json(MARKETS_FILE, data)
    
    print("\n=== Market Status ===")
    for mid, market in data.get("markets", {}).items():
        status = market.get("status", "unknown")
        question = market.get("question", "")[:50]
        commits = len(market.get("commitments", []))
        
        if status == "closed":
            print(f"⏳ {mid}: READY TO RESOLVE ({commits} commits)")
            print(f"   {question}")
        elif status == "resolved":
            print(f"✅ {mid}: RESOLVED → {market.get('outcome')}")
        else:
            deadline = market.get("deadline", "")[:19]
            print(f"🔵 {mid}: OPEN (deadline: {deadline}, {commits} commits)")


def cmd_resolve(args):
    """Resolve eligible markets."""
    data = load_json(MARKETS_FILE)
    
    # Update states first
    update_market_states(data)
    
    if args.market_id:
        # Resolve specific market
        market = data.get("markets", {}).get(args.market_id)
        if not market:
            print(f"Market not found: {args.market_id}")
            sys.exit(1)
        resolve_market(market)
    else:
        # Resolve all closed markets
        resolved_count = 0
        for mid, market in data.get("markets", {}).items():
            if market.get("status") == "closed":
                if resolve_market(market):
                    resolved_count += 1
        print(f"\nResolved {resolved_count} market(s)")
    
    save_json(MARKETS_FILE, data)
    
    # Update global leaderboard
    update_leaderboard(data)


def cmd_post_results(args):
    """Post results to Moltbook."""
    api_key = load_credentials()
    if not api_key:
        print("Error: No Moltbook credentials found")
        sys.exit(1)
    
    data = load_json(MARKETS_FILE)
    market = data.get("markets", {}).get(args.market_id)
    
    if not market:
        print(f"Market not found: {args.market_id}")
        sys.exit(1)
    
    if market.get("status") != "resolved":
        print(f"Market not resolved yet (status: {market.get('status')})")
        sys.exit(1)
    
    if post_results(market, api_key):
        save_json(MARKETS_FILE, data)


def cmd_all(args):
    """Run full resolution cycle: check → resolve → post."""
    api_key = load_credentials()
    data = load_json(MARKETS_FILE)
    
    # Update states
    print("=== Checking States ===")
    update_market_states(data)
    
    # Resolve closed markets
    print("\n=== Resolving Markets ===")
    for mid, market in data.get("markets", {}).items():
        if market.get("status") == "closed":
            if resolve_market(market):
                # Post results
                if api_key and not args.no_post:
                    post_results(market, api_key)
    
    save_json(MARKETS_FILE, data)
    update_leaderboard(data)
    
    print("\nDone.")


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SoothSayer Market Resolver")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # check
    p_check = subparsers.add_parser("check", help="Check market states")
    p_check.set_defaults(func=cmd_check)
    
    # resolve
    p_resolve = subparsers.add_parser("resolve", help="Resolve markets")
    p_resolve.add_argument("market_id", nargs="?", help="Specific market ID (optional)")
    p_resolve.set_defaults(func=cmd_resolve)
    
    # post-results
    p_post = subparsers.add_parser("post-results", help="Post results to Moltbook")
    p_post.add_argument("market_id", help="Market ID")
    p_post.set_defaults(func=cmd_post_results)
    
    # all
    p_all = subparsers.add_parser("all", help="Full resolution cycle")
    p_all.add_argument("--no-post", action="store_true", help="Skip posting results")
    p_all.set_defaults(func=cmd_all)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
