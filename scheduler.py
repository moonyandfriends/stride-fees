"""
Background scheduler for running daily redemption rate snapshots

This runs inside the FastAPI application and doesn't require external cron
"""
import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os

logger = logging.getLogger(__name__)


async def run_snapshot():
    """Run the snapshot collection"""
    try:
        logger.info("Starting scheduled redemption rate snapshot...")

        # Import here to avoid circular imports
        from stride_client import StrideClient
        from snapshot_redemption_rates import RedemptionRateTracker

        # Initialize client
        stride_api_url = os.getenv("STRIDE_API_URL", "https://stride-api.polkachu.com")
        stride_rpc_url = os.getenv("STRIDE_RPC_URL", "https://stride-rpc.polkachu.com")
        price_api_url = os.getenv("PRICE_API_URL", "https://api.coingecko.com/api/v3")

        stride_client = StrideClient(
            api_url=stride_api_url,
            rpc_url=stride_rpc_url,
            price_api_url=price_api_url
        )

        tracker = RedemptionRateTracker(stride_client)

        # Take snapshot
        await tracker.take_snapshot()

        # Cleanup
        await stride_client.close()

        logger.info("✅ Scheduled snapshot completed successfully")

    except Exception as e:
        logger.error(f"❌ Scheduled snapshot failed: {e}", exc_info=True)


async def run_price_update():
    """Update persistent price cache for all tokens"""
    try:
        logger.info("Starting scheduled price cache update...")

        # Import here to avoid circular imports
        from stride_client import StrideClient

        # Initialize client
        stride_api_url = os.getenv("STRIDE_API_URL", "https://stride-api.polkachu.com")
        stride_rpc_url = os.getenv("STRIDE_RPC_URL", "https://stride-rpc.polkachu.com")
        price_api_url = os.getenv("PRICE_API_URL", "https://api.coingecko.com/api/v3")

        stride_client = StrideClient(
            api_url=stride_api_url,
            rpc_url=stride_rpc_url,
            price_api_url=price_api_url
        )

        # Update price cache
        await stride_client.update_persistent_price_cache()

        # Cleanup
        await stride_client.close()

        logger.info("✅ Scheduled price update completed successfully")

    except Exception as e:
        logger.error(f"❌ Scheduled price update failed: {e}", exc_info=True)


def start_scheduler():
    """
    Start the background scheduler for daily snapshots and price updates

    Runs at midnight UTC every day
    """
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    # Schedule redemption rate snapshot at midnight UTC every day
    scheduler.add_job(
        run_snapshot,
        trigger=CronTrigger(hour=0, minute=0, timezone=timezone.utc),
        id='daily_snapshot',
        name='Daily Redemption Rate Snapshot',
        replace_existing=True
    )

    # Schedule price update at 00:30 UTC every day (30 min after snapshot)
    scheduler.add_job(
        run_price_update,
        trigger=CronTrigger(hour=0, minute=30, timezone=timezone.utc),
        id='daily_price_update',
        name='Daily Token Price Update',
        replace_existing=True
    )

    # Run both at startup (after a brief delay)
    scheduler.add_job(
        run_snapshot,
        'date',
        run_date=datetime.now(timezone.utc),
        id='startup_snapshot',
        name='Startup Snapshot'
    )

    scheduler.add_job(
        run_price_update,
        'date',
        run_date=datetime.now(timezone.utc),
        id='startup_price_update',
        name='Startup Price Update'
    )

    scheduler.start()
    logger.info("📅 Scheduler started - snapshots at 00:00 UTC, prices at 00:30 UTC daily")

    return scheduler
