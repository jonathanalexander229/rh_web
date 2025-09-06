#!/usr/bin/env python3
"""
Multi-Account Risk Manager Web Interface
Supports both single-account (legacy) and multi-account modes
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for
import json
import datetime
import threading
import time
import argparse
import sys
import logging
import os
import robin_stocks.robinhood as r
from base_risk_manager import BaseRiskManager
from risk_manager_logger import RiskManagerLogger
from account_detector import AccountDetector
from multi_account_manager import MultiAccountRiskManager
from shared.order_service import OrderService
from position_manager import position_manager

app = Flask(__name__)

# Initialize logger
rm_logger = RiskManagerLogger()
rm_logger.log_session_start()
logger = rm_logger.main_logger  # For backwards compatibility

# Initialize order service
order_service = OrderService(rm_logger)
position_manager.set_order_service(order_service)

# Global instances
multi_account_manager = None
account_detector = None
live_trading_mode = False

# JSON response helpers
def json_ok(data=None, **extra):
    payload = {'success': True}
    if data:
        payload.update(data)
    if extra:
        payload.update(extra)
    return jsonify(payload)

def json_err(message, status=400, **extra):
    payload = {'success': False, 'error': message}
    if extra:
        payload.update(extra)
    return jsonify(payload), status

def is_market_hours() -> bool:
    """Check if market is currently open"""
    from datetime import datetime
    import pytz
    
    # Get current Eastern time directly
    et = pytz.timezone('America/New_York')
    now = datetime.now(et)
    
    # Check if weekday
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Market hours: 9:30 AM to 4:00 PM ET
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return market_open <= now <= market_close

# Utility functions for order management and simulation

"""Simulation support removed; any old references are deprecated."""


"""Order submission handled by OrderService"""


@app.route('/')
def index():
    """Account selector landing page"""
    global account_detector
    
    if not account_detector:
        return "System not initialized", 500
    
    try:
        # Get all available accounts
        accounts = account_detector.detect_accounts()
        
        # Add activity status to each account
        for account_number, account_info in accounts.items():
            account_info['has_activity'] = account_detector.has_positions_or_orders(account_number)
        
        return render_template('account_selector.html', 
                             accounts=accounts,
                             live_trading_mode=live_trading_mode)
    except Exception as e:
        logger.error(f"Error in account selector: {e}")
        return f"Error loading accounts: {e}", 500

@app.route('/account/<account_prefix>')
def risk_manager_for_account(account_prefix):
    """Risk manager interface for a specific account"""
    global multi_account_manager, account_detector
    
    if not multi_account_manager:
        return "System not initialized", 500
    
    # Verify account exists and get full account number
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return f"Account not found: {account_prefix}", 404
    
    account_number = account_info['number']  # Get full account number for internal use
    
    # Start monitoring only if not already started to avoid duplicate loads
    if not multi_account_manager.get_account_risk_manager(account_number):
        multi_account_manager.start_account_monitoring(account_number)
    
    return render_template('risk_manager.html', 
                         account_prefix=account_prefix,
                         account_number=account_number,
                         account_info=account_info,
                         live_trading_mode=live_trading_mode)

def _build_positions_response(risk_manager, account_number=None):
    """Build positions response data"""
    global live_trading_mode  # Make sure we access the global variable
    positions_data = []
    total_pnl = 0
    
    for pos_key, position in risk_manager.positions.items():
        # Calculate current P&L via PositionManager
        position_manager.calculate_pnl(position)
        total_pnl += position.pnl
        
        # Add trailing stop data via PositionManager
        trail_stop_data = position_manager.update_trailing_stop_state(position)
        
        # Add take profit data (delegate to PositionManager to update flags)
        take_profit_data = position_manager.update_take_profit_state(position)
        
        # Trailing stop state (highest/trigger/triggered) already computed by PositionManager
        
        # Generate close order parameters
        if trail_stop_data['enabled']:
            limit_price = trail_stop_data['trigger_price']
        else:
            limit_price = round(position.current_price * 0.95, 2)
        
        proceeds = limit_price * position.quantity * 100
        
        close_order = {
            'positionEffect': 'close',
            'creditOrDebit': 'credit',
            'price': round(limit_price, 2),
            'symbol': position.symbol,
            'quantity': position.quantity,
            'expirationDate': position.expiration_date,
            'strike': position.strike_price,
            'optionType': position.option_type,
            'timeInForce': 'gtc',
            'estimated_proceeds': proceeds
        }
        
        position_data = {
            'symbol': position.symbol,
            'strike_price': position.strike_price,
            'option_type': position.option_type.upper(),
            'expiration_date': position.expiration_date,
            'quantity': position.quantity,
            'open_premium': position.open_premium,
            'current_price': position.current_price,
            'pnl': position.pnl,
            'pnl_percent': position.pnl_percent,
            'close_order': close_order,
            'status_color': 'success' if position.pnl > 0 else 'danger' if position.pnl < 0 else 'secondary',
            'trail_stop': trail_stop_data,
            'take_profit': take_profit_data
        }
        
        positions_data.append(position_data)
    
    response = {
        'positions': positions_data,
        'total_pnl': total_pnl,
        'market_open': risk_manager.is_market_hours(),
        'live_trading_mode': live_trading_mode,
        'last_update': datetime.datetime.now().strftime('%H:%M:%S')
    }
    
    # Add account info
    if account_number:
        response['account_number'] = account_number
        response['account_display'] = f"...{account_number[-4:]}"
    
    return jsonify(response)

def get_account_context(account_prefix):
    """Resolve account context (account_number, risk_manager) or return an error response."""
    global multi_account_manager, account_detector
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return None, None, json_err(f'Account not found: {account_prefix}')
    account_number = account_info['number']
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return None, None, json_err(f'Account ...{account_number[-4:]} not found')
    return account_number, risk_manager, None

@app.route('/api/account/<account_prefix>/positions')
def get_account_positions(account_prefix):
    """Get positions for a specific account"""
    global multi_account_manager, account_detector
    
    if not multi_account_manager:
        return jsonify({
            'positions': [],
            'total_pnl': 0,
            'market_open': False,
            'error': 'System not initialized',
            'last_update': datetime.datetime.now().strftime('%H:%M:%S')
        })
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({
            'positions': [],
            'total_pnl': 0,
            'market_open': False,
            'error': f'Account not found: {account_prefix}',
            'last_update': datetime.datetime.now().strftime('%H:%M:%S')
        })
    
    account_number = account_info['number']
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        # Try to start monitoring for this account
        multi_account_manager.start_account_monitoring(account_number)
        risk_manager = multi_account_manager.get_account_risk_manager(account_number)
        
        if not risk_manager:
            return jsonify({
                'positions': [],
                'total_pnl': 0,
                'market_open': False,
                'error': f'Account ...{account_number[-4:]} not found or has no positions',
                'last_update': datetime.datetime.now().strftime('%H:%M:%S')
            })
    
    # Use positions loaded by monitoring thread (no need to reload on every request)
    if len(risk_manager.positions) == 0:
        return jsonify({
            'positions': [],
            'total_pnl': 0,
            'market_open': risk_manager.is_market_hours(),
            'live_trading_mode': live_trading_mode,
            'message': f'No positions found for account ...{account_number[-4:]}',
            'last_update': datetime.datetime.now().strftime('%H:%M:%S')
        })
    
    return _build_positions_response(risk_manager, account_number)

@app.route('/api/account/<account_prefix>/reload-positions', methods=['POST'])
def reload_account_positions(account_prefix):
    """Force a one-time reload of positions for a specific account.
    Does not change default endpoint behavior; only runs on demand.
    """
    # Resolve account
    account_number, risk_manager, err = get_account_context(account_prefix)
    if err:
        return err

    try:
        # Refresh from Robinhood into PositionManager cache
        count = position_manager.load_positions_for_account(account_number)

        # Merge latest into the per-account risk_manager view, preserving config
        latest_positions = position_manager.get_positions_for_account(account_number)
        merged = {}
        old_positions = risk_manager.positions or {}
        for key, new_pos in latest_positions.items():
            old_pos = old_positions.get(key)
            if old_pos:
                if hasattr(old_pos, 'trail_stop_data'):
                    setattr(new_pos, 'trail_stop_data', getattr(old_pos, 'trail_stop_data'))
                if hasattr(old_pos, 'take_profit_data'):
                    setattr(new_pos, 'take_profit_data', getattr(old_pos, 'take_profit_data'))
            merged[key] = new_pos
        risk_manager.positions = merged

        return jsonify({
            'success': True,
            'message': f'Reloaded {count} position(s) for account ...{account_number[-4:]}',
            'account_number': account_number
        })
    except Exception as e:
        logger.error(f"Error reloading positions for account ...{account_number[-4:]}: {e}")
        return json_err(str(e))

@app.route('/api/account/<account_prefix>/close-simulation', methods=['POST'])
def close_account_simulation(account_prefix):
    """Close positions simulation for a specific account"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return json_err(f'Account not found: {account_prefix}')
    
    account_number = account_info['number']
    
    data = request.get_json()
    positions_data = data.get('positions', [])
    
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return json_err(f'Account ...{account_number[-4:]} not found')
    
    print(f"\n{'='*60}")
    print(f"🔥 LIVE TRADING MODE - Account ...{account_number[-4:]}: SUBMITTING REAL ORDERS FOR {len(positions_data)} POSITION(S)")
    print(f"{'='*60}")
    
    order_results = []
    positions_list = list(risk_manager.positions.items())
    
    # Process positions - now handling full position objects with custom prices
    for idx, position_data in enumerate(positions_data):
        # Extract limit price from the frontend data
        if isinstance(position_data, dict) and 'close_order' in position_data:
            limit_price = position_data['close_order']['price']
            estimated_proceeds = position_data['close_order']['estimated_proceeds']
            
            # Find the actual position in the risk manager
            pos_key = None
            position = None
            for key, pos in positions_list:
                if (pos.symbol == position_data['symbol'] and 
                    float(pos.strike_price) == float(position_data['strike_price']) and
                    pos.option_type.lower() == position_data['option_type'].lower() and
                    pos.expiration_date == position_data['expiration_date']):
                    pos_key = key
                    position = pos
                    break
        else:
            # Fallback to old behavior if we get an index
            if idx < len(positions_list):
                pos_key, position = positions_list[idx]
                limit_price = round(position.current_price * 0.95, 2)
                estimated_proceeds = limit_price * position.quantity * 100
        
        if position is None:
            continue
            
        print(f"\n📈 Position {idx + 1}: {position.symbol} {position.strike_price}{position.option_type.upper()} {position.expiration_date}")
        print(f"   Premium Paid: ${position.open_premium:.2f}")
        print(f"   Current Price: ${position.current_price:.2f}")
        print(f"   Limit Price: ${limit_price:.2f}")
        print(f"   Estimated Proceeds: ${estimated_proceeds:.2f}")
        
        order_info = {
            'symbol': position.symbol,
            'limit_price': limit_price,
            'estimated_proceeds': estimated_proceeds,
            'account': f"...{account_number[-4:]}",
            
        }
        
        if not live_trading_mode:
            return jsonify({
                'success': False,
                'error': 'Live trading required. Start with --live to submit orders.',
                'account_number': account_number
            }), 400

        print(f"   🔥 SUBMITTING REAL ORDER...")
        order_result = position_manager.submit_close_order(account_number, position, limit_price)
        if order_result['success']:
            order_info.update(order_result)
            print(f"   ✅ REAL ORDER SUBMITTED: {order_result['order_id']}")
        else:
            order_info['error'] = order_result['error']
            print(f"   ❌ ORDER FAILED: {order_result['error']}")

        order_results.append(order_info)
    
    return jsonify({
        'success': True,
        'message': f'LIVE ORDERS SUBMITTED for account ...{account_number[-4:]}: {len(positions_data)} position(s) processed',
        'orders': order_results,
        'live_trading_mode': True,
        'account_number': account_number
    })

@app.route('/api/account/<account_prefix>/trailing-stop', methods=['POST'])
def configure_account_trailing_stop(account_prefix):
    """Configure trailing stop for a position in a specific account"""
    global multi_account_manager, account_detector
    
    # Resolve account
    account_number, risk_manager, err = get_account_context(account_prefix)
    if err:
        return err
    data = request.get_json()
    
    symbol = data.get('symbol')
    enabled = data.get('enabled', False)
    percent = float(data.get('percent', 20.0))

    # Enable/disable via PositionManager
    if enabled:
        success = position_manager.enable_trailing_stop(account_number, symbol, percent)
        if not success:
            return json_err(
                f'Could not enable trailing stop for {symbol} - position not found or invalid price',
                account_number=account_number
            )
    else:
        position = position_manager.get_position(account_number, symbol)
        if position:
            trail = getattr(position, 'trail_stop_data', {})
            trail['enabled'] = False
            logger.info(f"Account ...{account_number[-4:]}: Trailing stop disabled for {symbol}")
            return jsonify({
                'success': True,
                'message': f'Trailing stop disabled for {symbol}',
                'config': trail,
                'account_number': account_number
            })
        return json_err(
            f'Position {symbol} not found in account ...{account_number[-4:]}',
            account_number=account_number
        )

    # Prepare and submit trailing stop order
    prep = position_manager.prepare_trailing_stop_order(account_number, symbol)
    if not prep.get('success'):
        return json_err(prep.get('error', 'Failed to prepare trailing stop order'), account_number=account_number)

    limit_price = prep['limit_price']
    stop_price = prep['stop_price']
    position = position_manager.get_position(account_number, symbol)

    if not live_trading_mode:
        return json_err('Live trading required. Start with --live to submit trailing stop orders.', account_number=account_number)

    print(f"   🔥 SUBMITTING REAL TRAILING STOP ORDER...")
    order_result = position_manager.submit_trailing_stop(account_number, position, limit_price, stop_price)
    order_info = {
        'symbol': position.symbol,
        'limit_price': limit_price,
        'stop_price': stop_price,
        'estimated_proceeds': limit_price * position.quantity * 100,
        'api_call': f'Trailing Stop: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}',
        'account': f"...{account_number[-4:]}",
        'simulated': False
    }
    if order_result['success']:
        order_info.update(order_result)
        print(f"   ✅ REAL TRAILING STOP ORDER: {order_result['order_id']}")
    else:
        order_info['error'] = order_result['error']
        print(f"   ❌ TRAILING STOP ORDER FAILED: {order_result['error']}")

    return jsonify({
        'success': True,
        'message': f'Trailing stop enabled for {symbol}',
        'config': getattr(position, 'trail_stop_data', {}),
        'order_created': order_info,
        'account_number': account_number
    })

@app.route('/api/account/<account_prefix>/take-profit', methods=['POST'])
def configure_account_take_profit(account_prefix):
    """Configure take profit for a position in a specific account"""
    global multi_account_manager, account_detector
    
    # Resolve account
    account_number, risk_manager, err = get_account_context(account_prefix)
    if err:
        return err
    data = request.get_json()
    
    symbol = data.get('symbol')
    enabled = data.get('enabled', False)
    percent = data.get('percent', 50.0)
    
    # Update take profit configuration
    risk_manager.take_profit_percent = percent
    
    # Use PositionManager to configure take profit (centralized logic)
    if enabled:
        success = position_manager.set_take_profit(account_number, symbol, percent)
        if not success:
            return json_err(
                f'Could not set take profit for {symbol} - position not found or invalid price',
                account_number=account_number
            )
    else:
        # Disable take profit
        position = position_manager.get_position(account_number, symbol)
        if position:
            take_profit_data = getattr(position, 'take_profit_data', {})
            take_profit_data['enabled'] = False
            logger.info(f"Account ...{account_number[-4:]}: Take profit disabled for {symbol}")
        else:
            return json_err(
                f'Position {symbol} not found in account ...{account_number[-4:]}',
                account_number=account_number
            )
    
    return jsonify({
        'success': True, 
        'message': f'Take profit {"enabled" if enabled else "disabled"} for {symbol} at {percent}%',
        'live_trading_mode': live_trading_mode,
        'account_number': account_number
    })
    
    return jsonify({'success': False, 'error': f'Position {symbol} not found in account ...{account_number[-4:]}'})

@app.route('/api/account/<account_prefix>/refresh-tracked-orders', methods=['GET'])
def refresh_tracked_orders(account_prefix):
    """Auto-refresh only our tracked orders (both live and simulation)"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({'success': False, 'error': f'Account not found: {account_prefix}'})
    
    account_number = account_info['number']
    orders = []
    # Only refresh our tracked live orders (efficient individual queries)
    try:
        tracked = position_manager.get_tracked_order_ids(account_number)
        for order_id, order_info in tracked.items():
            try:
                od_resp = order_service.get_order_info(order_id)
                if od_resp.get('success') and od_resp.get('details'):
                    od = od_resp['details']
                    orders.append({
                        'id': order_id,
                        'symbol': order_info.get('symbol', 'Unknown'),
                        'state': od.get('state', 'unknown'),
                        'price': float(od.get('price', order_info.get('price', 0))),
                        'quantity': int(float(od.get('quantity', 0))) if od.get('quantity') is not None else order_info.get('quantity', 0),
                        'submit_time': od.get('created_at', order_info.get('submit_time', '')),
                        'order_type': od.get('type', order_info.get('order_type', 'limit')),
                        'simulated': False
                    })
            except Exception as e:
                logger.error(f"Error refreshing tracked order {order_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error refreshing tracked orders: {str(e)}")
    
    return jsonify({
        'success': True,
        'message': f'Refreshed {len(orders)} tracked orders',
        'orders': orders,
        'account_number': account_number,
        'live_trading_mode': live_trading_mode
    })

@app.route('/api/account/<account_prefix>/check-orders', methods=['GET'])
def check_account_orders(account_prefix):
    """Check status of orders for a specific account"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({'success': False, 'error': f'Account not found: {account_prefix}'})
    
    account_number = account_info['number']
    
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return jsonify({
            'success': False,
            'error': f'Account ...{account_number[-4:]} not found',
            'orders': [],
            'live_trading_mode': live_trading_mode
        })
    
    try:
        # Use OrderService to fetch open orders (limited pages)
        os_resp = order_service.list_open_orders(max_pages=5)
        if not os_resp.get('success'):
            return jsonify({
                'success': False,
                'error': os_resp.get('error', 'Failed to fetch orders'),
                'message': f'Error checking orders for account ...{account_number[-4:]}'
            })

        orders = []
        for order in os_resp.get('orders', []):
            orders.append({
                'id': order.get('id', ''),
                'symbol': order.get('symbol', 'Unknown'),
                'state': order.get('state', 'unknown'),
                'price': float(order.get('price', 0) or 0),
                'quantity': int(float(order.get('quantity', 0) or 0)),
                'submit_time': order.get('created_at', ''),
        'order_type': order.get('type', 'limit')
            })

        return jsonify({
            'success': True,
            'message': f'Account ...{account_number[-4:]}: Found {len(orders)} orders',
            'orders': orders,
            'account_number': account_number,
            'live_trading_mode': live_trading_mode
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': f'Error checking orders for account ...{account_number[-4:]}'
        })

# Legacy API endpoints for backward compatibility (redirect to account-specific endpoints or provide fallbacks)
@app.route('/api/positions')
def get_positions_legacy():
    """Legacy endpoint - returns error directing to use account-specific endpoint"""
    return jsonify({
        'error': 'Please select an account first. This multi-account system requires using /api/account/{account_number}/positions',
        'message': 'Use the account selector at / to choose an account'
    }), 400

@app.route('/api/close-simulation', methods=['POST'])
def close_simulation_legacy():
    """Legacy endpoint - returns error directing to use account-specific endpoint"""
    return jsonify({
        'error': 'Please select an account first. This multi-account system requires using /api/account/{account_number}/close-simulation',
        'message': 'Use the account selector at / to choose an account'
    }), 400

@app.route('/api/trailing-stop', methods=['POST'])
def trailing_stop_legacy():
    """Legacy endpoint - returns error directing to use account-specific endpoint"""
    return jsonify({
        'error': 'Please select an account first. This multi-account system requires using /api/account/{account_number}/trailing-stop',
        'message': 'Use the account selector at / to choose an account'
    }), 400

@app.route('/api/check-orders', methods=['GET'])
def check_orders_legacy():
    """Legacy endpoint - returns error directing to use account-specific endpoint"""
    return jsonify({
        'error': 'Please select an account first. This multi-account system requires using /api/account/{account_number}/check-orders',
        'message': 'Use the account selector at / to choose an account'
    }), 400

@app.route('/api/order-status/<order_id>', methods=['GET'])
def get_order_status_legacy(order_id):
    """Legacy endpoint - returns error directing to use account-specific functionality"""
    return jsonify({
        'error': 'Order status checking requires account context in multi-account mode',
        'message': 'Use the account selector at / to choose an account, then use check orders'
    }), 400

@app.route('/api/cancel-order/<order_id>', methods=['POST'])
def cancel_order(order_id):
    """Cancel an existing order by ID (live-only)."""
    if not live_trading_mode:
        return json_err('Live trading required. Start with --live to cancel orders.')
    try:
        # account context is not necessary for cancel, but we attempt to keep stores consistent
        # We'll scan all accounts tracked orders to find the owning account
        owning_account = None
        for acc_prefix, acc_info in account_detector.detect_accounts().items():
            acct_num = acc_info['number']
            tracked = position_manager.get_tracked_order_ids(acct_num)
            if order_id in tracked:
                owning_account = acct_num
                break
        result = position_manager.cancel_order(owning_account or '', order_id)
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': result.get('message', f'Order {order_id} cancellation requested')
            })
        return json_err(result.get('error', 'Cancellation failed'))
    except Exception as e:
        return json_err(str(e))

def initialize_system():
    """Initialize the multi-account system with single login"""
    global multi_account_manager, account_detector
    
    logger.info("Initializing Multi-Account Risk Manager System...")
    print("Initializing Multi-Account Risk Manager System...")
    
    # Single login - robin_stocks maintains global session for all accounts
    logger.info("Authenticating with Robinhood...")
    print("Starting login process...")
    
    try:
        r.login()  # Global login shared by all components
        logger.info("Successfully authenticated with Robinhood")
        print("Authentication successful!")
    except Exception as e:
        logger.error(f"Failed to authenticate with Robinhood: {e}")
        print(f"Failed to authenticate with Robinhood: {e}")
        return False
    
    # Initialize components (will use existing global authentication)
    account_detector = AccountDetector()
    multi_account_manager = MultiAccountRiskManager()
    
    # Detect and show available accounts
    accounts = multi_account_manager.initialize_accounts()
    if not accounts:
        logger.error("No accounts detected")
        print("No accounts detected")
        return False
    
    logger.info(f"Detected {len(accounts)} account(s)")
    print(f"Detected {len(accounts)} account(s):")
    
    # Show account summary
    summary = multi_account_manager.list_accounts_summary()
    print(summary)
    
    # Auto-start monitoring for active accounts
    active_count = multi_account_manager.auto_start_active_accounts()
    # if active_count > 0:
    #     logger.info(f"Auto-started monitoring for {active_count} active account(s)")
    #     print(f"Auto-started monitoring for {active_count} active account(s)")
        
    #     # Wait for initial data loading to complete before starting web server
    #     multi_account_manager.wait_for_initial_loading()
    
    return True

if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Multi-Account Options Risk Manager Web Interface')
    parser.add_argument('--live', action='store_true', 
                       help='Enable live trading mode (DANGER: Will place real orders!)')
    parser.add_argument('--port', type=int, default=5001,
                       help='Port to run the web server on (default: 5001)')
    
    args = parser.parse_args()
    
    # Set live trading mode based on command line argument
    live_trading_mode = args.live
    
    if live_trading_mode:
        logger.warning("LIVE TRADING MODE ENABLED!")
        logger.warning("THIS WILL PLACE REAL ORDERS WITH REAL MONEY!")
        print("\n" + "="*60)
        print("🔥 WARNING: LIVE TRADING MODE ENABLED!")
        print("🔥 THIS WILL PLACE REAL ORDERS WITH REAL MONEY!")
        print("="*60)
        
        # Require explicit confirmation for live trading
        confirmation = input("\nType 'YES' to continue with live trading: ")
        if confirmation != "YES":
            logger.info("Live trading mode cancelled by user. Exiting.")
            print("Live trading mode cancelled. Exiting.")
            sys.exit(1)
        logger.warning("LIVE TRADING MODE CONFIRMED BY USER")
        print("✅ Live trading mode confirmed.\n")
    else:
        logger.info("Running in READ-ONLY MODE (order submission disabled)")
        print("📊 Running in READ-ONLY MODE (order submission disabled)")
    
    if initialize_system():
        logger.info(f"Multi-Account Risk Manager Web Interface Started - Port: {args.port}")
        logger.info(f"Trading Mode: {'LIVE TRADING' if live_trading_mode else 'READ-ONLY'}")
        print("Starting Multi-Account Risk Manager Web Interface...")
        print(f"Mode: {'🔥 LIVE TRADING' if live_trading_mode else '🛈 READ-ONLY'}")
        print(f"Access at: http://localhost:{args.port}")
        
        try:
            # Disable debug mode for live trading to avoid restart prompts
            debug_mode = not live_trading_mode
            app.run(debug=debug_mode, host='0.0.0.0', port=args.port)
        except KeyboardInterrupt:
            logger.info("Multi-Account Risk Manager shutdown requested by user")
            print("\nShutting down...")
            if multi_account_manager:
                multi_account_manager.stop_all_monitoring()
    else:
        logger.error("Failed to initialize multi-account system")
        print("Failed to initialize multi-account system")
