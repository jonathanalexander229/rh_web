#!/usr/bin/env python3
"""
Web-based Risk Manager for Long Options
Simple web interface to monitor positions and simulate close orders
"""

from flask import Flask, render_template, jsonify, request
import json
import datetime
import threading
import time
import argparse
import sys
import logging
import os
from base_risk_manager import BaseRiskManager
from risk_manager_logger import RiskManagerLogger

app = Flask(__name__)

# Initialize logger
rm_logger = RiskManagerLogger()
rm_logger.log_session_start()
logger = rm_logger.main_logger  # For backwards compatibility

# Global risk manager instance
risk_manager = None
monitoring_thread = None
is_monitoring = False
live_trading_mode = False  # Set to True to enable real order submission
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

def has_enabled_trailing_stops() -> bool:
    """Check if any positions have trailing stops enabled"""
    global risk_manager
    if not risk_manager or len(risk_manager.positions) == 0:
        return False
    
    for pos_key, position in risk_manager.positions.items():
        trail_stop_data = getattr(position, 'trail_stop_data', {})
        if trail_stop_data.get('enabled', False):
            return True
    return False

def update_trailing_stops():
    """Update trailing stop values with throttling and order cancellation logic"""
    global risk_manager, live_trading_mode
    if not risk_manager:
        return
        
    current_time = time.time()
    
    for pos_key, position in risk_manager.positions.items():
        trail_stop_data = getattr(position, 'trail_stop_data', {})
        
        if trail_stop_data.get('enabled', False) and position.current_price > 0:
            # Update market data for this position
            risk_manager.calculate_pnl(position)
            
            # Check if we need to throttle updates (max once every 10 seconds)
            last_update = trail_stop_data.get('last_update_time', 0.0)
            should_update = current_time - last_update >= 10.0
            
            # Update highest price (ratchet up only)
            price_increased = position.current_price > trail_stop_data['highest_price']
            if price_increased:
                trail_stop_data['highest_price'] = position.current_price
                logger.info(f"Trailing stop for {position.symbol}: New high ${position.current_price:.3f}")
            
            # Recalculate trigger price
            new_trigger_price = trail_stop_data['highest_price'] * (1 - trail_stop_data['percent'] / 100)
            old_trigger_price = trail_stop_data.get('trigger_price', 0.0)
            
            # Only update if trigger price changed significantly (>$0.01) AND we haven't updated recently
            trigger_changed = abs(new_trigger_price - old_trigger_price) > 0.01
            
            if (price_increased or trigger_changed) and should_update and not trail_stop_data.get('order_submitted', False):
                trail_stop_data['trigger_price'] = new_trigger_price
                trail_stop_data['last_update_time'] = current_time
                
                # Cancel existing trailing stop order if one exists
                last_order_id = trail_stop_data.get('last_order_id')
                if last_order_id:
                    logger.info(f"Cancelling previous trailing stop order for {position.symbol}: {last_order_id}")
                    cancel_result = cancel_order(last_order_id)
                    if cancel_result['success']:
                        logger.info(f"Previous order cancelled: {last_order_id}")
                    else:
                        logger.warning(f"Could not cancel previous order: {cancel_result['error']}")
                
                # Submit new trailing stop order with updated trigger price
                logger.info(f"Updating trailing stop order for {position.symbol}: New trigger ${new_trigger_price:.3f}")
                
                if live_trading_mode:
                    # Use stop-limit order: limit = user's exact trailing stop, stop = 3% above limit
                    limit_price = new_trigger_price  # User's exact trailing stop percentage
                    stop_price = new_trigger_price / 0.97  # 3% above limit to trigger the order
                    order_result = submit_real_order(position, limit_price, stop_price)
                    if order_result['success']:
                        trail_stop_data['last_order_id'] = order_result['order_id']
                        logger.info(f"UPDATED TRAILING STOP ORDER: {order_result['order_id']}")
                    else:
                        logger.error(f"TRAILING STOP UPDATE FAILED: {order_result['error']}")
                else:
                    # For simulation, create a new simulated order
                    limit_price = new_trigger_price  # User's exact trailing stop percentage
                    stop_price = new_trigger_price / 0.97  # 3% above limit to trigger
                    order_info = {
                        'symbol': position.symbol,
                        'limit_price': limit_price,
                        'estimated_proceeds': limit_price * position.quantity * 100,
                        'api_call': f'Updated trailing stop: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}'
                    }
                    sim_result = submit_simulated_order_handler(position, limit_price, order_info)
                    if 'order_id' in sim_result:
                        trail_stop_data['last_order_id'] = sim_result['order_id']
                        logger.info(f"UPDATED SIMULATED TRAILING STOP: {sim_result['order_id']}")
                        
                        # Mark the simulated order as a stop-limit type
                        if sim_result['order_id'] in simulated_orders:
                            simulated_orders[sim_result['order_id']]['order_type'] = 'stop_limit'
            
            # Check if current trigger is hit (for final execution)
            current_triggered = position.current_price <= trail_stop_data.get('trigger_price', 0.0)
            was_triggered = trail_stop_data.get('triggered', False)
            
            if current_triggered and not was_triggered and not trail_stop_data.get('order_submitted', False):
                print(f"🔥 TRAILING STOP TRIGGERED for {position.symbol}! Current: ${position.current_price:.3f} <= Trigger: ${trail_stop_data['trigger_price']:.3f}")
                # Mark as triggered but don't submit new order if we already have one pending
                trail_stop_data['triggered'] = True
                
                # If we have a pending order, it should execute automatically
                if trail_stop_data.get('last_order_id'):
                    print(f"💫 Pending trailing stop order should execute: {trail_stop_data['last_order_id']}")
            
            # Update triggered status
            trail_stop_data['triggered'] = current_triggered

def monitoring_loop():
    """High-frequency monitoring loop for trailing stops"""
    global is_monitoring
    print("Starting high-frequency trailing stop monitoring...")
    
    while is_monitoring:
        try:
            market_open = is_market_hours()
            has_trails = has_enabled_trailing_stops()
            
            if market_open and has_trails:
                update_trailing_stops()
                time.sleep(1)  # Update every second during market hours
            else:
                # Debug info every 30 seconds when not actively monitoring
                if int(time.time()) % 30 == 0:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Market: {'OPEN' if market_open else 'CLOSED'}, Trailing stops enabled: {has_trails}")
                time.sleep(10)  # Check less frequently outside market hours
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(5)
    
    print("Trailing stop monitoring stopped.")

def start_monitoring():
    """Start the background monitoring thread"""
    global monitoring_thread, is_monitoring
    if not is_monitoring:
        is_monitoring = True
        monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        monitoring_thread.start()
        print("High-frequency trailing stop monitoring started")

def stop_monitoring():
    """Stop the background monitoring thread"""
    global is_monitoring
    is_monitoring = False
    print("Stopping trailing stop monitoring...")

def update_simulated_orders():
    """Update simulated order states to simulate filling based on conditions
    
    - Stop-limit orders (trailing stops): Only fill when actual stop price is hit
    - Regular limit orders: Fill after 3-7 seconds (old behavior)
    """
    global simulated_orders, risk_manager
    import random
    
    if not risk_manager:
        return
    
    current_time = time.time()
    for order_id, order in simulated_orders.items():
        if order['state'] == 'confirmed':
            elapsed = current_time - order['submit_time']
            
            # Check if this is a stop-limit order (trailing stop)
            if order.get('order_type') == 'stop_limit':
                # For stop-limit orders, only fill when stop conditions are met
                # Find the position and check current price vs stop conditions
                symbol = order['symbol']
                position = None
                for pos_key, pos in risk_manager.positions.items():
                    if pos.symbol == symbol:
                        position = pos
                        break
                
                if position:
                    # Update current market price
                    risk_manager.calculate_pnl(position)
                    
                    # Check trailing stop conditions
                    trail_stop_data = getattr(position, 'trail_stop_data', {})
                    if trail_stop_data.get('enabled', False):
                        # Only fill if current price hits the stop trigger
                        trigger_price = trail_stop_data.get('trigger_price', 0)
                        if trigger_price > 0 and position.current_price <= trigger_price:
                            order['state'] = 'filled'
                            logger.info(f"SIMULATED STOP-LIMIT ORDER FILLED: {order_id} ({symbol}) - Price ${position.current_price:.3f} <= Stop ${trigger_price:.3f}")
                            
                            # Disable trailing stop since order filled
                            trail_stop_data['enabled'] = False
                            trail_stop_data['order_submitted'] = True
                            trail_stop_data['order_id'] = order_id
                    
                    # Check if trailing stop was disabled - cancel the order
                    elif not trail_stop_data.get('enabled', False):
                        order['state'] = 'cancelled'
                        logger.info(f"SIMULATED STOP-LIMIT ORDER CANCELLED: {order_id} ({symbol}) - Trailing stop disabled")
                    
                    # Timeout after 30 seconds if stop never hit
                    elif elapsed >= 30.0:
                        if random.random() < 0.1:  # 10% chance of timeout/cancel
                            order['state'] = 'cancelled'
                            logger.info(f"SIMULATED STOP-LIMIT ORDER TIMEOUT: {order_id} ({symbol})")
            else:
                # For regular limit orders, use the old time-based logic
                if elapsed >= 3.0:  # Minimum 3 seconds
                    if random.random() < 0.95:  # 95% fill rate
                        order['state'] = 'filled'
                        logger.info(f"SIMULATED LIMIT ORDER FILLED: {order_id} ({order['symbol']})")
                    elif elapsed >= 10.0:  # After 10 seconds, either fill or timeout
                        order['state'] = 'partially_filled' if random.random() < 0.7 else 'filled'

def check_simulated_orders():
    """Check and update simulated order status"""
    global simulated_orders
    
    if not simulated_orders:
        print("📋 No simulated orders to track")
        return []
    
    # Update simulated order states
    update_simulated_orders()
    
    print(f"\n📋 CHECKING {len(simulated_orders)} SIMULATED ORDERS")
    print("=" * 60)
    
    updated_orders = []
    for order_id, order in simulated_orders.items():
        print(f"📊 Order ID: {order_id} (SIMULATED)")
        print(f"   Symbol: {order['symbol']}")
        print(f"   Quantity: {order['quantity']} | Price: ${order['price']}")
        print(f"   State: {order['state']}")
        
        if order['state'] in ['filled', 'partially_filled']:
            print(f"   🎯 Simulated Order {order_id} is {order['state'].upper()}!")
        
        updated_orders.append(order)
        print("-" * 40)
    
    print("=" * 60)
    return updated_orders

def check_real_orders():
    """Check status of real submitted orders"""
    global submitted_orders
    import robin_stocks.robinhood as r
    
    if not submitted_orders:
        print("📋 No real orders to track")
        return []
        
    print(f"\n📋 CHECKING {len(submitted_orders)} REAL ORDERS")
    print("=" * 60)
    
    updated_orders = []
    for order_id, order_info in submitted_orders.items():
        try:
            print(f"Checking order {order_id[:8]}...")
            order_details = r.get_option_order_info(order_id)
            
            if order_details:
                state = order_details.get('state', 'Unknown')
                symbol = order_info.get('symbol', 'Unknown')
                price = order_details.get('price', 'Unknown')
                quantity = order_details.get('quantity', 'Unknown')
                
                print(f"📊 Order ID: {order_id[:8]}...")
                print(f"   Symbol: {symbol}")
                print(f"   Quantity: {quantity} | Price: ${price}")
                print(f"   State: {state}")
                print(f"   Created: {order_details.get('created_at', 'Unknown')}")
                
                # Update tracking
                submitted_orders[order_id]['current_state'] = state
                submitted_orders[order_id]['last_checked'] = datetime.datetime.now().isoformat()
                
                if state in ['filled', 'cancelled', 'rejected']:
                    print(f"   🎯 Order {order_id[:8]}... is {state.upper()}!")
                
                updated_orders.append(order_details)
            else:
                print(f"   ❌ Could not get details for order {order_id[:8]}...")
                
            print("-" * 40)
        except Exception as e:
            print(f"   ❌ Error checking order {order_id[:8]}...: {e}")
    
    print("=" * 60)
    return updated_orders

def check_order_status():
    """Check status of orders based on current mode"""
    if live_trading_mode:
        return check_real_orders()
    else:
        return check_simulated_orders()

def cancel_real_order(order_id):
    """Cancel a real order using Robinhood API"""
    import robin_stocks.robinhood as r
    
    try:
        # Use robin-stocks to cancel the order
        cancel_result = r.cancel_option_order(order_id)
        
        if cancel_result:
            logger.info(f"REAL ORDER CANCELLED: {order_id[:8]}...")
            
            # Update our tracking
            if order_id in submitted_orders:
                submitted_orders[order_id]['current_state'] = 'cancelled'
                submitted_orders[order_id]['cancelled_at'] = datetime.datetime.now().isoformat()
            
            return {
                'success': True,
                'message': f'Order {order_id[:8]}... cancelled successfully',
                'order_id': order_id
            }
        else:
            return {
                'success': False,
                'error': 'Cancellation failed - order may already be filled or cancelled'
            }
            
    except Exception as e:
        print(f"❌ Error cancelling real order {order_id[:8]}...: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def cancel_simulated_order(order_id):
    """Cancel a simulated order"""
    global simulated_orders
    
    try:
        if order_id not in simulated_orders:
            return {
                'success': False,
                'error': 'Order not found'
            }
        
        order = simulated_orders[order_id]
        
        # Can only cancel if still in confirmed state
        if order['state'] != 'confirmed':
            return {
                'success': False,
                'error': f'Cannot cancel order in {order["state"]} state'
            }
        
        # Update order state to cancelled
        order['state'] = 'cancelled'
        order['cancelled_at'] = time.time()
        
        logger.info(f"SIMULATED ORDER CANCELLED: {order_id} ({order['symbol']})")
        
        return {
            'success': True,
            'message': f'Simulated order for {order["symbol"]} cancelled successfully',
            'order_id': order_id
        }
        
    except Exception as e:
        print(f"❌ Error cancelling simulated order {order_id}: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def cancel_order(order_id):
    """Cancel an order based on current mode"""
    if live_trading_mode:
        return cancel_real_order(order_id)
    else:
        return cancel_simulated_order(order_id)

def submit_real_order_handler(position, limit_price, order_info):
    """Handle real order submission"""
    print(f"\n   🔥 SUBMITTING REAL ORDER...")
    order_result = submit_real_order(position, limit_price)
    
    if order_result['success']:
        order_info['order_id'] = order_result['order_id']
        order_info['order_state'] = order_result['order_result'].get('state', 'unknown')
        print(f"   ✅ REAL ORDER SUBMITTED: {order_result['order_id']}")
    else:
        order_info['error'] = order_result['error']
        print(f"   ❌ ORDER FAILED: {order_result['error']}")
    
    return order_info

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
        'order_type': 'limit'  # Default to limit, can be overridden for stop-limit
    }
    
    # Track in separate simulated orders dict
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

def submit_real_order(position, limit_price, stop_price=None):
    """Submit a real order and return order details with ID"""
    global submitted_orders
    import robin_stocks.robinhood as r
    
    try:
        logger.info(f"SUBMITTING REAL ORDER for {position.symbol}")
        print(f"🔥 SUBMITTING REAL ORDER for {position.symbol}")
        
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
            
            # Log the request after sending
            time_confirmed = datetime.datetime.now()
            logger.info(f"ROBINHOOD REQUEST - order_sell_option_stop_limit:")
            logger.info(f"  Time Sent: {time_sent}")
            logger.info(f"  Time Confirmed: {time_confirmed}")
            logger.info(f"  Request: {json.dumps({'positionEffect': 'close', 'creditOrDebit': 'credit', 'limitPrice': round(limit_price, 2), 'stopPrice': round(stop_price, 2), 'symbol': position.symbol, 'quantity': position.quantity, 'expirationDate': position.expiration_date, 'strike': position.strike_price, 'optionType': position.option_type, 'timeInForce': 'gtc'})}")
            logger.info(f"  Response: {json.dumps(order_result) if order_result else 'None'}")
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
            logger.info(f"Order State: {order_result.get('state', 'unknown')}, Price: ${limit_price}")
            print(f"✅ Order submitted successfully!")
            print(f"   Order ID: {order_id}")
            print(f"   State: {order_result.get('state', 'unknown')}")
            print(f"   Price: ${limit_price}")
            
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

@app.route('/')
def index():
    """Main risk manager page"""
    return render_template('risk_manager.html')

@app.route('/api/positions')
def get_positions():
    """API endpoint to get current positions and their status"""
    global risk_manager
    
    if not risk_manager or len(risk_manager.positions) == 0:
        return jsonify({
            'positions': [],
            'total_pnl': 0,
            'market_open': False,
            'last_update': datetime.datetime.now().strftime('%H:%M:%S')
        })
    
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
        
        # Check if trailing stop would be triggered (only if not already submitted)
        if trail_stop_data['enabled'] and position.current_price > 0 and not trail_stop_data.get('order_submitted', False):
            if position.current_price > trail_stop_data['highest_price']:
                trail_stop_data['highest_price'] = position.current_price
            trail_stop_data['trigger_price'] = trail_stop_data['highest_price'] * (1 - trail_stop_data['percent'] / 100)
            trail_stop_data['triggered'] = position.current_price <= trail_stop_data['trigger_price']
        
        # Generate close order parameters
        # Use trailing stop trigger price if enabled, otherwise use current market price with 5% discount
        if trail_stop_data['enabled']:
            limit_price = trail_stop_data['trigger_price']  # Use trailing stop trigger price
        else:
            limit_price = round(position.current_price * 0.95, 2)  # Default: 5% below current
        
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
            'trail_stop': trail_stop_data
        }
        
        positions_data.append(position_data)
    
    return jsonify({
        'positions': positions_data,
        'total_pnl': total_pnl,
        'market_open': is_market_hours(),
        'live_trading_mode': live_trading_mode,
        'last_update': datetime.datetime.now().strftime('%H:%M:%S')
    })

@app.route('/api/close-simulation', methods=['POST'])
def close_simulation():
    """Simulate closing positions"""
    global risk_manager
    data = request.get_json()
    position_indices = data.get('positions', [])
    
    if not risk_manager:
        return jsonify({'success': False, 'error': 'Risk manager not initialized'})
    
    print(f"\n{'='*60}")
    if live_trading_mode:
        print(f"🔥 LIVE TRADING MODE: SUBMITTING REAL ORDERS FOR {len(position_indices)} POSITION(S)")
    else:
        print(f"🎯 SIMULATION MODE: CLOSE ORDERS FOR {len(position_indices)} POSITION(S)")
    print(f"{'='*60}")
    
    simulated_orders = []
    positions_list = list(risk_manager.positions.items())
    
    for idx in position_indices:
        if idx < len(positions_list):
            pos_key, position = positions_list[idx]
            
            # Calculate close order parameters (same logic as in /api/positions)
            trail_stop_data = getattr(position, 'trail_stop_data', {
                'enabled': False,
                'percent': 20.0,
                'highest_price': position.current_price,
                'trigger_price': 0.0,
                'triggered': False
            })
            
            # Check if trailing stop order was already submitted automatically
            if trail_stop_data.get('order_submitted', False):
                print(f"\n⚠️  Position {idx + 1}: {position.symbol} - TRAILING STOP ORDER ALREADY SUBMITTED")
                print(f"   Order ID: {trail_stop_data.get('order_id', 'Unknown')}")
                print("   Skipping manual order to prevent duplicates...")
                continue
            
            # Update trailing stop data
            if trail_stop_data['enabled'] and position.current_price > 0:
                if position.current_price > trail_stop_data['highest_price']:
                    trail_stop_data['highest_price'] = position.current_price
                trail_stop_data['trigger_price'] = trail_stop_data['highest_price'] * (1 - trail_stop_data['percent'] / 100)
                trail_stop_data['triggered'] = position.current_price <= trail_stop_data['trigger_price']
            
            # Determine limit price
            if trail_stop_data['enabled']:
                limit_price = trail_stop_data['trigger_price']
                price_reason = f"Trailing Stop ({trail_stop_data['percent']}%)"
            else:
                limit_price = round(position.current_price * 0.95, 2)
                price_reason = "Market Price - 5%"
            
            # Generate robin-stocks API call
            api_call = f"""robin_stocks.order_sell_option_limit(
    positionEffect='close',
    creditOrDebit='credit',
    price={round(limit_price, 2)},
    symbol='{position.symbol}',
    quantity={position.quantity},
    expirationDate='{position.expiration_date}',
    strike={position.strike_price},
    optionType='{position.option_type}',
    timeInForce='gtc'
)"""
            
            estimated_proceeds = limit_price * position.quantity * 100
            
            print(f"\n📈 Position {idx + 1}: {position.symbol} {position.strike_price}{position.option_type.upper()} {position.expiration_date}")
            print(f"   Premium Paid: ${position.open_premium:.2f}")
            print(f"   Current Price: ${position.current_price:.2f}")
            print(f"   Limit Price: ${limit_price:.2f} ({price_reason})")
            print(f"   Estimated Proceeds: ${estimated_proceeds:.2f}")
            print(f"   Robin-Stocks API Call:")
            print(f"   {'-'*50}")
            print(api_call)
            
            order_info = {
                'symbol': position.symbol,
                'limit_price': round(limit_price, 2),
                'estimated_proceeds': estimated_proceeds,
                'api_call': api_call
            }
            
            # Submit orders based on mode
            if live_trading_mode:
                order_result = submit_real_order_handler(position, limit_price, order_info)
            else:
                order_result = submit_simulated_order_handler(position, limit_price, order_info)
            
            simulated_orders.append(order_result)
    
    print(f"\n{'='*60}")
    if live_trading_mode:
        print(f"✅ LIVE TRADING COMPLETE - {len(simulated_orders)} ORDERS SUBMITTED")
    else:
        print(f"✅ SIMULATION COMPLETE - {len(simulated_orders)} ORDERS GENERATED")
    print(f"{'='*60}\n")
    
    # Check order status (will show tracked orders if any were submitted)
    print("🔍 CHECKING ORDER STATUS...")
    check_order_status()
    
    result = {
        'success': True,
        'message': f'{"LIVE ORDERS SUBMITTED" if live_trading_mode else "SIMULATION"}: {len(position_indices)} position(s) processed',
        'orders_simulated': len(simulated_orders),
        'orders': simulated_orders,
        'live_trading_mode': live_trading_mode
    }
    
    return jsonify(result)

@app.route('/api/trailing-stop', methods=['POST'])
def configure_trailing_stop():
    """Configure trailing stop for a position"""
    global risk_manager, live_trading_mode
    data = request.get_json()
    
    symbol = data.get('symbol')
    enabled = data.get('enabled', False)
    percent = float(data.get('percent', 20.0))
    
    if not risk_manager:
        return jsonify({'success': False, 'error': 'Risk manager not initialized'})
    
    # Find the position and add trailing stop data
    for pos_key, position in risk_manager.positions.items():
        if position.symbol == symbol:
            if not hasattr(position, 'trail_stop_data'):
                position.trail_stop_data = {}
            
            # Calculate initial trigger price
            trigger_price = position.current_price * (1 - percent / 100) if enabled else 0
            
            position.trail_stop_data = {
                'enabled': enabled,
                'percent': percent,
                'highest_price': position.current_price if enabled else 0,
                'trigger_price': trigger_price,
                'triggered': False,
                'order_submitted': False,
                'order_id': None,
                'last_update_time': time.time() if enabled else 0.0,
                'last_order_id': None
            }
            
            # Submit initial trailing stop order when first enabled
            if enabled:
                logger.info(f"INITIAL TRAILING STOP ORDER for {symbol}: Stop=${trigger_price:.2f} ({percent}%)")
                
                # For trailing stops: limit = user's exact trailing stop, stop = 3% above limit
                limit_price = trigger_price  # User's exact trailing stop percentage
                stop_price = trigger_price / 0.97  # 3% above limit price to trigger the order
                
                if live_trading_mode:
                    order_result = submit_real_order(position, limit_price, stop_price)
                    if order_result['success']:
                        position.trail_stop_data['last_order_id'] = order_result['order_id']
                        logger.info(f"INITIAL TRAILING STOP ORDER SUBMITTED: {order_result['order_id']}")
                    else:
                        logger.error(f"INITIAL TRAILING STOP FAILED: {order_result['error']}")
                        return jsonify({'success': False, 'error': f'Failed to submit initial order: {order_result["error"]}'})
                else:
                    # Submit simulated trailing stop order
                    order_info = {
                        'symbol': symbol,
                        'limit_price': limit_price,
                        'estimated_proceeds': limit_price * position.quantity * 100,
                        'api_call': f'Initial trailing stop: Stop=${stop_price:.2f}, Limit=${limit_price:.2f}'
                    }
                    sim_result = submit_simulated_order_handler(position, limit_price, order_info)
                    if 'order_id' in sim_result:
                        position.trail_stop_data['last_order_id'] = sim_result['order_id']
                        logger.info(f"INITIAL SIMULATED TRAILING STOP: {sim_result['order_id']}")
                        
                        # Mark the simulated order as a stop-limit type
                        if sim_result['order_id'] in simulated_orders:
                            simulated_orders[sim_result['order_id']]['order_type'] = 'stop_limit'
            
            return jsonify({
                'success': True,
                'message': f'Trailing stop {"enabled" if enabled else "disabled"} for {symbol}' + 
                          (f' - Initial order submitted' if enabled else ''),
                'config': position.trail_stop_data
            })
    
    return jsonify({'success': False, 'error': f'Position {symbol} not found'})

@app.route('/api/check-orders', methods=['GET'])
def check_orders():
    """Check status of all open option orders"""
    try:
        orders = check_order_status()
        
        if orders:
            return jsonify({
                'success': True,
                'message': f'Found {len(orders)} orders',
                'orders': orders,
                'live_trading_mode': live_trading_mode
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No orders found',
                'orders': [],
                'live_trading_mode': live_trading_mode
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Error checking order status'
        })

@app.route('/api/order-status/<order_id>', methods=['GET'])
def get_order_status(order_id):
    """Get status of a specific order"""
    try:
        if live_trading_mode:
            # Check real orders
            if order_id in submitted_orders:
                order_info = submitted_orders[order_id]
                return jsonify({
                    'success': True,
                    'order': order_info,
                    'simulated': False
                })
        else:
            # Check simulated orders
            if order_id in simulated_orders:
                # Update simulated order state first
                update_simulated_orders()
                order = simulated_orders[order_id]
                return jsonify({
                    'success': True,
                    'order': order,
                    'simulated': True
                })
        
        return jsonify({
            'success': False,
            'error': 'Order not found'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/cancel-order/<order_id>', methods=['POST'])
def cancel_order_endpoint(order_id):
    """Cancel a specific order"""
    try:
        result = cancel_order(order_id)
        
        if result['success']:
            print(f"📋 Order cancellation successful: {order_id}")
        else:
            print(f"❌ Order cancellation failed: {result['error']}")
        
        return jsonify(result)
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error in cancel order endpoint: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg
        })


def initialize_risk_manager():
    """Initialize the risk manager"""
    global risk_manager
    logger.info("Initializing Risk Manager...")
    print("Initializing Risk Manager...")
    
    risk_manager = BaseRiskManager()
    
    # Login
    if not risk_manager.login_robinhood():
        logger.error("Failed to authenticate with Robinhood")
        print("Failed to authenticate with Robinhood")
        return False
    
    logger.info("Successfully authenticated with Robinhood")
    
    # Load positions
    risk_manager.load_long_positions()
    
    if len(risk_manager.positions) == 0:
        logger.warning("No long positions found")
        print("No long positions found")
        return False
    
    logger.info(f"Loaded {len(risk_manager.positions)} long option positions")
    print(f"Loaded {len(risk_manager.positions)} positions")
    return True

if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Options Risk Manager Web Interface')
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
        confirmation = input("\nType 'YES I UNDERSTAND' to continue with live trading: ")
        if confirmation != "YES I UNDERSTAND":
            logger.info("Live trading mode cancelled by user. Exiting.")
            print("Live trading mode cancelled. Exiting.")
            sys.exit(1)
        logger.warning("LIVE TRADING MODE CONFIRMED BY USER")
        print("✅ Live trading mode confirmed.\n")
    else:
        logger.info("Running in SIMULATION MODE (safe - no real orders)")
        print("📊 Running in SIMULATION MODE (safe - no real orders)")
    
    if initialize_risk_manager():
        logger.info(f"Risk Manager Web Interface Started - Port: {args.port}")
        logger.info(f"Trading Mode: {'LIVE TRADING' if live_trading_mode else 'SIMULATION'}")
        print("Starting Risk Manager Web Interface...")
        print(f"Mode: {'🔥 LIVE TRADING' if live_trading_mode else '🎯 SIMULATION'}")
        print(f"Access at: http://localhost:{args.port}")
        
        # Start high-frequency trailing stop monitoring
        start_monitoring()
        
        try:
            app.run(debug=True, host='0.0.0.0', port=args.port)
        except KeyboardInterrupt:
            logger.info("Risk Manager shutdown requested by user")
            print("\nShutting down...")
            stop_monitoring()
    else:
        logger.error("Failed to initialize risk manager")
        print("Failed to initialize risk manager")