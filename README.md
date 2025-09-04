# Multi-Account Options Risk Manager

A real-time web-based risk management system for monitoring and managing long option positions across multiple Robinhood accounts with advanced order customization, trailing stop functionality, and automated execution.

## Features

### 🏦 **Multi-Account Support**
- Automatic detection of all Robinhood accounts (Standard, Roth IRA, Traditional IRA)
- Isolated risk management per account to prevent cross-contamination
- Independent monitoring threads for each active account
- Account-specific order tracking and execution

### 🎯 **Position Monitoring**
- Real-time monitoring of long option positions from Robinhood
- Live P&L calculations using current market prices
- Automatic refresh every 10 seconds
- High-frequency price updates (1-second precision during market hours)

### 💰 **Advanced Order Customization**
- Interactive sliders for stop loss (5% - 50%) and take profit (10% - 200%)
- Real-time price calculation when adjusting sliders
- Manual price editing with instant preview updates
- Custom limit price submission

### 📈 **Trailing Stop Management**
- Interactive trailing stop configuration (5% - 50% range)
- Visual indicators for active/triggered trailing stops
- Real-time trigger price calculations
- Automatic highest price tracking (ratcheting up only)

### 🔥 **Order Execution**
- Live Trading Mode: Submit real orders with full tracking
- Intelligent limit pricing based on user input or market conditions
- Order status monitoring with specific order ID tracking

### 🛡️ **Safety Features**
- Command-line controlled live trading mode
- Explicit confirmation required for real money trading
- Detailed console logging of all order activities
- Eastern Time market hours detection
- Account isolation prevents accidental cross-account operations

## Installation

```bash
# Install dependencies
pip install flask robin-stocks pandas pytz
```

## Usage

### Starting the Application

#### Live Trading Mode (Real Orders!)
```bash
python risk_manager_web.py --live
```
⚠️ **WARNING**: This will place real orders with real money!
- Requires typing "YES" to confirm
- Shows clear warnings about live trading risks

#### Custom Port
```bash
python risk_manager_web.py --port 8000
```

### Web Interface

**Account Selector:**
- 🏦 Visual cards for each detected account type
- Activity indicators showing accounts with positions/orders
- Click any account to access its risk management dashboard

**Main Dashboard (Per Account):**
- 📊 Portfolio summary with total P&L for selected account
- 🔄 Refresh button for manual updates  
- 📋 Check Orders button for order status
- Real-time market hours and trading mode indicators

**Position Cards:**
- Current price vs premium paid
- P&L with percentage calculations
- Trailing stop and take profit visual indicators
- Close order preview with exact API calls
- Individual position controls per account

**Close Position Modal:**
- 🛑 Stop Loss slider (5% - 50% with 1% increments)
- 💰 Take Profit slider (10% - 200% with 5% increments)
- Manual price editing with real-time calculations
- Preview of exact order parameters before submission

**Trailing Stop Configuration:**
- Click "🎯 Trail Stop" on any position
- Interactive percentage slider (5% - 50%)
- Real-time trigger price preview
- Enable/disable toggle with visual feedback

## Architecture

### Components

1. **`risk_manager_web.py`** - Main Flask application
   - Web server and API endpoints
   - Multi-account order execution logic
   - Account-specific routing and isolation

2. **`multi_account_manager.py`** - Multi-account orchestration
   - Account detection and management
   - Independent monitoring threads per account
   - Thread lifecycle management

3. **`account_detector.py`** - Account discovery
   - Robinhood account detection (Standard, Roth IRA, Traditional IRA)
   - Activity checking (positions/orders)
   - Account information caching

4. **`base_risk_manager.py`** - Core risk management functionality
   - Position loading from Robinhood API per account
   - Market data fetching and P&L calculations
   - Order parameter generation

5. **`templates/`** - Web interface templates
   - `account_selector.html` - Multi-account selection interface
   - `risk_manager.html` - Account-specific risk management dashboard

### API Endpoints

#### Multi-Account Endpoints
- **`GET /`** - Account selector interface
- **`GET /account/<account_prefix>`** - Account-specific dashboard
- **`GET /api/account/<account_prefix>/positions`** - Get positions for specific account
- **`POST /api/account/<account_prefix>/close-simulation`** - Execute orders for specific account
- **`POST /api/account/<account_prefix>/trailing-stop`** - Configure trailing stops for specific account

#### Legacy Single-Account Endpoints (redirected)
- **`GET /api/positions`** - Redirects to account selector
- **`POST /api/close-simulation`** - Returns error directing to account-specific endpoint

### Data Flow

1. **Account Detection**: Automatic discovery of all Robinhood accounts on startup
2. **Authentication**: Automatic Robinhood login using cached credentials
3. **Account Selection**: User selects account from web interface
4. **Position Loading**: Fetch open long positions via `r.get_open_option_positions(account_number=...)`
5. **Market Data**: Real-time pricing via `r.get_option_market_data_by_id()`
6. **Risk Monitoring**: 1-second updates during market hours, 60-second intervals after hours
7. **Order Customization**: Interactive sliders and manual input for custom pricing
8. **Order Execution**: Account-specific `r.order_sell_option_limit()` calls
9. **Order Tracking**: `r.get_option_order_info(order_id)` for status monitoring

## Order Execution

### Live Trading Mode Output
```
============================================================
🔥 LIVE TRADING MODE - Account ...7315: SUBMITTING REAL ORDERS FOR 1 POSITION(S)
============================================================

📈 Position 1: QQQ 571.0CALL 2025-09-02
   🔥 SUBMITTING REAL ORDER...
   ✅ REAL ORDER SUBMITTED: abc123-def456-ghi789
   
🔍 CHECKING ORDER STATUS...
📊 Order ID: abc123...
   Account: ...7315
   Symbol: QQQ
   State: confirmed
   Price: $3.30
```

## Price Customization

### Interactive Sliders
- **Stop Loss**: 5% - 50% range with 1% increments
- **Take Profit**: 10% - 200% range with 5% increments
- Real-time price calculation as you move sliders
- Automatic limit price updates in order preview

### Manual Price Editing
- Click on any price field to edit manually
- Instant calculation of estimated proceeds
- Visual feedback for price changes
- Reset to default calculations available

### Order Preview
- Shows exact `robin_stocks.order_sell_option_limit()` call
- Updates dynamically with slider/manual changes
- Different preview for trailing stop orders (stop-limit type)
- Displays custom prices instead of default calculations

## Trailing Stop Logic

### How It Works
1. **Enable**: Set trailing stop percentage (5% - 50%)
2. **Track High**: System tracks highest price seen since activation
3. **Calculate Trigger**: `trigger_price = highest_price × (1 - percent/100)`
4. **Monitor**: Check every second during market hours per account
5. **Execute**: When `current_price ≤ trigger_price`, stop-limit order is triggered

### Example
- **Setup**: 20% trailing stop on option at $1.00
- **Price rises to $1.50**: `trigger_price = $1.20`
- **Price drops to $1.19**: 🔥 **TRIGGERED!** (stop-limit order submitted)

## Market Hours

- **Active Monitoring**: 9:30 AM - 4:00 PM ET (1-second updates)
- **After Hours**: 60-second monitoring intervals (options don't trade after hours)
- **Weekends**: Minimal monitoring
- **Independent per Account**: Each account monitored separately

## Multi-Account Safety

### Account Isolation
- **Separate Risk Managers**: Each account gets its own `BaseRiskManager` instance
- **Independent Monitoring**: Separate threads prevent cross-contamination
- **Account-Specific Orders**: All orders tagged with specific account numbers
- **Isolated Position Tracking**: Positions never mixed between accounts

### Account Types Supported
- **Standard Brokerage**: Regular trading account
- **Roth IRA**: Tax-advantaged retirement account  
- **Traditional IRA**: Traditional retirement account
- **Automatic Detection**: System discovers all available account types

## Safety Considerations

⚠️ **IMPORTANT**: This system can place real orders with real money when run in live mode.

### Before Using Live Trading:
1. **Test thoroughly** in simulation mode first
2. **Understand** trailing stop and price customization behavior
3. **Verify** all position details and custom limit prices
4. **Start small** with non-critical positions
5. **Monitor actively** during first live sessions
6. **Confirm account selection** before executing orders

### Risk Management:
- Only handles long option positions (buy-to-close orders)
- Uses limit orders only (no market orders)
- Account isolation prevents accidental cross-account operations
- Requires explicit confirmation for live trading
- Provides detailed logging of all activities per account
- Custom pricing allows for better risk control

## Troubleshooting

### Common Issues

**Authentication Errors:**
- Ensure Robinhood credentials are valid
- Check 2FA settings if applicable

**No Accounts Found:**
- Verify Robinhood login is successful
- Check account permissions for API access

**No Positions Found:**
- Verify you have open long option positions in selected account
- Check position types (only long positions supported)

**Price Customization Issues:**
- Ensure custom prices are reasonable (> $0.01)
- Check that sliders are working in close position modal
- Verify calculated prices match expected values

**Order Submission Failures:**
- Verify account has sufficient permissions
- Check position quantities and custom limit prices
- Ensure options are still valid (not expired)
- Confirm account selection is correct

### Debug Mode
All operations include detailed console logging for debugging and verification, including account-specific identifiers.

## File Structure
```
rh_web/
├── risk_manager_web.py          # Main Flask application with multi-account support
├── multi_account_manager.py     # Multi-account orchestration
├── account_detector.py          # Account discovery and management
├── base_risk_manager.py         # Core risk management per account
├── templates/
│   ├── account_selector.html    # Account selection interface
│   └── risk_manager.html        # Account-specific risk management dashboard
├── README.md                    # This file
└── CLAUDE.md                    # Project instructions for Claude Code
```

## Authentication

- Automatic Robinhood login on startup
- Credentials used only for authentication
- No credentials stored in application
- Session maintained throughout application runtime
- Multi-account support uses same authentication session

---

**⚠️ DISCLAIMER**: This software is provided as-is without warranty. Trading options involves significant risk. Always test thoroughly before using with real money. Multi-account features add complexity - ensure you understand which account you're operating on at all times.
