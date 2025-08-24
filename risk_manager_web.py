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
from base_risk_manager import BaseRiskManager

app = Flask(__name__)

# Global risk manager instance
risk_manager = None
monitoring_thread = None
is_monitoring = False
live_trading_mode = False  # Set to True to enable real order submission
submitted_orders = {}  # Track submitted orders: {order_id: {position_key, timestamp, status, symbol, details}}

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
    """Update trailing stop values for all enabled positions"""
    global risk_manager
    if not risk_manager:
        return
        
    for pos_key, position in risk_manager.positions.items():
        trail_stop_data = getattr(position, 'trail_stop_data', {})
        
        if trail_stop_data.get('enabled', False) and position.current_price > 0:
            # Update market data for this position
            risk_manager.calculate_pnl(position)
            
            # Update highest price (ratchet up only)
            if position.current_price > trail_stop_data['highest_price']:
                trail_stop_data['highest_price'] = position.current_price
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Trailing stop for {position.symbol}: New high ${position.current_price:.3f}")
            
            # Recalculate trigger price
            trail_stop_data['trigger_price'] = trail_stop_data['highest_price'] * (1 - trail_stop_data['percent'] / 100)
            
            # Check if triggered
            was_triggered = trail_stop_data.get('triggered', False)
            trail_stop_data['triggered'] = position.current_price <= trail_stop_data['trigger_price']
            
            # Alert when first triggered
            if trail_stop_data['triggered'] and not was_triggered:
                print(f"🔥 TRAILING STOP TRIGGERED for {position.symbol}! Current: ${position.current_price:.3f} <= Trigger: ${trail_stop_data['trigger_price']:.3f}")

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

def check_order_status():
    """Check status of tracked submitted orders using specific order IDs"""
    global submitted_orders
    import robin_stocks.robinhood as r
    
    try:
        if not submitted_orders:
            print("📋 No submitted orders to track")
            return []
            
        print(f"\n📋 CHECKING STATUS OF {len(submitted_orders)} TRACKED ORDERS")
        print("=" * 60)
        
        updated_orders = []
        
        for order_id, order_info in submitted_orders.items():
            try:
                # Get specific order info - no pagination needed!
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
                    
                    # Update our tracking
                    submitted_orders[order_id]['current_state'] = state
                    submitted_orders[order_id]['last_checked'] = datetime.datetime.now().isoformat()
                    
                    if state in ['filled', 'cancelled', 'rejected']:
                        print(f"   🎯 Order {order_id[:8]}... is {state.upper()}!")
                    
                    updated_orders.append(order_details)
                    print("-" * 40)
                else:
                    print(f"   ❌ Could not get details for order {order_id[:8]}...")
                    
            except Exception as e:
                print(f"   ❌ Error checking order {order_id[:8]}...: {e}")
        
        print("=" * 60)
        return updated_orders
        
    except Exception as e:
        print(f"Error in order status check: {e}")
        return []

def submit_real_order(position, limit_price):
    """Submit a real order and return order details with ID"""
    global submitted_orders
    import robin_stocks.robinhood as r
    
    try:
        print(f"🔥 SUBMITTING REAL ORDER for {position.symbol}")
        
        # Submit the order
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
            'triggered': False
        })
        
        # Check if trailing stop would be triggered
        if trail_stop_data['enabled'] and position.current_price > 0:
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
            
            # Submit real order if in live trading mode
            if live_trading_mode:
                print(f"\n   🔥 SUBMITTING REAL ORDER...")
                order_result = submit_real_order(position, limit_price)
                
                if order_result['success']:
                    order_info['order_id'] = order_result['order_id']
                    order_info['order_state'] = order_result['order_result'].get('state', 'unknown')
                    print(f"   ✅ REAL ORDER SUBMITTED: {order_result['order_id']}")
                else:
                    order_info['error'] = order_result['error']
                    print(f"   ❌ ORDER FAILED: {order_result['error']}")
            
            simulated_orders.append(order_info)
    
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
    global risk_manager
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
            
            position.trail_stop_data = {
                'enabled': enabled,
                'percent': percent,
                'highest_price': position.current_price if enabled else 0,
                'trigger_price': position.current_price * (1 - percent / 100) if enabled else 0,
                'triggered': False
            }
            
            return jsonify({
                'success': True,
                'message': f'Trailing stop {"enabled" if enabled else "disabled"} for {symbol}',
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
                'message': f'Found {len(orders)} open orders',
                'orders': orders
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No open orders found',
                'orders': []
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Error checking order status'
        })


def initialize_risk_manager():
    """Initialize the risk manager"""
    global risk_manager
    print("Initializing Risk Manager...")
    
    risk_manager = BaseRiskManager()
    
    # Login
    if not risk_manager.login_robinhood():
        print("Failed to authenticate with Robinhood")
        return False
    
    # Load positions
    risk_manager.load_long_positions()
    
    if len(risk_manager.positions) == 0:
        print("No long positions found")
        return False
    
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
        print("\n" + "="*60)
        print("🔥 WARNING: LIVE TRADING MODE ENABLED!")
        print("🔥 THIS WILL PLACE REAL ORDERS WITH REAL MONEY!")
        print("="*60)
        
        # Require explicit confirmation for live trading
        confirmation = input("\nType 'YES I UNDERSTAND' to continue with live trading: ")
        if confirmation != "YES I UNDERSTAND":
            print("Live trading mode cancelled. Exiting.")
            sys.exit(1)
        print("✅ Live trading mode confirmed.\n")
    else:
        print("📊 Running in SIMULATION MODE (safe - no real orders)")
    
    if initialize_risk_manager():
        print("Starting Risk Manager Web Interface...")
        print(f"Mode: {'🔥 LIVE TRADING' if live_trading_mode else '🎯 SIMULATION'}")
        print(f"Access at: http://localhost:{args.port}")
        
        # Start high-frequency trailing stop monitoring
        start_monitoring()
        
        try:
            app.run(debug=True, host='0.0.0.0', port=args.port)
        except KeyboardInterrupt:
            print("\nShutting down...")
            stop_monitoring()
    else:
        print("Failed to initialize risk manager")