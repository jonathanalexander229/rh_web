import sqlite3
import json
import datetime
import pandas as pd
from typing import Dict, List, Optional, Tuple
import os

class OptionsDatabase:
    def __init__(self, db_path: str = "options.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create option_orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS option_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                robinhood_id TEXT UNIQUE,
                symbol TEXT,
                created_at TEXT,
                position_effect TEXT,
                expiration_date TEXT,
                strike_price TEXT,
                price REAL,
                quantity INTEGER,
                premium REAL,
                strategy TEXT,
                direction TEXT,
                option_type TEXT,
                option_ids TEXT,
                raw_data TEXT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create positions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                option_key TEXT UNIQUE,
                symbol TEXT,
                open_date TEXT,
                close_date TEXT,
                expiration_date TEXT,
                strike_price TEXT,
                quantity INTEGER,
                open_price REAL,
                close_price REAL,
                open_premium REAL,
                close_premium REAL,
                net_credit REAL,
                strategy TEXT,
                direction TEXT,
                option_type TEXT,
                status TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index for faster queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_robinhood_id ON option_orders(robinhood_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_symbol ON option_orders(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON option_orders(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_option_key ON positions(option_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON positions(status)')
        
        conn.commit()
        conn.close()
    
    def get_last_order_date(self) -> Optional[str]:
        """Get the date of the most recent order in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT MAX(created_at) FROM option_orders')
        result = cursor.fetchone()
        
        conn.close()
        return result[0] if result and result[0] else None
    
    def insert_orders(self, orders: List[Dict]) -> int:
        """Insert new orders into the database, returning count of inserted orders"""
        if not orders:
            return 0
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        inserted_count = 0
        for order in orders:
            try:
                # Extract relevant fields from the order
                robinhood_id = order.get('id', '')
                symbol = order.get('chain_symbol', '')
                created_at = order.get('created_at', '')
                
                # Process legs to extract option data
                legs = order.get('legs', [])
                if legs:
                    position_effect = legs[0].get('position_effect', '')
                    expiration_date = legs[0].get('expiration_date', '')
                    strike_price = '/'.join([f"{float(leg['strike_price']):.2f}" for leg in legs])
                    option_type = '/'.join([leg['option_type'] for leg in legs])
                    option_ids = json.dumps([leg['option'][-13:][:-1] for leg in legs])
                else:
                    position_effect = ''
                    expiration_date = ''
                    strike_price = ''
                    option_type = ''
                    option_ids = json.dumps([])
                
                price = float(order.get('price', 0)) if order.get('price') else None
                quantity = int(float(order.get('processed_quantity', 0))) if order.get('processed_quantity') else None
                premium = float(order.get('processed_premium', 0)) if order.get('processed_premium') else None
                strategy = order.get('opening_strategy') or order.get('closing_strategy', '')
                direction = order.get('direction', '')
                
                cursor.execute('''
                    INSERT OR IGNORE INTO option_orders 
                    (robinhood_id, symbol, created_at, position_effect, expiration_date, 
                     strike_price, price, quantity, premium, strategy, direction, 
                     option_type, option_ids, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    robinhood_id, symbol, created_at, position_effect, expiration_date,
                    strike_price, price, quantity, premium, strategy, direction,
                    option_type, option_ids, json.dumps(order)
                ))
                
                if cursor.rowcount > 0:
                    inserted_count += 1
                    
            except Exception as e:
                print(f"Error inserting order {order.get('id', 'unknown')}: {str(e)}")
                continue
        
        conn.commit()
        conn.close()
        
        return inserted_count
    
    def rebuild_positions(self):
        """Rebuild the positions table from option_orders"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clear existing positions
        cursor.execute('DELETE FROM positions')
        
        # Get all orders grouped by option_ids
        cursor.execute('''
            SELECT option_ids, symbol, created_at, position_effect, expiration_date,
                   strike_price, price, quantity, premium, strategy, direction, option_type
            FROM option_orders
            ORDER BY created_at
        ''')
        
        orders = cursor.fetchall()
        
        # Group orders by option_ids to create positions
        positions_dict = {}
        
        for order in orders:
            option_ids, symbol, created_at, position_effect, expiration_date, strike_price, price, quantity, premium, strategy, direction, option_type = order
            
            option_key = f"{symbol}_{option_ids}_{expiration_date}_{strike_price}"
            
            if option_key not in positions_dict:
                positions_dict[option_key] = {
                    'option_key': option_key,
                    'symbol': symbol,
                    'expiration_date': expiration_date,
                    'strike_price': strike_price,
                    'strategy': strategy,
                    'direction': direction,
                    'option_type': option_type,
                    'open_orders': [],
                    'close_orders': [],
                    'status': 'open'
                }
            
            position = positions_dict[option_key]
            
            if position_effect == 'open':
                position['open_orders'].append({
                    'date': created_at,
                    'price': price,
                    'quantity': quantity or 0,
                    'premium': premium
                })
            elif position_effect == 'close':
                position['close_orders'].append({
                    'date': created_at,
                    'price': price,
                    'quantity': quantity or 0,
                    'premium': premium
                })
        
        # Now calculate aggregated values for each position
        for position in positions_dict.values():
            # Initialize all fields first
            position['open_date'] = None
            position['close_date'] = None
            position['quantity'] = 0
            position['open_price'] = None
            position['close_price'] = None
            position['open_premium'] = None
            position['close_premium'] = None
            position['net_credit'] = None
            
            # Calculate open position aggregates
            if position['open_orders']:
                total_open_quantity = sum(order['quantity'] for order in position['open_orders'])
                total_open_premium = sum(order['premium'] or 0 for order in position['open_orders'])
                
                # Calculate weighted average price
                weighted_price_sum = sum((order['price'] or 0) * order['quantity'] for order in position['open_orders'])
                position['open_price'] = weighted_price_sum / total_open_quantity if total_open_quantity > 0 else None
                position['open_premium'] = total_open_premium
                position['open_date'] = position['open_orders'][0]['date']  # First open date
                position['quantity'] = total_open_quantity
            
            # Calculate close position aggregates
            if position['close_orders']:
                total_close_quantity = sum(order['quantity'] for order in position['close_orders'])
                total_close_premium = sum(order['premium'] or 0 for order in position['close_orders'])
                
                # Calculate weighted average price
                weighted_price_sum = sum((order['price'] or 0) * order['quantity'] for order in position['close_orders'])
                position['close_price'] = weighted_price_sum / total_close_quantity if total_close_quantity > 0 else None
                position['close_premium'] = total_close_premium
                position['close_date'] = position['close_orders'][-1]['date']  # Last close date
                # Don't subtract close quantity - keep the original open quantity for display
                # position['quantity'] -= total_close_quantity
            
            # Clean up temporary arrays
            del position['open_orders']
            del position['close_orders']
        
        # Calculate net credit and determine status
        for position in positions_dict.values():
            if position['open_premium'] is not None and position['close_premium'] is not None:
                # Calculate P&L based on debit/credit strategy
                if position['open_price'] is not None and position['close_price'] is not None and position['quantity'] is not None and position['quantity'] > 0:
                    price_diff = position['close_price'] - position['open_price']
                    print(f"Debug: {position['symbol']} - direction: '{position['direction']}', quantity: {position['quantity']}, price_diff: {price_diff}")
                    
                    if position['direction'] == 'debit':  # Buying options (long positions)
                        position['net_credit'] = price_diff * position['quantity'] * 100
                    elif position['direction'] == 'credit':  # Credit strategies (short positions)
                        position['net_credit'] = -price_diff * position['quantity'] * 100
                    else:
                        # Fallback if direction is unexpected
                        print(f"Warning: Unknown direction '{position['direction']}' for {position['symbol']}")
                        position['net_credit'] = price_diff * position['quantity'] * 100  # Default to debit
                else:
                    # Fallback to premium calculation if prices are missing
                    print(f"Debug: Missing data for {position['symbol']} - open_price: {position['open_price']}, close_price: {position['close_price']}, quantity: {position['quantity']}")
                    position['net_credit'] = position['open_premium'] + position['close_premium']
                position['status'] = 'closed'
            elif position['open_premium'] is not None:
                # Check if expired
                if position['expiration_date']:
                    try:
                        exp_date = datetime.datetime.strptime(position['expiration_date'], '%Y-%m-%d')
                        if exp_date < datetime.datetime.now():
                            position['status'] = 'expired'
                    except ValueError:
                        pass
            
            # Insert position
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (option_key, symbol, open_date, close_date, expiration_date, strike_price,
                 quantity, open_price, close_price, open_premium, close_premium, net_credit,
                 strategy, direction, option_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position['option_key'], position['symbol'], position['open_date'], 
                position['close_date'], position['expiration_date'], position['strike_price'],
                position['quantity'], position['open_price'], position['close_price'],
                position['open_premium'], position['close_premium'], position['net_credit'],
                position['strategy'], position['direction'], position['option_type'],
                position['status']
            ))
        
        conn.commit()
        conn.close()
    
    def get_positions_by_status(self, status: str) -> List[Dict]:
        """Get positions filtered by status"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT option_key, symbol, open_date, close_date, expiration_date, strike_price,
                   quantity, open_price, close_price, open_premium, close_premium, net_credit,
                   strategy, direction, option_type, status
            FROM positions
            WHERE status = ?
            ORDER BY open_date DESC
        ''', (status,))
        
        columns = ['option_key', 'symbol', 'open_date', 'close_date', 'expiration_date', 
                  'strike_price', 'quantity', 'open_price', 'close_price', 'open_premium', 
                  'close_premium', 'net_credit', 'strategy', 'direction', 'option_type', 'status']
        
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        
        conn.close()
        return results
    
    def get_all_orders(self) -> List[Dict]:
        """Get all orders from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, created_at, position_effect, expiration_date, strike_price,
                   price, quantity, premium, strategy, direction, option_type, option_ids
            FROM option_orders
            ORDER BY created_at DESC
        ''')
        
        columns = ['symbol', 'created_at', 'position_effect', 'expiration_date', 
                  'strike_price', 'price', 'quantity', 'premium', 'strategy', 
                  'direction', 'option_type', 'option_ids']
        
        results = []
        for row in cursor.fetchall():
            order_dict = dict(zip(columns, row))
            # Parse option_ids back to list
            try:
                order_dict['option'] = json.loads(order_dict['option_ids'])
            except:
                order_dict['option'] = []
            del order_dict['option_ids']
            results.append(order_dict)
        
        conn.close()
        return results