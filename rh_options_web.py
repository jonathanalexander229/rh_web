import os
import robin_stocks.robinhood as r
import pandas as pd
import datetime
import getpass
from flask import Flask, render_template, jsonify
import json

app = Flask(__name__)

def fetch_option_orders():
    """Fetch and process option orders from Robinhood"""
    try:
        # Try to login with saved credentials
        login = r.login()
    except:
        # If login fails, prompt for credentials
        username = input("Enter your username: ")
        password = getpass.getpass("Enter your password: ")
        login = r.login(username, password)
    
    # Get all option orders from the last week (adjust date as needed)
    all_orders = r.orders.get_all_option_orders(start_date='2025-2-25')
    
    # Convert the list of dictionaries to a DataFrame
    df = pd.DataFrame(all_orders)
    
    # Filter out cancelled orders
    df = df[df['state'] != 'cancelled']
    
    # Extract data from legs
    df['expiration_date'] = df['legs'].apply(lambda x: x[0]['expiration_date'] if x else None)
    df['strike_price'] = df['legs'].apply(lambda x: '/'.join([f"{float(leg['strike_price']):.2f}" for leg in x]) if x else None)
    df['option_type'] = df['legs'].apply(lambda x: '/'.join([leg['option_type'] for leg in x]) if x else None)
    df['position_effect'] = df['legs'].apply(lambda x: x[0]['position_effect'] if x else None)
    df['option'] = df['legs'].apply(lambda x: x[0]['option'][-13:][:-1] if x else None)
    
    # Specify the columns to drop
    columns_to_drop = ['net_amount', 'estimated_total_net_amount', 'premium', 'regulatory_fees',
                'time_in_force', 'form_source', 'client_bid_at_submission', 'client_ask_at_submission',
                'client_time_at_submission', 'trigger', 'type', 'updated_at', 'chain_id', 'quantity',
                'pending_quantity', 'response_category', 'stop_price', 'account_number',
                'cancel_url', 'canceled_quantity', 'ref_id', 'legs', 'state', 'id',
                'estimated_total_net_amount_direction']
    
    # Drop the specified columns
    df = df.drop(columns=columns_to_drop)
    
    # Reorder columns
    df = df[['chain_symbol'] + [col for col in df.columns if col != 'chain_symbol']]
    
    # Convert 'created_at' to datetime format
    df['created_at'] = pd.to_datetime(df['created_at'])
    
    # Filter by date
    df = df[df['created_at'] > '2025-2-25']
    
    # Format date
    df['created_at'] = df['created_at'].dt.date
    
    # Specify the new column order
    new_order = ['chain_symbol', 'created_at', 'option', 'position_effect', 'expiration_date', 'strike_price', 'price', 'processed_quantity', 'opening_strategy', 
                'direction', 'processed_premium', 'option_type', 'closing_strategy', 'net_amount_direction', 'average_net_premium_paid']
    
    # Reorder the columns
    df = df.reindex(columns=new_order)
    
    # Specify the column abbreviations
    column_abbreviations = {
        'chain_symbol': 'symbol',
        'average_net_premium_paid': 'avg_net_premium',
        'processed_premium': 'premium',
        'processed_quantity': 'quantity',
    }
    
    # Rename the columns
    df = df.rename(columns=column_abbreviations)
    
    # Sort by date
    df = df.sort_values(['created_at', 'option'])
    
    # Convert numeric columns to float
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, datetime.date)).any():
            continue
        try:
            df[col] = df[col].astype(float).round(2)
        except ValueError:
            pass
    
    # Convert date columns to string for JSON serialization
    df['created_at'] = df['created_at'].astype(str)
    
    # Count the occurrences of each 'option' value
    option_counts = df['option'].value_counts()
    
    # Get the 'option' values that appear only once
    open_options = option_counts[option_counts == 1].index
    
    # Save to CSV (optional)
    df.to_csv('recent_option_orders.csv', index=False)
    
    return df

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/api/options')
def get_options():
    """API endpoint to get option orders as JSON"""
    try:
        df = fetch_option_orders()
        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Create templates directory if it doesn't exist
if not os.path.exists('templates'):
    os.makedirs('templates')

# Create index.html template
with open('templates/index.html', 'w') as f:
    f.write('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Robinhood Options Orders</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #00C805;
            text-align: center;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .filters {
            margin-bottom: 20px;
            padding: 15px;
            background: white;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .filter-row {
            display: flex;
            gap: 15px;
            margin-bottom: 10px;
        }
        select, input {
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        button {
            background-color: #00C805;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 4px;
            cursor: pointer;
        }
        button:hover {
            background-color: #00A804;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            border-radius: 5px;
            overflow: hidden;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #00C805;
            color: white;
            position: sticky;
            top: 0;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .buy {
            color: #00C805;
            font-weight: bold;
        }
        .sell {
            color: #FF5000;
            font-weight: bold;
        }
        .loading {
            text-align: center;
            padding: 20px;
            font-size: 18px;
        }
        .error {
            background-color: #ffeeee;
            color: #cc0000;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Robinhood Options Orders</h1>
        
        <div class="filters">
            <div class="filter-row">
                <select id="symbolFilter">
                    <option value="">All Symbols</option>
                </select>
                <select id="positionFilter">
                    <option value="">All Positions</option>
                    <option value="open">Open</option>
                    <option value="close">Close</option>
                </select>
                <select id="optionTypeFilter">
                    <option value="">All Types</option>
                    <option value="call">Calls</option>
                    <option value="put">Puts</option>
                </select>
                <input type="date" id="dateFilter" placeholder="Filter by date">
                <button id="resetFilters">Reset Filters</button>
            </div>
            <div class="filter-row">
                <button id="refreshData">Refresh Data</button>
                <span id="lastUpdated"></span>
            </div>
        </div>
        
        <div id="errorMessage" class="error" style="display: none;"></div>
        
        <div id="loadingIndicator" class="loading">Loading options data...</div>
        
        <table id="optionsTable" style="display: none;">
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Date</th>
                    <th>Option</th>
                    <th>Position</th>
                    <th>Expiration</th>
                    <th>Strike</th>
                    <th>Price</th>
                    <th>Quantity</th>
                    <th>Strategy</th>
                    <th>Direction</th>
                    <th>Premium</th>
                    <th>Type</th>
                </tr>
            </thead>
            <tbody>
                <!-- Data will be inserted here -->
            </tbody>
        </table>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Initial data load
            fetchOptionsData();
            
            // Set up event listeners
            document.getElementById('refreshData').addEventListener('click', fetchOptionsData);
            document.getElementById('resetFilters').addEventListener('click', resetFilters);
            
            document.getElementById('symbolFilter').addEventListener('change', applyFilters);
            document.getElementById('positionFilter').addEventListener('change', applyFilters);
            document.getElementById('optionTypeFilter').addEventListener('change', applyFilters);
            document.getElementById('dateFilter').addEventListener('change', applyFilters);
            
            // Store the original data
            let originalData = [];
            
            function fetchOptionsData() {
                const loadingIndicator = document.getElementById('loadingIndicator');
                const optionsTable = document.getElementById('optionsTable');
                const errorMessage = document.getElementById('errorMessage');
                
                loadingIndicator.style.display = 'block';
                optionsTable.style.display = 'none';
                errorMessage.style.display = 'none';
                
                fetch('/api/options')
                    .then(response => {
                        if (!response.ok) {
                            throw new Error('Network response was not ok');
                        }
                        return response.json();
                    })
                    .then(data => {
                        originalData = data;
                        populateTable(data);
                        populateFilters(data);
                        
                        loadingIndicator.style.display = 'none';
                        optionsTable.style.display = 'table';
                        
                        // Update last updated time
                        const now = new Date();
                        document.getElementById('lastUpdated').textContent = 
                            `Last updated: ${now.toLocaleTimeString()}`;
                    })
                    .catch(error => {
                        console.error('Error fetching data:', error);
                        loadingIndicator.style.display = 'none';
                        errorMessage.textContent = `Error loading data: ${error.message}`;
                        errorMessage.style.display = 'block';
                    });
            }
            
            function populateTable(data) {
                const tbody = document.querySelector('#optionsTable tbody');
                tbody.innerHTML = '';
                
                if (data.length === 0) {
                    const row = document.createElement('tr');
                    const cell = document.createElement('td');
                    cell.colSpan = 12;
                    cell.textContent = 'No options data found';
                    cell.style.textAlign = 'center';
                    row.appendChild(cell);
                    tbody.appendChild(row);
                    return;
                }
                
                data.forEach(order => {
                    const row = document.createElement('tr');
                    
                    // Add cells for each column
                    const columns = [
                        'symbol', 'created_at', 'option', 'position_effect', 
                        'expiration_date', 'strike_price', 'price', 'quantity', 
                        'opening_strategy', 'direction', 'premium', 'option_type'
                    ];
                    
                    columns.forEach(column => {
                        const cell = document.createElement('td');
                        cell.textContent = order[column] !== null ? order[column] : '';
                        
                        // Add styling based on direction or position
                        if (column === 'direction') {
                            if (order[column] === 'debit') {
                                cell.classList.add('buy');
                            } else if (order[column] === 'credit') {
                                cell.classList.add('sell');
                            }
                        }
                        
                        row.appendChild(cell);
                    });
                    
                    tbody.appendChild(row);
                });
            }
            
            function populateFilters(data) {
                // Populate symbol filter
                const symbolFilter = document.getElementById('symbolFilter');
                const symbols = [...new Set(data.map(item => item.symbol))];
                
                // Clear existing options except the first one
                while (symbolFilter.options.length > 1) {
                    symbolFilter.remove(1);
                }
                
                symbols.sort().forEach(symbol => {
                    const option = document.createElement('option');
                    option.value = symbol;
                    option.textContent = symbol;
                    symbolFilter.appendChild(option);
                });
            }
            
            function applyFilters() {
                const symbolValue = document.getElementById('symbolFilter').value;
                const positionValue = document.getElementById('positionFilter').value;
                const optionTypeValue = document.getElementById('optionTypeFilter').value;
                const dateValue = document.getElementById('dateFilter').value;
                
                let filteredData = [...originalData];
                
                // Apply symbol filter
                if (symbolValue) {
                    filteredData = filteredData.filter(item => item.symbol === symbolValue);
                }
                
                // Apply position filter
                if (positionValue) {
                    filteredData = filteredData.filter(item => item.position_effect === positionValue);
                }
                
                // Apply option type filter
                if (optionTypeValue) {
                    filteredData = filteredData.filter(item => 
                        item.option_type && item.option_type.toLowerCase().includes(optionTypeValue)
                    );
                }
                
                // Apply date filter
                if (dateValue) {
                    filteredData = filteredData.filter(item => item.created_at === dateValue);
                }
                
                populateTable(filteredData);
            }
            
            function resetFilters() {
                document.getElementById('symbolFilter').value = '';
                document.getElementById('positionFilter').value = '';
                document.getElementById('optionTypeFilter').value = '';
                document.getElementById('dateFilter').value = '';
                
                populateTable(originalData);
            }
        });
    </script>
</body>
</html>
    ''')

if __name__ == '__main__':
    print("Starting Robinhood Options Order Web Server...")
    print("Visit http://127.0.0.1:5000 in your browser")
    app.run(debug=True)