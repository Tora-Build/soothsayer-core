#!/usr/bin/env node
/**
 * SoothSayer On-Chain Settler — Settle and finalize markets on Monad.
 * 
 * Usage:
 *   node scripts/settler.mjs list                          # List markets with on-chain status
 *   node scripts/settler.mjs settle <market_address> <outcome>  # 0=NO, 1=YES, 2=INVALID
 *   node scripts/settler.mjs finalize <market_address>     # Finalize after challenge period
 *   node scripts/settler.mjs status <market_address>       # Check on-chain status
 */

import { ethers } from 'ethers';
import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

// Load .env from soothsayer root or fallback locations
dotenv.config({ path: resolve(root, '.env') });
if (!process.env.PRIVATE_KEY) {
  dotenv.config({ path: resolve(root, '../uma-mirror-adjudicator/.env') });
}

// ─── Config ───────────────────────────────────────────────────────────────

const MONAD_RPC = process.env.MONAD_RPC || 'https://testnet-rpc.monad.xyz';
const MONAD_CHAIN_ID = 10143;

// V11.1 Monad Testnet
const CONTRACTS = {
  LaunchpadEngine: '0x744724aa5b389644f31dfcfbb67786b581602084',
  AMMEngine: '0x67147bc54df45ce43cb88b735043c496047596a7',
  MockUSDC: '0x3b2f5a6e16cb5d5cf277f8718a9add3af0b1222a',
};

const MARKETS_FILE = resolve(root, 'data/markets.json');

// TruthMarket ABI (minimal for settle/finalize)
const TRUTH_MARKET_ABI = [
  'function settle(uint8 outcome, uint64 tStar) external',
  'function finalize() external',
  'function isSettled() external view returns (bool)',
  'function isFinalized() external view returns (bool)',
  'function adjudicator() external view returns (address)',
  'function question() external view returns (string)',
  'function deadline() external view returns (uint256)',
  'function state() external view returns (uint8)',
  'function outcome() external view returns (uint8)',
];

const MARKET_STATES = ['PENDING', 'LIVE', 'SETTLING', 'SETTLED', 'FINALIZED', 'CANCELLED'];
const OUTCOMES = ['NO', 'YES', 'INVALID'];

// ─── Settler Class ────────────────────────────────────────────────────────

class Settler {
  constructor() {
    this.provider = new ethers.JsonRpcProvider(MONAD_RPC);
    
    if (!process.env.PRIVATE_KEY) {
      console.error('❌ PRIVATE_KEY not found in .env');
      console.error('   Create ~/github/soothsayer/.env with:');
      console.error('   PRIVATE_KEY=0x...');
      process.exit(1);
    }
    
    this.wallet = new ethers.Wallet(process.env.PRIVATE_KEY, this.provider);
    console.log(`Wallet: ${this.wallet.address}`);
  }

  loadMarkets() {
    try {
      return JSON.parse(readFileSync(MARKETS_FILE, 'utf-8'));
    } catch {
      return { markets: {} };
    }
  }

  saveMarkets(data) {
    writeFileSync(MARKETS_FILE, JSON.stringify(data, null, 2));
  }

  async getMarketStatus(marketAddress) {
    const market = new ethers.Contract(marketAddress, TRUTH_MARKET_ABI, this.provider);
    
    try {
      const [isSettled, isFinalized, adjudicator, question, deadline, state] = await Promise.all([
        market.isSettled(),
        market.isFinalized(),
        market.adjudicator(),
        market.question(),
        market.deadline(),
        market.state(),
      ]);
      
      let outcome = null;
      if (isSettled) {
        outcome = Number(await market.outcome());
      }
      
      return {
        address: marketAddress,
        isSettled,
        isFinalized,
        adjudicator,
        question,
        deadline: Number(deadline),
        deadlineDate: new Date(Number(deadline) * 1000).toISOString(),
        state: Number(state),
        stateStr: MARKET_STATES[Number(state)] || 'UNKNOWN',
        outcome: outcome !== null ? OUTCOMES[outcome] : null,
        isOurs: adjudicator.toLowerCase() === this.wallet.address.toLowerCase(),
      };
    } catch (e) {
      return { address: marketAddress, error: e.message };
    }
  }

  async list() {
    const db = this.loadMarkets();
    const markets = Object.values(db.markets).filter(m => m.market_address);
    
    if (markets.length === 0) {
      console.log('No graduated markets found.');
      return;
    }
    
    console.log('\nGraduated Markets:\n');
    
    for (const m of markets) {
      const status = await this.getMarketStatus(m.market_address);
      console.log(`${m.id}`);
      console.log(`  Address: ${m.market_address}`);
      console.log(`  Question: ${m.question.slice(0, 50)}...`);
      console.log(`  State: ${status.stateStr}`);
      console.log(`  Settled: ${status.isSettled}, Finalized: ${status.isFinalized}`);
      console.log(`  Our adjudicator: ${status.isOurs}`);
      console.log('');
    }
  }

  async settle(marketAddress, outcomeInt) {
    console.log(`\nSettling market: ${marketAddress}`);
    console.log(`Outcome: ${outcomeInt} (${OUTCOMES[outcomeInt]})`);
    
    const status = await this.getMarketStatus(marketAddress);
    
    if (status.error) {
      console.error(`❌ Error: ${status.error}`);
      return;
    }
    
    if (!status.isOurs) {
      console.error(`❌ Not our market. Adjudicator: ${status.adjudicator}`);
      return;
    }
    
    if (status.isSettled) {
      console.log(`⚠️  Already settled. Outcome: ${status.outcome}`);
      return;
    }
    
    const market = new ethers.Contract(marketAddress, TRUTH_MARKET_ABI, this.wallet);
    const tStar = BigInt(Math.floor(Date.now() / 1000));
    
    console.log(`Calling settle(${outcomeInt}, ${tStar})...`);
    
    try {
      const tx = await market.settle(outcomeInt, tStar);
      console.log(`TX: ${tx.hash}`);
      
      const receipt = await tx.wait();
      console.log(`✅ Settled in block ${receipt.blockNumber}`);
      
      // Update local state
      const db = this.loadMarkets();
      for (const m of Object.values(db.markets)) {
        if (m.market_address === marketAddress) {
          m.status = 'settling';
          m.settled_tx = tx.hash;
        }
      }
      this.saveMarkets(db);
      
    } catch (e) {
      console.error(`❌ TX failed: ${e.message}`);
    }
  }

  async finalize(marketAddress) {
    console.log(`\nFinalizing market: ${marketAddress}`);
    
    const status = await this.getMarketStatus(marketAddress);
    
    if (status.error) {
      console.error(`❌ Error: ${status.error}`);
      return;
    }
    
    if (!status.isSettled) {
      console.error(`❌ Not settled yet. Run settle first.`);
      return;
    }
    
    if (status.isFinalized) {
      console.log(`⚠️  Already finalized.`);
      return;
    }
    
    const market = new ethers.Contract(marketAddress, TRUTH_MARKET_ABI, this.wallet);
    
    console.log(`Calling finalize()...`);
    
    try {
      const tx = await market.finalize();
      console.log(`TX: ${tx.hash}`);
      
      const receipt = await tx.wait();
      console.log(`✅ Finalized in block ${receipt.blockNumber}`);
      
      // Update local state
      const db = this.loadMarkets();
      for (const m of Object.values(db.markets)) {
        if (m.market_address === marketAddress) {
          m.status = 'finalized';
          m.finalized_tx = tx.hash;
        }
      }
      this.saveMarkets(db);
      
    } catch (e) {
      console.error(`❌ TX failed: ${e.message}`);
    }
  }

  async status(marketAddress) {
    const status = await this.getMarketStatus(marketAddress);
    console.log(JSON.stringify(status, null, 2));
  }
}

// ─── CLI ──────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0];
  
  if (!cmd) {
    console.log(`
SoothSayer On-Chain Settler

Usage:
  node scripts/settler.mjs list                              # List graduated markets
  node scripts/settler.mjs settle <market_address> <outcome> # 0=NO, 1=YES, 2=INVALID
  node scripts/settler.mjs finalize <market_address>         # Finalize after challenge
  node scripts/settler.mjs status <market_address>           # Check on-chain status
`);
    return;
  }
  
  const settler = new Settler();
  
  switch (cmd) {
    case 'list':
      await settler.list();
      break;
      
    case 'settle':
      if (args.length < 3) {
        console.error('Usage: settler.mjs settle <market_address> <outcome>');
        process.exit(1);
      }
      await settler.settle(args[1], parseInt(args[2]));
      break;
      
    case 'finalize':
      if (args.length < 2) {
        console.error('Usage: settler.mjs finalize <market_address>');
        process.exit(1);
      }
      await settler.finalize(args[1]);
      break;
      
    case 'status':
      if (args.length < 2) {
        console.error('Usage: settler.mjs status <market_address>');
        process.exit(1);
      }
      await settler.status(args[1]);
      break;
      
    default:
      console.error(`Unknown command: ${cmd}`);
      process.exit(1);
  }
}

main().catch(console.error);
