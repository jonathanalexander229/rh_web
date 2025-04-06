import robin_stocks.robinhood as r
import pandas as pd
import datetime
import getpass
import json
import traceback
from flask import Flask, render_template, jsonify, request, url_for, send_from_directory, redirect

# Update the Flask app initialization to serve static files
app = Flask(__name__, static_url_path='/static')

# Add route to serve static files
@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

def fetch_and_process_option_orders():
    """Fetch and process option orders from Robinhood, pairing opening and closing positions"""
    try:
        # Try to login with saved credentials
        login = r.login()
    except Exception as e:
        # If login fails, prompt for credentials
        username = input("Enter your username: ")
        password = getpass.getpass("Enter your password: ")
        login = r.login(username, password)
    
    # Get all option orders from last 3 months (adjust date as needed)
    try:
        all_orders = r.orders.get_all_option_orders(start_date='2025-02-5')
        
        # IMPORTANT: Add validation to make sure the response is properly formatted
        if not isinstance(all_orders, list):
            raise ValueError(f"Expected list of orders, got {type(all_orders)}")
            
        # Convert the list of dictionaries to a DataFrame
        df = pd.DataFrame(all_orders)
        
        # Filter for filled orders only
        df = df[df['state'] == 'filled']
        
        # Sort legs by option ID
        df['sorted_legs'] = df['legs'].apply(lambda x: sorted(x, key=lambda leg: leg['option']) if x else None)
        df['legs'] = df['sorted_legs']
        
        # Extract data from legs
        df['strike_price'] = df['legs'].apply(lambda x: '/'.join([f"{float(leg['strike_price']):.2f}" for leg in x]) if x else None)
        df['expiration_date'] = df['legs'].apply(lambda x: x[0]['expiration_date'] if x else None)
        df['option_type'] = df['legs'].apply(lambda x: '/'.join([leg['option_type'] for leg in x]) if x else None)
        df['position_effect'] = df['legs'].apply(lambda x: x[0]['position_effect'] if x else None)
        df['option'] = df['legs'].apply(lambda x: [leg['option'][-13:][:-1] for leg in x] if x else None)
        
        # Specify columns to drop
        columns_to_drop = ['net_amount','estimated_total_net_amount','premium','regulatory_fees',
                    'time_in_force','form_source','client_bid_at_submission','client_ask_at_submission',
                    'client_time_at_submission','trigger','type','updated_at','chain_id','quantity',
                    'pending_quantity','response_category','stop_price','account_number',
                    'cancel_url', 'canceled_quantity', 'ref_id', 'legs', 'state', 'id',
                    'estimated_total_net_amount_direction', 'sorted_legs']
        
        # Drop specified columns that exist in the DataFrame
        columns_to_drop = [col for col in columns_to_drop if col in df.columns]
        df = df.drop(columns=columns_to_drop)
        
        # Reorder columns with chain_symbol first (if it exists)
        if 'chain_symbol' in df.columns:
            df = df[['chain_symbol'] + [col for col in df.columns if col != 'chain_symbol']]
        
        # Convert 'created_at' to datetime format with time
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'])
            df['created_at'] = df['created_at'].dt.strftime('%Y-%m-%d %H:%M')
        
        # Specify column order (only include columns that exist)
        new_order = [
            'chain_symbol', 'created_at', 'option', 'position_effect', 'expiration_date', 
            'strike_price', 'price', 'processed_quantity', 'opening_strategy', 
            'direction', 'processed_premium', 'option_type', 'closing_strategy', 
            'net_amount_direction', 'average_net_premium_paid'
        ]
        
        # Only include columns that exist in the DataFrame
        new_order = [col for col in new_order if col in df.columns]
        
        # Reorder columns
        df = df.reindex(columns=new_order)
        
        # Rename columns
        column_abbreviations = {
            'chain_symbol': 'symbol',
            'average_net_premium_paid': 'avg_net_premium',
            'processed_premium': 'premium',
            'processed_quantity': 'quantity',
        }
        # Only rename columns that exist
        column_abbreviations = {k: v for k, v in column_abbreviations.items() if k in df.columns}
        df = df.rename(columns=column_abbreviations)
        
        # Sort and reset index
        df.sort_values(by=['symbol', 'created_at', 'strike_price'] if all(col in df.columns for col in ['symbol', 'created_at', 'strike_price']) else 
                    [col for col in ['symbol', 'created_at', 'strike_price'] if col in df.columns], 
                    inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        # Safely convert numeric columns to float with error handling
        for col in ['quantity', 'price', 'premium', 'avg_net_premium']:
            if col in df.columns:
                try:
                    # First check if any values are None/NaN and handle them
                    df[col] = df[col].apply(lambda x: x if pd.notnull(x) else None)
                    # Then attempt conversion with error handling for each value
                    df[col] = df[col].apply(lambda x: float(x) if pd.notnull(x) else None)
                except Exception as e:
                    print(f"Error converting column {col}: {str(e)}")
                    # Identify problematic values
                    problem_values = df[~df[col].apply(lambda x: isinstance(x, (int, float, type(None))))]
                    if not problem_values.empty:
                        print(f"Problematic values in {col}: {problem_values[col].tolist()}")
                    # Set column to None if conversion fails
                    df[col] = None
        
        # Create strategy column if both columns exist
        if 'opening_strategy' in df.columns and 'closing_strategy' in df.columns:
            df['strategy'] = df[['opening_strategy', 'closing_strategy']].apply(
                lambda x: x.iloc[0] if pd.notnull(x.iloc[0]) else x.iloc[1], axis=1
            )
        
        # Convert option column to tuple for grouping if it exists
        if 'option' in df.columns:
            df['option'] = df['option'].apply(lambda x: tuple(x) if isinstance(x, list) else x)
        
        # Group by option and position_effect if both columns exist
        if 'option' in df.columns and 'position_effect' in df.columns:
            # Define aggregation dictionary with only columns that exist
            agg_dict = {}
            for col in ['option', 'symbol', 'created_at', 'position_effect', 'expiration_date', 
                       'strike_price', 'quantity', 'price', 'direction', 'premium', 'strategy']:
                if col in df.columns:
                    if col in ['quantity']:
                        agg_dict[col] = 'sum'
                    elif col in ['price']:
                        agg_dict[col] = 'mean'
                    elif col == 'premium' and 'direction' in df.columns:
                        agg_dict[col] = lambda x: -x.sum() if any(df.loc[x.index, 'direction'] == 'debit') else x.sum()
                    else:
                        agg_dict[col] = 'first'
            
            # Only perform groupby if we have aggregation columns
            if agg_dict:
                merged_df = df.groupby(['option', 'position_effect'], as_index=False).agg(agg_dict)
                
                # Sort and reset index
                sort_cols = [col for col in ['option', 'created_at', 'strike_price'] if col in merged_df.columns]
                if sort_cols:
                    merged_df.sort_values(by=sort_cols, inplace=True)
                merged_df.reset_index(drop=True, inplace=True)
                
                # Create open/close date and price columns
                if all(col in merged_df.columns for col in ['created_at', 'position_effect']):
                    merged_df['open_date'] = merged_df.apply(lambda x: x['created_at'] if x['position_effect'] == 'open' else None, axis=1)
                    merged_df['close_date'] = merged_df.apply(lambda x: x['created_at'] if x['position_effect'] == 'close' else None, axis=1)
                
                if all(col in merged_df.columns for col in ['price', 'position_effect']):
                    merged_df['open_price'] = merged_df.apply(lambda x: x['price'] if x['position_effect'] == 'open' else None, axis=1)
                    
                if all(col in merged_df.columns for col in ['premium', 'position_effect']):
                    merged_df['open_premium'] = merged_df.apply(lambda x: x['premium'] if x['position_effect'] == 'open' else None, axis=1)
                
                if all(col in merged_df.columns for col in ['price', 'position_effect']):
                    merged_df['close_price'] = merged_df.apply(lambda x: x['price'] if x['position_effect'] == 'close' else None, axis=1)
                
                if all(col in merged_df.columns for col in ['premium', 'position_effect']):
                    merged_df['close_premium'] = merged_df.apply(lambda x: x['premium'] if x['position_effect'] == 'close' else None, axis=1)
                
                # Group by option to pair open and close positions
                if 'option' in merged_df.columns:
                    # Define paired aggregation dictionary
                    paired_agg = {}
                    for col in ['symbol', 'open_date', 'close_date', 'expiration_date', 
                               'strike_price', 'quantity', 'open_price', 'open_premium', 
                               'close_price', 'close_premium', 'strategy', 'direction', 'option_type']:
                        if col in merged_df.columns:
                            if col == 'quantity':
                                paired_agg[col] = 'sum'
                            else:
                                paired_agg[col] = 'first'
                    
                    paired = merged_df.groupby(['option'], as_index=False).agg(paired_agg)
                    
                    # Convert expiration_date to datetime if it exists
                    if 'expiration_date' in paired.columns:
                        paired['expiration_date'] = pd.to_datetime(paired['expiration_date'])
                    
                    # Sort by close date if it exists
                    if 'close_date' in paired.columns:
                        paired = paired.sort_values(by=['close_date'], ascending=[True])
                    
                    # Calculate net credit/debit if both columns exist
                    if 'open_premium' in paired.columns and 'close_premium' in paired.columns:
                        paired['net_credit'] = paired.apply(
                            lambda x: x['open_premium'] + x['close_premium'] 
                            if pd.notnull(x['open_premium']) and pd.notnull(x['close_premium']) 
                            else None, axis=1
                        )
                    
                    # Format dates for display
                    if 'expiration_date' in paired.columns:
                        paired['expiration_date'] = paired['expiration_date'].dt.strftime('%Y-%m-%d')
                    
                    # Create three separate dataframes based on available columns
                    if all(col in paired.columns for col in ['close_date', 'open_date', 'expiration_date']):
                        # Expired positions: only those without closing orders that have passed expiration date
                        expired_df = paired[(paired['close_date'].isnull()) & 
                                          (paired['open_date'].notnull()) &
                                          (pd.to_datetime(paired['expiration_date']) < pd.Timestamp.now())]
                        
                        # Closed positions: those with both opening and closing orders
                        closed_df = paired[(paired['open_date'].notnull()) & (paired['close_date'].notnull())]
                        
                        # Open positions: those with opening orders but no closing orders and not yet expired
                        open_df = paired[(paired['open_date'].notnull()) & (paired['close_date'].isnull()) & 
                                       (pd.to_datetime(paired['expiration_date']) >= pd.Timestamp.now())]
                        
                        # Ensure all values are JSON serializable
                        def clean_for_json(df):
                            """Convert DataFrame to JSON-serializable dictionary"""
                            if df.empty:
                                return []
                                
                            # First convert to records
                            records = df.to_dict(orient='records')
                            
                            # Then sanitize each record
                            for record in records:
                                for key, value in list(record.items()):
                                    # Handle NaN, None, and other non-serializable values
                                    if pd.isna(value) or value is None:
                                        record[key] = None
                                    elif isinstance(value, (tuple, list)):
                                        record[key] = [str(x) for x in value]
                                        
                            return records
                        
                        # Convert all DataFrames to dict for JSON serialization with clean values
                        result = {
                            'open_positions': clean_for_json(open_df),
                            'closed_positions': clean_for_json(closed_df),
                            'expired_positions': clean_for_json(expired_df),
                            'all_orders': clean_for_json(df)
                        }
                        
                        return result
        
        # If we couldn't process the data properly, return empty results
        return {
            'open_positions': [],
            'closed_positions': [],
            'expired_positions': [],
            'all_orders': df.to_dict(orient='records') if not df.empty else []
        }
                        
    except Exception as e:
        # Print the full error traceback to the console for debugging
        print(f"Error processing option orders: {str(e)}")
        print(traceback.format_exc())
        
        # Return a detailed error object that can be displayed to the user
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
            r.login(username, password)
            return redirect(url_for('index'))
        except Exception as e:
            error = f"Login failed: {str(e)}"
    
    return render_template('login.html', error=error)

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
    app.run(debug=True, host='0.0.0.0', port=5000)