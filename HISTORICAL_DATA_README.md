# Historical Fee Data Generation

This directory contains scripts to generate historical fee data for Stride protocol from June 13, 2025 to December 19, 2025.

## Current Status

✅ **Partial data generated**: `stride_historical_fees.csv` contains data for June 13-15, 2025
⚠️ **CoinGecko Rate Limiting**: The free tier has strict limits preventing rapid data fetching

## Generated Files

- `stride_historical_fees.csv` - Partial historical fee data (currently June 13-15, 2025)
- `generate_historical_fees_optimized.py` - Optimized script using bulk price fetching
- `generate_historical_fees.py` - Original day-by-day script (slower)

## CSV Format

The generated CSV contains:
```csv
chain,date,dailyFees,dailyRevenue
cosmos,2025-06-13,15101.47,1510.15
celestia,2025-06-13,1025.58,102.56
...
```

- **chain**: Chain identifier (cosmos, celestia, osmosis, etc.)
- **date**: Date in YYYY-MM-DD format
- **dailyFees**: Total fees in USD
- **dailyRevenue**: Stride's revenue (10% of fees) in USD

## Rate Limiting Issue

CoinGecko's **free tier** has severe rate limits:
- ~10-50 requests per minute
- Our data generation requires ~13 API calls (one per chain) for the full date range
- The script implements exponential backoff (60s, 120s, 240s, 300s...)

### Solutions to Complete Data Generation

#### Option 1: Let Script Run Overnight (Free)
The optimized script is currently running with exponential backoff. It will eventually complete, but may take several hours.

```bash
# Check if script is still running
ps aux | grep generate_historical_fees_optimized

# Monitor progress
tail -f /tmp/claude/-Users-steven-stride-fees/tasks/*.output

# Once complete, check the CSV
wc -l stride_historical_fees.csv  # Should have ~2,470 rows (190 days × 13 chains)
```

#### Option 2: Get CoinGecko API Key (Recommended for Production)
Sign up for a paid CoinGecko API plan with higher rate limits:

1. Visit https://www.coingecko.com/en/api/pricing
2. Get an API key
3. Modify the script to use the API key:

```python
# In generate_historical_fees_optimized.py, add:
headers = {"x-cg-pro-api-key": "YOUR_API_KEY_HERE"}
response = await self.client.get(url, params=params, headers=headers)
```

4. Update the `price_api_url` to use the pro endpoint:
```python
PRICE_API_URL=https://pro-api.coingecko.com/api/v3
```

#### Option 3: Run in Chunks
Modify the date range to generate data in smaller chunks:

```python
# Run for each month separately
python3 generate_historical_fees_optimized.py

# Then manually edit the dates in main():
start_date = datetime(2025, 6, 13)   # June
end_date = datetime(2025, 6, 30)

# Then July, August, etc.
# Combine CSV files afterward
```

#### Option 4: Use Alternative Price API
Replace CoinGecko with another price API that has better free tier limits:
- CoinCap API (https://coincap.io/)
- CryptoCompare API (https://min-api.cryptocompare.com/)
- Messari API (https://messari.io/api)

## Methodology Notes

### Current Implementation

1. **Staking Data**: Uses current staking amounts from Stride blockchain (proxy for historical)
2. **Redemption Rates**: Uses current redemption rates
3. **Chain-Specific APRs**: **Queries real-time APR from each chain** using:
   - Inflation rate from `/cosmos/mint/v1beta1/inflation`
   - Bonded ratio from `/cosmos/staking/v1beta1/pool`
   - Community tax from `/cosmos/distribution/v1beta1/params`
   - Formula: `APR = inflation × (1 - community_tax) / bonded_ratio`
   - Falls back to hardcoded estimates if chain query fails
   - Cached for 1 hour to reduce API calls
4. **Historical Prices**: Fetches actual historical token prices from CoinGecko

**Example Real APRs** (as of December 2025):
- Cosmos Hub: 10.13% (inflation 10%, bonded 96.77%)
- Celestia: ~12%
- Osmosis: ~25% (including external incentives)

### Limitations

- **Staking amounts are current, not historical**: Real historical data would require querying past blockchain state
- **Fixed APR assumption**: Actual daily rewards vary based on network conditions
- **Dymension excluded**: Host zone returns 500 error

### For More Accurate Historical Data

To get true historical fee data, you would need to:

1. Query historical blockchain state for each day (requires archive node)
2. Track actual redemption rate changes over time
3. Calculate real rewards based on chain-specific staking parameters

## Running the Scripts

### Optimized Version (Recommended)
```bash
python3 generate_historical_fees_optimized.py
```

Features:
- Fetches price ranges in bulk (one API call per chain)
- Reduces total API calls from ~2,470 to ~13
- Implements exponential backoff for rate limits
- Progress logging

### Original Version
```bash
python3 generate_historical_fees.py
```

Features:
- Fetches prices day-by-day
- More granular progress updates
- Slower but more resilient to partial failures

## Examining the Data

```bash
# View first 20 lines
head -20 stride_historical_fees.csv

# Count total rows
wc -l stride_historical_fees.csv

# Filter by chain
grep "^cosmos," stride_historical_fees.csv

# Calculate total fees for a chain
awk -F',' '$1=="cosmos" {sum+=$3} END {print sum}' stride_historical_fees.csv

# View data in columns (requires column command)
column -t -s',' stride_historical_fees.csv | less
```

## Next Steps

1. **Wait for script to complete** (check with `ps aux | grep python3`)
2. **Verify data completeness**: Should have 190 days × 13 chains = 2,470 rows
3. **Upload to Google Sheets** or analyze with pandas/Excel
4. **Consider getting API key** for future data updates

## Questions or Issues?

- Check logs for API errors or rate limiting messages
- Verify CoinGecko service status at https://status.coingecko.com/
- Consider running during off-peak hours for better API availability
