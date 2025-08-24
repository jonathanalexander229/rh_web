import robin_stocks.robinhood as r
import pandas as pd
import datetime
import getpass
import json
import traceback
from flask import Flask, render_template, jsonify, request, url_for, send_from_directory, redirect
from data_fetcher import SmartDataFetcher

# Update the Flask app initialization to serve static files
app = Flask(__name__, static_url_path='/static')

# Initialize the smart data fetcher
data_fetcher = SmartDataFetcher()

# Add route to serve static files
@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

def fetch_and_process_option_orders():
    """Fetch and process option orders using the normalized database approach"""
    try:
        # Use the smart data fetcher to get processed data
        result = data_fetcher.get_processed_data()
        
        # If there's an error, return it
        if 'error' in result:
            return result
        
        # Format the data for compatibility with existing frontend
        formatted_result = {
            'open_positions': result['open_positions'],
            'closed_positions': result['closed_positions'],
            'expired_positions': result['expired_positions'],
            'all_orders': result['all_orders']
        }
        
        return formatted_result
        
    except Exception as e:
        print(f"Error getting processed data: {str(e)}")
        print(traceback.format_exc())
        
        return {
            'error': True,
            'message': str(e),
            'traceback': traceback.format_exc()
        }

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle login for Robinhood"""
    error = None
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        try:
            # Update database with initial data after login
            result = data_fetcher.update_data(username, password)
            
            if 'error' in result:
                error = f"Login failed: {result['error']}"
            else:
                return redirect(url_for('index'))
                
        except Exception as e:
            error = f"Login failed: {str(e)}"
    
    return render_template('login.html', error=error)

@app.route('/api/update', methods=['POST'])
def update_data():
    """API endpoint to update data from Robinhood"""
    try:
        force_refresh = request.json.get('force_refresh', False) if request.json else False
        result = data_fetcher.update_data(force_full_refresh=force_refresh)
        
        if 'error' in result:
            return jsonify({
                'error': result['error'],
                'details': result.get('traceback', '')
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Data updated successfully',
            'data': result
        })
        
    except Exception as e:
        print(f"Update API Error: {str(e)}")
        print(traceback.format_exc())
        
        return jsonify({
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

@app.route('/api/options')
def get_options():
    """API endpoint to get option orders as JSON"""
    try:
        result = fetch_and_process_option_orders()
        
        # Check if there's an error
        if result and 'error' in result and result['error']:
            return jsonify({
                'error': result['message'],
                'details': result['traceback']
            }), 500
        
        # Ensure the result is JSON serializable
        try:
            # Try to serialize to JSON as a validation step
            json_test = json.dumps(result)
            return jsonify(result)
        except TypeError as e:
            print(f"JSON serialization error: {str(e)}")
            
            # Attempt to fix non-serializable values
            if 'all_orders' in result:
                for i, order in enumerate(result['all_orders']):
                    for key, value in list(order.items()):
                        if isinstance(value, (tuple, set)):
                            result['all_orders'][i][key] = list(value)
                        elif pd.isna(value):
                            result['all_orders'][i][key] = None
            
            return jsonify(result)
            
    except Exception as e:
        # Print the full error traceback to the console
        print(f"API Error: {str(e)}")
        print(traceback.format_exc())
        
        return jsonify({
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

if __name__ == '__main__':
    # Trigger authentication on startup like main branch
    print("Starting Robinhood Options Dashboard...")
    try:
        # This will prompt for credentials if needed, just like main branch
        data_fetcher.login_robinhood()
        print("Authentication successful!")
        
        # Fetch initial data after authentication
        print("Fetching initial data...")
        result = data_fetcher.fetch_option_orders()
        if result['success']:
            print(f"✓ {result['message']}")
        else:
            print(f"⚠ Data fetch warning: {result['error']}")
            
    except Exception as e:
        print(f"Authentication failed: {e}")
        print("You can try again when the server starts by refreshing the page.")
    
    app.run(debug=True, host='0.0.0.0', port=3000)