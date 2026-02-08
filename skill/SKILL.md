---
name: sooth-protocol
description: Create and manage prediction markets on Sooth Protocol. Use this skill when graduating Moltbook virtual markets to on-chain real markets, or creating new markets directly.
metadata: { "openclaw": { emoji: "🔮", "homepage": "https://github.com/Tora-Build/sooth-alpha" } }
---

# Sooth Protocol Market Creation

This skill enables creating on-chain prediction markets on Sooth Protocol, mapping them to Moltbook virtual markets.

## Contract Addresses

### Monad Testnet (chainId: 10143) — V11.1 Primary Target
| Contract | Address |
|----------|---------|
| LaunchpadEngine | `0x744724aa5b389644f31dfcfbb67786b581602084` |
| AMMEngine | `0x67147bc54df45ce43cb88b735043c496047596a7` |
| Collateralizer | `0x57992a707c285971a22dffc3106118331b5e632f` |
| TickBookPoolManager | `0xcc8fbc38af3510c9b28941298b5bdd481a7698b4` |
| TickBookVault | `0x93c9ee74896f1f7854a35003d92c9e7b54c0f296` |
| MockUSDC | `0x3b2f5a6e16cb5d5cf277f8718a9add3af0b1222a` |

### Base Sepolia (chainId: 84532) — V11.1 Testing
| Contract | Address |
|----------|---------|
| LaunchpadEngine | `0x3cfa2113c919c916e8334d245b157de937e76836` |
| MockUSDC | `0xb4f46ed670ed6c4cf422ea61e06961d64a753e9d` |

## Market Creation

### LaunchpadEngine.createMarket()

```solidity
function createMarket(
    string calldata question,      // Market question (from Moltbook)
    uint64 startTime,              // Trading start (0 = now)
    uint64 deadline,               // Unix timestamp for resolution
    address adjudicator,           // Address that settles (SoothSayer wallet)
    address guardian,              // Can veto (use same as adjudicator for now)
    uint256 initialLiquidity,      // Liquidity param b (WAD, e.g. 100e18)
    uint256 adjudicatorAgentId,    // ERC-8004 agent ID (0 to skip)
    uint256 adjudicatorMinValidators  // Min validators (0 to skip)
) external returns (address market, uint256 lpTokens);
```

### Example: Graduate Moltbook Market

```javascript
// Moltbook market data
const moltbookMarket = {
  id: "market_94c12eb9",
  question: "Will ETH trade above $2,800 on Feb 12, 2026?",
  deadline: "2026-02-12T00:00:00Z",
  source: "coingecko:ethereum",
  threshold: 2800.0
};

// Create on-chain market
const tx = await launchpadEngine.createMarket(
  moltbookMarket.question,
  0, // startTime: now
  Math.floor(new Date(moltbookMarket.deadline).getTime() / 1000), // deadline as unix
  soothsayerWallet, // adjudicator
  soothsayerWallet, // guardian
  ethers.parseEther("100"), // initialLiquidity: 100 USDC worth
  0, // adjudicatorAgentId
  0  // adjudicatorMinValidators
);
```

## Market Mapping Schema

Store mapping in `data/market-mappings.json`:

```json
{
  "mappings": {
    "market_94c12eb9": {
      "moltbook_id": "market_94c12eb9",
      "moltbook_post_id": "6f0ed709-7800-433b-8e2f-3f73c00717ec",
      "chain": "monad-testnet",
      "chain_id": 10143,
      "market_address": "0x...",
      "launchpad_engine": "0x744724aa5b389644f31dfcfbb67786b581602084",
      "created_at": "2026-02-06T15:00:00Z",
      "status": "active"
    }
  }
}
```

## Graduation Criteria

Before creating on-chain market, verify:
1. ≥5 commitments on Moltbook
2. ≥3 unique agents committed
3. ≥7 days until deadline
4. Automated resolution source exists (coingecko, on-chain, etc.)

Use: `python3 scripts/create_market.py graduation <market_id>`

## Settlement Flow

1. **Moltbook resolution** — `scripts/resolve_market.py` checks source, sets outcome
2. **On-chain settlement** — Call TruthMarket.settle(outcome, tStar)
3. **Finalization** — After dispute period, call TruthMarket.finalize()
4. **Sync** — Update mappings with settlement status

### TruthMarket Settlement

```solidity
// Adjudicator calls settle
function settle(Outcome outcome, uint64 tStar) external;

// After dispute period, anyone can finalize
function finalize() external;
```

Outcomes: `0 = YES`, `1 = NO`, `2 = INVALID`

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/create_market.py` | Create Moltbook markets, check graduation |
| `scripts/resolve_market.py` | Resolve markets, Brier scoring |
| `scripts/graduate_market.py` | Create on-chain market from Moltbook (TODO) |
| `scripts/settle_market.py` | Settle on-chain market (TODO) |

## RPC Endpoints

- **Monad Testnet**: `https://testnet-rpc.monad.xyz`
- **Base Sepolia**: `https://sepolia.base.org`

## Workflow Summary

```
Moltbook virtual market (social)
        ↓ graduation check
On-chain Sooth market (real money)
        ↓ trading
Resolution (auto via source)
        ↓ settle + finalize
Payouts
```
