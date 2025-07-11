import robin_stocks.robinhood as r
import datetime
import traceback
from typing import Dict, List, Optional
from database import OptionsDatabase

class SmartDataFetcher:
    def __init__(self, db_path: str = "options.db"):
        self.db = OptionsDatabase(db_path)
    
    def login_robinhood(self, username: str = None, password: str = None) -> bool:
        """Login to Robinhood with smart credential handling"""
        try:
            # Try to login with saved credentials first
            r.login()
            return True
        except Exception as e:
            if username and password:
                try:
                    r.login(username, password)
                    return True
                except Exception as login_error:
                    print(f"Login failed: {str(login_error)}")
                    return False
            else:
                print(f"No saved credentials and no username/password provided: {str(e)}")
                return False
    
    def get_incremental_start_date(self) -> str:
        """Determine the start date for incremental fetching"""
        last_order_date = self.db.get_last_order_date()
        
        if last_order_date:
            # Start from the last order date
            try:
                last_date = datetime.datetime.strptime(last_order_date[:10], '%Y-%m-%d')
                # Go back 1 day to catch any orders that might have been missed
                start_date = last_date - datetime.timedelta(days=1)
                return start_date.strftime('%Y-%m-%d')
            except ValueError:
                # If date parsing fails, fall back to default
                pass
        
        # Default to 60 days ago for new installations
        default_start = datetime.datetime.now() - datetime.timedelta(days=60)
        return default_start.strftime('%Y-%m-%d')
    
    def fetch_option_orders(self, start_date: str = None, force_full_refresh: bool = False) -> Dict:
        """Fetch option orders with smart incremental updates"""
        try:
            if not start_date:
                if force_full_refresh:
                    # For full refresh, go back 90 days
                    start_date = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
                else:
                    start_date = self.get_incremental_start_date()
            
            print(f"Fetching orders from {start_date}")
            
            # Get option orders from Robinhood
            all_orders = r.orders.get_all_option_orders(start_date=start_date)
            
            if not isinstance(all_orders, list):
                raise ValueError(f"Expected list of orders, got {type(all_orders)}")
            
            # Filter for filled orders only
            filled_orders = [order for order in all_orders if order.get('state') == 'filled']
            
            print(f"Found {len(filled_orders)} filled orders")
            
            # Insert new orders into database
            inserted_count = self.db.insert_orders(filled_orders)
            print(f"Inserted {inserted_count} new orders")
            
            # Rebuild positions table
            self.db.rebuild_positions()
            print("Rebuilt positions table")
            
            return {
                'success': True,
                'orders_fetched': len(filled_orders),
                'orders_inserted': inserted_count,
                'message': f"Successfully updated database with {inserted_count} new orders"
            }
            
        except Exception as e:
            print(f"Error fetching option orders: {str(e)}")
            print(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
    
    def get_processed_data(self) -> Dict:
        """Get processed data from the database"""
        try:
            # Get positions by status
            open_positions = self.db.get_positions_by_status('open')
            closed_positions = self.db.get_positions_by_status('closed')
            expired_positions = self.db.get_positions_by_status('expired')
            all_orders = self.db.get_all_orders()
            
            return {
                'open_positions': open_positions,
                'closed_positions': closed_positions,
                'expired_positions': expired_positions,
                'all_orders': all_orders
            }
            
        except Exception as e:
            print(f"Error getting processed data: {str(e)}")
            return {
                'error': True,
                'message': str(e),
                'traceback': traceback.format_exc()
            }
    
    def update_data(self, username: str = None, password: str = None, force_full_refresh: bool = False) -> Dict:
        """Update the database with latest data"""
        # Login first
        if not self.login_robinhood(username, password):
            return {
                'success': False,
                'error': 'Failed to login to Robinhood'
            }
        
        # Fetch and process data
        fetch_result = self.fetch_option_orders(force_full_refresh=force_full_refresh)
        
        if fetch_result['success']:
            # Return processed data
            return self.get_processed_data()
        else:
            return fetch_result