# Robinhood Trading Tools

Flask-based web applications for managing and analyzing Robinhood trading:
- **Portfolio Dashboard (Options)**: Analyze options trading history with P&L tracking and calendar views
- **Stocks Dashboard**: Track stock trades with comprehensive P&L analytics
- **Futures Dashboard**: Monitor futures positions and trading activity
- **Risk Manager**: Real-time multi-account risk management with automated execution

📊 **[View Class Diagram](class-diagram.html)** - Technical architecture diagram

## Quick Start

### Portfolio Dashboard (Options)
```bash
python -m portfolio.rh_web
```
Visit: http://localhost:3000

### Stocks Dashboard
```bash
python -m stocks.stocks_web
```
Visit: http://localhost:3002

### Futures Dashboard
```bash
python -m futures.futures_web
```
Visit: http://localhost:3001

### Risk Manager
```bash
# Simulation mode (safe)
python -m risk_manager.risk_manager_web

# Live trading mode (real orders!)
python -m risk_manager.risk_manager_web --live
```
Visit: http://localhost:5000

## Installation

```bash
pip install flask robin-stocks pandas pytz
```

## Running with Docker

The apps ship with a `Dockerfile` and `docker-compose.yml` for containerized runs.

**One-time auth setup.** Robinhood login uses MFA and can't run non-interactively.
Log in once on the host to generate the session token, then the containers reuse it:

```bash
python -m risk_manager.risk_manager_web   # complete MFA, then Ctrl-C
```

This writes `~/.tokens/robinhood.pickle`, which every service mounts read-write.
Re-run whenever the token expires.

**Build and run (read-only dashboards):**

```bash
docker compose up --build portfolio risk-manager
```

| Service | URL | Mode |
|---|---|---|
| `portfolio` | http://localhost:3000 | dashboard |
| `risk-manager` | http://localhost:5001 | read-only |

**Live trading** (places REAL orders) is gated behind the `live` profile:

```bash
docker compose --profile live up risk-manager-live
```

The `risk-manager-live` service sets `RH_CONFIRM_LIVE=YES` to bypass the interactive
confirmation prompt. It binds the same port 5001 as `risk-manager`, so run only one
at a time.

State (`*.db`, `logs/`, `exports/`) is persisted via volume mounts, so rebuilding
images does not lose data.

## Portfolio Dashboard

Modern dashboard for analyzing Robinhood options trading history.

### Features

- **📊 P&L Tracking**: Accurate profit/loss calculations with orphaned order filtering
- **📅 Calendar View**: Daily P&L breakdown in calendar format
- **🔄 Incremental Updates**: Efficient data fetching (only new orders)
- **📈 Position Analysis**: Track open, closed, and expired positions
- **🎨 Modular Frontend**: Component-based architecture with fallback safety

### Components

**Backend:**
- `portfolio/rh_web.py` - Flask application
- `portfolio/data_fetcher.py` - Data fetching with smart incremental updates
- `portfolio/database.py` - SQLite operations
- `services/option_service.py` - Business logic orchestration
- `services/pnl_calculator.py` - Accurate P&L calculations
- `services/position_classifier.py` - Position status determination

**Frontend:**
- `portfolio/static/js/components/` - Modular components (summary-card, position-table)
- `portfolio/static/js/services/` - API service layer
- `portfolio/static/js/calendar.js` - Calendar view
- `portfolio/templates/` - HTML templates

### Database Schema

**option_orders** - Individual orders from Robinhood API
```sql
robinhood_id, symbol, created_at, position_effect,
expiration_date, strike_price, price, quantity, premium,
strategy, direction, option_type, option_ids, raw_data
```

**positions** - Computed paired open/close positions
```sql
option_key, symbol, open_date, close_date, expiration_date,
strike_price, quantity, open_price, close_price,
open_premium, close_premium, net_credit,
strategy, direction, option_type, status
```

### Configuration

Edit `config.json` to customize data fetching:
```json
{
  "data_fetching": {
    "default_start_date": "2024-01-01",
    "use_start_of_year": true,
    "incremental_buffer_days": 1
  }
}
```

## Risk Manager

Real-time multi-account risk management system for monitoring and managing long option positions.

### Features

#### 🏦 Multi-Account Support
- Automatic detection of all Robinhood accounts (Standard, Roth IRA, Traditional IRA)
- Isolated risk management per account
- Independent monitoring threads for each account
- Account-specific order tracking and execution

#### 🎯 Position Monitoring
- Real-time monitoring of long option positions
- Live P&L calculations using current market prices
- Automatic refresh every 10 seconds
- High-frequency updates (1-second during market hours)

#### 💰 Advanced Order Customization
- Interactive sliders for stop loss (5% - 50%) and take profit (10% - 200%)
- Real-time price calculation when adjusting sliders
- Manual price editing with instant preview updates
- Custom limit price submission

#### 📈 Trailing Stop Management
- Interactive trailing stop configuration (5% - 50% range)
- Visual indicators for active/triggered trailing stops
- Real-time trigger price calculations
- Automatic highest price tracking (ratcheting up only)

#### 🔥 Order Execution
- **Simulation Mode** (default): Preview orders without execution
- **Live Trading Mode** (`--live` flag): Submit real orders with full tracking
- Intelligent limit pricing based on user input or market conditions
- Order status monitoring with specific order ID tracking

#### 🛡️ Safety Features
- Command-line controlled live trading mode
- Explicit confirmation required for real money trading
- Detailed console logging of all order activities
- Eastern Time market hours detection
- Account isolation prevents accidental cross-account operations

### Components

**Core:**
- `risk_manager/risk_manager_web.py` - Main Flask application
- `risk_manager/multi_account_manager.py` - Multi-account orchestration
- `risk_manager/base_risk_manager.py` - Core risk management per account
- `risk_manager/risk_manager_logger.py` - Logging system

**Shared:**
- `shared/account_detector.py` - Account discovery and management
- `shared/position_manager.py` - Centralized position tracking
- `shared/position_types.py` - Position data structures

**Templates:**
- `risk_manager/templates/account_selector.html` - Multi-account selection interface
- `risk_manager/templates/risk_manager.html` - Account-specific dashboard

### Usage

#### Starting Live Trading Mode
```bash
python -m risk_manager.risk_manager_web --live
```
⚠️ **WARNING**: This will place real orders with real money!
- Requires typing "YES" to confirm
- Shows clear warnings about live trading risks

#### Web Interface

**Account Selector:**
- Visual cards for each detected account type
- Activity indicators showing accounts with positions/orders
- Click any account to access its risk management dashboard

**Main Dashboard (Per Account):**
- Portfolio summary with total P&L for selected account
- Refresh button for manual updates
- Check Orders button for order status
- Real-time market hours and trading mode indicators

**Position Cards:**
- Current price vs premium paid
- P&L with percentage calculations
- Trailing stop and take profit visual indicators
- Close order preview with exact API calls
- Individual position controls per account

**Close Position Modal:**
- Stop Loss slider (5% - 50% with 1% increments)
- Take Profit slider (10% - 200% with 5% increments)
- Manual price editing with real-time calculations
- Preview of exact order parameters before submission

**Trailing Stop Configuration:**
- Click "🎯 Trail Stop" on any position
- Interactive percentage slider (5% - 50%)
- Real-time trigger price preview
- Enable/disable toggle with visual feedback

### API Endpoints

#### Multi-Account Endpoints
- `GET /` - Account selector interface
- `GET /account/<account_prefix>` - Account-specific dashboard
- `GET /api/account/<account_prefix>/positions` - Get positions for specific account
- `POST /api/account/<account_prefix>/close-simulation` - Execute orders for specific account
- `POST /api/account/<account_prefix>/trailing-stop` - Configure trailing stops

### Trailing Stop Logic

1. **Enable**: Set trailing stop percentage (5% - 50%)
2. **Track High**: System tracks highest price seen since activation
3. **Calculate Trigger**: `trigger_price = highest_price × (1 - percent/100)`
4. **Monitor**: Check every second during market hours per account
5. **Execute**: When `current_price ≤ trigger_price`, stop-limit order is triggered

**Example:**
- Setup: 20% trailing stop on option at $1.00
- Price rises to $1.50: `trigger_price = $1.20`
- Price drops to $1.19: 🔥 **TRIGGERED!** (stop-limit order submitted)

### Market Hours

- **Active Monitoring**: 9:30 AM - 4:00 PM ET (1-second updates)
- **After Hours**: 60-second monitoring intervals
- **Weekends**: Minimal monitoring
- **Independent per Account**: Each account monitored separately

## Project Structure

```
rh_web/
├── portfolio/              # Portfolio Dashboard
│   ├── rh_web.py          # Flask app
│   ├── data_fetcher.py    # Data fetching with incremental updates
│   ├── database.py        # SQLite operations
│   ├── static/            # CSS, JS components
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
│   ├── account_detector.py        # Account discovery
│   ├── position_manager.py        # Position tracking
│   ├── position_types.py          # Data structures
│   └── order_service.py           # Order utilities
│
├── models/                # Data models
│   ├── position.py
│   ├── option_order.py
│   └── pnl_summary.py
│
├── services/              # Business logic
│   ├── option_service.py          # Main orchestration
│   ├── pnl_calculator.py          # P&L calculations
│   ├── position_classifier.py     # Position status
│   └── data_repository.py         # Data access
│
├── tests/                 # All test files
├── docs/                  # Documentation
├── config.json            # Configuration
└── README.md              # This file
```

## Testing

```bash
# Run all tests
pytest tests/

# Run specific test
pytest tests/test_futures_helpers.py

# Test imports
python -c "from portfolio.rh_web import app; print('Portfolio OK')"
python -c "from risk_manager.risk_manager_web import app; print('Risk Manager OK')"
```

## Safety Considerations

⚠️ **IMPORTANT**: Risk Manager can place real orders with real money when run in live mode.

### Before Using Live Trading:
1. **Understand** trailing stop and price customization behavior
2. **Verify** all position details and custom limit prices
3. **Start small** with non-critical positions
4. **Monitor actively** during first live sessions
5. **Confirm account selection** before executing orders

### Risk Management:
- Only handles long option positions (buy-to-close orders)
- Uses limit orders only (no market orders)
- Account isolation prevents accidental cross-account operations
- Requires explicit confirmation for live trading
- Provides detailed logging of all activities
- Custom pricing allows for better risk control

## Authentication

- Automatic Robinhood login on startup
- Credentials used only for authentication
- No credentials stored in application
- Session maintained throughout application runtime
- Multi-account support uses same authentication session

## Documentation

See `docs/` for detailed documentation:
- **ARCHITECTURE.md** - Detailed architecture
- **FUTURES_API_DISCOVERY.md** - Futures API reverse engineering
- **API.md** - API endpoints
- **RISK_MANAGER_PLAN.md** - Risk manager design
- **CLAUDE.md** - Development guidelines

---

**⚠️ DISCLAIMER**: This software is provided as-is without warranty. Trading options involves significant risk. Always test thoroughly before using with real money. Multi-account features add complexity - ensure you understand which account you're operating on at all times.
