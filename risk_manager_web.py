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
from position_manager import position_manager

app = Flask(__name__)

# Initialize logger
rm_logger = RiskManagerLogger()
rm_logger.log_session_start()
logger = rm_logger.main_logger  # For backwards compatibility

# Global instances
multi_account_manager = None
account_detector = None
live_trading_mode = False
submitted_orders = {}  # Track submitted orders: {order_id: {position_key, timestamp, status, symbol, details}}
simulated_orders = {}  # Track simulated orders separately: {sim_id: {symbol, state, submit_time, etc}}

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

def update_simulated_orders():
    """Update simulated order states to simulate filling based on conditions"""
    global simulated_orders
    import random
    
    if not simulated_orders:
        return
    
    current_time = time.time()
    for order_id, order in simulated_orders.items():
        if order['state'] == 'confirmed':
            elapsed = current_time - order['submit_time']
            
            # For regular limit orders, use time-based logic for now
            if elapsed >= 3.0:  # Minimum 3 seconds
                if random.random() < 0.95:  # 95% fill rate
                    order['state'] = 'filled'
                    logger.info(f"SIMULATED LIMIT ORDER FILLED: {order_id} ({order['symbol']})")
                elif elapsed >= 10.0:  # After 10 seconds, either fill or timeout
                    order['state'] = 'partially_filled' if random.random() < 0.7 else 'filled'

def submit_real_order(position, limit_price, stop_price=None):
    """Submit a real order and return order details with ID"""
    global submitted_orders
    import robin_stocks.robinhood as r
    
    try:
        logger.info(f"SUBMITTING REAL ORDER for {position.symbol}")
        print(f"🔥 SUBMITTING REAL ORDER for {position.symbol}")
        
        time_sent = datetime.datetime.now()
        
        # Use stop-limit order if stop_price provided (for trailing stops)
        if stop_price is not None:
            logger.info(f"STOP-LIMIT ORDER: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}")
            print(f"   📋 STOP-LIMIT ORDER: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}")
            order_result = r.order_sell_option_stop_limit(
                positionEffect='close',
                creditOrDebit='credit',
                limitPrice=round(limit_price, 2),
                stopPrice=round(stop_price, 2),
                symbol=position.symbol,
                quantity=position.quantity,
                expirationDate=position.expiration_date,
                strike=position.strike_price,
                optionType=position.option_type,
                timeInForce='gtc'
            )
        else:
            # Regular limit order
            logger.info(f"LIMIT ORDER: ${limit_price:.2f}")
            print(f"   📋 LIMIT ORDER: ${limit_price:.2f}")
            order_result = r.order_sell_option_limit(
                positionEffect='close',
                creditOrDebit='credit',
                price=round(limit_price, 2),
                symbol=position.symbol,
                quantity=position.quantity,
                expirationDate=position.expiration_date,
                strike=position.strike_price,
                optionType=position.option_type,
                timeInForce='gtc'
            )
        
        if order_result and 'id' in order_result:
            order_id = order_result['id']
            time_confirmed = datetime.datetime.now()
            
            # Log the real order
            request_params = {
                'positionEffect': 'close',
                'creditOrDebit': 'credit',
                'limitPrice': round(limit_price, 2),
                'stopPrice': round(stop_price, 2) if stop_price is not None else None,
                'symbol': position.symbol,
                'quantity': position.quantity,
                'expirationDate': position.expiration_date,
                'strike': position.strike_price,
                'optionType': position.option_type,
                'timeInForce': 'gtc'
            }
            rm_logger.log_real_order(
                order_id=order_id,
                symbol=position.symbol,
                time_sent=time_sent,
                time_confirmed=time_confirmed,
                request_params=request_params,
                response=order_result,
                order_type='stop_limit' if stop_price is not None else 'limit'
            )
            
            # Track this order
            position_key = f"{position.symbol}_{position.expiration_date}_{position.strike_price}"
            submitted_orders[order_id] = {
                'position_key': position_key,
                'symbol': position.symbol,
                'timestamp': datetime.datetime.now().isoformat(),
                'initial_state': order_result.get('state', 'unknown'),
                'current_state': order_result.get('state', 'unknown'),
                'limit_price': limit_price,
                'details': order_result
            }
            
            logger.info(f"REAL ORDER SUBMITTED SUCCESSFULLY: {order_id}")
            print(f"✅ Order submitted successfully!")
            print(f"   Order ID: {order_id}")
            print(f"   State: {order_result.get('state', 'unknown')}")
            
            return {
                'success': True,
                'order_id': order_id,
                'order_result': order_result
            }
        else:
            print(f"❌ Order submission failed: {order_result}")
            return {
                'success': False,
                'error': 'No order ID returned',
                'order_result': order_result
            }
            
    except Exception as e:
        print(f"❌ Error submitting order: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def submit_simulated_order_handler(position, limit_price, order_info):
    """Handle simulated order creation"""
    global simulated_orders
    import uuid
    
    simulated_order_id = f"SIM_{uuid.uuid4().hex[:12]}"
    
    # Create simulated order data
    sim_order = {
        'id': simulated_order_id,
        'symbol': position.symbol,
        'quantity': position.quantity,
        'price': round(limit_price, 2),
        'state': 'confirmed',
        'submit_time': time.time(),
        'position_key': f"{position.symbol}_{position.expiration_date}_{position.strike_price}",
        'order_type': 'limit'
    }
    
    # Track in simulated orders dict
    simulated_orders[simulated_order_id] = sim_order
    
    # Log the simulated order
    time_sent = datetime.datetime.fromtimestamp(sim_order['submit_time'])
    request_params = {
        'positionEffect': 'close',
        'creditOrDebit': 'credit',
        'price': round(limit_price, 2),
        'symbol': position.symbol,
        'quantity': position.quantity,
        'expirationDate': position.expiration_date,
        'strike': position.strike_price,
        'optionType': position.option_type,
        'timeInForce': 'gtc'
    }
    rm_logger.log_simulated_order(
        order_id=simulated_order_id,
        symbol=position.symbol,
        time_sent=time_sent,
        request_params=request_params,
        order_type='limit'
    )
    
    # Update order_info for response
    order_info['order_id'] = simulated_order_id
    order_info['order_state'] = 'confirmed'
    order_info['simulated'] = True
    
    print(f"   🎯 SIMULATED ORDER CREATED: {simulated_order_id}")
    return order_info

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
        # Calculate current P&L
        risk_manager.calculate_pnl(position)
        total_pnl += position.pnl
        
        # Add trailing stop data
        trail_stop_data = getattr(position, 'trail_stop_data', {
            'enabled': False,
            'percent': 20.0,
            'highest_price': position.current_price,
            'trigger_price': 0.0,
            'triggered': False,
            'order_submitted': False,
            'order_id': None,
            'last_update_time': 0.0,
            'last_order_id': None
        })
        
        # Add take profit data
        take_profit_data = getattr(position, 'take_profit_data', {
            'enabled': False,
            'percent': 50.0,
            'target_pnl': 50.0,
            'triggered': False
        })
        
        # Check if trailing stop would be triggered
        if trail_stop_data['enabled'] and position.current_price > 0 and not trail_stop_data.get('order_submitted', False):
            if position.current_price > trail_stop_data['highest_price']:
                trail_stop_data['highest_price'] = position.current_price
            trail_stop_data['trigger_price'] = trail_stop_data['highest_price'] * (1 - trail_stop_data['percent'] / 100)
            trail_stop_data['triggered'] = position.current_price <= trail_stop_data['trigger_price']
        
        # Check if take profit would be triggered
        if take_profit_data['enabled']:
            take_profit_data['triggered'] = position.pnl_percent >= take_profit_data['percent']
        
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

@app.route('/api/account/<account_prefix>/close-simulation', methods=['POST'])
def close_account_simulation(account_prefix):
    """Close positions simulation for a specific account"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({'success': False, 'error': f'Account not found: {account_prefix}'})
    
    account_number = account_info['number']
    
    data = request.get_json()
    positions_data = data.get('positions', [])
    
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return jsonify({'success': False, 'error': f'Account ...{account_number[-4:]} not found'})
    
    print(f"\n{'='*60}")
    if live_trading_mode:
        print(f"🔥 LIVE TRADING MODE - Account ...{account_number[-4:]}: SUBMITTING REAL ORDERS FOR {len(positions_data)} POSITION(S)")
    else:
        print(f"🎯 SIMULATION MODE - Account ...{account_number[-4:]}: CLOSE ORDERS FOR {len(positions_data)} POSITION(S)")
    print(f"{'='*60}")
    
    simulated_order_results = []
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
            'simulated': not live_trading_mode
        }
        
        # Actually submit the order based on mode
        if live_trading_mode:
            print(f"   🔥 SUBMITTING REAL ORDER...")
            order_result = submit_real_order(position, limit_price)
            if order_result['success']:
                order_info.update(order_result)
                print(f"   ✅ REAL ORDER SUBMITTED: {order_result['order_id']}")
            else:
                order_info['error'] = order_result['error']
                print(f"   ❌ ORDER FAILED: {order_result['error']}")
        else:
            print(f"   🎯 CREATING SIMULATED ORDER...")
            order_result = submit_simulated_order_handler(position, limit_price, order_info.copy())
            order_info.update(order_result)
            print(f"   ✅ SIMULATED ORDER CREATED: {order_result.get('order_id', 'Unknown')}")
        
        simulated_order_results.append(order_info)
    
    return jsonify({
        'success': True,
        'message': f'{"LIVE ORDERS SUBMITTED" if live_trading_mode else "SIMULATION"} for account ...{account_number[-4:]}: {len(positions_data)} position(s) processed',
        'orders_simulated': len(simulated_order_results),
        'orders': simulated_order_results,
        'live_trading_mode': live_trading_mode,
        'account_number': account_number
    })

@app.route('/api/account/<account_prefix>/trailing-stop', methods=['POST'])
def configure_account_trailing_stop(account_prefix):
    """Configure trailing stop for a position in a specific account"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({'success': False, 'error': f'Account not found: {account_prefix}'})
    
    account_number = account_info['number']
    
    data = request.get_json()
    
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return jsonify({'success': False, 'error': f'Account ...{account_number[-4:]} not found'})
    
    symbol = data.get('symbol')
    enabled = data.get('enabled', False)
    percent = float(data.get('percent', 20.0))
    
    # Use PositionManager to configure trailing stop (centralized logic)
    if enabled:
        success = position_manager.enable_trailing_stop(account_number, symbol, percent)
        if not success:
            return jsonify({
                'success': False,
                'error': f'Could not enable trailing stop for {symbol} - position not found or invalid price',
                'account_number': account_number
            })
    else:
        # Disable trailing stop by getting position and clearing the data
        position = position_manager.get_position(account_number, symbol)
        if position:
            trail_stop_data = getattr(position, 'trail_stop_data', {})
            trail_stop_data['enabled'] = False
            logger.info(f"Account ...{account_number[-4:]}: Trailing stop disabled for {symbol}")
        else:
            return jsonify({
                'success': False,
                'error': f'Position {symbol} not found in account ...{account_number[-4:]}',
                'account_number': account_number
            })
    
    # Get updated position for response
    position = position_manager.get_position(account_number, symbol)
    if position:

            # Create simulated/real order when trailing stop is enabled
            order_info = None
            if enabled:
                # Pull trigger price from position's trail stop data (set by PositionManager)
                trail_stop_data = getattr(position, 'trail_stop_data', {})
                trigger_price = float(trail_stop_data.get('trigger_price', 0.0))
                if trigger_price <= 0 and position.current_price > 0:
                    trigger_price = position.current_price * (1 - float(percent) / 100.0)

                limit_price = trigger_price  # Use trigger price as limit
                stop_price = trigger_price / 0.97  # Stop price slightly above limit
                
                order_info = {
                    'symbol': position.symbol,
                    'limit_price': limit_price,
                    'stop_price': stop_price,
                    'estimated_proceeds': limit_price * position.quantity * 100,
                    'api_call': f'Trailing Stop: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}',
                    'account': f"...{account_number[-4:]}",
                    'simulated': not live_trading_mode
                }
                
                if live_trading_mode:
                    print(f"   🔥 SUBMITTING REAL TRAILING STOP ORDER...")
                    order_result = submit_real_order(position, limit_price, stop_price)
                    if order_result['success']:
                        order_info.update(order_result)
                        position.trail_stop_data['order_id'] = order_result['order_id']
                        position.trail_stop_data['order_submitted'] = True
                        print(f"   ✅ REAL TRAILING STOP ORDER: {order_result['order_id']}")
                    else:
                        order_info['error'] = order_result['error']
                        print(f"   ❌ TRAILING STOP ORDER FAILED: {order_result['error']}")
                else:
                    print(f"   🎯 CREATING SIMULATED TRAILING STOP ORDER...")
                    order_result = submit_simulated_order_handler(position, limit_price, order_info.copy())
                    order_info.update(order_result)
                    if 'order_id' in order_result:
                        position.trail_stop_data['order_id'] = order_result['order_id']
                        # Mark the simulated order as stop-limit type
                        if order_result['order_id'] in simulated_orders:
                            simulated_orders[order_result['order_id']]['order_type'] = 'stop_limit'
                            simulated_orders[order_result['order_id']]['stop_price'] = stop_price
                        print(f"   ✅ SIMULATED TRAILING STOP ORDER: {order_result['order_id']}")
            
            response = {
                'success': True,
                'message': f'Trailing stop {"enabled" if enabled else "disabled"} for {symbol}',
                'config': position.trail_stop_data,
                'account_number': account_number
            }
            
            if order_info:
                response['order_created'] = order_info
                
            return jsonify(response)
    
    return jsonify({'success': False, 'error': f'Position {symbol} not found in account ...{account_number[-4:]}'})

@app.route('/api/account/<account_prefix>/take-profit', methods=['POST'])
def configure_account_take_profit(account_prefix):
    """Configure take profit for a position in a specific account"""
    global multi_account_manager, account_detector
    
    # Get full account number from prefix
    account_info = account_detector.get_account_info(account_prefix)
    if not account_info:
        return jsonify({'success': False, 'error': f'Account not found: {account_prefix}'})
    
    account_number = account_info['number']
    
    data = request.get_json()
    
    risk_manager = multi_account_manager.get_account_risk_manager(account_number)
    if not risk_manager:
        return jsonify({'success': False, 'error': f'Account ...{account_number[-4:]} not found'})
    
    symbol = data.get('symbol')
    enabled = data.get('enabled', False)
    percent = data.get('percent', 50.0)
    
    # Update take profit configuration
    risk_manager.take_profit_percent = percent
    
    # Use PositionManager to configure take profit (centralized logic)
    if enabled:
        success = position_manager.set_take_profit(account_number, symbol, percent)
        if not success:
            return jsonify({
                'success': False,
                'error': f'Could not set take profit for {symbol} - position not found or invalid price',
                'account_number': account_number
            })
    else:
        # Disable take profit
        position = position_manager.get_position(account_number, symbol)
        if position:
            take_profit_data = getattr(position, 'take_profit_data', {})
            take_profit_data['enabled'] = False
            logger.info(f"Account ...{account_number[-4:]}: Take profit disabled for {symbol}")
        else:
            return jsonify({
                'success': False,
                'error': f'Position {symbol} not found in account ...{account_number[-4:]}',
                'account_number': account_number
            })
    
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
    
    if live_trading_mode:
        # Only refresh our tracked live orders (efficient individual queries)
        try:
            for order_id, order_info in submitted_orders.items():
                try:
                    order_details = r.get_option_order_info(order_id)
                    if order_details:
                        orders.append({
                            'id': order_id,
                            'symbol': order_info.get('symbol', 'Unknown'),
                            'state': order_details.get('state', 'unknown'),
                            'price': float(order_details.get('price', order_info.get('limit_price', 0))),
                            'quantity': int(float(order_details.get('quantity', 0))),
                            'submit_time': order_details.get('created_at', order_info.get('timestamp', '')),
                            'order_type': order_details.get('type', 'limit'),
                            'simulated': False
                        })
                except Exception as e:
                    logger.error(f"Error refreshing tracked order {order_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Error refreshing tracked orders: {str(e)}")
    else:
        # Return simulated orders (same as check-orders for simulation)
        for order_id, order in simulated_orders.items():
            orders.append({
                'id': order_id,
                'symbol': order['symbol'],
                'state': order['state'],
                'price': order['price'],
                'quantity': order['quantity'],
                'submit_time': order['submit_time'],
                'order_type': order.get('order_type', 'limit'),
                'simulated': True
            })
    
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
        # Update simulated order states
        update_simulated_orders()
        
        # Get all orders (simulated and real)
        orders = []
        
        if live_trading_mode:
            # Get first 5 pages of all orders to find any open orders
            try:
                # Use a custom request to limit to 5 pages max
                import robin_stocks.robinhood.helper as helper
                from robin_stocks.robinhood.urls import option_orders_url
                
                url = option_orders_url()
                all_orders = []
                
                # Fetch first 5 pages only
                for page in range(5):
                    try:
                        data = helper.request_get(url, 'regular')
                        if data and 'results' in data:
                            all_orders.extend(data['results'])
                            if 'next' in data and data['next']:
                                url = data['next']
                            else:
                                break
                        else:
                            break
                    except Exception as e:
                        logger.error(f"Error fetching page {page+1}: {str(e)}")
                        break
                
                # Filter for open orders only
                for order in all_orders:
                    if order.get('state') in ['queued', 'confirmed', 'partially_filled']:
                        orders.append({
                            'id': order.get('id', ''),
                            'symbol': order.get('symbol', 'Unknown'),
                            'state': order.get('state', 'unknown'),
                            'price': float(order.get('price', 0)),
                            'quantity': int(float(order.get('quantity', 0))),
                            'submit_time': order.get('created_at', ''),
                            'order_type': order.get('type', 'limit'),
                            'simulated': False
                        })
                        
            except Exception as e:
                logger.error(f"Error processing orders from first 5 pages: {str(e)}")
        else:
            # Return simulated orders
            for order_id, order in simulated_orders.items():
                orders.append({
                    'id': order_id,
                    'symbol': order['symbol'],
                    'state': order['state'],
                    'price': order['price'],
                    'quantity': order['quantity'],
                    'submit_time': order['submit_time'],
                    'order_type': order.get('order_type', 'limit'),
                    'simulated': True
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
def cancel_order_legacy(order_id):
    """Legacy endpoint - returns error directing to use account-specific functionality"""
    return jsonify({
        'error': 'Order cancellation requires account context in multi-account mode', 
        'message': 'Use the account selector at / to choose an account'
    }), 400

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
        logger.info("Running in SIMULATION MODE (safe - no real orders)")
        print("📊 Running in SIMULATION MODE (safe - no real orders)")
    
    if initialize_system():
        logger.info(f"Multi-Account Risk Manager Web Interface Started - Port: {args.port}")
        logger.info(f"Trading Mode: {'LIVE TRADING' if live_trading_mode else 'SIMULATION'}")
        print("Starting Multi-Account Risk Manager Web Interface...")
        print(f"Mode: {'🔥 LIVE TRADING' if live_trading_mode else '🎯 SIMULATION'}")
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
