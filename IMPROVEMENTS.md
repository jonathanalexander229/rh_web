# IMPROVEMENTS.md

Proposed refactors to simplify, de‑duplicate, and harden the Risk Manager Web code without changing behavior.

## Order Service Abstraction (Live Only)
- Create an `OrderService` abstraction focused on live trading:
  - Wraps `r.order_sell_option_limit/stop_limit`, `r.get_option_order_info()`, and `r.cancel_option_order()`.
- Interface: `submit_close(position, limit_price, stop_price=None) -> { order_id, state, ... }`.
- Routes call PositionManager; PositionManager uses `OrderService` internally.
- Benefits: centralizes Robinhood calls, logging, and error handling.

## Centralize Account Context
- Helper/decorator: `get_account_context(account_prefix)` → `{ account_number, account_info, risk_manager }` or a standard error JSON.
- Use in positions, close‑simulation, trailing‑stop, take‑profit, refresh‑tracked‑orders, check‑orders.
- Benefits: eliminates repeated prefix→number resolution and repeated error blocks.

## Move Position Logic Into BaseRiskManager
- Extend `LongPosition` with nested dataclasses for `trail_stop` and `take_profit` (config + runtime state).
- Add methods:
  - `configure_trailing_stop(symbol, enabled, percent)` → returns updated config and trigger.
  - `configure_take_profit(symbol, enabled, percent)` → returns updated config.
  - `compute_trail_trigger(position)` → updates highest/trigger/triggered flags.
- Keep `_build_positions_response()` as a thin serializer; put state math in `BaseRiskManager`.
- Benefits: route code becomes simple; logic is testable in one place.

## Unify Market Hours Logic
- Add `shared/time_utils.py:is_market_hours_et()` and reuse in both `risk_manager_web.py` and `BaseRiskManager`.
- Benefits: avoids duplicate implementations and drift.

## Thread Safety for Orders
- Use a per‑account order tracker (PositionManager) protected by a lock.
- Benefits: prevents race conditions during high‑frequency polling.

## Check‑Orders Efficiency
- Keep two clear paths:
  - Tracked only: current `refresh-tracked-orders` (cheap; used for auto‑refresh in UI).
  - Heavy fetch: current `check-orders` (pages open orders from RH; manual user action).
- Benefits: reduces repeated paging during frequent UI polls.

## Consolidate Logging
- Prefer logger over `print`; gate console prints behind a verbosity flag.
- Ensure every log includes account suffix, symbol, and order_id when applicable.
- Keep structured files via `RiskManagerLogger` (session + real orders).
- Benefits: cleaner live output; easier grepping.

## Consistent Response Helpers
- Small helpers for standardized responses:
  - `ok(data={}, message="") -> jsonify({ success: true, ... })`
  - `err(message, status=400, data={}) -> (jsonify({ success: false, error: message, ... }), status)`
- Benefits: removes repeated JSON literals and status mismatches.

## Dataclasses for Orders
- Define `CloseOrderRequest` and `OrderSummary` dataclasses.
- Benefits: fewer shape bugs; clear field names aligned with `risk_manager.html`.

## Monitor Lifecycle Utilities
- Add `MultiAccountRiskManager.get_or_start(account_number)` to return an existing monitor or start one.
- Add `/api/monitors/status` to expose `get_monitoring_status()` for diagnostics.
- Benefits: prevents accidental duplicates and simplifies routes.

## Minor Cleanups
- Extract `compute_default_limit(position)` (used by preview and fallback paths).
- Extract `compute_stop_limit_prices(trigger_price)` to keep trailing stop orders consistent.
- Move repeated banner strings to constants for clarity.

## Suggested Implementation Plan
1) OrderService abstraction (live), reuse existing code paths internally; no route signature changes.
2) Add account context helper + `ok/err` response helpers; refactor routes to use them.
3) Move trailing/take‑profit math into `BaseRiskManager`; keep serializer thin.
4) Add locks or per‑account order trackers; switch routes to read through manager.
5) Unify market hours in `shared/time_utils.py` and replace local copies.

## Non‑Goals (for now)
- Changing UI payload shapes (unless bugs are discovered).
- Introducing a background scheduler beyond the existing per‑account loops.
