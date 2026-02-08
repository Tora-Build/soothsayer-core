#!/usr/bin/env node
/**
 * SoothSayer On-Chain Market Creator — Create markets on Monad via LaunchpadEngine.
 * 
 * Usage:
 *   node scripts/create-market.mjs <market_id>   # Create on-chain from virtual market
 *   node scripts/create-market.mjs list          # List virtual markets ready for sync
 */

import { ethers } from 'ethers';
import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

dotenv.config({ path: resolve(root, '.env') });
if (!process.env.PRIVATE_KEY) {
  dotenv.config({ path: resolve(root, '../uma-mirror-adjudicator/.env') });
}

// ─── Config ───────────────────────────────────────────────────────────────

const MONAD_RPC = process.env.MONAD_RPC || 'https://testnet-rpc.monad.xyz';

// V11.1 Monad Testnet
const CONTRACTS = {
  LaunchpadEngine: '0x744724aa5b389644f31dfcfbb67786b581602084',
  MockUSDC: '0x3b2f5a6e16cb5d5cf277f8718a9add3af0b1222a',
  ProtocolConfig: '0x6784f9b2e3a629c94cc05b441b6fdec4a6890830',
};

const MARKETS_FILE = resolve(root, 'data/markets.json');
const MAPPINGS_FILE = resolve(root, 'data/market-mappings.json');

// LaunchpadEngine ABI (minimal for createMarket)
const LAUNCHPAD_ABI = [
  'function createMarket(string calldata question, uint64 startTime, uint64 deadline, address adjudicator, address guardian, uint256 initialLiquidity, uint256 adjudicatorAgentId, uint256 adjudicatorMinValidators) external returns (address market, uint256 lpTokens)',
];

const ERC20_ABI = [
  'function approve(address spender, uint256 amount) external returns (bool)',
  'function balanceOf(address account) external view returns (uint256)',
];

// ─── Creator Class ────────────────────────────────────────────────────────

class MarketCreator {
  constructor() {
    this.provider = new ethers.JsonRpcProvider(MONAD_RPC);
    
    if (!process.env.PRIVATE_KEY) {
      console.error('❌ PRIVATE_KEY not found in .env');
      process.exit(1);
    }
    
    this.wallet = new ethers.Wallet(process.env.PRIVATE_KEY, this.provider);
    this.launchpad = new ethers.Contract(CONTRACTS.LaunchpadEngine, LAUNCHPAD_ABI, this.wallet);
    this.usdc = new ethers.Contract(CONTRACTS.MockUSDC, ERC20_ABI, this.wallet);
    
    console.log(`Wallet: ${this.wallet.address}`);
  }

  loadMarkets() {
    try {
      return JSON.parse(readFileSync(MARKETS_FILE, 'utf-8'));
    } catch {
      return { markets: {} };
    }
  }

  loadMappings() {
    try {
      return JSON.parse(readFileSync(MAPPINGS_FILE, 'utf-8'));
    } catch {
      return { mappings: {}, onchain_only: {} };
    }
  }

  saveMappings(data) {
    writeFileSync(MAPPINGS_FILE, JSON.stringify(data, null, 2));
  }

  async list() {
    const db = this.loadMarkets();
    const mappings = this.loadMappings();
    
    console.log('\n📋 Virtual Markets Ready for On-Chain Sync:\n');
    
    for (const [id, market] of Object.entries(db.markets)) {
      if (market.status !== 'open') continue;
      if (mappings.mappings[id]) {
        console.log(`✅ ${id} — Already synced: ${mappings.mappings[id].market_address}`);
        continue;
      }
      
      const deadline = market.deadline || 'No deadline';
      console.log(`⏳ ${id} — ${market.question?.slice(0, 50)}...`);
      console.log(`   Deadline: ${deadline}`);
    }
  }

  async create(marketId) {
    const db = this.loadMarkets();
    const market = db.markets[marketId];
    
    if (!market) {
      console.error(`❌ Market not found: ${marketId}`);
      return;
    }
    
    const mappings = this.loadMappings();
    if (mappings.mappings[marketId]) {
      console.log(`Already synced: ${mappings.mappings[marketId].market_address}`);
      return;
    }
    
    console.log(`\n🚀 Creating on-chain market for: ${marketId}`);
    console.log(`   Question: ${market.question}`);
    
    // Parse deadline
    const deadlineStr = market.deadline;
    const deadline = Math.floor(new Date(deadlineStr).getTime() / 1000);
    const now = Math.floor(Date.now() / 1000);
    
    if (deadline <= now) {
      console.error(`❌ Deadline already passed: ${deadlineStr}`);
      return;
    }
    
    // Format question with creator attribution
    const question = `@SoothSayer ${market.question}`;
    
    // Initial liquidity: 1000 USDC in WAD format (18 decimals internally)
    // Contract expects WAD, then converts: depositWad = (liquidity * LN2_WAD) / WAD
    // MIN_DEPOSIT_WAD = 10e18, so we need at least ~15 WAD to get 10 after LN2 calc
    const liquidity = ethers.parseUnits('1000', 18);  // 1000 WAD
    
    // Check USDC balance
    // Contract will convert WAD liquidity to actual USDC: deposit ≈ liquidity * 0.693
    const estimatedDeposit = liquidity * 693n / 1000n;  // ~69.3% of WAD value
    const depositUsdc = estimatedDeposit / BigInt(1e12);  // WAD to USDC (18->6 decimals)
    const balance = await this.usdc.balanceOf(this.wallet.address);
    console.log(`   USDC balance: ${ethers.formatUnits(balance, 6)}`);
    console.log(`   Estimated deposit: ${ethers.formatUnits(depositUsdc, 6)} USDC`);
    
    if (balance < depositUsdc) {
      console.error(`❌ Insufficient USDC. Need ~${ethers.formatUnits(depositUsdc, 6)}, have ${ethers.formatUnits(balance, 6)}`);
      return;
    }
    
    // Approve USDC (max approval for simplicity)
    console.log('   Approving USDC...');
    const approveTx = await this.usdc.approve(CONTRACTS.LaunchpadEngine, ethers.MaxUint256);
    await approveTx.wait();
    console.log(`   ✅ Approved (max)`);
    
    // Create market
    console.log('   Creating market...');
    const startTime = now + 60;   // 1 minute in future to avoid timing issues
    const tx = await this.launchpad.createMarket(
      question,
      startTime,                  // startTime: 1 min in future
      deadline,                   // deadline
      this.wallet.address,        // adjudicator: SoothSayer wallet
      CONTRACTS.ProtocolConfig,   // guardian: must be protocol config
      liquidity,                  // initialLiquidity: 1000 USDC
      0,                          // adjudicatorAgentId: 0 (skip registry)
      0                           // adjudicatorMinValidators: 0 (must be 0 if agentId is 0)
    );
    
    const receipt = await tx.wait();
    console.log(`   ✅ Tx: ${receipt.hash}`);
    
    // Parse MarketCreated event to get market address
    // Event: MarketCreated(address indexed market, address indexed creator, string question, uint64 deadline)
    const marketCreatedTopic = ethers.id('MarketCreated(address,address,string,uint64)');
    const log = receipt.logs.find(l => l.topics[0] === marketCreatedTopic);
    
    if (!log) {
      console.error('❌ Could not find MarketCreated event');
      return;
    }
    
    const marketAddress = ethers.getAddress('0x' + log.topics[1].slice(26));
    console.log(`\n🎯 Market created: ${marketAddress}`);
    
    // Save mapping
    mappings.mappings[marketId] = {
      moltbook_id: marketId,
      moltbook_post_id: market.moltbook_post_id,
      chain: 'monad-testnet',
      chain_id: 10143,
      market_address: marketAddress,
      question: question,
      status: 'live',
      created_at: new Date().toISOString()
    };
    
    this.saveMappings(mappings);
    console.log('✅ Mapping saved to market-mappings.json');
  }
}

// ─── Main ─────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    console.log('Usage:');
    console.log('  node create-market.mjs list           # Show markets ready for sync');
    console.log('  node create-market.mjs <market_id>    # Create on-chain market');
    process.exit(0);
  }
  
  const creator = new MarketCreator();
  
  if (args[0] === 'list') {
    await creator.list();
  } else {
    await creator.create(args[0]);
  }
}

main().catch(console.error);
