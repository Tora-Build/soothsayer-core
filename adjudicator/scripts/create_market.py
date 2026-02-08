#!/usr/bin/env python3
"""
SoothSayer Market Creator — Create structured prediction markets on Moltbook.

Usage:
    python scripts/create_market.py create --question "Will ETH trade above $2,800?" --deadline 2026-02-12T00:00:00Z --source coingecko:ethereum --threshold 2800 --operator gte
    python scripts/create_market.py list
    python scripts/create_market.py show <market_id>
"""

import argparse
import json
import os
import sys
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETS_FILE = REPO_ROOT / "data" / "markets.json"
CREDENTIALS_FILE = Path.home() / ".config" / "moltbook" / "credentials.json"
API_BASE = "https://www.moltbook.com/api/v1"
SUBMOLT = "predictmarket"  # Default submolt for markets

# Resolution source types
SOURCES = {
    "coingecko": {
        "description": "CoinGecko price API",
        "format": "coingecko:<coin_id>",
        "example": "coingecko:ethereum",
    },
    "manual": {
        "description": "Manual resolution by SoothSayer",
        "format": "manual",
        "example": "manual",
    },
}

# Operators for threshold comparison
OPERATORS = {
    "gte": "≥",
    "gt": ">",
    "lte": "≤",
    "lt": "<",
    "eq": "=",
}


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


def api_get(endpoint: str, api_key: str) -> dict | None:
    url = f"{API_BASE}{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  API error {e.code}: {endpoint}")
        return None
    except Exception as e:
        print(f"  Request failed: {e}")
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


def make_market_id(question: str, deadline: str) -> str:
    h = hashlib.sha256(f"{question}:{deadline}".encode()).hexdigest()[:8]
    return f"market_{h}"


# ─── Market Post Formatting ───────────────────────────────────────────────

def format_market_post(question: str, deadline: str, source: str, threshold: float | None, operator: str | None) -> str:
    """Format a structured market post for Moltbook."""
    
    deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    deadline_str = deadline_dt.strftime("%b %d, %Y at %H:%M UTC")
    
    # Parse resolution source
    source_parts = source.split(":")
    source_type = source_parts[0]
    
    if source_type == "coingecko" and threshold and operator:
        coin = source_parts[1] if len(source_parts) > 1 else "unknown"
        op_symbol = OPERATORS.get(operator, operator)
        resolution_desc = f"CoinGecko {coin.upper()}/USD {op_symbol} ${threshold:,.0f}"
    elif source_type == "manual":
        resolution_desc = "Manual resolution by SoothSayer"
    else:
        resolution_desc = source
    
    post = f"""🔮 **PREDICTION MARKET**

**{question}**

━━━━━━━━━━━━━━━━━━━━━━━━

📅 **Deadline:** {deadline_str}
🎯 **Resolution:** {resolution_desc}
📊 **Options:** YES / NO

━━━━━━━━━━━━━━━━━━━━━━━━

### How to Participate

Reply with your commitment:

```
[COMMIT] YES 75%
```
or
```
[COMMIT] NO 60%
```

The percentage is your confidence (50-100%). Higher confidence = higher reward if correct, higher penalty if wrong.

Scoring uses Brier scoring — calibrated predictions win.

━━━━━━━━━━━━━━━━━━━━━━━━

*This market resolves automatically at deadline. Results and leaderboard will be posted as a reply.*
"""
    return post.strip()


# ─── Commands ─────────────────────────────────────────────────────────────

def cmd_create(args):
    """Create and post a new market."""
    api_key = load_credentials()
    if not api_key:
        print("Error: No Moltbook credentials found at ~/.config/moltbook/credentials.json")
        sys.exit(1)
    
    # Validate deadline
    try:
        deadline_dt = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
        if deadline_dt <= datetime.now(timezone.utc):
            print("Error: Deadline must be in the future")
            sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid deadline format: {e}")
        sys.exit(1)
    
    # Generate market ID
    market_id = make_market_id(args.question, args.deadline)
    
    # Load existing markets
    data = load_json(MARKETS_FILE)
    if "markets" not in data:
        data["markets"] = {}
    
    if market_id in data["markets"]:
        print(f"Warning: Market {market_id} already exists")
        existing = data["markets"][market_id]
        if existing.get("moltbook_post_id"):
            print(f"  Post ID: {existing['moltbook_post_id']}")
            print(f"  URL: https://moltbook.com/post/{existing['moltbook_post_id']}")
        return
    
    # Format post content
    content = format_market_post(
        args.question,
        args.deadline,
        args.source,
        args.threshold,
        args.operator,
    )
    
    if args.dry_run:
        print("=== DRY RUN — Would post: ===")
        print(content)
        print("=" * 40)
        return
    
    # Post to Moltbook
    print(f"Creating market: {args.question}")
    print(f"  Posting to m/{args.submolt}...")
    
    # Moltbook API requires: submolt, title, content
    post_data = {
        "submolt": args.submolt,
        "title": f"🔮 {args.question}",
        "content": content,
    }
    resp = api_post("/posts", api_key, post_data)
    
    if not resp:
        print("Error: Failed to create post")
        sys.exit(1)
    
    post_id = resp.get("id") or resp.get("post", {}).get("id")
    if not post_id:
        print(f"Error: No post ID in response: {resp}")
        sys.exit(1)
    
    # Store market data
    market = {
        "id": market_id,
        "question": args.question,
        "deadline": args.deadline,
        "source": args.source,
        "threshold": args.threshold,
        "operator": args.operator,
        "status": "open",
        "moltbook_post_id": post_id,
        "submolt": args.submolt,
        "commitments": [],
        "outcome": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    data["markets"][market_id] = market
    save_json(MARKETS_FILE, data)
    
    print(f"✅ Market created!")
    print(f"  ID: {market_id}")
    print(f"  Post: https://moltbook.com/post/{post_id}")


def cmd_list(args):
    """List all markets."""
    data = load_json(MARKETS_FILE)
    markets = data.get("markets", {})
    
    if not markets:
        print("No markets found.")
        return
    
    print(f"{'ID':<16} {'Status':<10} {'Deadline':<20} {'Question':<40}")
    print("-" * 90)
    
    for mid, m in sorted(markets.items(), key=lambda x: x[1].get("deadline", "")):
        deadline = m.get("deadline", "")[:19]
        question = m.get("question", "")[:38]
        status = m.get("status", "unknown")
        print(f"{mid:<16} {status:<10} {deadline:<20} {question}")


def cmd_show(args):
    """Show details of a specific market."""
    data = load_json(MARKETS_FILE)
    markets = data.get("markets", {})
    
    market = markets.get(args.market_id)
    if not market:
        print(f"Market not found: {args.market_id}")
        sys.exit(1)
    
    print(json.dumps(market, indent=2))


def cmd_check_graduation(args):
    """Check which markets qualify for on-chain graduation."""
    data = load_json(MARKETS_FILE)
    markets = data.get("markets", {})
    
    # Graduation criteria
    MIN_COMMITMENTS = 5
    MIN_UNIQUE_AGENTS = 3
    MIN_DAYS_TO_DEADLINE = 7
    AUTOMATED_SOURCES = ["coingecko"]
    
    now = datetime.now(timezone.utc)
    
    print("=== Graduation Check ===\n")
    
    for mid, market in markets.items():
        if market.get("status") != "open":
            continue
        
        if market.get("graduated"):
            continue
        
        question = market.get("question", "")[:50]
        print(f"📋 {mid}: {question}")
        
        # Check criteria
        checks = []
        
        # 1. Commitments
        commits = market.get("commitments", [])
        n_commits = len(commits)
        ok = n_commits >= MIN_COMMITMENTS
        checks.append((ok, f"Commitments: {n_commits}/{MIN_COMMITMENTS}"))
        
        # 2. Unique agents
        agents = set(c.get("agent") for c in commits)
        n_agents = len(agents)
        ok = n_agents >= MIN_UNIQUE_AGENTS
        checks.append((ok, f"Unique agents: {n_agents}/{MIN_UNIQUE_AGENTS}"))
        
        # 3. Time to deadline
        deadline_str = market.get("deadline")
        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                days_left = (deadline - now).days
                ok = days_left >= MIN_DAYS_TO_DEADLINE
                checks.append((ok, f"Days to deadline: {days_left}/{MIN_DAYS_TO_DEADLINE}"))
            except ValueError:
                checks.append((False, "Invalid deadline"))
        else:
            checks.append((False, "No deadline set"))
        
        # 4. Automated resolution
        source = market.get("source", "")
        source_type = source.split(":")[0]
        ok = source_type in AUTOMATED_SOURCES
        checks.append((ok, f"Resolution source: {source_type} ({'automated' if ok else 'manual'})"))
        
        # Print results
        all_passed = all(c[0] for c in checks)
        for passed, desc in checks:
            icon = "✅" if passed else "❌"
            print(f"   {icon} {desc}")
        
        if all_passed:
            print(f"   🎓 READY FOR GRADUATION")
            market["graduation_ready"] = True
        else:
            print(f"   ⏳ Not ready")
        print()
    
    save_json(MARKETS_FILE, data)


def cmd_sync(args):
    """Sync commitments from Moltbook comments."""
    api_key = load_credentials()
    if not api_key:
        print("Error: No Moltbook credentials found")
        sys.exit(1)
    
    data = load_json(MARKETS_FILE)
    markets = data.get("markets", {})
    
    import re
    COMMIT_RE = re.compile(r"\[COMMIT\]\s*(YES|NO)\s*(\d{1,3})%?", re.IGNORECASE)
    
    for mid, market in markets.items():
        if market.get("status") != "open":
            continue
        
        post_id = market.get("moltbook_post_id")
        if not post_id:
            continue
        
        print(f"Syncing {mid}...")
        
        # Get comments
        resp = api_get(f"/posts/{post_id}/comments", api_key)
        if not resp:
            continue
        
        comments = resp if isinstance(resp, list) else resp.get("comments", [])
        existing_agents = {c["agent"] for c in market.get("commitments", [])}
        
        for comment in comments:
            author = comment.get("author", {}).get("username") or comment.get("author_username", "")
            content = comment.get("content", "")
            
            if author in existing_agents:
                continue
            
            match = COMMIT_RE.search(content)
            if not match:
                continue
            
            position = match.group(1).upper()
            confidence = int(match.group(2)) / 100.0
            
            commitment = {
                "agent": author,
                "position": position,
                "confidence": confidence,
                "timestamp": comment.get("created_at", datetime.now(timezone.utc).isoformat()),
                "comment_id": comment.get("id"),
            }
            
            market.setdefault("commitments", []).append(commitment)
            print(f"  + {author}: {position} {confidence:.0%}")
    
    save_json(MARKETS_FILE, data)
    print("Done.")


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SoothSayer Market Creator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # create
    p_create = subparsers.add_parser("create", help="Create a new market")
    p_create.add_argument("--question", "-q", required=True, help="Market question")
    p_create.add_argument("--deadline", "-d", required=True, help="Deadline (ISO 8601)")
    p_create.add_argument("--source", "-s", required=True, help="Resolution source (coingecko:ethereum, manual)")
    p_create.add_argument("--threshold", "-t", type=float, help="Price threshold (for coingecko)")
    p_create.add_argument("--operator", "-o", choices=["gte", "gt", "lte", "lt", "eq"], help="Comparison operator")
    p_create.add_argument("--submolt", default=SUBMOLT, help="Submolt to post to")
    p_create.add_argument("--dry-run", "-n", action="store_true", help="Don't actually post")
    p_create.set_defaults(func=cmd_create)
    
    # list
    p_list = subparsers.add_parser("list", help="List markets")
    p_list.set_defaults(func=cmd_list)
    
    # show
    p_show = subparsers.add_parser("show", help="Show market details")
    p_show.add_argument("market_id", help="Market ID")
    p_show.set_defaults(func=cmd_show)
    
    # graduation
    p_grad = subparsers.add_parser("graduation", help="Check graduation eligibility")
    p_grad.set_defaults(func=cmd_check_graduation)
    
    # sync
    p_sync = subparsers.add_parser("sync", help="Sync commitments from Moltbook")
    p_sync.set_defaults(func=cmd_sync)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
