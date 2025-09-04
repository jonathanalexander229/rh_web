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

## Architecture

See `ARCHITECTURE.md` for a high-level overview of both apps (Portfolio Dashboard and Risk Manager Web) and their shared components.

### Portfolio Dashboard (rh_web.py)

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
- `GET /` and `GET /account/<account_prefix>` entry points.
- Account API under `/api/account/<account_prefix>/*` for positions, orders, and controls.
- Full request/response examples: see `API.md`.

### Orders and Modes
- Simulation mode: creates entries under `simulated_orders` with state transitions; outputs readable console logs and writes to `logs/simulated_orders_YYYYMMDD.log`.
- Live mode: submits `order_sell_option_limit` or `order_sell_option_stop_limit` (for trailing stops); logs full request/response to `logs/real_orders_YYYYMMDD.log`.
- All sessions log to `logs/risk_manager_YYYYMMDD.log` via `RiskManagerLogger`.

### Payload Shapes
- See `API.md` for detailed request/response examples.

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

### Startup Sequence
1. Parse args: `--live` and `--port` in `risk_manager_web.py`.
2. Set mode: live → print warnings and require typing `YES`; simulation → safe mode banner.
3. `initialize_system()`:
   - Call `r.login()` once (global session).
   - Instantiate `AccountDetector` and `MultiAccountRiskManager`.
   - Detect accounts: `MultiAccountRiskManager.initialize_accounts()` → `AccountDetector.detect_accounts()` (builds prefix map like `STD-1234`).
   - Print summary: `MultiAccountRiskManager.list_accounts_summary()`.
   - Auto-start monitors: `auto_start_active_accounts()` resolves prefixes and starts monitors with full account numbers.
4. For each started account:
   - Create `AccountMonitoringThread(full_account_number, account_info)`.
   - Inside thread, call `BaseRiskManager.load_long_positions()` once (uses `r.get_open_option_positions(account_number=...)`).
   - Mark `initial_loading_complete = True` and enter loop.
5. Start Flask: `app.run(debug=not live, host=0.0.0.0, port=PORT)`.
6. First UI visit `/`:
   - `AccountDetector.detect_accounts()` and `has_positions_or_orders()` flag cards.
7. Visit `/account/<account_prefix>`:
   - Resolve prefix → full number; only start monitoring if not already running.
   - Render `risk_manager.html`.
8. Frontend polling:
   - `GET /api/account/<prefix>/positions` returns cached `positions` from the account’s `BaseRiskManager`.
   - `GET /api/account/<prefix>/refresh-tracked-orders` or `check-orders` fetch tracked/sim orders (or Robinhood pages in live mode).
9. Monitoring loop per account:
   - Market hours (ET): `check_trailing_stops()` every 1s updates prices and evaluates triggers.
   - Off hours: sleep ~60s.

For full endpoint details and examples, see `API.md`.
