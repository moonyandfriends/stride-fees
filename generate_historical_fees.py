"""
Generate historical fee data for Stride protocol
Fetches historical prices and calculates fees from June 13, 2025 to present
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

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class HistoricalFeeGenerator:
    """Generate historical fee data using CoinGecko price history and Stride staking data"""

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

    async def get_historical_price(self, chain: str, date: datetime) -> float:
        """
        Get historical token price for a specific date using CoinGecko

        Args:
            chain: Chain name
            date: Date to fetch price for

        Returns:
            Price in USD or None if not available
        """
        try:
            coingecko_id = self.stride_client.COINGECKO_IDS.get(chain)
            if not coingecko_id:
                logger.warning(f"No CoinGecko ID for {chain}")
                return None

            # Format date as dd-mm-yyyy for CoinGecko API
            date_str = date.strftime("%d-%m-%Y")

            url = f"{self.stride_client.price_api_url}/coins/{coingecko_id}/history"
            params = {
                "date": date_str,
                "localization": "false"
            }

            response = await self.client.get(url, params=params)

            # Handle rate limiting
            if response.status_code == 429:
                logger.warning(f"Rate limited, waiting 60 seconds...")
                await asyncio.sleep(60)
                response = await self.client.get(url, params=params)

            response.raise_for_status()
            data = response.json()

            # Extract price from response
            price = data.get("market_data", {}).get("current_price", {}).get("usd")

            if price is not None:
                logger.info(f"Fetched price for {chain} on {date_str}: ${price}")
                return float(price)
            else:
                logger.warning(f"No price data for {chain} on {date_str}")
                return None

        except Exception as e:
            logger.error(f"Failed to fetch historical price for {chain} on {date}: {e}")
            return None

    async def get_current_staking_data(self, chain: str) -> Dict:
        """
        Get current staking data from Stride blockchain
        This will be used as a proxy for historical data

        Returns:
            Dict with redemption_rate and staked_amount
        """
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

    async def calculate_historical_fees(
        self,
        chain: str,
        date: datetime,
        staking_data: Dict,
        historical_price: float
    ) -> Dict:
        """
        Calculate fees for a specific chain and date

        Args:
            chain: Chain name
            date: Date to calculate fees for
            staking_data: Current staking data (redemption rate, staked amount)
            historical_price: Historical token price in USD

        Returns:
            Dict with dailyFees and dailyRevenue
        """
        try:
            if not staking_data or historical_price is None:
                return {
                    "chain": chain,
                    "date": date.strftime("%Y-%m-%d"),
                    "dailyFees": 0.0,
                    "dailyRevenue": 0.0
                }

            redemption_rate = staking_data["redemption_rate"]
            staked_amount = staking_data["staked_amount"]

            # Calculate total value in native tokens
            total_native_value = staked_amount * redemption_rate

            # Daily rewards using estimated rate (~18% APR)
            estimated_daily_rate = 0.0005
            daily_rewards_native = total_native_value * estimated_daily_rate

            # Get decimals for this chain
            decimals = self.stride_client.TOKEN_DECIMALS.get(chain, 6)
            divisor = 10 ** decimals

            # Calculate fees in USD using historical price
            daily_fees_usd = daily_rewards_native * historical_price / divisor

            # Revenue is 10% of fees
            daily_revenue_usd = daily_fees_usd * 0.10

            return {
                "chain": chain,
                "date": date.strftime("%Y-%m-%d"),
                "dailyFees": round(daily_fees_usd, 2),
                "dailyRevenue": round(daily_revenue_usd, 2)
            }

        except Exception as e:
            logger.error(f"Failed to calculate fees for {chain} on {date}: {e}")
            return {
                "chain": chain,
                "date": date.strftime("%Y-%m-%d"),
                "dailyFees": 0.0,
                "dailyRevenue": 0.0
            }

    async def generate_historical_data(
        self,
        start_date: datetime,
        end_date: datetime,
        output_file: str = "stride_historical_fees.csv"
    ):
        """
        Generate historical fee data for all chains and dates

        Args:
            start_date: Start date for data collection
            end_date: End date for data collection
            output_file: Output CSV filename
        """
        logger.info(f"Generating historical data from {start_date} to {end_date}")

        # Get current staking data for all chains (proxy for historical)
        logger.info("Fetching current staking data for all chains...")
        staking_data_by_chain = {}
        for chain in self.chains:
            staking_data = await self.get_current_staking_data(chain)
            if staking_data:
                staking_data_by_chain[chain] = staking_data

        logger.info(f"Fetched staking data for {len(staking_data_by_chain)} chains")

        # Prepare CSV file
        with open(output_file, 'w', newline='') as csvfile:
            fieldnames = ['chain', 'date', 'dailyFees', 'dailyRevenue']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            # Iterate through each date
            current_date = start_date
            while current_date <= end_date:
                logger.info(f"\nProcessing date: {current_date.strftime('%Y-%m-%d')}")

                # Process each chain for this date
                for chain in self.chains:
                    if chain not in staking_data_by_chain:
                        logger.warning(f"No staking data for {chain}, skipping")
                        continue

                    # Fetch historical price
                    historical_price = await self.get_historical_price(chain, current_date)

                    # Add delay to avoid rate limiting (CoinGecko free tier)
                    await asyncio.sleep(1.5)  # ~40 requests per minute

                    # Calculate fees
                    fee_data = await self.calculate_historical_fees(
                        chain,
                        current_date,
                        staking_data_by_chain[chain],
                        historical_price
                    )

                    # Write to CSV
                    writer.writerow(fee_data)
                    csvfile.flush()  # Ensure data is written immediately

                    logger.info(
                        f"  {chain}: ${fee_data['dailyFees']:.2f} fees, "
                        f"${fee_data['dailyRevenue']:.2f} revenue"
                    )

                # Move to next day
                current_date += timedelta(days=1)

        logger.info(f"\nHistorical data written to {output_file}")


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

    generator = HistoricalFeeGenerator(stride_client)

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
