# Risk Manager - Plan and Architecture

## Overview
A real-time risk management system that monitors open option positions during market hours and can automatically close positions based on predefined risk criteria.

## Core Objectives
- **Monitor open positions** with minimal API calls during market hours
- **Risk assessment** based on P&L, time decay, and market conditions  
- **Automated position closing** via limit orders when risk thresholds are exceeded
- **Debug mode** with detailed logging for development and testing
- **Safe execution** with dry-run mode and manual override capabilities

## Architecture

### 1. Data Integration - High Frequency Monitoring
- **Cached position data**: Load open positions once, cache in memory
- **Strategic API calls**: 
  - Position details: Every 30-60 seconds (only open positions)
  - Market data/quotes: Every 5-10 seconds for current prices
  - Order status: Every 2-3 seconds when orders are active
- **Real-time monitoring**: Check cached positions every 1 second for risk calculations
- **Smart refresh**: Only API call when position count changes or significant time elapsed

### 2. Risk Assessment Engine
- **P&L thresholds**: Close positions at predefined loss/profit levels
- **Time decay**: Monitor theta decay on short options positions  
- **Days to expiration**: Emergency close positions approaching expiration
- **Volatility changes**: React to IV expansion/contraction
- **Delta exposure**: Monitor overall portfolio delta

### 3. Position Closing System
- **Limit orders only**: No market orders for safety
- **Position type detection**: Automatically determine close order type:
  - Long calls/puts → Sell to close (credit)
  - Short calls/puts → Buy to close (debit)
  - Spreads → Close both legs with appropriate order types
- **Order validation**: Verify all parameters before submission
- **Execution tracking**: Monitor order status and fills

### 4. Safety Mechanisms
- **Dry-run mode**: Test all logic without placing real orders
- **Manual override**: Ability to disable automated trading
- **Position limits**: Maximum number of positions to close per session
- **Error handling**: Graceful handling of API failures and network issues

## Implementation Plan

### Phase 1: Position Monitor (Current Sprint)
```python
# Core monitoring functionality
- Connect to existing database
- Fetch open positions efficiently  
- Calculate real-time P&L
- Print position status with debug info
- Market hours detection
```

### Phase 2: Risk Rules Engine
```python  
# Risk assessment logic
- Configurable risk thresholds
- P&L calculation improvements
- Time-based rules (DTE, theta)
- Portfolio-level risk metrics
```

### Phase 3: Position Closing
```python
# Automated order placement
- Robin-stocks integration for closing orders
- Order type determination logic
- Limit price calculation strategies
- Order status monitoring
```

### Phase 4: Advanced Features  
```python
# Enhanced capabilities
- Volatility monitoring
- Greeks calculation
- Multi-leg spread handling
- Performance analytics
```

## Risk Management Rules

### Default Risk Thresholds
- **Stop Loss**: -50% of premium paid/received per position
- **Profit Target**: 50% of max profit on short positions  
- **Emergency Close**: 1 DTE (day to expiration) for short positions
- **Time Decay**: Close short positions at 21 DTE if unprofitable

### Position-Specific Rules
- **Long Options**: Focus on P&L and time decay
- **Short Options**: Focus on early profit capture and assignment risk
- **Spreads**: Monitor both legs and net position risk
- **High IV Positions**: Tighter stop losses due to volatility risk

## Technical Implementation

### Robin-Stocks API Integration
Based on research, key functions for closing positions:

```python
# Long position closing (sell to close)
robin_stocks.order_sell_option_limit(
    positionEffect='close',
    creditOrDebit='credit', 
    price=limit_price,
    symbol=underlying,
    quantity=contracts,
    expirationDate=exp_date,
    strike=strike_price,
    optionType='call'/'put',
    timeInForce='gtc'
)

# Short position closing (buy to close)  
robin_stocks.order_buy_option_limit(
    positionEffect='close',
    creditOrDebit='debit',
    price=limit_price,
    symbol=underlying, 
    quantity=contracts,
    expirationDate=exp_date,
    strike=strike_price,
    optionType='call'/'put',
    timeInForce='gtc'
)
```

### Market Hours Detection & Monitoring Frequency
- **Regular Hours**: 9:30 AM - 4:00 PM ET
- **High-Frequency Mode**: 
  - Risk calculations: Every 1 second (using cached data)
  - Price updates: Every 5-10 seconds via quotes API
  - Position refresh: Every 30-60 seconds
  - Order status: Every 2-3 seconds when orders active
- **Off-hours Mode**: Every 5 minutes, primarily for after-hours news

### Database Integration
- **Read-only access** to existing options.db
- **Separate risk_log table** for tracking actions and decisions
- **Position state caching** to minimize database queries

## File Structure
```
risk_manager.py          # Main risk management script
risk_config.py          # Configuration and thresholds  
position_monitor.py     # Position monitoring functions
order_manager.py        # Order placement and tracking
market_utils.py         # Market hours and timing utilities
risk_logger.py          # Logging and alerting system
```

## Configuration Example
```python
RISK_CONFIG = {
    'stop_loss_percent': 0.50,      # 50% stop loss
    'profit_target_percent': 0.50,   # 50% profit target  
    'emergency_close_dte': 1,        # Close at 1 DTE
    'check_interval': 180,           # 3 minutes
    'max_daily_closes': 10,          # Safety limit
    'dry_run': True,                 # Start in test mode
    'debug_mode': True               # Verbose logging
}
```

## Next Steps
1. ✅ Research robin-stocks API (completed)
2. 🔄 Create initial position monitor script  
3. ⏳ Add market hours detection
4. ⏳ Implement basic risk rules
5. ⏳ Add order placement functionality
6. ⏳ Testing and validation

## Success Criteria
- **Reliable monitoring**: No missed position updates during market hours
- **Safe execution**: No unintended orders or system failures  
- **Effective risk management**: Demonstrable P&L protection
- **Operational efficiency**: Minimal manual intervention required

---

**Note**: This system will start in debug/dry-run mode and require explicit activation for live trading. All automated actions will be logged and auditable.