#!/usr/bin/env python3
"""
Robinhood Order Submission / Cancellation Test

Tests the live order plumbing that auto-execution depends on:
order_buy_option_limit -> get_option_order_info -> cancel_option_order

Run this AFTER HOURS. The market being closed is what keeps it safe -- the
order rests unfilled until we cancel it. The script refuses to run while the
market is open.

The unit tests in tests/test_auto_execution.py run against a FakeOrderService,
so the order states they assert on ('queued', 'cancelled') are assumed. This
confirms them against the real API.

Prerequisites:
- Authentication pickle from the rh_web app (run it once and complete MFA)

Usage:
    python -m risk_manager.tools.live_order_smoke_test
    python -m risk_manager.tools.live_order_smoke_test --symbol QQQ
    python -m risk_manager.tools.live_order_smoke_test --confirm
"""

import argparse
import logging
import sys
import time
from datetime import datetime

import pytz
import robin_stocks.robinhood as r

PRICE = 0.01        # 1 cent -- nothing at risk even in the impossible case it fills
QUANTITY = 1
SETTLE_SECONDS = 2.0

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()],
    )


def is_market_hours() -> bool:
    """True when the US equity option market is open (9:30-16:00 ET, weekdays)."""
    et = pytz.timezone('America/New_York')
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


def run_order_test(symbol: str, option_type: str, confirm: bool) -> bool:
    print(f"\n🧪 Robinhood Order Submission / Cancellation Test -- {symbol}")

    # Step 1: after-hours guard
    print(f"\n🔍 Step 1: Checking market hours...")
    if is_market_hours():
        print(f"   ❌ Market is OPEN -- the order could fill")
        print(f"   💡 Run after 16:00 ET")
        return False
    print(f"   ✅ Market is closed -- a resting order cannot fill")

    # Step 2: auth
    print(f"\n🔍 Step 2: Authenticating with Robinhood...")
    r.login()
    print(f"   ✅ Authenticated")

    # Step 3: pick a contract
    print(f"\n🔍 Step 3: Finding a tradable {symbol} {option_type}...")
    # Resolve the nearest expiration first -- querying every expiration pages
    # through the whole chain and hammers the API for no reason.
    chains = r.get_chains(symbol) or {}
    expirations = sorted(chains.get('expiration_dates') or [])
    if not expirations:
        print(f"   ❌ No expirations found for {symbol}")
        return False
    expiration = expirations[0]

    options = r.find_tradable_options(symbol, expirationDate=expiration, optionType=option_type)
    contracts = [o for o in (options or []) if o.get('strike_price')]
    if not contracts:
        print(f"   ❌ No tradable {option_type} contracts for {symbol} exp {expiration}")
        return False
    strike = float(contracts[0]['strike_price'])
    print(f"   ✅ {symbol} {strike} {option_type} exp {expiration}")

    # Step 4: submit
    print(f"\n🔍 Step 4: Submitting limit order...")
    print(f"   📊 BUY {QUANTITY} @ ${PRICE:.2f} limit, GTC")
    if not confirm:
        print(f"   💡 DRY RUN -- nothing submitted. Add --confirm to place it.")
        return True

    result = r.order_buy_option_limit(
        positionEffect='open', creditOrDebit='debit', price=PRICE,
        symbol=symbol, quantity=QUANTITY, expirationDate=expiration,
        strike=strike, optionType=option_type, timeInForce='gtc',
    )
    order_id = (result or {}).get('id')
    if not order_id:
        print(f"   ❌ No order id returned: {result}")
        return False
    print(f"   ✅ Order accepted -- id={order_id}")

    passed = True
    try:
        # Step 5: read state back
        print(f"\n🔍 Step 5: Reading order state back...")
        time.sleep(SETTLE_SECONDS)
        state = (r.get_option_order_info(order_id) or {}).get('state')
        if state in ('filled', 'partially_filled'):
            print(f"   ❌ Order FILLED unexpectedly -- state={state!r}")
            passed = False
        else:
            print(f"   ✅ Resting unfilled -- state={state!r}")
    finally:
        # Step 6: cancel
        print(f"\n🔍 Step 6: Cancelling...")
        r.cancel_option_order(order_id)
        time.sleep(SETTLE_SECONDS)
        state = (r.get_option_order_info(order_id) or {}).get('state')
        if state in ('cancelled', 'canceled'):
            print(f"   ✅ Cancelled -- state={state!r}")
        else:
            print(f"   ❌ Not cancelled -- state={state!r}")
            print(f"   *** ORDER {order_id} MAY STILL BE LIVE -- CHECK THE APP ***")
            passed = False

    return passed


def main():
    parser = argparse.ArgumentParser(description='Robinhood Order Submission / Cancellation Test')
    parser.add_argument('--symbol', default='SPY', help='Symbol to test (default: SPY)')
    parser.add_argument('--type', choices=['call', 'put'], default='call',
                        help='Option type (default: call)')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually submit and cancel a real order (default: dry run)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        success = run_order_test(args.symbol.upper(), args.type, args.confirm)
    except Exception as e:
        logger.error(f"Error in order test: {e}")
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        success = False

    if success:
        print(f"\n✅ All tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ Test failed!")
        sys.exit(1)


if __name__ == '__main__':
    main()
