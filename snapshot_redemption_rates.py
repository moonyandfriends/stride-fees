#!/usr/bin/env python3
"""
Daily Redemption Rate Snapshot Script

Run this script daily (via cron) to track redemption rate changes.
This enables accurate fee calculation without relying on APR estimates.

Usage:
    python3 snapshot_redemption_rates.py

Cron example (runs daily at midnight UTC):
    0 0 * * * cd /path/to/stride-fees && /usr/bin/python3 snapshot_redemption_rates.py
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
import os
from dotenv import load_dotenv
from stride_client import StrideClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Snapshot file path - use Railway volume if available, otherwise local directory
SNAPSHOT_DATA_DIR = os.getenv("SNAPSHOT_DATA_DIR")
if SNAPSHOT_DATA_DIR:
    SNAPSHOT_FILE = Path(SNAPSHOT_DATA_DIR) / "redemption_rate_snapshots.json"
    logger.info(f"Using persistent volume: {SNAPSHOT_FILE}")
else:
    SNAPSHOT_FILE = Path(__file__).parent / "redemption_rate_snapshots.json"
    logger.info(f"Using local directory: {SNAPSHOT_FILE}")


class RedemptionRateTracker:
    """Track redemption rates over time for accurate fee calculation"""

    def __init__(self, stride_client: StrideClient):
        self.client = stride_client
        # All chains with active Stride host zones (verified against Stride API)
        self.chains = [
            "cosmos", "celestia", "osmosis", "dydx",
            "juno", "stargaze", "terra2", "evmos", "injective",
            "umee", "comdex", "haqq", "band", "saga", "sommelier"
        ]

    async def get_snapshot(self) -> Dict:
        """
        Get current redemption rates and stToken supplies for all chains

        Returns:
            Dict with timestamp and per-chain data
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        snapshot = {
            "timestamp": timestamp,
            "date": date,
            "chains": {}
        }

        for chain in self.chains:
            try:
                chain_id = self.client.CHAIN_ID_MAP.get(chain)
                if not chain_id:
                    logger.warning(f"No chain ID mapping for {chain}")
                    continue

                # Get host zone data
                host_zone = await self.client.get_host_zone(chain_id)
                if not host_zone:
                    logger.warning(f"Could not fetch host zone for {chain_id}")
                    continue

                # Extract redemption rate and total delegations
                redemption_rate = float(host_zone.get("redemption_rate", "0"))
                total_delegations = float(host_zone.get("total_delegations", "0"))

                # Get stToken supply
                host_denom = host_zone.get("host_denom", "")
                st_denom = f"st{host_denom}"
                sttoken_supply = await self.client.get_sttoken_supply(st_denom)

                snapshot["chains"][chain] = {
                    "chain_id": chain_id,
                    "redemption_rate": redemption_rate,
                    "total_delegations": total_delegations,
                    "sttoken_supply": sttoken_supply or 0,
                    "st_denom": st_denom
                }

                logger.info(f"✓ {chain}: RR={redemption_rate:.6f}, Supply={sttoken_supply:,.0f}")

            except Exception as e:
                logger.error(f"Failed to snapshot {chain}: {e}")
                continue

        return snapshot

    def load_snapshots(self) -> Dict:
        """Load existing snapshots from file"""
        if not SNAPSHOT_FILE.exists():
            logger.info(f"No existing snapshot file at {SNAPSHOT_FILE}")
            return {"snapshots": []}

        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load snapshots: {e}")
            return {"snapshots": []}

    def save_snapshots(self, data: Dict):
        """Save snapshots to file"""
        try:
            with open(SNAPSHOT_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved snapshots to {SNAPSHOT_FILE}")
        except Exception as e:
            logger.error(f"Failed to save snapshots: {e}")

    async def take_snapshot(self):
        """Take a new snapshot and append to history"""
        logger.info("Taking redemption rate snapshot...")

        # Get new snapshot
        new_snapshot = await self.get_snapshot()

        # Load existing snapshots
        data = self.load_snapshots()
        snapshots = data.get("snapshots", [])

        # Check if we already have a snapshot for today
        today = new_snapshot["date"]
        existing_dates = [s["date"] for s in snapshots]

        if today in existing_dates:
            logger.info(f"Snapshot for {today} already exists, replacing...")
            snapshots = [s for s in snapshots if s["date"] != today]

        # Add new snapshot
        snapshots.append(new_snapshot)

        # Keep last 400 days of snapshots (about 13 months)
        if len(snapshots) > 400:
            snapshots = snapshots[-400:]
            logger.info(f"Trimmed to last 400 snapshots")

        # Save
        data["snapshots"] = snapshots
        data["last_updated"] = new_snapshot["timestamp"]
        self.save_snapshots(data)

        logger.info(f"Snapshot complete: {len(new_snapshot['chains'])} chains recorded")
        logger.info(f"Total snapshots in history: {len(snapshots)}")


async def main():
    """Main entry point"""
    logger.info("=== Redemption Rate Snapshot Script ===")

    # Initialize Stride client
    stride_api_url = os.getenv("STRIDE_API_URL", "https://stride-api.polkachu.com")
    stride_rpc_url = os.getenv("STRIDE_RPC_URL", "https://stride-rpc.polkachu.com")
    price_api_url = os.getenv("PRICE_API_URL", "https://api.coingecko.com/api/v3")

    stride_client = StrideClient(
        api_url=stride_api_url,
        rpc_url=stride_rpc_url,
        price_api_url=price_api_url
    )

    tracker = RedemptionRateTracker(stride_client)

    try:
        await tracker.take_snapshot()
        logger.info("✅ Snapshot completed successfully")
    except Exception as e:
        logger.error(f"❌ Snapshot failed: {e}")
        raise
    finally:
        await stride_client.close()


if __name__ == "__main__":
    asyncio.run(main())
