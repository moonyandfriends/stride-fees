"""
Client for querying Stride blockchain data
"""
import httpx
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)


class StrideClient:
    """Client for interacting with Stride blockchain API"""

    # Mapping of DefiLlama chain names to Stride host zone chain IDs
    CHAIN_ID_MAP = {
        "cosmos": "cosmoshub-4",
        "celestia": "celestia",
        "osmosis": "osmosis-1",
        "dydx": "dydx-mainnet-1",
        "dymension": "dymension_1100-1",
        "juno": "juno-1",
        "stargaze": "stargaze-1",
        "terra": "phoenix-1",  # terra2
        "terra2": "phoenix-1",
        "evmos": "evmos_9001-2",
        "injective": "injective-1",
        "umee": "umee-1",
        "comdex": "comdex-1",
        "haqq": "haqq_11235-1",
        "band": "laozi-mainnet",
    }

    # CoinGecko IDs for price fetching
    COINGECKO_IDS = {
        "cosmos": "cosmos",
        "celestia": "celestia",
        "osmosis": "osmosis",
        "dydx": "dydx-chain",
        "dymension": "dymension",
        "juno": "juno-network",
        "stargaze": "stargaze",
        "terra": "terra-luna-2",
        "terra2": "terra-luna-2",
        "evmos": "evmos",
        "injective": "injective-protocol",
        "umee": "umee",
        "comdex": "comdex",
        "haqq": "islamic-coin",
        "band": "band-protocol",
    }

    # Token decimals (most Cosmos chains use 6, but some use 18)
    TOKEN_DECIMALS = {
        "cosmos": 6,      # uatom
        "celestia": 6,    # utia
        "osmosis": 6,     # uosmo
        "dydx": 18,       # adydx (18 decimals like Ethereum)
        "dymension": 18,  # adym
        "juno": 6,        # ujuno
        "stargaze": 6,    # ustars
        "terra": 6,       # uluna
        "terra2": 6,      # uluna
        "evmos": 18,      # aevmos
        "injective": 18,  # inj
        "umee": 6,        # uumee
        "comdex": 6,      # ucmdx
        "haqq": 18,       # aISLM
        "band": 6,        # uband
    }

    def __init__(self, api_url: str, rpc_url: str, price_api_url: str = "https://api.coingecko.com/api/v3"):
        self.api_url = api_url.rstrip("/")
        self.rpc_url = rpc_url.rstrip("/")
        self.price_api_url = price_api_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)

        # Price caching
        self._price_cache: Dict[str, Dict] = {}  # {chain: {"price": float, "timestamp": datetime}}
        self._cache_duration = timedelta(minutes=5)  # Cache prices for 5 minutes
        self._price_fetch_lock = asyncio.Lock()  # Prevent concurrent fetches

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    async def get_host_zones(self) -> List[Dict]:
        """Query all host zones from Stride"""
        try:
            url = f"{self.api_url}/Stride-Labs/stride/stakeibc/host_zone"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("host_zone", [])
        except Exception as e:
            logger.error(f"Failed to fetch host zones: {e}")
            raise

    async def get_host_zone(self, chain_id: str) -> Optional[Dict]:
        """Query a specific host zone by chain ID"""
        try:
            url = f"{self.api_url}/Stride-Labs/stride/stakeibc/host_zone/{chain_id}"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("host_zone")
        except Exception as e:
            logger.warning(f"Failed to fetch host zone for {chain_id}: {e}")
            return None

    async def get_sttoken_supply(self, denom: str) -> Optional[float]:
        """Get the total supply of a stToken"""
        try:
            url = f"{self.api_url}/cosmos/bank/v1beta1/supply/by_denom"
            params = {"denom": denom}
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            amount = data.get("amount", {}).get("amount", "0")
            return float(amount)
        except Exception as e:
            logger.warning(f"Failed to fetch supply for {denom}: {e}")
            return None

    def _is_price_cached(self, chain: str) -> bool:
        """Check if price is cached and still valid"""
        if chain not in self._price_cache:
            return False

        cached_data = self._price_cache[chain]
        age = datetime.now() - cached_data["timestamp"]
        return age < self._cache_duration

    async def get_token_prices_batch(self, chains: List[str]) -> Dict[str, Optional[float]]:
        """
        Fetch multiple token prices in a single request (batch)
        Uses caching to avoid redundant API calls
        """
        async with self._price_fetch_lock:
            # Separate cached and uncached chains
            prices = {}
            chains_to_fetch = []

            for chain in chains:
                if self._is_price_cached(chain):
                    prices[chain] = self._price_cache[chain]["price"]
                    logger.debug(f"Using cached price for {chain}: ${prices[chain]}")
                else:
                    chains_to_fetch.append(chain)

            # Fetch uncached prices in batch
            if chains_to_fetch:
                try:
                    # Get CoinGecko IDs for chains that need fetching
                    coingecko_ids = []
                    chain_id_map = {}  # Map coingecko_id -> chain
                    for chain in chains_to_fetch:
                        coingecko_id = self.COINGECKO_IDS.get(chain)
                        if coingecko_id:
                            coingecko_ids.append(coingecko_id)
                            chain_id_map[coingecko_id] = chain

                    if coingecko_ids:
                        # Batch request for all uncached prices
                        url = f"{self.price_api_url}/simple/price"
                        params = {
                            "ids": ",".join(coingecko_ids),
                            "vs_currencies": "usd"
                        }
                        logger.info(f"Fetching batch prices for: {', '.join(chains_to_fetch)}")
                        response = await self.client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()

                        # Cache and store results
                        now = datetime.now()
                        for coingecko_id, chain in chain_id_map.items():
                            price = data.get(coingecko_id, {}).get("usd")
                            if price is not None:
                                prices[chain] = price
                                self._price_cache[chain] = {
                                    "price": price,
                                    "timestamp": now
                                }
                                logger.info(f"Cached price for {chain}: ${price}")
                            else:
                                prices[chain] = None
                                logger.warning(f"No price data for {chain}")
                    else:
                        logger.warning(f"No CoinGecko IDs found for: {chains_to_fetch}")

                except Exception as e:
                    logger.error(f"Failed to fetch batch prices: {e}")
                    # Fill in None for failed chains
                    for chain in chains_to_fetch:
                        if chain not in prices:
                            prices[chain] = None

            return prices

    async def get_token_price(self, chain: str) -> Optional[float]:
        """Get USD price for a token using CoinGecko (with caching)"""
        # Check cache first
        if self._is_price_cached(chain):
            price = self._price_cache[chain]["price"]
            logger.debug(f"Using cached price for {chain}: ${price}")
            return price

        # Fetch single price (will be cached)
        prices = await self.get_token_prices_batch([chain])
        return prices.get(chain)

    async def calculate_daily_fee(self, chain: str) -> Dict[str, float]:
        """
        Calculate daily fees for a specific chain

        Returns:
            Dict with dailyFees and dailyRevenue (10% of fees)
        """
        try:
            # Get chain ID
            chain_id = self.CHAIN_ID_MAP.get(chain.lower())
            if not chain_id:
                raise ValueError(f"Unknown chain: {chain}")

            # Get host zone data
            host_zone = await self.get_host_zone(chain_id)
            if not host_zone:
                raise ValueError(f"Host zone not found for {chain_id}")

            # Extract redemption rate and staked amount
            redemption_rate = float(host_zone.get("redemption_rate", "1.0"))
            staked_amount_str = host_zone.get("total_delegations", "0")
            staked_amount = float(staked_amount_str)

            # Get stToken supply (this represents total liquid staked)
            st_denom = host_zone.get("host_denom", "")
            if st_denom.startswith("u"):
                # Convert to st token denom (e.g., uatom -> stuatom)
                st_denom = f"st{st_denom}"

            # Calculate total value in native tokens
            # stToken supply * redemption rate = total native tokens
            total_native_value = staked_amount * redemption_rate

            # Calculate daily rewards (approximate based on typical staking APR)
            # This is a simplified calculation - in production you'd track historical redemption rates
            # Typical cosmos chain APR is around 15-20% annually
            # Daily rate ≈ annual_rate / 365
            estimated_daily_rate = 0.0005  # ~18% APR / 365
            daily_rewards_native = total_native_value * estimated_daily_rate

            # Get USD price
            token_price = await self.get_token_price(chain)
            if not token_price:
                logger.warning(f"Could not get price for {chain}, using $0")
                token_price = 0.0

            # Get the correct decimal places for this chain
            decimals = self.TOKEN_DECIMALS.get(chain, 6)  # Default to 6 if unknown
            divisor = 10 ** decimals

            # Calculate fees in USD
            # Fees are the total rewards earned by stakers
            daily_fees_usd = daily_rewards_native * token_price / divisor

            # Revenue is 10% of fees (Stride's cut)
            daily_revenue_usd = daily_fees_usd * 0.10

            return {
                "dailyFees": daily_fees_usd,
                "dailyRevenue": daily_revenue_usd
            }

        except Exception as e:
            logger.error(f"Failed to calculate fees for {chain}: {e}")
            raise
