# API.md

Risk Manager Web API and Robinhood integration details.

## Overview
- Base path: `/api/account/<account_prefix>` where `<account_prefix>` is a safe alias (e.g., `STD-1234`). The backend resolves it to the full account number.
- Authentication: one global `robin_stocks` session via `r.login()` during startup.
- Mode: Live-only for write endpoints. Read endpoints are available without `--live`, but order submission requires starting with `--live`.

## Endpoints

### GET `/api/account/<account_prefix>/positions`
Returns current positions cached by the per-account monitor.

Response example:
```json
{
  "positions": [
    {
      "symbol": "QQQ",
      "strike_price": 571.0,
      "option_type": "CALL",
      "expiration_date": "2025-09-02",
      "quantity": 1,
      "open_premium": 315.0,
      "current_price": 3.3,
      "pnl": 15.0,
      "pnl_percent": 4.76,
      "close_order": {
        "positionEffect": "close",
        "creditOrDebit": "credit",
        "price": 3.14,
        "symbol": "QQQ",
        "quantity": 1,
        "expirationDate": "2025-09-02",
        "strike": 571.0,
        "optionType": "call",
        "timeInForce": "gtc",
        "estimated_proceeds": 314.0
      },
      "status_color": "success",
      "trail_stop": {
        "enabled": false,
        "percent": 20.0,
        "highest_price": 3.3,
        "trigger_price": 0.0,
        "triggered": false,
        "order_submitted": false,
        "order_id": null,
        "last_update_time": 0.0,
        "last_order_id": null
      },
      "take_profit": {
        "enabled": false,
        "percent": 50.0,
        "target_pnl": 50.0,
        "triggered": false
      }
    }
  ],
  "total_pnl": 15.0,
  "market_open": true,
  "live_trading_mode": false,
  "last_update": "14:05:12",
  "account_number": "XXXXXXXX7315",
  "account_display": "...7315"
}
```

### POST `/api/account/<account_prefix>/close-simulation`
Submits real close orders (live-only). Returns 400 if not started with `--live`.

Request:
```json
{
  "positions": [
    {
      "symbol": "QQQ",
      "strike_price": 571.0,
      "option_type": "call",
      "expiration_date": "2025-09-02",
      "close_order": { "price": 3.3, "estimated_proceeds": 330.0 }
    }
  ]
}
```

Response:
```json
{
  "success": true,
  "message": "LIVE ORDERS SUBMITTED for account ...7315: 1 position(s) processed",
  "orders": [
    {
      "symbol": "QQQ",
      "limit_price": 3.3,
      "estimated_proceeds": 330.0,
      "account": "...7315",
      "order_id": "abc123-def456",
      "order_result": { "id": "abc123-def456", "state": "confirmed" },
      "success": true
    }
  ],
  "live_trading_mode": true,
  "account_number": "XXXXXXXX7315"
}
```

### POST `/api/account/<account_prefix>/trailing-stop`
Enable/disable trailing stop for a symbol with percentage.

Request:
```json
{ "symbol": "QQQ", "enabled": true, "percent": 20 }
```

Response:
```json
{
  "success": true,
  "message": "Trailing stop enabled for QQQ",
  "config": {
    "enabled": true,
    "percent": 20.0,
    "highest_price": 3.3,
    "trigger_price": 2.64,
    "triggered": false,
    "order_submitted": false,
    "order_id": "SIM_abc123def456",
    "last_update_time": 1725387910.12,
    "last_order_id": null
  },
  "order_created": {
    "symbol": "QQQ",
    "limit_price": 2.64,
    "stop_price": 2.72,
    "estimated_proceeds": 264.0,
    "api_call": "Trailing Stop: Stop=$2.72, Limit=$2.64",
    "account": "...7315",
    "order_id": "abc123-def456"
  },
  "account_number": "XXXXXXXX7315"
}
```

### POST `/api/account/<account_prefix>/take-profit`
Enable/disable take profit for a symbol at a target P&L percentage.

Request:
```json
{ "symbol": "QQQ", "enabled": true, "percent": 50 }
```

Response:
```json
{ "success": true, "message": "Take profit enabled for QQQ at 50%", "live_trading_mode": false, "account_number": "XXXXXXXX7315" }
```

### GET `/api/account/<account_prefix>/refresh-tracked-orders`
Returns only orders tracked by this app.

Response:
```json
{
  "success": true,
  "message": "Refreshed 0 tracked orders",
  "orders": [],
  "account_number": "XXXXXXXX7315",
  "live_trading_mode": true
}
```

### GET `/api/account/<account_prefix>/check-orders`
Fetches open orders from Robinhood (first ~5 pages).

Response (live):
```json
{
  "success": true,
  "message": "Account ...7315: Found 1 orders",
  "orders": [ { "id": "abc123-def456", "symbol": "QQQ", "state": "confirmed", "price": 3.3, "quantity": 1, "submit_time": "2025-09-02T14:00:00Z", "order_type": "limit" } ],
  "account_number": "XXXXXXXX7315",
  "live_trading_mode": true
}
```

### Legacy Endpoints
The following routes without account context return 400 with a message directing to account-specific routes:
- `GET /api/positions`
- `POST /api/close-simulation`
- `POST /api/trailing-stop`
- `GET /api/check-orders`
- `GET /api/order-status/<order_id>`
- `POST /api/cancel-order/<order_id>`

## Robinhood (robin_stocks) Calls
- `r.login()` — global login during app startup
- `r.load_account_profile(dataType="regular")` — discover accounts
- `r.get_open_option_positions(account_number=...)` — load open options per account
- `r.get_open_stock_positions(account_number=...)` — activity check
- `r.get_option_instrument_data_by_id(option_id)` — instrument metadata
- `r.get_option_market_data_by_id(option_id)` — current option prices
- `r.order_sell_option_limit(positionEffect='close', creditOrDebit='credit', price, symbol, quantity, expirationDate, strike, optionType, timeInForce='gtc')`
- `r.order_sell_option_stop_limit(positionEffect='close', creditOrDebit='credit', limitPrice, stopPrice, symbol, quantity, expirationDate, strike, optionType, timeInForce='gtc')`
- `r.get_option_order_info(order_id)` — poll live order status
- `robin_stocks.robinhood.helper.request_get(url, 'regular')` + `robin_stocks.robinhood.urls.option_orders_url()` — page recent option orders (limited to first ~5 pages)
