# ARCHITECTURE.md

High-level architecture for the two web apps in this repository.

## Overview
- Two main components:
  - Portfolio Dashboard: `rh_web.py` (aka “RH Web”)
  - Risk Manager: `risk_manager_web.py` (aka “Risk Manager Web”)
- Shared utilities support both where noted.

## Portfolio Dashboard (rh_web.py)
- Purpose: View and analyze Robinhood options orders and positions.
- Stack: Flask + Jinja + modular JS (rendering, filters, sorting) + pandas.
- Key files:
  - `rh_web.py`: Flask app and data processing routes.
  - `templates/`: `index.html`, `login.html`.
  - `static/js/`: `main.js`, `rendering.js`, `filters.js`, `sorting.js`.
  - `static/css/`: `styles.css`.
- Data flow:
  1. Login via `/login` (credentials not stored).
  2. Fetch Robinhood option orders; process with pandas.
  3. Categorize into Open/Closed/Expired/All and return JSON to UI.
- Notes:
  - Normalized DB approach (SQLite) proposed to reduce re-fetching; see CLAUDE.md TODO.

## Risk Manager Web (risk_manager_web.py)
- Purpose: Real-time multi-account long-options risk management with live order execution.
- Stack: Flask + multi-threaded per-account monitors + robin_stocks.
- Key files:
  - `risk_manager_web.py`: Flask app, endpoints, startup and mode handling.
  - `multi_account_manager.py`: Orchestrates per-account monitoring threads.
  - `account_detector.py`: Discovers accounts and maps prefixes (e.g., `STD-1234`) to full numbers.
  - `base_risk_manager.py`: Loads positions, updates prices, computes P&L, trailing/take-profit helpers.
  - `risk_manager_logger.py`: Structured logs for sessions and real orders.
  - `templates/`: `account_selector.html`, `risk_manager.html`.
- Runtime flow:
  1. Startup parses `--live`/`--port`; confirms live mode.
  2. Single `r.login()` creates a global session.
  3. Detect accounts; auto-start monitors for active accounts (uses full account numbers).
  4. Each monitor loads positions once, then loops: 1s during market hours, ~60s off-hours.
  5. UI: `/` (selector) → `/account/<prefix>` (dashboard). API under `/api/account/<prefix>/*` serves cached positions and order actions.
- Orders:
  - Live: `order_sell_option_limit` / `order_sell_option_stop_limit`; logs to `logs/real_orders_*.log`.

## Shared/Supporting
- `shared/`, `portfolio/`, `position_manager.py`, `position_types.py`, `database.py`, `data_fetcher.py` — utilities for the portfolio dashboard and common logic.
- Logging directory: `logs/` (auto-created) with daily-rotated files per logger.
- Templates directory separation: portfolio vs risk manager templates.

## Run Commands
- Portfolio Dashboard (safe): `python rh_web.py` → http://localhost:5000
- Risk Manager Web (live; DANGER): `python risk_manager_web.py --live --port 5001` and type `YES` to confirm

## References
- README.md: Detailed Risk Manager features and UI.
- CLAUDE.md: Portfolio dashboard details and normalized DB plan (TODO).
- API.md: Full Risk Manager API request/response examples and robin_stocks calls.
