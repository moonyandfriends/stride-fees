# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI-based service that calculates Stride protocol fees for DefiLlama integration. The API queries the Stride blockchain to compute daily fees and revenue across 14+ Cosmos chains where Stride provides liquid staking services.

**Key purpose**: Replaced deprecated `https://edge.stride.zone/api/{chain}/stats/fees` endpoints with a modern, containerized API.

**Supported chains**: cosmos, celestia, osmosis, dydx, dymension, juno, stargaze, terra2, evmos, injective, umee, comdex, haqq, band

## Development Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the API (development mode with auto-reload)
python main.py

# API available at http://localhost:8000
```

### Docker
```bash
# Build image
docker build -t stride-fees-api .

# Run container
docker run -d -p 8000:8000 --env-file .env stride-fees-api

# Or use docker-compose
docker-compose up -d
```

### Testing Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Single chain fees
curl http://localhost:8000/api/cosmos/stats/fees

# All chains (batch)
curl http://localhost:8000/api/all/stats/fees
```

### Historical Data Generation
```bash
# Generate historical fee data (optimized version - recommended)
python3 generate_historical_fees_optimized.py

# Original version (slower, day-by-day fetching)
python3 generate_historical_fees.py

# Verify fee calculations with detailed breakdown
python3 verify_fees.py
```

**Note on historical data**: Uses CoinGecko's market_chart/range API to fetch price ranges. Free tier has rate limits (~10-15 requests/min), so the script includes exponential backoff. Output is written to `stride_historical_fees.csv`.

### Redemption Rate Tracking (Recommended)
```bash
# Take a daily snapshot of redemption rates (run via cron)
python3 snapshot_redemption_rates.py

# Cron example - run daily at midnight UTC:
# 0 0 * * * cd /path/to/stride-fees && /usr/bin/python3 snapshot_redemption_rates.py
```

**Why this is better**: The snapshot method calculates fees from actual redemption rate changes instead of estimating with APRs. This eliminates issues with:
- Chains that don't expose APR endpoints (Celestia, Stargaze, dYdX, etc.)
- Inconsistent APRs across different mint modules
- Missing external incentives (Osmosis shows 580% more accurate with snapshots!)

**How it works**: Snapshots are stored in `redemption_rate_snapshots.json`. The API automatically uses snapshot data when available, falling back to APR estimation if snapshots are missing.

## Architecture

### Core Files

**main.py** - FastAPI application layer
- Route handlers for `/api/{chain}/stats/fees` and `/api/all/stats/fees`
- Lifespan management (startup/shutdown of StrideClient)
- Environment variable configuration
- HTTP error handling

**stride_client.py** - Blockchain data layer (490 lines)
- Queries Stride blockchain via REST API and RPC
- Calculates fees using redemption rates and staked amounts
- Manages CoinGecko price fetching with intelligent caching
- Chain ID mapping and token decimal handling
- Three critical dictionaries: `CHAIN_ID_MAP`, `COINGECKO_IDS`, `TOKEN_DECIMALS`
- APR querying with chain-specific methods for Osmosis and Celestia
- Standard Cosmos SDK inflation calculation for other chains

### Utility Scripts

**snapshot_redemption_rates.py** - Daily redemption rate tracker (NEW - Recommended)
- Queries redemption rates and stToken supplies for all chains
- Stores daily snapshots in `redemption_rate_snapshots.json`
- Enables accurate fee calculation without APR estimation
- Should be run daily via cron for production use
- Keeps last 400 days of history (~13 months)

**generate_historical_fees_optimized.py** - Bulk historical data generation
- Uses CoinGecko's `market_chart/range` endpoint for efficient price fetching
- One API call per chain for entire date range (vs. one per day)
- Exponential backoff for rate limiting
- Outputs to `stride_historical_fees.csv`

**generate_historical_fees.py** - Day-by-day historical data generation
- Fetches prices individually for each day using `/coins/{id}/history` endpoint
- More granular but slower (190 days × 13 chains = 2,470 API calls)
- Useful when specific date precision is needed

**verify_fees.py** - Fee calculation verification script
- Provides detailed breakdown of fee calculations for debugging
- Shows each step: delegations → APR → rewards → USD conversion
- Compares manual calculation against API result

### Global State & Caching

The app uses a **single global `stride_client` instance** initialized in the FastAPI lifespan context manager. This client is shared across all requests and manages:

**Price Cache** (5-minute TTL):
- In-memory dict: `{chain: {"price": float, "timestamp": datetime}}`
- Async lock prevents concurrent fetches of same data
- Batch fetching pre-loads all 14 chain prices in one CoinGecko call

**APR Cache** (1-hour TTL):
- In-memory dict: `{chain: {"apr": float, "timestamp": datetime}}`
- Reduces repeated queries to chain APIs for staking parameters
- Each chain has custom query logic or falls back to hardcoded values

**HTTP Client**:
- Single `httpx.AsyncClient` with 30s timeout
- Connection pooling for efficient reuse
- Closed on FastAPI shutdown

### Fee Calculation Flow

The API supports **two calculation methods** and automatically uses the most accurate available:

**Method 1: Redemption Rate Snapshots (Preferred - Most Accurate)**
1. Receive request for chain (e.g., "cosmos")
2. Load today's and yesterday's snapshots from `redemption_rate_snapshots.json`
3. Calculate redemption rate change: `rr_today - rr_yesterday`
4. Calculate actual daily rewards: `stToken_supply × rr_change`
5. Fetch USD price from CoinGecko (or use 5-minute cache)
6. Convert to USD using chain-specific decimals
7. Return `{dailyFees: X, dailyRevenue: X * 0.10, method: "redemption_rate_snapshot"}`

**Method 2: APR Estimation (Fallback)**
1. Receive request for chain (e.g., "cosmos")
2. Map DefiLlama name → Stride chain ID (e.g., "cosmos" → "cosmoshub-4")
3. Query Stride API for host zone data (redemption_rate, total_delegations)
4. **Query real-time APR from chain** (cached for 1 hour):
   - Get inflation rate, bonded ratio, community tax
   - Calculate: `APR = inflation × (1 - community_tax) / bonded_ratio`
   - Falls back to hardcoded value if query fails
5. Calculate estimated daily rewards: `total_delegations × daily_rate`
6. Fetch USD price from CoinGecko (or use 5-minute cache)
7. Convert to USD using chain-specific decimals
8. Return `{dailyFees: X, dailyRevenue: X * 0.10, method: "apr_estimation"}`

**Automatic Fallback**: If snapshot data is unavailable (e.g., first day after setup), the API automatically falls back to APR estimation.

**APR Querying**: System queries actual APRs from each chain's staking parameters with fallback to hardcoded values:

**Standard Cosmos SDK chains** (cosmos, dydx, juno, etc.):
- Query: `inflation`, `bonded_ratio`, `community_tax` from chain APIs
- Formula: `APR = inflation × (1 - community_tax) / bonded_ratio`

**Osmosis** (custom mint module):
- Query: `epoch_provisions` (daily minting), `staking_proportion`, `bonded_tokens`
- Formula: `APR = (epoch_provisions × staking_proportion × 365) / bonded_tokens`

**Celestia**: Returns `None` (no standard endpoint), uses fallback value

**Fallback APRs**: Hardcoded in `STAKING_APRS` dict (based on Mintscan, StakingRewards.com, Dec 2024)
- Example: Cosmos Hub queries 10.13% real APR (vs. 17% hardcoded fallback)

### Price Caching Strategy

**Problem**: CoinGecko free tier has strict rate limits
**Solution**: In-memory cache with 5-minute TTL + batch fetching

- Individual chain requests check cache before calling CoinGecko
- `/api/all/stats/fees` pre-fetches all 14 token prices in **one batch request**
- Subsequent individual chain requests benefit from shared cache
- Async lock prevents concurrent fetches of the same data
- Cache is per-instance (use Redis for multi-instance deployments)

Example: After calling `/api/all/stats/fees`, all individual chain endpoints respond in ~50ms instead of ~300ms.

## Chain Configuration

### Adding New Chains

To add support for a new chain, update **four locations** in `stride_client.py`:

1. **CHAIN_ID_MAP** (line ~17): DefiLlama name → Stride chain ID
   ```python
   "newchain": "newchain-1"
   ```

2. **COINGECKO_IDS** (line ~36): Chain → CoinGecko API ID
   ```python
   "newchain": "new-chain-token"
   ```

3. **TOKEN_DECIMALS** (line ~54): Chain → decimal places (6 or 18)
   ```python
   "newchain": 6  # or 18 for EVM-based chains
   ```

4. **CHAIN_API_URLS** (line ~73): Chain → API endpoint for APR queries
   ```python
   "newchain": "https://newchain-api.polkachu.com"
   ```

5. **Optional - STAKING_APRS** (line ~94): Add fallback APR if needed
   ```python
   "newchain": 0.15  # 15% APR fallback
   ```

Then add the chain name to `supported_chains` list in `main.py:get_all_fees()` (line ~85).

### Chain Name Overrides

The API handles `terra` → `terra2` alias in `main.py:get_chain_fees()` (line ~132). Add similar overrides there if needed.

### Chain-Specific APR Logic

If a chain has a custom mint module (like Osmosis), add a new method in `stride_client.py`:
- Follow the pattern of `query_osmosis_apr()` or `query_celestia_apr()`
- Add a condition in `query_chain_apr()` to call your custom method

## Environment Variables

All variables have sensible defaults - no configuration required for basic deployment.

**Stride endpoints**:
- `STRIDE_API_URL` (default: https://stride-api.polkachu.com)
- `STRIDE_RPC_URL` (default: https://stride-rpc.polkachu.com)

**Price data**:
- `PRICE_API_URL` (default: https://api.coingecko.com/api/v3)

**Server config**:
- `HOST` (default: 0.0.0.0)
- `PORT` (default: 8000)

**Deployment detection**:
- Auto-disables uvicorn reload if `RAILWAY_ENVIRONMENT` or `DOCKER_CONTAINER` is set

## Railway Deployment

This repo is configured for automatic Railway deployment via `railway.toml`:
- Uses Dockerfile builder
- Starts with `python main.py`
- Restart policy: on_failure (max 10 retries)

When GitHub repo updates, Railway automatically rebuilds the container.

### Setting Up Redemption Rate Snapshots in Production

**IMPORTANT**: For accurate fee calculations in production, set up daily snapshots:

1. **SSH into your Railway container** or server:
   ```bash
   # Install crontab if not available
   apt-get update && apt-get install -y cron

   # Edit crontab
   crontab -e
   ```

2. **Add cron job** (runs daily at midnight UTC):
   ```
   0 0 * * * cd /app && /usr/local/bin/python3 snapshot_redemption_rates.py >> /app/snapshot.log 2>&1
   ```

3. **Create initial snapshot** manually:
   ```bash
   cd /app
   python3 snapshot_redemption_rates.py
   ```

4. **Verify**:
   ```bash
   # Check snapshot file exists
   ls -lh redemption_rate_snapshots.json

   # Check cron logs
   tail -f snapshot.log
   ```

**Note**: The API will use APR estimation until you have at least 2 days of snapshots. After that, it automatically switches to the more accurate snapshot method.

## Dependencies

Core stack:
- **FastAPI 0.115.0** - Web framework
- **uvicorn 0.32.1** - ASGI server
- **httpx 0.27.2** - Async HTTP client (for Stride/CoinGecko APIs)
- **pydantic 2.10.3** - Data validation
- **python-dotenv 1.0.1** - Environment management

## Important Implementation Details

### APR Calculation Methods

**Three approaches** are used depending on the chain:

1. **Real-time querying** (preferred): Queries current staking parameters from chain APIs
   - Covers: cosmos, osmosis, dydx, juno, stargaze, terra2, evmos, injective, umee, comdex, haqq, band
   - Osmosis has special logic due to custom mint module

2. **Fallback values** (if query fails): Uses hardcoded APRs from `STAKING_APRS` dict
   - Based on December 2024 data from Mintscan and StakingRewards.com
   - Celestia always uses fallback (no standard API endpoint)

3. **1-hour caching**: APRs are cached to reduce API load since they change slowly

### Historical Data Methodology

**Current approach** (as of December 2024):
- Uses **current** staking amounts as proxy for historical (not true historical state)
- Uses **current** redemption rates
- Fetches **real historical prices** from CoinGecko
- Applies chain-specific APRs (queried or fallback)

**Limitations**:
- Staking amounts were different in the past (requires archive node to query historical state)
- APRs fluctuate over time (uses current APR for all historical dates)
- Dymension excluded from historical data (host zone returns 500 error)

**For truly accurate historical data**, you would need:
1. Archive node access to query past blockchain state
2. Historical APR tracking or redemption rate change monitoring
3. Daily snapshots of Stride's delegation amounts per chain

### Decimal Handling

**Critical for accuracy**: Each chain uses different token denominations

**6 decimals** (most Cosmos chains):
- 1 ATOM = 1,000,000 uatom
- cosmos, celestia, osmosis, juno, stargaze, terra2, umee, comdex, band

**18 decimals** (EVM-based chains):
- 1 DYDX = 1,000,000,000,000,000,000 adydx
- dydx, dymension, evmos, injective, haqq

**Always use `TOKEN_DECIMALS` dict** when converting native amounts to token amounts.

## Known Limitations

1. **Snapshot data collection**: Requires daily cron job for optimal accuracy (falls back to APR estimation if unavailable)
2. **Single-instance cache**: Price and APR caches are in-memory; consider Redis for horizontal scaling
3. **No authentication**: Public API with no rate limiting
4. **CoinGecko rate limits**: Free tier limits batch operations; may need paid API key for production
5. **No tests**: No unit or integration tests yet
6. **Historical data approximation**: Historical fee generation uses current staking amounts as proxy (not true historical state)

## Advantages of Redemption Rate Method

**Solved Problems** (compared to APR estimation):
- ✅ **No APR query failures**: Works for all chains regardless of mint module
- ✅ **Captures all rewards**: Includes external incentives (e.g., Osmosis shows 580% more accurate)
- ✅ **No hardcoded fallbacks**: Uses actual on-chain data
- ✅ **Consistent across chains**: Single calculation method for all chains
- ✅ **Handles slashing events**: Automatically detects and handles negative rate changes

**Remaining Limitations**:
- Requires 2+ days of snapshots to start working
- Depends on daily cron job execution
- Snapshot file must be accessible to API (shared storage in multi-instance setups)
