# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This repository contains four Flask-based web applications:

### Portfolio Dashboard (`portfolio/`)
Modern dashboard for analyzing Robinhood options trading history with P&L tracking and calendar views.

```bash
python -m portfolio.rh_web
```

### Risk Manager (`risk_manager/`)
Real-time multi-account risk management system for monitoring and managing long option positions.

```bash
python -m risk_manager.risk_manager_web
# Or with live trading: python -m risk_manager.risk_manager_web --live
```

### Stocks Dashboard (`stocks/`)
Dashboard for stock/equity trading history.

```bash
python -m stocks.stocks_web
```

### Futures Dashboard (`futures/`)
Dashboard for futures trading history.

```bash
python -m futures.futures_web
```

### Running with Docker
`Dockerfile` and `docker-compose.yml` containerize the portfolio and risk
manager apps. See the "Running with Docker" section in `README.md` for the
one-time Robinhood auth setup and compose commands.

## Directory Structure

```
rh_web/
├── portfolio/              # Portfolio Dashboard
│   ├── rh_web.py          # Flask app
│   ├── data_fetcher.py    # Data fetching
│   ├── database.py        # SQLite operations
│   ├── static/            # CSS, JS, components
│   └── templates/         # HTML templates
│
├── risk_manager/          # Risk Manager
│   ├── risk_manager_web.py        # Flask app
│   ├── base_risk_manager.py       # Core risk logic
│   ├── multi_account_manager.py   # Multi-account orchestration
│   ├── risk_manager_logger.py     # Logging
│   └── templates/                 # HTML templates
│
├── shared/                # Shared utilities
│   ├── account_detector.py
│   ├── position_manager.py
│   ├── position_types.py
│   └── order_service.py
│
├── stocks/                # Stocks Dashboard (stocks_web.py Flask app)
├── futures/               # Futures Dashboard (futures_web.py Flask app)
│
├── models/                # Data models (Position, OptionOrder, PnLSummary)
├── services/              # Business logic services
│   ├── option_service.py
│   ├── pnl_calculator.py
│   ├── position_classifier.py
│   └── data_repository.py
│
├── tests/                 # All test files
├── docs/                  # Documentation
└── backup/                # Old files (untracked)
```

## Portfolio Dashboard Architecture

**Backend (Service Layer):**
- **Flask Routes**: API endpoints (`/api/options`, `/api/daily-pnl`, `/api/update`)
- **OptionService**: Main business orchestration and position management
- **PnLCalculator**: Accurate P&L calculations with orphaned order filtering
- **PositionClassifier**: Position status determination (open/closed/expired)
- **DataRepository**: SQLite operations with normalized schema
- **OptionsDatabase**: Normalized SQLite with incremental data collection

**Frontend (Modular Components):**
- **api-service.js**: Centralized HTTP request handling
- **summary-card.js**: Reusable summary statistics cards
- **position-table.js**: Enhanced table rendering with sorting
- **calendar.js**: Calendar view for daily P&L
- **main.js**, **rendering.js**, **filters.js**, **sorting.js**: Core functionality

**Key Features:**
- Incremental data fetching (only new orders since last update)
- Orphaned order filtering for accurate P&L
- Calendar view showing daily P&L
- Configurable start dates via config.json

## Risk Manager Architecture

**Components:**
- **MultiAccountRiskManager**: Orchestrates multiple accounts
- **BaseRiskManager**: Core risk management per account
- **AccountDetector**: Discovers all Robinhood accounts
- **PositionManager**: Centralized position tracking

**Key Features:**
- Multi-account support (Standard, Roth IRA, Traditional IRA)
- Real-time position monitoring with 1-second updates
- Trailing stop management
- Custom limit price configuration
- Live trading mode with safety confirmations

## Database Schema (Portfolio)

```sql
-- Individual option orders
CREATE TABLE option_orders (
    robinhood_id TEXT UNIQUE,
    symbol TEXT,
    created_at TEXT,
    position_effect TEXT,  -- 'open' or 'close'
    expiration_date TEXT,
    strike_price TEXT,
    price REAL,
    quantity INTEGER,
    premium REAL,
    strategy TEXT,
    direction TEXT,
    option_type TEXT,
    option_ids TEXT,
    raw_data TEXT,
    fetched_at DATETIME
);

-- Computed positions (paired open/close orders)
CREATE TABLE positions (
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
    status TEXT,  -- 'open', 'closed', 'expired'
    updated_at DATETIME
);
```

## Dependencies

```bash
pip install flask robin-stocks pandas pytz
```

## Testing

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_futures_helpers.py

# Test imports
python -c "from portfolio.rh_web import app; print('Portfolio OK')"
python -c "from risk_manager.risk_manager_web import app; print('Risk Manager OK')"
```

## Key Implementation Details

**Portfolio P&L Accuracy:**
- Filters out orphaned close orders (positions with no open_premium)
- Handles debit/credit expiration logic correctly
- Service layer architecture for better maintainability

**Risk Manager Safety:**
- Account isolation prevents cross-account operations
- Requires explicit `--live` flag for real trading
- Detailed logging of all order activities
- Limit orders only (no market orders)

**Incremental Data Collection:**
- Uses configurable start date (default: Jan 1st of current year)
- Fetches only new orders since last update
- Deduplicates using robinhood_id

## Configuration

**config.json** - Portfolio dashboard settings:
```json
{
  "data_fetching": {
    "default_start_date": "2024-01-01",
    "default_days_back": 60,
    "full_refresh_days_back": 90,
    "use_start_of_year": true,
    "incremental_buffer_days": 1
  }
}
```

## Security Considerations

- Robinhood credentials used only for authentication, not stored
- Flask debug mode enabled (disable in production)
- No explicit session management or CSRF protection
- Multi-account operations are isolated by account_number

## Git Commits

Do NOT include AI attribution (Co-Authored-By) in commit messages.

## Documentation

See `docs/` for detailed architecture and API documentation:
- **ARCHITECTURE.md** - Detailed architecture documentation
- **FUTURES_API_DISCOVERY.md** - Robinhood Futures API reverse engineering
- **API.md** - API endpoint documentation
- **RISK_MANAGER_PLAN.md** - Risk manager implementation plan
