#!/usr/bin/env python3
"""
Base Risk Manager for Long Options
Core functionality for monitoring and managing long option positions
"""

import robin_stocks.robinhood as r
import datetime
import time
from typing import Dict, List, Optional
from position_types import LongPosition
from position_manager import position_manager

class BaseRiskManager:
    def __init__(self, stop_loss_percent: float = 50.0, take_profit_percent: float = 50.0, account_number: Optional[str] = None):
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        self.account_number = account_number
        self.positions: Dict[str, LongPosition] = {}
        
        print("Base Risk Manager for Long Options")
        print(f"Stop Loss: -{self.stop_loss_percent}%")
        print(f"Take Profit: {self.take_profit_percent}%")
        print("=" * 50)
    
    def login_robinhood(self) -> bool:
        """Login to Robinhood"""
        try:
            print("Authenticating with Robinhood...")
            print("Starting login process...")
            
            # Try existing login first
            r.login()
            print("Authentication successful!")
            return True
            
        except Exception as e:
            print(f"Authentication failed: {e}")
            return False
    
    def load_long_positions(self) -> int:
        """Load long positions using cached data from PositionManager"""
        try:
            account_display = f" for account ...{self.account_number[-4:]}" if self.account_number else ""
            print(f"Loading cached positions{account_display}...")
            
            # Get positions from PositionManager cache (already loaded by AccountDetector)
            cached_positions = position_manager.get_positions_for_account(self.account_number)
            
            if not cached_positions:
                print("No open positions found")
                return 0
            
            # Copy cached positions to local storage (preserve existing interface)
            self.positions = cached_positions.copy()
            loaded_count = len(self.positions)
            
            print(f"Loaded {loaded_count} cached positions{account_display}")
            return loaded_count
            
        except Exception as e:
            print(f"Error loading positions: {e}")
            return 0
            
    def load_long_positions_original(self) -> int:
        """FALLBACK: Original position loading method (kept for safety)"""
        try:
            account_display = f" for account ...{self.account_number[-4:]}" if self.account_number else ""
            print(f"Fetching positions from Robinhood{account_display} (FALLBACK)...")
            
            # Get open option positions for this specific account
            positions = r.get_open_option_positions(account_number=self.account_number)
            
            if not positions:
                print("No open positions found")
                return 0
            
            loaded_count = 0
            
            for position in positions:
                try:
                    
                    # Skip if not a long position (we only want debit positions)
                    if position.get('type') != 'long':
                        continue
                    
                    # Get option instrument details
                    # Try option field first, then instrument field
                    instrument_url = position.get('option') or position.get('instrument')
                    option_id = position.get('option_id')
                    
                    if not instrument_url and not option_id:
                        print(f"No instrument URL or option_id found")
                        continue
                    
                    # Extract option_id from URL if we don't have it directly
                    if not option_id and instrument_url:
                        option_id = instrument_url.split('/')[-2]
                    instrument_data = r.get_option_instrument_data_by_id(option_id)
                    
                    if not instrument_data:
                        continue
                    
                    # Extract position details
                    symbol = instrument_data.get('chain_symbol', '')
                    strike_price = float(instrument_data.get('strike_price', 0))
                    option_type = instrument_data.get('type', '').lower()
                    expiration_date = instrument_data.get('expiration_date', '')
                    quantity = int(float(position.get('quantity', 0)))
                    
                    # Get the net premium paid per contract (this is the average_price field)
                    premium_per_contract = float(position.get('average_price', 0))
                    
                    # For options, average_price is the premium per contract in dollars
                    # Total cost = average_price * quantity (no need to multiply by 100)
                    total_cost = premium_per_contract * quantity
                    
                    # Use the option_id we already extracted or get it from URL  
                    if not option_id and instrument_url:
                        option_id = instrument_url.split('/')[-2]
                    
                    # Get current market data
                    try:
                        market_data = r.get_option_market_data_by_id(option_id)
                        
                        if market_data:
                            # Check if it's a list or dict
                            if isinstance(market_data, list) and len(market_data) > 0:
                                market_info = market_data[0]
                            else:
                                market_info = market_data
                            current_price = float(market_info.get('adjusted_mark_price', 0))
                        else:
                            current_price = 0.0
                            
                    except Exception as e:
                        current_price = 0.0
                    
                    # Create position object
                    position_key = f"{symbol}_{expiration_date}_{strike_price}"
                    long_position = LongPosition(
                        symbol=symbol,
                        strike_price=strike_price,
                        option_type=option_type,
                        expiration_date=expiration_date,
                        quantity=quantity,
                        open_premium=total_cost,
                        current_price=current_price,
                        option_ids=[option_id]
                    )
                    
                    # Calculate P&L
                    self.calculate_pnl(long_position)
                    
                    self.positions[position_key] = long_position
                    print(f"  {symbol} {strike_price}{option_type.upper()} {expiration_date} - Paid: ${total_cost:.2f}")
                    
                    loaded_count += 1
                    
                except Exception as e:
                    print(f"Error processing position: {e}")
                    continue
            
            print(f"Loaded {loaded_count} long positions from Robinhood:")
            return loaded_count
            
        except Exception as e:
            print(f"Error loading positions: {e}")
            return 0
    
    def calculate_pnl(self, position: LongPosition) -> None:
        """Delegate P&L calculation to PositionManager"""
        position_manager.calculate_pnl(position)
    
    def _update_current_price(self, position: LongPosition) -> None:
        """Deprecated: PositionManager handles price updates"""
        position_manager.calculate_pnl(position)
    
    def update_position_prices(self) -> None:
        """Delegate bulk price refresh to PositionManager"""
        if self.account_number:
            position_manager.refresh_prices(self.account_number)
    
    def check_trailing_stops(self) -> None:
        """Update prices and evaluate trailing stops via PositionManager"""
        if not self.account_number:
            return
        if self.is_market_hours():
            position_manager.refresh_prices(self.account_number)
            try:
                position_manager.check_trailing_stops(self.account_number)
            except Exception:
                pass
    
    def is_market_hours(self) -> bool:
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
    
    def should_close_position(self, position: LongPosition) -> tuple[bool, str]:
        """Check if a position should be closed based on risk rules"""
        # Stop loss check
        if position.pnl_percent <= -self.stop_loss_percent:
            return True, f"Stop Loss: {position.pnl_percent:.1f}%"
        
        # Take profit check
        if position.pnl_percent >= self.take_profit_percent:
            return True, f"Take Profit: {position.pnl_percent:.1f}%"
        
        return False, ""
    
    # simulate_close_position removed (simulation no longer supported)
