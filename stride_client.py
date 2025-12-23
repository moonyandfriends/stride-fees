"""
Client for querying Stride blockchain data
"""
import httpx
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
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

    # API endpoints for each chain to query staking parameters
    CHAIN_API_URLS = {
        "cosmos": "https://cosmos-api.polkachu.com",
        "celestia": "https://celestia-api.polkachu.com",
        "osmosis": "https://osmosis-api.polkachu.com",
        "dydx": "https://dydx-api.polkachu.com",
        "dymension": "https://dymension-api.polkachu.com",
        "juno": "https://juno-api.polkachu.com",
        "stargaze": "https://stargaze-api.polkachu.com",
        "terra2": "https://terra-api.polkachu.com",
        "evmos": "https://evmos-api.polkachu.com",
        "injective": "https://injective-api.polkachu.com",
        "umee": "https://umee-api.polkachu.com",
        "comdex": "https://comdex-api.polkachu.com",
        "haqq": "https://haqq-api.polkachu.com",
        "band": "https://band-api.polkachu.com",
    }

    # Fallback APRs (used if chain query fails)
    # These values are typical/average rates - actual rates fluctuate over time
    # Sources: Mintscan, StakingRewards.com, dYdX Foundation, chain explorers (Dec 2024)
    STAKING_APRS = {
        "cosmos": 0.17,      # ~17% APR
        "celestia": 0.08,    # ~8% APR (updated from on-chain data)
        "osmosis": 0.015,    # ~1.5% APR (only 8% of mint goes to staking)
        "dydx": 0.07,        # ~7% APR (dYdX Foundation: ~6.36%)
        "dymension": 0.22,   # ~22% APR
        "juno": 0.30,        # ~30% APR
        "stargaze": 0.10,    # ~10% APR (sources: 8-13%, some up to 26%)
        "terra": 0.20,       # ~20% APR (sources: 18-32%)
        "terra2": 0.20,      # ~20% APR (sources: 18-32%)
        "evmos": 0.02,       # ~2% APR (TC Network: 1.49%, conservative estimate)
        "injective": 0.10,   # ~10% APR
        "umee": 0.17,        # ~17% APR
        "comdex": 0.25,      # ~25% APR
        "haqq": 0.12,        # ~12% APR
        "band": 0.12,        # ~12% APR
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

        # APR caching (cache for 1 hour since APRs change slowly)
        self._apr_cache: Dict[str, Dict] = {}  # {chain: {"apr": float, "timestamp": datetime}}
        self._apr_cache_duration = timedelta(hours=1)

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    async def get_chain_apr(self, chain: str) -> float:
        """
        Get APR for a chain - queries from chain if possible, falls back to hardcoded value

        Args:
            chain: Chain name

        Returns:
            APR as decimal (e.g., 0.17 for 17%)
        """
        chain_lower = chain.lower()

        # Check cache first
        if chain_lower in self._apr_cache:
            cached_data = self._apr_cache[chain_lower]
            age = datetime.now() - cached_data["timestamp"]
            if age < self._apr_cache_duration:
                logger.debug(f"Using cached APR for {chain}: {cached_data['apr']*100:.2f}%")
                return cached_data["apr"]

        # Try to query from chain
        chain_api_url = self.CHAIN_API_URLS.get(chain_lower)
        if chain_api_url:
            queried_apr = await self.query_chain_apr(chain_lower, chain_api_url)
            if queried_apr is not None:
                # Cache the result
                self._apr_cache[chain_lower] = {
                    "apr": queried_apr,
                    "timestamp": datetime.now()
                }
                return queried_apr

        # Fall back to hardcoded value
        fallback_apr = self.STAKING_APRS.get(chain_lower, 0.18)
        logger.info(f"Using fallback APR for {chain}: {fallback_apr*100:.1f}%")
        return fallback_apr

    async def query_osmosis_apr(self, chain_api_url: str) -> Optional[float]:
        """
        Query actual APR from Osmosis chain (uses custom mint module)

        Args:
            chain_api_url: API endpoint for Osmosis (e.g., https://osmosis-api.polkachu.com)

        Returns:
            Calculated APR as decimal or None if query fails
        """
        try:
            # Query epoch provisions (daily minting)
            provisions_url = f"{chain_api_url}/osmosis/mint/v1beta1/epoch_provisions"
            provisions_resp = await self.client.get(provisions_url)
            provisions_resp.raise_for_status()
            provisions_data = provisions_resp.json()
            epoch_provisions = float(provisions_data.get("epoch_provisions", "0"))

            # Query mint params to get staking distribution proportion
            params_url = f"{chain_api_url}/osmosis/mint/v1beta1/params"
            params_resp = await self.client.get(params_url)
            params_resp.raise_for_status()
            params_data = params_resp.json()
            staking_proportion = float(
                params_data.get("params", {})
                .get("distribution_proportions", {})
                .get("staking", "0")
            )

            # Query bonded tokens
            pool_url = f"{chain_api_url}/cosmos/staking/v1beta1/pool"
            pool_resp = await self.client.get(pool_url)
            pool_resp.raise_for_status()
            pool_data = pool_resp.json()
            bonded = float(pool_data.get("pool", {}).get("bonded_tokens", "0"))

            if bonded == 0:
                logger.warning("Zero bonded tokens for Osmosis")
                return None

            # Calculate APR
            # (epoch_provisions * staking_proportion * 365) / bonded_tokens
            # epoch_provisions is per day (epoch_identifier = "day")
            annual_staking_rewards = epoch_provisions * staking_proportion * 365
            apr = annual_staking_rewards / bonded

            logger.info(f"Calculated Osmosis APR: {apr*100:.2f}% (staking_proportion={staking_proportion*100:.1f}%)")
            return apr

        except Exception as e:
            logger.warning(f"Failed to query Osmosis APR: {e}")
            return None

    async def query_celestia_apr(self, chain_api_url: str) -> Optional[float]:
        """
        Query actual APR from Celestia chain (uses custom mint module)

        Args:
            chain_api_url: API endpoint for Celestia

        Returns:
            Calculated APR as decimal or None if query fails
        """
        try:
            # Celestia doesn't expose standard inflation endpoints
            # Try to calculate from params if available
            # For now, return None and use fallback
            # TODO: Find proper Celestia inflation endpoint
            return None

        except Exception as e:
            logger.warning(f"Failed to query Celestia APR: {e}")
            return None

    async def query_chain_apr(self, chain: str, chain_api_url: str) -> Optional[float]:
        """
        Query actual APR from a Cosmos chain's staking parameters

        Args:
            chain: Chain name
            chain_api_url: API endpoint for the chain (e.g., https://cosmos-api.polkachu.com)

        Returns:
            Calculated APR as decimal (e.g., 0.17 for 17%) or None if query fails
        """
        # Use chain-specific methods for chains with custom mint modules
        if chain == "osmosis":
            return await self.query_osmosis_apr(chain_api_url)
        elif chain == "celestia":
            return await self.query_celestia_apr(chain_api_url)

        # Standard Cosmos SDK inflation calculation for other chains
        try:
            # Query inflation rate
            inflation_url = f"{chain_api_url}/cosmos/mint/v1beta1/inflation"
            inflation_resp = await self.client.get(inflation_url)
            inflation_resp.raise_for_status()
            inflation_data = inflation_resp.json()
            inflation = float(inflation_data.get("inflation", "0"))

            # Query bonded tokens ratio
            pool_url = f"{chain_api_url}/cosmos/staking/v1beta1/pool"
            pool_resp = await self.client.get(pool_url)
            pool_resp.raise_for_status()
            pool_data = pool_resp.json()

            bonded = float(pool_data.get("pool", {}).get("bonded_tokens", "0"))
            not_bonded = float(pool_data.get("pool", {}).get("not_bonded_tokens", "0"))
            total_supply = bonded + not_bonded

            if total_supply == 0:
                logger.warning(f"Zero total supply for {chain}")
                return None

            bonded_ratio = bonded / total_supply

            # Query community tax
            try:
                params_url = f"{chain_api_url}/cosmos/distribution/v1beta1/params"
                params_resp = await self.client.get(params_url)
                params_resp.raise_for_status()
                params_data = params_resp.json()
                community_tax = float(params_data.get("params", {}).get("community_tax", "0"))
            except:
                community_tax = 0.02  # Default 2% if query fails

            # Calculate APR: inflation * (1 - community_tax) / bonded_ratio
            # This gives the base staking APR before validator commission
            apr = inflation * (1 - community_tax) / bonded_ratio if bonded_ratio > 0 else 0

            logger.info(f"Calculated APR for {chain}: {apr*100:.2f}% (inflation={inflation*100:.2f}%, bonded={bonded_ratio*100:.2f}%)")
            return apr

        except Exception as e:
            logger.warning(f"Failed to query APR for {chain} from {chain_api_url}: {e}")
            return None

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

            # Extract staked amount from host zone
            # total_delegations represents the total native tokens delegated by Stride
            staked_amount_str = host_zone.get("total_delegations", "0")
            staked_amount = float(staked_amount_str)

            # Get chain-specific APR (queries from chain, falls back to hardcoded)
            annual_apr = await self.get_chain_apr(chain)
            daily_rate = annual_apr / 365  # Convert annual rate to daily rate

            logger.info(f"Using APR {annual_apr*100:.1f}% ({daily_rate*100:.4f}% daily) for {chain}")

            # Calculate daily rewards based on total delegations
            # Note: We use total_delegations directly, NOT total_delegations * redemption_rate
            # because total_delegations already represents the total native tokens delegated
            daily_rewards_native = staked_amount * daily_rate

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

    def load_snapshots(self) -> Optional[Dict]:
        """
        Load redemption rate snapshots from file

        Returns:
            Dict with snapshot data or None if file doesn't exist
        """
        # Use Railway volume path if available, otherwise local directory
        import os
        snapshot_data_dir = os.getenv("SNAPSHOT_DATA_DIR")
        if snapshot_data_dir:
            snapshot_file = Path(snapshot_data_dir) / "redemption_rate_snapshots.json"
        else:
            snapshot_file = Path(__file__).parent / "redemption_rate_snapshots.json"

        if not snapshot_file.exists():
            logger.debug(f"No snapshot file at {snapshot_file}")
            return None

        try:
            with open(snapshot_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load snapshots: {e}")
            return None

    def get_snapshot_for_date(self, date: str) -> Optional[Dict]:
        """
        Get snapshot for a specific date (YYYY-MM-DD)

        Args:
            date: Date string in YYYY-MM-DD format

        Returns:
            Snapshot dict or None if not found
        """
        data = self.load_snapshots()
        if not data:
            return None

        snapshots = data.get("snapshots", [])
        for snapshot in snapshots:
            if snapshot.get("date") == date:
                return snapshot

        return None

    async def calculate_daily_fee_from_snapshots(self, chain: str) -> Optional[Dict[str, float]]:
        """
        Calculate daily fees using redemption rate snapshots (more accurate than APR)

        This method looks for snapshots from today and yesterday, calculates the
        redemption rate change, and computes actual rewards earned.

        Args:
            chain: Chain name (e.g., "cosmos", "osmosis")

        Returns:
            Dict with dailyFees and dailyRevenue, or None if snapshot data unavailable
        """
        try:
            # Get today and yesterday's dates
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            yesterday_dt = datetime.now(timezone.utc) - timedelta(days=1)
            yesterday = yesterday_dt.strftime("%Y-%m-%d")

            # Load snapshots
            snapshot_today = self.get_snapshot_for_date(today)
            snapshot_yesterday = self.get_snapshot_for_date(yesterday)

            if not snapshot_today or not snapshot_yesterday:
                logger.debug(f"Missing snapshots for {chain} (today: {snapshot_today is not None}, yesterday: {snapshot_yesterday is not None})")
                return None

            # Get chain data from snapshots
            chain_today = snapshot_today.get("chains", {}).get(chain)
            chain_yesterday = snapshot_yesterday.get("chains", {}).get(chain)

            if not chain_today or not chain_yesterday:
                logger.debug(f"Missing chain data for {chain} in snapshots")
                return None

            # Extract redemption rates and stToken supply
            rr_today = float(chain_today.get("redemption_rate", 0))
            rr_yesterday = float(chain_yesterday.get("redemption_rate", 0))
            sttoken_supply = float(chain_today.get("sttoken_supply", 0))

            if rr_today == 0 or rr_yesterday == 0 or sttoken_supply == 0:
                logger.warning(f"Invalid snapshot data for {chain}: rr_today={rr_today}, rr_yesterday={rr_yesterday}, supply={sttoken_supply}")
                return None

            # Calculate actual daily rewards from redemption rate change
            rr_change = rr_today - rr_yesterday
            daily_rewards_native = sttoken_supply * rr_change

            # Handle negative changes (shouldn't happen normally, but could due to slashing)
            if daily_rewards_native < 0:
                logger.warning(f"Negative rewards for {chain}: {daily_rewards_native} (slashing event?)")
                daily_rewards_native = 0

            # Get USD price
            token_price = await self.get_token_price(chain)
            if not token_price:
                logger.warning(f"Could not get price for {chain}")
                token_price = 0.0

            # Get decimals and convert to USD
            decimals = self.TOKEN_DECIMALS.get(chain, 6)
            divisor = 10 ** decimals

            daily_fees_usd = daily_rewards_native * token_price / divisor
            daily_revenue_usd = daily_fees_usd * 0.10

            logger.info(f"[SNAPSHOT] {chain}: RR change {rr_change:.10f} → ${daily_fees_usd:,.2f} fees")

            return {
                "dailyFees": daily_fees_usd,
                "dailyRevenue": daily_revenue_usd,
                "method": "redemption_rate_snapshot"
            }

        except Exception as e:
            logger.warning(f"Failed to calculate fees from snapshots for {chain}: {e}")
            return None
