#!/usr/bin/env python3
"""
Verification script to fact-check all fee calculations
"""
import asyncio
import httpx
from stride_client import StrideClient


async def verify_chain_fees(client: StrideClient, chain: str):
    """Verify fees for a single chain with detailed breakdown"""
    print(f"\n{'='*70}")
    print(f"Verifying {chain.upper()}")
    print(f"{'='*70}")

    try:
        # Get host zone data
        chain_id = client.CHAIN_ID_MAP.get(chain)
        if not chain_id:
            print(f"❌ Chain not found in CHAIN_ID_MAP")
            return

        host_zone = await client.get_host_zone(chain_id)
        if not host_zone:
            print(f"❌ Host zone not found for {chain_id}")
            return

        # Extract data
        total_delegations = float(host_zone.get("total_delegations", "0"))
        redemption_rate = float(host_zone.get("redemption_rate", "1.0"))

        print(f"📊 Host Zone Data:")
        print(f"   Chain ID: {chain_id}")
        print(f"   Total Delegations: {total_delegations:,.0f}")
        print(f"   Redemption Rate: {redemption_rate:.6f}")

        # Get APR
        apr = await client.get_chain_apr(chain)
        daily_rate = apr / 365

        print(f"\n📈 APR Data:")
        print(f"   Annual APR: {apr*100:.2f}%")
        print(f"   Daily Rate: {daily_rate*100:.4f}%")

        # Calculate daily rewards
        daily_rewards_native = total_delegations * daily_rate

        print(f"\n💰 Rewards Calculation:")
        print(f"   Daily Rewards (native): {daily_rewards_native:,.0f}")

        # Get price
        price = await client.get_token_price(chain)
        decimals = client.TOKEN_DECIMALS.get(chain, 6)

        print(f"\n💵 Price Data:")
        print(f"   Token Price: ${price:.6f}")
        print(f"   Decimals: {decimals}")

        # Calculate USD value
        divisor = 10 ** decimals
        daily_fees_usd = daily_rewards_native * price / divisor
        daily_revenue_usd = daily_fees_usd * 0.10

        print(f"\n💸 Final Calculation:")
        print(f"   Formula: {daily_rewards_native:,.0f} × ${price:.6f} / {divisor:,}")
        print(f"   Daily Fees (USD): ${daily_fees_usd:,.2f}")
        print(f"   Daily Revenue (10%): ${daily_revenue_usd:,.2f}")

        # Get API result
        api_result = await client.calculate_daily_fee(chain)

        print(f"\n🔍 API Result:")
        print(f"   Daily Fees: ${api_result['dailyFees']:,.2f}")
        print(f"   Daily Revenue: ${api_result['dailyRevenue']:,.2f}")

        # Compare
        diff = abs(daily_fees_usd - api_result['dailyFees'])
        if diff < 0.01:
            print(f"\n✅ VERIFIED - Values match!")
        else:
            print(f"\n❌ MISMATCH - Difference: ${diff:,.2f}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Verify all chains"""
    client = StrideClient(
        api_url="https://stride-api.polkachu.com",
        rpc_url="https://stride-rpc.polkachu.com",
        price_api_url="https://api.coingecko.com/api/v3"
    )

    chains = [
        "cosmos", "osmosis", "celestia", "dydx",
        "juno", "stargaze", "terra2", "evmos",
        "injective", "umee", "comdex", "haqq", "band"
    ]

    print("\n" + "="*70)
    print("STRIDE FEES VERIFICATION REPORT")
    print("="*70)

    # Pre-fetch all prices
    print("\n🔄 Pre-fetching all token prices...")
    await client.get_token_prices_batch(chains)

    # Verify each chain
    for chain in chains:
        await verify_chain_fees(client, chain)

    await client.close()

    print("\n" + "="*70)
    print("VERIFICATION COMPLETE")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
