#!/usr/bin/env python3
"""
Live Order Submission / Cancellation Smoke Test

Exercises the real Robinhood order pathway that auto-execution depends on --
OrderService.submit_close, submit_trailing_stop, get_order_info, list_open_orders
and cancel_order -- without any risk of a fill.

It does this by running AFTER HOURS and pricing every order far away from the
market: a sell-to-close limit is submitted at a multiple of the current mark, so
no counterparty would ever take it. Every order placed is cancelled before the
script exits, including on failure or Ctrl-C.

This is the production validation the unit tests in tests/test_auto_execution.py
cannot provide: they assert against a FakeOrderService, so the fill, partial-fill
and cancel shapes they rely on are assumed, not observed.

Usage:
    # Show what it would do, place nothing (default)
    python -m risk_manager.tools.live_order_smoke_test

    # Actually submit and cancel real orders
    python -m risk_manager.tools.live_order_smoke_test --confirm

    # Also exercise the stop-limit (trailing stop) path
    python -m risk_manager.tools.live_order_smoke_test --confirm --include-stop-limit
"""

import argparse
import copy
import datetime
import logging
import sys
import time

import pytz
import robin_stocks.robinhood as r

from shared.account_detector import AccountDetector
from shared.position_manager import position_manager
from shared.order_service import OrderService
from risk_manager.risk_manager_logger import RiskManagerLogger

logger = logging.getLogger('live_order_smoke_test')

# A resting order is priced this many times above the current mark so it cannot fill.
LIMIT_PRICE_MULTIPLE = 10.0
MIN_LIMIT_PRICE = 5.00
# Seconds to wait after submitting before querying order state.
SETTLE_SECONDS = 2.0

OPEN_STATES = ('queued', 'confirmed', 'unconfirmed')
CANCELLED_STATES = ('cancelled', 'canceled')


def is_market_hours() -> bool:
    """True when the US equity option market is open (9:30-16:00 ET, weekdays)."""
    et = pytz.timezone('America/New_York')
    now = datetime.datetime.now(et)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


class SmokeTest:
    def __init__(self, order_service: OrderService, confirm: bool):
        self.svc = order_service
        self.confirm = confirm
        self.results = []
        self.submitted_order_ids = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        mark = "PASS" if passed else "FAIL"
        self.results.append((name, passed, detail))
        print(f"  [{mark}] {name}" + (f" -- {detail}" if detail else ""))
        return passed

    # -- individual order pathways -------------------------------------------

    def run_limit_close(self, position, limit_price: float) -> None:
        print(f"\nLimit sell-to-close  {position.symbol} "
              f"{position.strike_price}{position.option_type[0].upper()} "
              f"exp {position.expiration_date}  qty {position.quantity}  @ ${limit_price:.2f}")
        if not self.confirm:
            print("  (dry run -- not submitted; pass --confirm to place it)")
            return

        result = self.svc.submit_close(position, limit_price)
        if not self.check("submit_close accepted", result.get('success'), result.get('error', '')):
            return
        order_id = result['order_id']
        self.submitted_order_ids.append(order_id)
        print(f"  order_id={order_id}")
        self._verify_open_then_cancel(order_id, "limit")

    def run_stop_limit(self, position, limit_price: float, stop_price: float) -> None:
        print(f"\nStop-limit sell-to-close  {position.symbol}  "
              f"stop ${stop_price:.2f} / limit ${limit_price:.2f}")
        if not self.confirm:
            print("  (dry run -- not submitted; pass --confirm to place it)")
            return

        result = self.svc.submit_trailing_stop(position, limit_price, stop_price)
        if not self.check("submit_trailing_stop accepted", result.get('success'), result.get('error', '')):
            return
        order_id = result['order_id']
        self.submitted_order_ids.append(order_id)
        print(f"  order_id={order_id}")
        self._verify_open_then_cancel(order_id, "stop_limit")

    # -- shared verification -------------------------------------------------

    def _verify_open_then_cancel(self, order_id: str, label: str) -> None:
        time.sleep(SETTLE_SECONDS)

        info = self.svc.get_order_info(order_id)
        if self.check(f"get_order_info returns {label} order", info.get('success'), info.get('error', '')):
            state = (info.get('details') or {}).get('state', '')
            self.check(f"{label} order is resting (not filled)",
                       state in OPEN_STATES, f"state={state!r}")
            # This is the assumption the unit tests bake in -- confirm it is real.
            self.check(f"{label} order did NOT fill", state not in ('filled', 'partially_filled'),
                       f"state={state!r}")

        listing = self.svc.list_open_orders()
        if self.check("list_open_orders succeeds", listing.get('success'), listing.get('error', '')):
            ids = {o.get('id') for o in listing.get('orders', [])}
            self.check(f"{label} order appears in list_open_orders", order_id in ids)

        cancel = self.svc.cancel_order(order_id)
        if not self.check(f"cancel_order accepted for {label}", cancel.get('success'), cancel.get('error', '')):
            return

        time.sleep(SETTLE_SECONDS)
        info = self.svc.get_order_info(order_id)
        if self.check(f"get_order_info after cancel ({label})", info.get('success'), info.get('error', '')):
            state = (info.get('details') or {}).get('state', '')
            if self.check(f"{label} order reached a cancelled state",
                          state in CANCELLED_STATES, f"state={state!r}"):
                self.submitted_order_ids.remove(order_id)

        listing = self.svc.list_open_orders()
        if listing.get('success'):
            ids = {o.get('id') for o in listing.get('orders', [])}
            self.check(f"{label} order gone from list_open_orders", order_id not in ids)

    # -- cleanup -------------------------------------------------------------

    def cleanup(self) -> None:
        """Cancel anything still outstanding. Runs even on failure or Ctrl-C."""
        if not self.submitted_order_ids:
            return
        print("\nCleanup -- cancelling orders left outstanding:")
        for order_id in list(self.submitted_order_ids):
            res = self.svc.cancel_order(order_id)
            status = "cancelled" if res.get('success') else f"FAILED: {res.get('error')}"
            print(f"  {order_id}: {status}")
            if res.get('success'):
                self.submitted_order_ids.remove(order_id)
        if self.submitted_order_ids:
            print("\n  *** MANUAL ACTION REQUIRED -- these orders are still live: ***")
            for order_id in self.submitted_order_ids:
                print(f"    {order_id}")

    def summary(self) -> int:
        if not self.results:
            print("\nNo checks ran (dry run). Re-run with --confirm to place real orders.")
            return 0
        failed = [r for r in self.results if not r[1]]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} checks passed")
        if failed:
            print("\nFailed:")
            for name, _, detail in failed:
                print(f"  - {name}" + (f" ({detail})" if detail else ""))
            return 1
        return 0


def pick_position(positions: dict, position_key: str = None):
    """Pick the cheapest position, or the one named by --position-key."""
    if not positions:
        return None, None
    if position_key:
        pos = positions.get(position_key)
        return (position_key, pos) if pos else (None, None)
    key = min(positions, key=lambda k: positions[k].current_price or float('inf'))
    return key, positions[key]


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Validate live order submission and cancellation against Robinhood, after hours.'
    )
    parser.add_argument('--confirm', action='store_true',
                        help='Actually submit and cancel real orders (default: dry run)')
    parser.add_argument('--account', help='Account prefix to use (default: first with positions)')
    parser.add_argument('--position-key', help='Specific position key to test against')
    parser.add_argument('--include-stop-limit', action='store_true',
                        help='Also exercise the stop-limit (trailing stop) pathway')
    parser.add_argument('--allow-market-hours', action='store_true',
                        help='DANGEROUS: permit running while the market is open, where a fill is possible')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')

    if is_market_hours() and not args.allow_market_hours:
        print("Market is OPEN. This test relies on being after hours so nothing can fill.")
        print("Re-run after 16:00 ET, or pass --allow-market-hours to override (not advised).")
        return 2

    print("Authenticating with Robinhood...")
    r.login()

    detector = AccountDetector()
    accounts = detector.get_active_accounts()
    if not accounts:
        print("No active accounts found.")
        return 2

    if args.account:
        account_number = detector.get_account_number_from_prefix(args.account)
        if not account_number:
            print(f"No account matching prefix {args.account!r}.")
            return 2
    else:
        account_number = next(iter(accounts.values()))['number']

    print(f"Account ...{account_number[-4:]}")
    position_manager.load_positions_for_account(account_number)
    positions = position_manager.get_positions_for_account(account_number)

    key, position = pick_position(positions, args.position_key)
    if not position:
        print("No long option position available to test against.")
        print("This test sells to close, so it needs at least one open long option.")
        return 2

    if not position.current_price or position.current_price <= 0:
        print(f"Position {key} has no current mark price; cannot price a safe limit.")
        return 2

    # One contract only, priced far above the mark so it cannot be hit.
    test_position = copy.copy(position)
    test_position.quantity = 1
    limit_price = round(max(position.current_price * LIMIT_PRICE_MULTIPLE, MIN_LIMIT_PRICE), 2)

    print(f"Position {key}  mark ${position.current_price:.2f}  "
          f"held qty {position.quantity} -> testing with qty 1")
    print(f"Limit price ${limit_price:.2f} "
          f"({LIMIT_PRICE_MULTIPLE:g}x mark) -- far above market, cannot fill")
    if not args.confirm:
        print("\nDRY RUN -- no orders will be placed. Pass --confirm to run for real.")

    order_service = OrderService(RiskManagerLogger())
    test = SmokeTest(order_service, args.confirm)

    try:
        test.run_limit_close(test_position, limit_price)
        if args.include_stop_limit:
            # Stop well above the mark too, so the stop itself never triggers.
            stop_price = round(max(position.current_price * LIMIT_PRICE_MULTIPLE, MIN_LIMIT_PRICE), 2)
            test.run_stop_limit(test_position, limit_price, stop_price)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        test.cleanup()

    return test.summary()


if __name__ == '__main__':
    sys.exit(main())
