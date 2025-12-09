# Stride Fees API

FastAPI-based service for calculating Stride protocol fees for DefiLlama integration.

## Overview

This API provides endpoints to query daily fees and revenue for Stride's liquid staking protocol across multiple Cosmos ecosystem chains. It replaces the deprecated `https://edge.stride.zone/api/{chain}/stats/fees` endpoints.

## Features

- Calculate daily fees and revenue for 14+ Cosmos chains
- Real-time data from Stride blockchain
- USD price conversion via CoinGecko
- Docker containerized deployment
- Health check endpoints
- Compatible with DefiLlama fee adapter format

## Supported Chains

- Cosmos Hub (cosmos)
- Celestia (celestia)
- Osmosis (osmosis)
- dYdX (dydx)
- Dymension (dymension)
- Juno (juno)
- Stargaze (stargaze)
- Terra 2 (terra/terra2)
- Evmos (evmos)
- Injective (injective)
- Umee (umee)
- Comdex (comdex)
- HAQQ (haqq)
- Band Protocol (band)

## API Endpoints

### Get Chain Fees
```
GET /api/{chain}/stats/fees
```

Returns daily fees and revenue for a specific chain.

**Response:**
```json
{
  "fees": {
    "dailyFees": 12345.67,
    "dailyRevenue": 1234.57
  }
}
```

### Get All Fees
```
GET /api/all/stats/fees
```

Returns fees for all supported chains.

### Health Check
```
GET /health
```

Returns API health status and connectivity to Stride blockchain.

## Setup

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key variables:
- `STRIDE_API_URL`: Stride REST API endpoint
- `STRIDE_RPC_URL`: Stride RPC endpoint
- `PRICE_API_URL`: CoinGecko API URL
- `HOST`: API host (default: 0.0.0.0)
- `PORT`: API port (default: 8000)

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the API:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

### Docker Deployment

1. Build the image:
```bash
docker build -t stride-fees-api .
```

2. Run the container:
```bash
docker run -d -p 8000:8000 --env-file .env stride-fees-api
```

Or use docker-compose:
```bash
docker-compose up -d
```

### Railway Deployment

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/YOUR_USERNAME/stride-fees-api)

1. **Fork or push this repository to GitHub**

2. **Create a new project on [Railway](https://railway.app)**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `stride-fees-api` repository

3. **Configure environment variables** (optional - defaults work):
   - `STRIDE_API_URL` - Default: `https://stride-api.polkachu.com`
   - `STRIDE_RPC_URL` - Default: `https://stride-rpc.polkachu.com`
   - `PRICE_API_URL` - Default: `https://api.coingecko.com/api/v3`

4. **Deploy**
   - Railway will automatically detect the Dockerfile
   - Your API will be available at `https://your-app.railway.app`

5. **Test your deployment**:
   ```bash
   curl https://your-app.railway.app/health
   curl https://your-app.railway.app/api/cosmos/stats/fees
   ```

## Testing

Test the API with curl:

```bash
# Get Cosmos fees
curl http://localhost:8000/api/cosmos/stats/fees

# Get all fees
curl http://localhost:8000/api/all/stats/fees

# Health check
curl http://localhost:8000/health
```

## Integration with DefiLlama

Update the DefiLlama adapter to use your deployed endpoint:

```typescript
const fetch = (chain: string) => {
  return async (timestamp: number): Promise<FetchResult> => {
    const overriddenChain = chainOverrides[chain] || chain;
    const response: DailyFeeResponse = await httpGet(
      `https://your-api.example.com/api/${overriddenChain}/stats/fees`
    );

    return {
      timestamp: timestamp,
      dailyFees: String(response.fees.dailyFees),
      dailyRevenue: String(response.fees.dailyRevenue),
    };
  };
};
```

## Architecture

### Components

- **main.py**: FastAPI application with route handlers
- **stride_client.py**: Client for querying Stride blockchain and calculating fees
- **Dockerfile**: Container configuration
- **docker-compose.yml**: Orchestration for local development

### Fee Calculation Method

1. Query Stride blockchain for host zone data (staked balances, redemption rates)
2. Calculate total value staked for each chain
3. Estimate daily rewards based on redemption rate changes
4. Convert to USD using CoinGecko prices
5. Calculate revenue as 10% of total fees (Stride's protocol fee)

### Data Sources

- **Stride Blockchain**: Host zone data, redemption rates, staking info
- **CoinGecko API**: USD price data for tokens
- **Public RPC/API nodes**: Polkachu, kjnodes (with fallbacks)

## Rate Limit Handling & Caching

The API implements intelligent caching to avoid CoinGecko rate limits on the free tier:

### Price Caching (5-minute TTL)
- Token prices are cached in-memory for **5 minutes**
- Subsequent requests within the cache window return cached data instantly
- No redundant API calls to CoinGecko during cache validity period
- Automatic cache expiration ensures prices stay reasonably fresh

### Batch Price Fetching
- `/api/all/stats/fees` fetches **all 14 token prices in a single CoinGecko request**
- Uses CoinGecko's batch API: `/simple/price?ids=cosmos,osmosis,celestia,...`
- Individual chain endpoints (`/api/cosmos/stats/fees`) benefit from the shared cache
- Example: After calling `/api/all/stats/fees`, all individual chain requests use cached prices

### Benefits
- ✅ **Avoids 429 rate limit errors** on free CoinGecko tier
- ✅ **Faster response times** for cached requests (~50ms vs ~300ms)
- ✅ **Reduced external API calls** by 90%+ in typical usage
- ✅ **More reliable service** with fewer points of failure

### Cache Behavior
```bash
# First request - fetches from CoinGecko
curl http://localhost:8000/api/cosmos/stats/fees  # ~300ms, 1 API call

# Second request within 5 minutes - uses cache
curl http://localhost:8000/api/cosmos/stats/fees  # ~50ms, 0 API calls

# Batch endpoint - fetches all prices at once
curl http://localhost:8000/api/all/stats/fees     # ~500ms, 1 API call for 14 chains

# Individual requests now use cached batch data
curl http://localhost:8000/api/osmosis/stats/fees # ~50ms, 0 API calls
```

## Notes

- The current implementation uses estimated daily rates based on typical Cosmos staking APRs (~18%)
- For production, consider tracking historical redemption rates for more accurate calculations
- Price caching is in-memory per instance; consider Redis for multi-instance deployments
- Cache duration (5 minutes) can be adjusted in `stride_client.py:_cache_duration`

## License

MIT
