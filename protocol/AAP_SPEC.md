# AAP v2 Specification — Deterministic Adjudicator Protocol

*Version: 2.0 | Date: 2026-02-21*

## Principles

1. **Agents never touch Moltbook API directly** — all interactions through the AAP adapter
2. **Resolution is deterministic** — parse metadata, fetch data, compare, done
3. **No deletes ever** — fix forward, never destroy
4. **Verification is built-in** — every write auto-solves challenges
5. **Schema is enforced** — missing required fields = hard error

---

## On-Chain Question Format

The `question` field (Solidity `string`) carries structured metadata using `§` tags.

### Tags

| Tag | Level | Required | Lines | Purpose |
|-----|-------|----------|-------|---------|
| `§question` | Top | Yes | 1 | Human-readable question |
| `§rule` | Top | Yes | Multi | Resolution logic |
| `§§source` | Sub | No | 1 | Provenance (creator, origin) |
| `§event` | Top | No | 1 | Event grouping (e.g. "US Election 2026") |
| `§category` | Top | No | 1 | Market category (crypto, politics, tech, sports, agents) |
| `§picture` | Top | No | 1 | Image URL for market card display |

### Syntax

```
§question <human-readable question>
§rule
<key>:<value>
<key>:<value>
§§source <key>:<value> <key>:<value>
§event <event name>
§category <category>
§picture <image URL>
```

- `§` = top-level tag
- `§§` = sub-tag (optional, nested under parent `§` block)
- Top-level tags start a new section
- Sub-tags are inline within their parent section
- One-line tags: everything after the tag name on same line
- Multi-line tags: key:value pairs on subsequent lines until next `§`

### Rule Keys

| Key | Required | Values | Example |
|-----|----------|--------|---------|
| `source` | Yes | `<provider>:<asset>` or `manual` | `coingecko:bitcoin` |
| `metric` | If auto | What to measure | `price_usd`, `tvl`, `market_cap` |
| `op` | If auto | Comparison | `gte`, `lte`, `gt`, `lt`, `eq` |
| `target` | If auto | Numeric threshold | `75000` |
| `resolver` | No | Resolution authority | `soothsayer`, `brevis:zktls` |

### Source Keys (§§source)

| Key | Purpose | Example |
|-----|---------|---------|
| `creator` | Who originated the prediction | `HypeWatcher` |
| `origin` | Platform + post ID | `moltbook:95759b5b` |
| `created` | ISO date | `2026-02-10` |

### Examples

**Crypto price (auto-resolve):**
```
§question Will BTC hit $75,000 by Feb 20, 2026?
§rule
source:coingecko:bitcoin
metric:price_usd
op:gte
target:75000
§§source creator:HypeWatcher origin:moltbook:95759b5b
```

**Manual resolution:**
```
§question Will OpenAI announce GPT-5 by March 31, 2026?
§rule
source:manual
resolver:soothsayer
§§source origin:moltbook:5d5f032f
```

**Minimal:**
```
§question Will ETH hit $5,000 by June 2026?
§rule
source:coingecko:ethereum
op:gte
target:5000
```

### Parsing

```python
def parse_question(raw: str) -> dict:
    result = {}
    current_tag = None
    current_content = []
    
    for line in raw.strip().splitlines():
        if line.startswith('§§'):
            # Sub-tag: inline key:value pairs
            parts = line.split(None, 1)
            subtag = parts[0][2:]  # strip §§
            if len(parts) > 1:
                pairs = {}
                for token in parts[1].split():
                    if ':' in token:
                        k, v = token.split(':', 1)
                        pairs[k] = v
                if current_tag:
                    result.setdefault(current_tag, {})
                    result[current_tag][f'__{subtag}'] = pairs
        elif line.startswith('§'):
            # Save previous tag
            if current_tag and current_content:
                _save_tag(result, current_tag, current_content)
            # Start new tag
            parts = line.split(None, 1)
            current_tag = parts[0][1:]  # strip §
            current_content = []
            if len(parts) > 1:
                current_content.append(parts[1])
        else:
            current_content.append(line)
    
    if current_tag and current_content:
        _save_tag(result, current_tag, current_content)
    
    return result

def _save_tag(result, tag, content):
    if len(content) == 1 and ':' not in content[0]:
        result[tag] = content[0]
    else:
        pairs = {}
        for line in content:
            if ':' in line:
                k, v = line.split(':', 1)
                pairs[k.strip()] = v.strip()
            else:
                pairs['_text'] = line
        result[tag] = pairs if pairs else content[0]
```

---

## Adapter Architecture

```
Agent (cron) → market.py <command> → Moltbook API
                  ↑                      ↑
            enforces rules         agent never sees
```

### Commands

| Command | Purpose | LLM needed? |
|---------|---------|-------------|
| `market.py cycle` | Full cycle: sync + resolve + post | No |
| `market.py create --question "..." --rule "..." [--source ...]` | Create market + post to Moltbook | No |
| `market.py engage --post "content" --submolt "name"` | Post to Moltbook (non-market) | No (content passed as arg) |
| `market.py comment --post-id "uuid" --content "text"` | Comment on a post | No |
| `market.py upvote --post-id "uuid"` | Upvote a post | No |
| `market.py browse [--submolt "name"] [--sort hot]` | Read posts (no writes) | No |
| `market.py status` | Account status + market summary | No |

### Cycle Pipeline

```
market.py cycle
├── 1. sync       (fetch comments, parse [COMMIT], save)
├── 2. resolve    (check deadlines, fetch prices, determine outcomes)
└── 3. post       (comment resolutions on original market posts)
```

Each step is deterministic. The agent runs `market.py cycle` and reports output.

### Verification Flow

Built into every Moltbook write:

```python
def api_post_verified(endpoint, data, api_key):
    resp = api_post(endpoint, data, api_key)
    
    verification = extract_verification(resp)
    if not verification:
        return resp  # No challenge (upvotes, etc.)
    
    challenge = verification['challenge_text']
    code = verification['verification_code']
    
    # Solve via Claude API (one call, ~$0.001)
    answer = solve_challenge_llm(challenge)
    
    # Submit — ONE attempt only
    result = api_post('/verify', {
        'verification_code': code,
        'answer': answer
    }, api_key)
    
    if not result.get('success'):
        log_error(f"Challenge failed: {challenge} → {answer}")
        return None  # Abort, don't retry
    
    return resp
```

### Challenge Solver

Uses Claude Haiku via API (~$0.001/call, <1s):

```python
def solve_challenge_llm(challenge_text: str) -> str:
    prompt = f"""Parse this obfuscated text. Extract all numbers (written as words).
Identify the math operation (sum, difference, product, etc).
Calculate the result. Return ONLY the number with 2 decimal places.

Text: {challenge_text}

Answer:"""
    
    resp = call_anthropic(model='claude-haiku', prompt=prompt, max_tokens=20)
    return resp.strip()
```

### No-Delete Guard

```python
def api_request(method, endpoint, data=None, api_key=None):
    if method.upper() == 'DELETE':
        raise PermissionError("DELETE operations are forbidden by AAP policy")
    # ... proceed
```

---

## Data Schema (markets.json v2)

```json
{
  "version": 2,
  "markets": {
    "market_abc123": {
      "id": "market_abc123",
      "status": "open",
      
      "question_raw": "§question Will BTC hit $75,000 by Feb 20, 2026?\n§rule\nsource:coingecko:bitcoin\nmetric:price_usd\nop:gte\ntarget:75000\n§§source creator:SoothSayer origin:moltbook:32ca597b",
      "question_display": "Will BTC hit $75,000 by Feb 20, 2026?",
      "deadline": "2026-02-20T23:59:00Z",
      
      "rule": {
        "source": "coingecko:bitcoin",
        "metric": "price_usd",
        "op": "gte",
        "target": 75000
      },
      
      "moltbook_post_id": "uuid-required",
      "source_post_id": "uuid|null",
      "creator": "SoothSayer",
      
      "outcome": null,
      "outcome_value": null,
      "outcome_evidence": null,
      "resolved_at": null,
      "resolution_comment_id": null,
      
      "commitments": [],
      
      "onchain": null,
      
      "created_at": "2026-02-10T...",
      "updated_at": "2026-02-10T..."
    }
  }
}
```

### Required Fields (enforced)

| Field | When Required |
|-------|--------------|
| `id` | Always |
| `question_raw` | Always |
| `question_display` | Always |
| `deadline` | Always |
| `status` | Always |
| `moltbook_post_id` | After creation (post must succeed) |
| `rule.source` | Always |
| `rule.op` + `rule.target` | When source ≠ manual |

### Status Transitions

```
open → resolved → settled → finalized
                ↘ invalid
```

No skipping. Enforced in code.

---

## Engage Adapter

For non-market Moltbook interactions (W3Cash, SoothSayer social posting):

```bash
# Post to a submolt
market.py engage --post "content here" --submolt agentfi --title "Title"

# Comment on a post  
market.py comment --post-id abc123 --content "comment here"

# Upvote
market.py upvote --post-id abc123

# Browse (read-only, no verification needed)
market.py browse --submolt agents --sort hot --limit 20
market.py browse --search "prediction oracle" --limit 10
```

All writes go through `api_post_verified()`. Agent passes content as arguments, never constructs API calls.

### Engage for W3Cash

Separate credentials file, same adapter:

```bash
market.py engage --account w3cash --post "content" --submolt agentfi
market.py comment --account w3cash --post-id abc123 --content "text"
```

`--account` selects credentials from `~/.config/moltbook/<account>-credentials.json`.

---

## Migration Plan

### Phase 1: Core adapter (build first)
1. Question format parser (`parse_question`, `format_question`)
2. `api_post_verified()` with Claude challenge solver  
3. No-delete guard
4. Schema validation

### Phase 2: Market commands
5. `market.py cycle` (sync + resolve + post-resolution)
6. `market.py create` (with new question format)
7. Data migration (backfill existing markets.json)

### Phase 3: Engage commands  
8. `market.py engage` / `comment` / `upvote` / `browse`
9. W3Cash account support (`--account`)

### Phase 4: Wire crons
10. Update adjudicator cron → `market.py cycle`
11. Update soothsayer-moltbook-engage → `market.py engage` commands
12. Update w3cash-moltbook-engage → `market.py engage --account w3cash`

### Phase 5: Cleanup
13. Remove redundant scripts (resolve_market.py, create_market.py, crawler.py)
14. Remove all raw Moltbook API instructions from cron prompts
15. Test full cycle end-to-end
