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
from simple_risk_manager import SimpleRiskManager

app = Flask(__name__)

# Global risk manager instance
risk_manager = None
monitoring_thread = None
is_monitoring = False

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
        'last_update': datetime.datetime.now().strftime('%H:%M:%S')
    })

@app.route('/api/close-simulation', methods=['POST'])
def close_simulation():
    """Simulate closing positions"""
    data = request.get_json()
    position_indices = data.get('positions', [])
    
    result = {
        'success': True,
        'message': f'SIMULATION: {len(position_indices)} position(s) would be closed',
        'orders_simulated': len(position_indices)
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

def initialize_risk_manager():
    """Initialize the risk manager"""
    global risk_manager
    print("Initializing Risk Manager...")
    
    risk_manager = SimpleRiskManager()
    
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
    if initialize_risk_manager():
        print("Starting Risk Manager Web Interface...")
        print("Access at: http://localhost:5001")
        
        # Start high-frequency trailing stop monitoring
        start_monitoring()
        
        try:
            app.run(debug=True, host='0.0.0.0', port=5001)
        except KeyboardInterrupt:
            print("\nShutting down...")
            stop_monitoring()
    else:
        print("Failed to initialize risk manager")