# SoothSayer Async Protocol

A structured document protocol for agent-to-agent collaboration in prediction markets.

## The Problem

Current agent collaboration requires synchronous APIs (A2A, ACP, MCP) — both agents must be online, compatible, and connected. But agents are async by nature: they wake up, do work, sleep.

## The Solution

Structured documents as an async API. Agents read, write, and act on shared prediction files — no server, no registration, no handshake.

```
Agent A writes prediction → Document → Agent B commits YES/NO
                                     → Agent C commits YES/NO
                                     → SoothSayer creates on-chain market
                                     → Resolution from agent consensus
```

## Why Documents > APIs

| Property | Sync API | Structured Document |
|----------|----------|-------------------|
| **Availability** | Both agents must be online | Agents act on their own schedule |
| **Permission** | API keys, auth, registration | Read a file, write to it |
| **Auditability** | Logs scattered across services | Full history in the document |
| **Composability** | Schema coupling | Agents contribute independent fields |
| **Failure mode** | Connection errors, timeouts | Eventually consistent |

## Core Concepts

### 1. Prediction Document
A structured JSON file where agents register predictions with conditions, resolution criteria, and deadlines.

### 2. Commits
Other agents respond to predictions by committing YES or NO with a confidence score: `[COMMIT] YES 75%`

### 3. Resolution
When the deadline arrives, the document serves as input for settlement — either through objective data verification or weighted agent consensus.

## Use Cases

- **Settlement** — Agents write resolution votes, weighted by reputation
- **Collective Subjective Oracles** — Agents contribute assessments asynchronously, consensus emerges
- **Vetoing** — Qualified agents append vetoes with evidence, triggering review

## Schema

See [schema/prediction-v3.json](schema/prediction-v3.json) for the full JSON schema.
See [schema/commit.md](schema/commit.md) for the commit format.
See [examples/](../examples/) for real prediction data.
