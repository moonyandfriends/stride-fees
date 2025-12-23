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


def start_scheduler():
    """
    Start the background scheduler for daily snapshots

    Runs at midnight UTC every day
    """
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    # Schedule snapshot at midnight UTC every day
    scheduler.add_job(
        run_snapshot,
        trigger=CronTrigger(hour=0, minute=0, timezone=timezone.utc),
        id='daily_snapshot',
        name='Daily Redemption Rate Snapshot',
        replace_existing=True
    )

    # Also run once at startup (after 30 seconds to let API stabilize)
    scheduler.add_job(
        run_snapshot,
        'date',
        run_date=datetime.now(timezone.utc),
        id='startup_snapshot',
        name='Startup Snapshot'
    )

    scheduler.start()
    logger.info("📅 Scheduler started - snapshots will run daily at 00:00 UTC")

    return scheduler
