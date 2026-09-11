#!/usr/bin/env python3
"""
Robinhood Order Submission / Cancellation Test

Tests the live order plumbing that auto-execution depends on:
order_buy_option_limit -> get_option_order_info -> cancel_option_order

The order is priced at the ask, exactly as the production order path prices
its own orders, so this exercises the real thing. Run it AFTER HOURS -- the
market being closed is the only reason it rests instead of filling, and the
script refuses to run while the market is open.

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

    # Pick the nearest out-of-the-money strike. Taking an arbitrary contract can
    # land deep ITM, where one contract is tens of thousands of dollars of notional
    # resting on the book.
    spot = float((r.get_latest_price(symbol) or [0])[0] or 0)
    if spot <= 0:
        print(f"   ❌ Could not fetch {symbol} price")
        return False
    if option_type == 'call':
        otm = [o for o in contracts if float(o['strike_price']) >= spot]
        contract = min(otm, key=lambda o: float(o['strike_price'])) if otm else \
            max(contracts, key=lambda o: float(o['strike_price']))
    else:
        otm = [o for o in contracts if float(o['strike_price']) <= spot]
        contract = max(otm, key=lambda o: float(o['strike_price'])) if otm else \
            min(contracts, key=lambda o: float(o['strike_price']))
    strike = float(contract['strike_price'])
    print(f"   📊 {symbol} spot ${spot:.2f}")
    print(f"   ✅ {symbol} {strike} {option_type} exp {expiration}")

    # Step 4: price it at the ask, like the production order path does
    print(f"\n🔍 Step 4: Fetching market price...")
    data = r.get_option_market_data_by_id(contract['id'])
    quote = (data or [{}])[0] if isinstance(data, list) else data or {}
    price = float(quote.get('ask_price') or quote.get('adjusted_mark_price') or 0)
    if price <= 0:
        print(f"   ❌ No usable ask/mark price returned: {quote}")
        return False
    price = round(price, 2)
    print(f"   ✅ Ask ${price:.2f}")

    # Step 5: submit
    print(f"\n🔍 Step 5: Submitting limit order...")
    print(f"   📊 BUY {QUANTITY} @ ${price:.2f} limit, GTC")
    if not confirm:
        print(f"   💡 DRY RUN -- nothing submitted. Add --confirm to place it.")
        return True

    result = r.order_buy_option_limit(
        positionEffect='open', creditOrDebit='debit', price=price,
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
        print(f"\n🔍 Step 6: Reading order state back...")
        time.sleep(SETTLE_SECONDS)
        state = (r.get_option_order_info(order_id) or {}).get('state')
        if state in ('filled', 'partially_filled'):
            print(f"   ❌ Order FILLED unexpectedly -- state={state!r}")
            passed = False
        else:
            print(f"   ✅ Resting unfilled -- state={state!r}")
    finally:
        # Step 6: cancel
        print(f"\n🔍 Step 7: Cancelling...")
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
