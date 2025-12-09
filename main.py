"""
Stride Fees API - FastAPI application for calculating Stride protocol fees
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from stride_client import StrideClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global client instance
stride_client: StrideClient = None


class FeeResponse(BaseModel):
    """Response model for fee endpoints"""
    fees: dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI"""
    global stride_client

    # Startup
    stride_api_url = os.getenv("STRIDE_API_URL", "https://stride-api.polkachu.com")
    stride_rpc_url = os.getenv("STRIDE_RPC_URL", "https://stride-rpc.polkachu.com")
    price_api_url = os.getenv("PRICE_API_URL", "https://api.coingecko.com/api/v3")

    stride_client = StrideClient(
        api_url=stride_api_url,
        rpc_url=stride_rpc_url,
        price_api_url=price_api_url
    )
    logger.info("Stride client initialized")

    yield

    # Shutdown
    await stride_client.close()
    logger.info("Stride client closed")


# Create FastAPI app
app = FastAPI(
    title="Stride Fees API",
    description="API for calculating Stride protocol fees for DefiLlama",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Stride Fees API",
        "status": "healthy",
        "version": "1.0.0"
    }


@app.get("/api/all/stats/fees")
async def get_all_fees():
    """
    Get fees for all supported chains
    Uses batch price fetching to minimize API calls

    Returns:
        Dictionary with fees for each chain
    """
    try:
        supported_chains = [
            "cosmos", "celestia", "osmosis", "dydx", "dymension",
            "juno", "stargaze", "terra2", "evmos", "injective",
            "umee", "comdex", "haqq", "band"
        ]

        # Pre-fetch all prices in a single batch request to avoid rate limits
        logger.info("Pre-fetching prices for all chains in batch...")
        await stride_client.get_token_prices_batch(supported_chains)

        results = {}
        for chain in supported_chains:
            try:
                # Now calculate fees (prices will come from cache)
                fees_data = await stride_client.calculate_daily_fee(chain)
                results[chain] = fees_data
            except Exception as e:
                logger.warning(f"Failed to get fees for {chain}: {e}")
                results[chain] = {
                    "dailyFees": 0,
                    "dailyRevenue": 0,
                    "error": str(e)
                }

        return {"chains": results}

    except Exception as e:
        logger.error(f"Error fetching all fees: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/{chain}/stats/fees")
async def get_chain_fees(chain: str) -> FeeResponse:
    """
    Get daily fees and revenue for a specific chain

    Args:
        chain: Chain name (e.g., 'cosmos', 'osmosis', 'celestia')

    Returns:
        FeeResponse with dailyFees and dailyRevenue in USD
    """
    try:
        # Normalize chain name
        chain = chain.lower()

        # Handle terra -> terra2 override
        if chain == "terra":
            chain = "terra2"

        # Calculate fees
        fees_data = await stride_client.calculate_daily_fee(chain)

        return FeeResponse(fees=fees_data)

    except ValueError as e:
        logger.error(f"Invalid chain: {chain} - {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error calculating fees for {chain}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health_check():
    """Detailed health check endpoint"""
    try:
        # Test connectivity by fetching host zones
        host_zones = await stride_client.get_host_zones()
        return {
            "status": "healthy",
            "stride_api": "connected",
            "host_zones_count": len(host_zones)
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    # Disable reload in production (Railway, Docker, etc.)
    is_production = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("DOCKER_CONTAINER")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=not is_production,
        log_level="info"
    )
