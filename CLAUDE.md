# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI-based service that calculates Stride protocol fees for DefiLlama integration. The API queries the Stride blockchain to compute daily fees and revenue across 14+ Cosmos chains where Stride provides liquid staking services.

**Key purpose**: Replaced deprecated `https://edge.stride.zone/api/{chain}/stats/fees` endpoints with a modern, containerized API.

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

## Architecture

### Two-File Design

**main.py** - FastAPI application layer
- Route handlers for `/api/{chain}/stats/fees` and `/api/all/stats/fees`
- Lifespan management (startup/shutdown of StrideClient)
- Environment variable configuration
- HTTP error handling

**stride_client.py** - Blockchain data layer
- Queries Stride blockchain via REST API and RPC
- Calculates fees using redemption rates and staked amounts
- Manages CoinGecko price fetching with intelligent caching
- Chain ID mapping and token decimal handling

### Global State

The app uses a **single global `stride_client` instance** initialized in the FastAPI lifespan context manager. This client is shared across all requests and manages:
- HTTP connection pooling (httpx.AsyncClient)
- Price caching with 5-minute TTL
- Async locks for batch price fetching

### Fee Calculation Flow

1. Receive request for chain (e.g., "cosmos")
2. Map DefiLlama name → Stride chain ID (e.g., "cosmos" → "cosmoshub-4")
3. Query Stride API for host zone data (redemption_rate, total_delegations)
4. **Query real-time APR from chain** (cached for 1 hour):
   - Get inflation rate, bonded ratio, community tax
   - Calculate: `APR = inflation × (1 - community_tax) / bonded_ratio`
   - Falls back to hardcoded value if query fails
5. Calculate daily rewards: `total_delegations × redemption_rate × daily_rate`
6. Fetch USD price from CoinGecko (or use 5-minute cache)
7. Convert to USD using chain-specific decimals (6 for most Cosmos, 18 for EVM-based)
8. Return `{dailyFees: X, dailyRevenue: X * 0.10}`

**APR Querying**: System now queries actual APRs from each chain's staking parameters instead of using hardcoded estimates. Example: Cosmos Hub returns 10.13% real APR (vs. 17% hardcoded estimate).

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

Update three dictionaries in `stride_client.py`:

1. **CHAIN_ID_MAP**: DefiLlama name → Stride chain ID
2. **COINGECKO_IDS**: Chain → CoinGecko API ID
3. **TOKEN_DECIMALS**: Chain → decimal places (6 or 18)

Then add the chain name to `supported_chains` list in `main.py:get_all_fees()`.

### Chain Name Overrides

The API handles `terra` → `terra2` alias in `main.py:get_chain_fees()`. Add similar overrides there if needed.

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

## Dependencies

Core stack:
- **FastAPI 0.115.0** - Web framework
- **uvicorn 0.32.1** - ASGI server
- **httpx 0.27.2** - Async HTTP client (for Stride/CoinGecko APIs)
- **pydantic 2.10.3** - Data validation
- **python-dotenv 1.0.1** - Environment management

## Known Limitations

1. **Estimated APR**: Uses hardcoded 18% APR instead of tracking historical redemption rates
2. **Single-instance cache**: Price cache is in-memory; consider Redis for horizontal scaling
3. **No authentication**: Public API with no rate limiting
4. **No historical data**: Only current daily fees, no time-series support
