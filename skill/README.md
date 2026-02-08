# SoothSayer Skill

A drop-in skill for any AI agent framework. Teach your agent to create prediction markets, trade outcomes, and resolve truth on Sooth Protocol.

## Installation

Copy the `SKILL.md` file into your agent's skills directory. Compatible with:
- [OpenClaw](https://openclaw.ai)
- Any agent framework that supports markdown skill files
- Manual integration via the contract ABIs and addresses listed in SKILL.md

## What Your Agent Learns

- **Create markets** on Sooth Protocol's LaunchpadEngine
- **Trade YES/NO tokens** via bonding curve or AMM
- **Check market state** (bonding, live, settled, finalized)
- **Resolve markets** through the adjudicator system
- **Read structured predictions** from the async protocol

## Deployed On

| Chain | ChainId |
|-------|---------|
| Monad Testnet | 10143 |
| Base Sepolia | 84532 |

## Quick Start

```bash
# Copy skill into your agent workspace
cp skill/SKILL.md ~/your-agent/skills/sooth-protocol/SKILL.md

# Your agent now knows how to:
# - Read prediction documents
# - Create on-chain markets
# - Trade outcome tokens
# - Participate in resolution
```
