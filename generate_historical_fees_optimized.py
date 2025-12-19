"""
Optimized historical fee data generator using CoinGecko's range endpoint
Fetches price ranges instead of individual days to minimize API calls
"""
import asyncio
import csv
from datetime import datetime, timedelta
from typing import List, Dict
import httpx
import logging
from stride_client import StrideClient
from dotenv import load_dotenv
import os
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OptimizedHistoricalFeeGenerator:
    """Generate historical fee data using CoinGecko's market_chart/range endpoint"""

    def __init__(self, stride_client: StrideClient):
        self.stride_client = stride_client
        self.client = httpx.AsyncClient(timeout=60.0)

        # All supported chains
        self.chains = [
            "cosmos", "celestia", "osmosis", "dydx", "dymension",
            "juno", "stargaze", "terra2", "evmos", "injective",
            "umee", "comdex", "haqq", "band"
        ]

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def get_price_range(
        self,
        chain: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, float]:
        """
        Get historical prices for a date range using CoinGecko's market_chart/range

        Args:
            chain: Chain name
            start_date: Start date
            end_date: End date

        Returns:
            Dict mapping date string (YYYY-MM-DD) to price
        """
        try:
            coingecko_id = self.stride_client.COINGECKO_IDS.get(chain)
            if not coingecko_id:
                logger.warning(f"No CoinGecko ID for {chain}")
                return {}

            # Convert to Unix timestamps
            from_timestamp = int(start_date.timestamp())
            to_timestamp = int(end_date.timestamp())

            url = f"{self.stride_client.price_api_url}/coins/{coingecko_id}/market_chart/range"
            params = {
                "vs_currency": "usd",
                "from": from_timestamp,
                "to": to_timestamp
            }

            logger.info(f"Fetching price range for {chain} from {start_date.date()} to {end_date.date()}")

            response = await self.client.get(url, params=params)

            # Handle rate limiting with exponential backoff
            retry_count = 0
            while response.status_code == 429 and retry_count < 5:
                wait_time = min(60 * (2 ** retry_count), 300)  # Max 5 minutes
                logger.warning(f"Rate limited, waiting {wait_time} seconds... (attempt {retry_count + 1})")
                await asyncio.sleep(wait_time)
                retry_count += 1
                response = await self.client.get(url, params=params)

            response.raise_for_status()
            data = response.json()

            # Extract prices and map to dates
            # market_chart returns [[timestamp_ms, price], ...]
            prices_by_date = {}
            if "prices" in data:
                for timestamp_ms, price in data["prices"]:
                    # Convert timestamp to date
                    dt = datetime.fromtimestamp(timestamp_ms / 1000)
                    date_key = dt.strftime("%Y-%m-%d")
                    # Use the first price we see for each day (midnight UTC)
                    if date_key not in prices_by_date:
                        prices_by_date[date_key] = price

            logger.info(f"Fetched {len(prices_by_date)} daily prices for {chain}")
            return prices_by_date

        except Exception as e:
            logger.error(f"Failed to fetch price range for {chain}: {e}")
            return {}

    async def get_current_staking_data(self, chain: str) -> Dict:
        """Get current staking data from Stride blockchain"""
        try:
            chain_id = self.stride_client.CHAIN_ID_MAP.get(chain.lower())
            if not chain_id:
                raise ValueError(f"Unknown chain: {chain}")

            host_zone = await self.stride_client.get_host_zone(chain_id)
            if not host_zone:
                raise ValueError(f"Host zone not found for {chain_id}")

            redemption_rate = float(host_zone.get("redemption_rate", "1.0"))
            staked_amount = float(host_zone.get("total_delegations", "0"))

            return {
                "redemption_rate": redemption_rate,
                "staked_amount": staked_amount
            }

        except Exception as e:
            logger.error(f"Failed to get staking data for {chain}: {e}")
            return None

    async def calculate_fees(
        self,
        chain: str,
        staking_data: Dict,
        price: float
    ) -> Dict:
        """Calculate fees for given staking data and price"""
        try:
            if not staking_data or price is None:
                return {"dailyFees": 0.0, "dailyRevenue": 0.0}

            redemption_rate = staking_data["redemption_rate"]
            staked_amount = staking_data["staked_amount"]

            # Calculate total value in native tokens
            total_native_value = staked_amount * redemption_rate

            # Get chain-specific APR (queries from chain, falls back to hardcoded)
            annual_apr = await self.stride_client.get_chain_apr(chain)
            daily_rate = annual_apr / 365  # Convert annual to daily rate
            daily_rewards_native = total_native_value * daily_rate

            # Get decimals for this chain
            decimals = self.stride_client.TOKEN_DECIMALS.get(chain, 6)
            divisor = 10 ** decimals

            # Calculate fees in USD
            daily_fees_usd = daily_rewards_native * price / divisor
            daily_revenue_usd = daily_fees_usd * 0.10

            return {
                "dailyFees": round(daily_fees_usd, 2),
                "dailyRevenue": round(daily_revenue_usd, 2)
            }

        except Exception as e:
            logger.error(f"Failed to calculate fees: {e}")
            return {"dailyFees": 0.0, "dailyRevenue": 0.0}

    async def generate_historical_data(
        self,
        start_date: datetime,
        end_date: datetime,
        output_file: str = "stride_historical_fees.csv"
    ):
        """Generate historical fee data for all chains and dates"""
        logger.info(f"Generating historical data from {start_date.date()} to {end_date.date()}")

        # Get current staking data for all chains
        logger.info("Fetching current staking data for all chains...")
        staking_data_by_chain = {}
        for chain in self.chains:
            staking_data = await self.get_current_staking_data(chain)
            if staking_data:
                staking_data_by_chain[chain] = staking_data
                logger.info(f"  {chain}: {staking_data['staked_amount']:.0f} staked")

        logger.info(f"\nFetched staking data for {len(staking_data_by_chain)} chains")

        # Fetch price ranges for all chains
        logger.info("\nFetching price ranges for all chains...")
        prices_by_chain = {}
        for i, chain in enumerate(self.chains):
            if chain not in staking_data_by_chain:
                logger.warning(f"Skipping {chain} (no staking data)")
                continue

            prices = await self.get_price_range(chain, start_date, end_date)
            prices_by_chain[chain] = prices

            # Rate limiting: ~10-15 requests per minute
            if i < len(self.chains) - 1:  # Don't sleep after last request
                await asyncio.sleep(6)  # 10 requests per minute

        logger.info(f"\nFetched price data for {len(prices_by_chain)} chains")

        # Generate date list
        dates = []
        current_date = start_date
        while current_date <= end_date:
            dates.append(current_date)
            current_date += timedelta(days=1)

        # Write CSV
        logger.info(f"\nWriting data to {output_file}...")
        with open(output_file, 'w', newline='') as csvfile:
            fieldnames = ['chain', 'date', 'dailyFees', 'dailyRevenue']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            rows_written = 0
            for date in dates:
                date_str = date.strftime("%Y-%m-%d")

                for chain in sorted(staking_data_by_chain.keys()):
                    # Get price for this date
                    chain_prices = prices_by_chain.get(chain, {})
                    price = chain_prices.get(date_str)

                    if price is None:
                        logger.warning(f"No price data for {chain} on {date_str}")
                        price = 0.0

                    # Calculate fees
                    fees = await self.calculate_fees(
                        chain,
                        staking_data_by_chain[chain],
                        price
                    )

                    # Write row
                    writer.writerow({
                        "chain": chain,
                        "date": date_str,
                        "dailyFees": fees["dailyFees"],
                        "dailyRevenue": fees["dailyRevenue"]
                    })

                    rows_written += 1

            csvfile.flush()

        logger.info(f"\n✅ Successfully wrote {rows_written} rows to {output_file}")
        logger.info(f"   Chains: {len(staking_data_by_chain)}")
        logger.info(f"   Days: {len(dates)}")
        logger.info(f"   Date range: {dates[0].date()} to {dates[-1].date()}")


async def main():
    """Main entry point"""
    # Initialize Stride client
    stride_api_url = os.getenv("STRIDE_API_URL", "https://stride-api.polkachu.com")
    stride_rpc_url = os.getenv("STRIDE_RPC_URL", "https://stride-rpc.polkachu.com")
    price_api_url = os.getenv("PRICE_API_URL", "https://api.coingecko.com/api/v3")

    stride_client = StrideClient(
        api_url=stride_api_url,
        rpc_url=stride_rpc_url,
        price_api_url=price_api_url
    )

    generator = OptimizedHistoricalFeeGenerator(stride_client)

    try:
        # Define date range: June 13, 2025 to December 19, 2025
        start_date = datetime(2025, 6, 13)
        end_date = datetime(2025, 12, 19)

        # Generate historical data
        await generator.generate_historical_data(start_date, end_date)

    finally:
        await generator.close()
        await stride_client.close()


if __name__ == "__main__":
    asyncio.run(main())
