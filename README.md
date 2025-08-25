# Options Risk Manager

A real-time web-based risk management system for monitoring and managing long option positions with trailing stop functionality and automated order execution.

## Features

### 🎯 **Position Monitoring**
- Real-time monitoring of long option positions from Robinhood
- Live P&L calculations using current market prices
- Automatic refresh every 10 seconds
- High-frequency trailing stop updates (1-second precision during market hours)

### 📈 **Trailing Stop Management**
- Interactive trailing stop configuration (5% - 50% range)
- Visual indicators for active/triggered trailing stops
- Real-time trigger price calculations
- Automatic highest price tracking (ratcheting up only)

### 🔥 **Order Execution**
- **Simulation Mode**: Preview exact robin-stocks API calls
- **Live Trading Mode**: Submit real orders with full tracking
- Intelligent limit pricing based on trailing stops or market conditions
- Order status monitoring with specific order ID tracking

### 🛡️ **Safety Features**
- Command-line controlled live trading mode
- Explicit confirmation required for real money trading
- Detailed console logging of all order activities
- Eastern Time market hours detection

## Installation

```bash
# Install dependencies
pip install flask robin-stocks pandas pytz
```

## Usage

### Starting the Application

#### Simulation Mode (Safe - No Real Orders)
```bash
python risk_manager_web.py
```
Access at: http://localhost:5001

#### Live Trading Mode (Real Orders!)
```bash
python risk_manager_web.py --live
```
⚠️ **WARNING**: This will place real orders with real money!
- Requires typing "YES I UNDERSTAND" to confirm
- Shows clear warnings about live trading risks

#### Custom Port
```bash
python risk_manager_web.py --port 8000
```

### Web Interface

**Main Dashboard:**
- 📊 Portfolio summary with total P&L
- 🔄 Refresh button for manual updates  
- 📋 Check Orders button for order status
- Real-time market hours and trading mode indicators

**Position Cards:**
- Current price vs premium paid
- P&L with percentage calculations
- Trailing stop visual indicators
- Close order preview with exact API calls
- Individual position controls

**Trailing Stop Configuration:**
- Click "🎯 Trail Stop" on any position
- Interactive percentage slider (5% - 50%)
- Real-time trigger price preview
- Enable/disable toggle with visual feedback

## Architecture

### Components

1. **`risk_manager_web.py`** - Main Flask application
   - Web server and API endpoints
   - Order simulation and execution logic
   - High-frequency monitoring system

2. **`base_risk_manager.py`** - Core risk management functionality
   - Position loading from Robinhood API
   - Market data fetching and P&L calculations
   - Order parameter generation

3. **`templates/risk_manager.html`** - Web interface
   - Bootstrap-based responsive UI
   - JavaScript for real-time updates
   - Interactive trailing stop controls

### API Endpoints

- **`GET /api/positions`** - Get current positions and P&L
- **`POST /api/close-simulation`** - Simulate/execute position closures
- **`POST /api/trailing-stop`** - Configure trailing stops
- **`GET /api/check-orders`** - Check status of submitted orders

### Data Flow

1. **Authentication**: Automatic Robinhood login on startup
2. **Position Loading**: Fetch open long positions via `r.get_open_option_positions()`
3. **Market Data**: Real-time pricing via `r.get_option_market_data_by_id()`
4. **Risk Monitoring**: 1-second trailing stop updates during market hours
5. **Order Execution**: `r.order_sell_option_limit()` for position closures
6. **Order Tracking**: `r.get_option_order_info(order_id)` for status monitoring

## Order Execution

### Simulation Mode Output
```
============================================================
🎯 SIMULATION MODE: CLOSE ORDERS FOR 1 POSITION(S)
============================================================

📈 Position 1: QQQ 565.0PUT 2025-08-25
   Premium Paid: $47.00
   Current Price: $0.26
   Limit Price: $0.25 (Market Price - 5%)
   Estimated Proceeds: $25.00
   Robin-Stocks API Call:
   --------------------------------------------------
robin_stocks.order_sell_option_limit(
    positionEffect='close',
    creditOrDebit='credit',
    price=0.25,
    symbol='QQQ',
    quantity=1,
    expirationDate='2025-08-25',
    strike=565.0,
    optionType='put',
    timeInForce='gtc'
)
```

### Live Trading Mode Output
```
============================================================
🔥 LIVE TRADING MODE: SUBMITTING REAL ORDERS FOR 1 POSITION(S)
============================================================

📈 Position 1: QQQ 565.0PUT 2025-08-25
   🔥 SUBMITTING REAL ORDER...
   ✅ REAL ORDER SUBMITTED: abc123-def456-ghi789
   
🔍 CHECKING ORDER STATUS...
📊 Order ID: abc123...
   Symbol: QQQ
   State: confirmed
   Price: $0.25
```

## Trailing Stop Logic

### How It Works
1. **Enable**: Set trailing stop percentage (5% - 50%)
2. **Track High**: System tracks highest price seen since activation
3. **Calculate Trigger**: `trigger_price = highest_price × (1 - percent/100)`
4. **Monitor**: Check every second during market hours
5. **Execute**: When `current_price ≤ trigger_price`, order is triggered

### Example
- **Setup**: 20% trailing stop on option at $1.00
- **Price rises to $1.50**: `trigger_price = $1.20`
- **Price drops to $1.19**: 🔥 **TRIGGERED!** (order submitted)

## Market Hours

- **Active Monitoring**: 9:30 AM - 4:00 PM ET (1-second updates)
- **After Hours**: 10-second monitoring intervals
- **Weekends**: Minimal monitoring

## Safety Considerations

⚠️ **IMPORTANT**: This system can place real orders with real money when run in live mode.

### Before Using Live Trading:
1. **Test thoroughly** in simulation mode first
2. **Understand** trailing stop behavior
3. **Verify** all position details and limit prices
4. **Start small** with non-critical positions
5. **Monitor actively** during first live sessions

### Risk Management:
- Only handles long option positions (buy-to-close orders)
- Uses limit orders only (no market orders)
- Requires explicit confirmation for live trading
- Provides detailed logging of all activities

## Troubleshooting

### Common Issues

**Authentication Errors:**
- Ensure Robinhood credentials are valid
- Check 2FA settings if applicable

**No Positions Found:**
- Verify you have open long option positions
- Check position types (only long positions supported)

**Market Data Issues:**
- Ensure market is open for real-time pricing
- Check network connectivity

**Order Submission Failures:**
- Verify account has sufficient permissions
- Check position quantities and limit prices
- Ensure options are still valid (not expired)

### Debug Mode
All operations include detailed console logging for debugging and verification.

## File Structure
```
rh_web/
├── risk_manager_web.py      # Main Flask application
├── base_risk_manager.py     # Core risk management
├── templates/
│   └── risk_manager.html    # Web interface
├── README.md               # This file
└── RISK_MANAGER_PLAN.md    # Detailed architecture plan
```

## Authentication

- Automatic Robinhood login on startup
- Credentials used only for authentication
- No credentials stored in application
- Session maintained throughout application runtime

---

**⚠️ DISCLAIMER**: This software is provided as-is without warranty. Trading options involves significant risk. Always test thoroughly before using with real money.