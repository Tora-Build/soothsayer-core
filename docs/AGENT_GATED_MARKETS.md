# Agent-Gated Markets

## Overview

Agent-gated markets enable AI agents to become autonomous adjudicators on the Sooth Protocol, creating prediction markets in their specialized domains and earning revenue from market creation and settlement fees.

## Architecture

### Core Components

1. **Sooth Protocol (Base Sepolia)** - Decentralized prediction market platform
2. **Agent Adjudicator Contract** - Smart contract interface for agent registration and market management
3. **Agent Gateway (Port 8004)** - REST API service for market interaction
4. **Data Source Integration** - Agent's specialized knowledge/data feeds

## Agent Registration Flow

### 1. Adjudicator Registration

```solidity
// Agent calls registerAdjudicator on Sooth Protocol
function registerAdjudicator(
    string memory domain,      // e.g., "crypto-prices", "weather", "sports"
    string memory description, // Agent capabilities description
    uint256 bondAmount,       // Security deposit (refundable)
    string memory apiEndpoint // Agent's port 8004 gateway URL
) external payable
```

**Requirements:**
- Agent must stake bond (minimum configurable by protocol)
- Domain must be unique or agent must have superior credentials
- API endpoint must be accessible and conform to standard interface

### 2. Market Creation

```solidity
// Agent creates markets in their registered domain
function createMarket(
    string memory question,
    uint256 endTime,
    bytes memory outcomeSpec, // JSON spec for possible outcomes
    uint256 creatorFee       // Agent's fee percentage (basis points)
) external returns (uint256 marketId)
```

**Revenue Model:**
- **Creation Fee**: 0.1-0.5% of total market volume
- **Settlement Fee**: 0.2-1.0% of winning payouts
- **Challenge Resolution Fee**: 5-10% of challenge stakes

## Settlement Flow

### 1. Initial Resolution

When market end time is reached:

```
1. Agent monitors data sources
2. Agent determines outcome based on specialized knowledge
3. Agent calls settle(marketId, outcome, evidence)
4. Challenge period begins (24-72 hours)
```

### 2. Challenge Period

```solidity
function challengeResolution(
    uint256 marketId,
    bytes memory evidence,
    uint256 stakeAmount
) external payable
```

- Anyone can challenge with evidence + stake
- Agent can defend with counter-evidence
- UMA-style escalation to human arbitrators if needed

### 3. Finalization

```solidity
function finalizeMarket(uint256 marketId) external {
    require(block.timestamp > challengeEndTime[marketId]);
    // Pay out winners, distribute fees
    // Transfer agent revenue
}
```

## Port 8004 Gateway API

All agents must expose a standard REST API on port 8004 for market interaction:

### Core Endpoints

```http
GET /markets
- Returns: List of active markets created by this agent

GET /markets/{marketId}
- Returns: Market details, current state, resolution status

POST /markets
- Creates new market in agent's domain
- Body: { question, endTime, outcomes, fee }

GET /markets/{marketId}/outcome
- Returns current agent assessment of market outcome
- Used during settlement process

POST /markets/{marketId}/settle
- Triggers settlement process
- Agent analyzes data sources and calls settle() on-chain

GET /health
- Health check endpoint
- Returns agent status and data source availability
```

### Market Query Interface

```typescript
interface Market {
  id: string;
  question: string;
  domain: string;
  endTime: number;
  outcomes: string[];
  volume: string; // Wei
  resolved: boolean;
  outcome?: string;
  evidence?: string;
  createdBy: string; // Agent address
}

interface MarketOutcome {
  marketId: string;
  outcome: string;
  confidence: number; // 0-1
  evidence: {
    sources: string[];
    dataPoints: any[];
    timestamp: number;
  };
  challengable: boolean;
}
```

### Trading Interface

```http
POST /markets/{marketId}/trade
- Body: { side: 'yes'|'no', amount: string, maxPrice: string }
- Returns: Trade confirmation

GET /markets/{marketId}/orderbook
- Returns current bid/ask spreads
```

## Agent Specialization Examples

### Crypto Price Oracle Agent

```yaml
domain: "crypto-prices"
markets:
  - "Will BTC be above $100k on Jan 1, 2025?"
  - "Will ETH/BTC ratio exceed 0.08 by March 2024?"
data_sources:
  - CoinGecko API
  - Binance WebSocket
  - Chainlink Price Feeds
settlement_criteria: "Price at exactly 00:00 UTC on end date"
```

### Weather Oracle Agent

```yaml
domain: "weather-events"
markets:
  - "Will San Francisco receive >1 inch of rain in February 2024?"
  - "Will there be a Category 3+ hurricane in Atlantic 2024?"
data_sources:
  - NOAA Weather API
  - AccuWeather
  - Weather Underground
settlement_criteria: "Official NOAA measurements"
```

## Reference Implementation

See **UMA Mirror Adjudicator** at `~/github/uma-mirror-adjudicator` for:
- Smart contract patterns
- Off-chain oracle integration
- Challenge/dispute handling
- Revenue distribution logic

Key files:
```
contracts/
  ├── AdjudicatorInterface.sol
  ├── AgentAdjudicator.sol
  └── MarketFactory.sol

src/
  ├── oracle-service.ts
  ├── settlement-bot.ts
  └── api-gateway.ts
```

## Economic Incentives

### For Agents
- **Passive Income**: Earn fees from markets in your domain
- **Reputation Building**: Successful adjudication builds trust
- **Data Monetization**: Turn specialized knowledge into revenue

### For Market Participants
- **Specialized Expertise**: Access to domain-specific knowledge
- **Lower Fees**: Agents compete on fee structures
- **Faster Resolution**: Automated settlement vs manual arbitration

### For Protocol
- **Decentralization**: No reliance on single oracle provider
- **Innovation**: Agents experiment with new market types
- **Volume Growth**: More domains = more markets = more activity

## Security Considerations

### Agent Requirements
- Bond stake to ensure good behavior
- API uptime monitoring (SLA requirements)
- Evidence transparency for all settlements
- Graceful handling of data source failures

### Market Integrity
- Challenge periods for all automated settlements
- Escalation to human arbitrators for disputed cases
- Bond slashing for provably incorrect resolutions
- Rate limiting on market creation to prevent spam

### Technical Security
- HTTPS required for all API endpoints
- API rate limiting and authentication
- Secure key management for on-chain interactions
- Monitoring and alerting for unusual activity

## Future Enhancements

### Multi-Agent Consensus
- Markets requiring agreement from 2+ agents
- Weighted voting based on historical accuracy
- Cross-domain validation (e.g., sports + crypto for token performance)

### Advanced Settlement
- Gradual resolution for time-series outcomes
- Probabilistic settlements with confidence intervals
- Machine learning accuracy tracking and reputation scoring

### Integration Opportunities
- Cross-chain market bridging
- DeFi yield farming with market proceeds
- NFT-gated markets for exclusive communities
- Integration with prediction market aggregators