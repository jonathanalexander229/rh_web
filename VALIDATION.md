# Risk Manager Web — End-to-End Validation

Concise, behavior-focused checks to verify the refactor (PositionManager + OrderService) works as intended.

## 1) Start Server
- Run: `python risk_manager_web.py --live`
- Expect: login prompt, accounts detected, server started.

## 2) Account Selector
- Open: http://localhost:5001
- Expect: account cards with activity indicator; banner shows Live Trading.
- Click an account to open its dashboard.

## 3) Dashboard Basics
- Expect: positions list, P&L totals, Refresh and Load Orders buttons.
- Click Refresh; timestamp and P&L update.

## 4) Close Order (Limit)
- Open Close modal for a position.
- Adjust limit price; confirm estimated proceeds updates.
- Submit Orders.
- Expect: order ID in terminal logs; order appears in Active Orders after Load Orders.

## 5) Trailing Stop
- Open Trail Stop; enable and set percent.
- Save configuration; trailing stop state shows enabled on the card.
- Expect: stop-limit order submission logs; order appears in Active Orders.

## 6) Take Profit
- Open Take Profit; enable and set percent.
- Save configuration; card shows take-profit enabled.
- Note: configuration updates state; no order is submitted at this step.

## 7) Refresh Tracked Orders
- Use the Load Orders button and auto-refresh.
- Expect: tracked orders reflect latest state (confirmed/filled/partial, etc.).

## 8) Cancel Order
- Click Cancel on a confirmed order.
- Expect: cancel request accepted; subsequent Load Orders shows updated state.

## 9) API Spot Checks
- Positions: GET `/api/account/<prefix>/positions` → positions array, total_pnl.
- Close: POST `/api/account/<prefix>/close-simulation` → success, orders with real IDs.
- Trail Stop: POST `/api/account/<prefix>/trailing-stop` → success, order_created object.
- Refresh Tracked: GET `/api/account/<prefix>/refresh-tracked-orders` → tracked orders.
- Check Orders: GET `/api/account/<prefix>/check-orders` → open orders list.

## 10) Logging
- Files in `logs/`:
  - `risk_manager_YYYYMMDD.log` for session/actions.
  - `real_orders_YYYYMMDD.log` for order request/response.
- Expect entries for submitted close and stop-limit orders.

## 11) Thread/Monitor Sanity
- Only one monitoring thread per account.
- No duplicate “Loading positions…” when navigating.

## 12) Ownership Sanity
- Position state and triggers come from PositionManager.
- All Robinhood order API calls flow through OrderService.
- Routes act only as thin controllers.

