# AGENTS.md

Guidance for AI coding agents working in this repository. This distills the most useful, action‑oriented bits from `CLAUDE.md` so agents can get productive quickly and make safe, consistent changes.

## Quick Start

### Run
```bash
# Simple options dashboard (Flask)
python rh_web.py   # http://localhost:5000
```

### Dependencies
```bash
pip install flask robin-stocks pandas
```
Notes:
- This is a Python Flask application (no `package.json`).
- For the multi‑account risk manager app in `README.md`, you may also need `pytz`.

## Architecture (rh_web.py)

### Core Components
- `rh_web.py`: Main Flask app with API routes and data processing.
- `templates/`: Jinja HTML templates
  - `index.html`: Main dashboard
  - `login.html`: Authentication
- `static/`: Frontend assets
  - `js/main.js`: App init, tab switching, API calls
  - `js/rendering.js`: Rendering helpers for all views
  - `js/filters.js`: Advanced filters, incl. date ranges
  - `js/sorting.js`: Table sorting
  - `css/styles.css`: Responsive styles

### Data Flow
1. Authentication via `/login` using Robinhood credentials (not stored).
2. `/api/options` -> `fetch_and_process_option_orders()` retrieves and processes data.
3. Processing categorizes into Open, Closed, Expired, and All orders.
4. Frontend JS handles display, filtering, sorting, and interactions.

### Key Processing Logic
`fetch_and_process_option_orders()` should:
- Fetch option orders via `robin_stocks`.
- Clean/normalize with `pandas`.
- Group opening/closing legs by option ID.
- Compute P&L for closed positions.
- Categorize by status (open/closed/expired).
- Return JSON‑serializable structures.

### Frontend Notes
- Modular JS by concern (main/rendering/filters/sorting).
- Tabbed UI to switch views of option data.
- Real‑time filtering (incl. date ranges) and responsive design.

## Security Considerations
- Robinhood credentials used only for login; do not persist.
- Flask debug is on for dev; disable for production.
- No explicit session/CSRF protection is implemented—be cautious if exposing beyond localhost.

## Normalized Database Plan (TODO)
Current issue: all data is fetched/processed on every request -> inefficient API usage and duplicate processing.

Proposed solution: add a normalized SQLite store with incremental updates and server‑side precomputation.

### Schema
```sql
-- Individual option orders (raw from Robinhood API)
CREATE TABLE option_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    robinhood_id TEXT UNIQUE,
    symbol TEXT,
    created_at TEXT,
    position_effect TEXT,
    expiration_date TEXT,
    strike_price TEXT,
    price REAL,
    quantity INTEGER,
    premium REAL,
    strategy TEXT,
    direction TEXT,
    option_type TEXT,
    option_ids TEXT,   -- JSON array
    raw_data TEXT,     -- full JSON
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Computed positions (paired open/close)
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    option_key TEXT UNIQUE,
    symbol TEXT,
    open_date TEXT,
    close_date TEXT,
    expiration_date TEXT,
    strike_price TEXT,
    quantity INTEGER,
    open_price REAL,
    close_price REAL,
    open_premium REAL,
    close_premium REAL,
    net_credit REAL,
    strategy TEXT,
    direction TEXT,
    option_type TEXT,
    status TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Implementation Benefits
- Incremental updates (fetch only new orders).
- Deduplication via `robinhood_id`.
- Move heavy JSON processing server‑side.
- Precomputed positions -> faster responses.
- Historical tracking of order/position evolution.

### Smart Fetch Strategy
- Initial: fetch ~60 days for first run.
- Update: pull orders since last stored.
- Deduplicate: enforce unique `robinhood_id`.
- Recompute: rebuild `positions` as new orders arrive.

### API Adjustments
- Store raw orders with deduplication.
- Precompute positions server‑side.
- Return clean, structured JSON to clients.

Dependency: use Python’s built‑in `sqlite3`.

## Agent Tips
- Keep changes minimal and consistent with existing style.
- Prefer server‑side data shaping so the client stays simple.
- Coordinate template/JS changes with API shape updates.
- Avoid storing secrets; treat auth/session with care.
- If adding the DB layer, update docs and remove this TODO when done.

## Related
- `README.md`: Details the multi‑account risk manager (`risk_manager_web.py`). If you work on that app, also install `pytz` and follow its documented endpoints and flows.

## Risk Manager Web (Multi‑Account)

This is the system currently under active development on branch `multi-account-support`.

### Run
```bash
# Simulation mode (safe)
python risk_manager_web.py --port 5001

# Live mode (DANGER: real orders). Requires typing "YES" to confirm.
python risk_manager_web.py --live --port 5001
```

### Dependencies
```bash
pip install flask robin-stocks pandas pytz
```

### High‑Level Flow
- Single `robin_stocks` login shared across components (`initialize_system()`).
- `AccountDetector` discovers accounts and creates safe prefixes (e.g., `STD-1234`).
- `MultiAccountRiskManager` launches one monitoring thread per selected/active account.
- Each monitor uses a dedicated `BaseRiskManager` to track positions and trailing stops.
- Web UI: account selector at `/` → per‑account dashboard at `/account/<account_prefix>`.

### Monitoring Model
- One thread per account via `AccountMonitoringThread`.
- During market hours (ET): 1‑second loop runs `check_trailing_stops()`.
- Off hours: loop sleeps for ~60 seconds.
- Positions are loaded once when monitoring starts; APIs serve cached state.

### Key Endpoints
- `GET /` → Account selector (lists detected accounts, with activity indicators).
- `GET /account/<account_prefix>` → Renders dashboard for that account.
- `GET /api/account/<account_prefix>/positions` → Current positions, totals, market hours, mode.
- `POST /api/account/<account_prefix>/close-simulation` → Close orders using per‑position custom limit prices; in live mode submits real orders, otherwise creates simulated orders.
- `POST /api/account/<account_prefix>/trailing-stop` → Enable/disable trailing stop for a symbol with a percent; live mode uses stop‑limit orders.
- `GET /api/account/<account_prefix>/check-orders` → Returns recent orders; in simulation returns in‑memory simulated orders.
- Legacy endpoints (`/api/positions`, `/api/close-simulation`, `/api/trailing-stop`, `/api/check-orders`, `/api/order-status/*`, `/api/cancel-order/*`) respond with guidance to use account‑specific routes.

### Orders and Modes
- Simulation mode: creates entries under `simulated_orders` with state transitions; outputs readable console logs and writes to `logs/simulated_orders_YYYYMMDD.log`.
- Live mode: submits `order_sell_option_limit` or `order_sell_option_stop_limit` (for trailing stops); logs full request/response to `logs/real_orders_YYYYMMDD.log`.
- All sessions log to `logs/risk_manager_YYYYMMDD.log` via `RiskManagerLogger`.

### Payload Shapes (abridged)
- Close simulation POST body (from UI): an array of positions with embedded `close_order.price` and `estimated_proceeds`.
- Trailing stop POST body: `{ symbol: str, enabled: bool, percent: number }`.

### UI/Frontend Notes
- Templates: `templates/account_selector.html`, `templates/risk_manager.html`.
- The per‑account UI supports custom limit pricing, sliders for stop‑loss/take‑profit, and trailing stop configuration; ensure API responses include the fields the UI expects (`positions`, `pnl`, `pnl_percent`, `trail_stop`, `take_profit`, etc.).

### Safety
- Live mode requires explicit terminal confirmation. Keep debug off in live mode.
- Do not store credentials. Robinhood session is global and ephemeral.
- No CSRF; do not expose beyond trusted local environment without adding protections.

### Current Status (from git)
- Branch: `multi-account-support`
- Latest: "Fix multi-account system initialization and order management" (HEAD)
- Recent: "Add price customization sliders and fix simulated order submission"

### Agent Tips
- When changing API response shapes, update `risk_manager.html` and any JS to match.
- Coordinate thread lifecycle changes with `MultiAccountRiskManager` to avoid orphan threads.
- Use account prefixes in routes and map to full numbers with `AccountDetector`.
- Prefer reusing cached `positions` in handlers; avoid calling Robinhood on every GET.

### App API Examples

- `GET /api/account/<account_prefix>/positions`
  Response:
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

- `POST /api/account/<account_prefix>/close-simulation`
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
  Response (simulation):
  ```json
  {
    "success": true,
    "message": "SIMULATION for account ...7315: 1 position(s) processed",
    "orders_simulated": 1,
    "orders": [
      {
        "symbol": "QQQ",
        "limit_price": 3.3,
        "estimated_proceeds": 330.0,
        "account": "...7315",
        "simulated": true,
        "order_id": "SIM_abc123def456",
        "order_state": "confirmed"
      }
    ],
    "live_trading_mode": false,
    "account_number": "XXXXXXXX7315"
  }
  ```
  Response (live):
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
        "simulated": false,
        "order_id": "abc123-def456",
        "order_result": { "id": "abc123-def456", "state": "confirmed" },
        "success": true
      }
    ],
    "live_trading_mode": true,
    "account_number": "XXXXXXXX7315"
  }
  ```

- `POST /api/account/<account_prefix>/trailing-stop`
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
      "simulated": true,
      "order_id": "SIM_abc123def456"
    },
    "account_number": "XXXXXXXX7315"
  }
  ```

- `POST /api/account/<account_prefix>/take-profit`
  Request:
  ```json
  { "symbol": "QQQ", "enabled": true, "percent": 50 }
  ```
  Response:
  ```json
  { "success": true, "message": "Take profit enabled for QQQ at 50%", "live_trading_mode": false, "account_number": "XXXXXXXX7315" }
  ```

- `GET /api/account/<account_prefix>/refresh-tracked-orders`
  Response (simulation):
  ```json
  {
    "success": true,
    "message": "Refreshed 1 tracked orders",
    "orders": [ { "id": "SIM_abc123def456", "symbol": "QQQ", "state": "filled", "price": 3.3, "quantity": 1, "submit_time": 1725387890.73, "order_type": "limit", "simulated": true } ],
    "account_number": "XXXXXXXX7315",
    "live_trading_mode": false
  }
  ```

- `GET /api/account/<account_prefix>/check-orders`
  Response (live; filtered open states):
  ```json
  {
    "success": true,
    "message": "Account ...7315: Found 1 orders",
    "orders": [ { "id": "abc123-def456", "symbol": "QQQ", "state": "confirmed", "price": 3.3, "quantity": 1, "submit_time": "2025-09-02T14:00:00Z", "order_type": "limit", "simulated": false } ],
    "account_number": "XXXXXXXX7315",
    "live_trading_mode": true
  }
  ```

Legacy routes under `/api/*` without account context return 400 with an error directing users to account‑specific routes.

### Robin Stocks Calls Used
- `r.login()`
- `r.load_account_profile(dataType="regular")` to enumerate accounts
- `r.get_open_option_positions(account_number=...)` to load options
- `r.get_open_stock_positions(account_number=...)` for activity checks
- `r.get_option_instrument_data_by_id(option_id)` for instrument metadata
- `r.get_option_market_data_by_id(option_id)` for current option prices
- `r.order_sell_option_limit(positionEffect='close', creditOrDebit='credit', price, symbol, quantity, expirationDate, strike, optionType, timeInForce='gtc')`
- `r.order_sell_option_stop_limit(positionEffect='close', creditOrDebit='credit', limitPrice, stopPrice, symbol, quantity, expirationDate, strike, optionType, timeInForce='gtc')`
- `r.get_option_order_info(order_id)` for status polling of live orders
- `robin_stocks.robinhood.helper.request_get(url, 'regular')` with `robin_stocks.robinhood.urls.option_orders_url()` to page through recent option orders (capped to first ~5 pages in our code)
