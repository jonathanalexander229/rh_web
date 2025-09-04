#!/usr/bin/env python3
"""
Position Manager - MVP
Centralized position data management and trading logic
"""

import robin_stocks.robinhood as r
import threading
import logging
from typing import Dict, Optional, List
from position_types import LongPosition

class PositionManager:
    """Centralized position management for multi-account system"""
    
    def __init__(self):
        # Simple position storage by account
        self._positions: Dict[str, Dict[str, LongPosition]] = {}  # {account_number: {position_key: position}}
        self._lock = threading.RLock()  # Basic thread safety
        self.logger = logging.getLogger('position_manager')
    
    def load_positions_for_account(self, account_number: str) -> int:
        """Load positions for a specific account from API"""
        with self._lock:
            try:
                account_display = f"...{account_number[-4:]}"
                self.logger.info(f"Loading positions for account {account_display}")
                
                # Get positions from API
                positions = r.get_open_option_positions(account_number=account_number)
                
                if not positions:
                    self.logger.info(f"No positions found for account {account_display}")
                    self._positions[account_number] = {}
                    return 0
                
                # Process positions (same logic as BaseRiskManager)
                account_positions = {}
                loaded_count = 0
                
                for position in positions:
                    try:
                        # Skip if not a long position (we only want debit positions)
                        if position.get('type') != 'long':
                            continue
                        
                        # Get option instrument details
                        instrument_url = position.get('option') or position.get('instrument')
                        option_id = position.get('option_id')
                        
                        if not instrument_url and not option_id:
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
                        option_type = instrument_data.get('type', '')
                        expiration_date = instrument_data.get('expiration_date', '')
                        quantity = int(float(position.get('quantity', 0)))
                        
                        if quantity <= 0:
                            continue
                        
                        # Calculate premium paid
                        average_price = float(position.get('average_price', 0))
                        open_premium = average_price * quantity * 100
                        
                        # Create position key
                        position_key = f"{symbol}_{expiration_date}_{strike_price}_{option_type}"
                        
                        # Create LongPosition object
                        long_position = LongPosition(
                            symbol=symbol,
                            strike_price=strike_price,
                            option_type=option_type,
                            expiration_date=expiration_date,
                            quantity=quantity,
                            open_premium=open_premium,
                            option_ids=[option_id]
                        )
                        
                        account_positions[position_key] = long_position
                        loaded_count += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error processing position: {e}")
                        continue
                
                # Store positions for this account
                self._positions[account_number] = account_positions
                self.logger.info(f"Loaded {loaded_count} positions for account {account_display}")
                return loaded_count
                
            except Exception as e:
                self.logger.error(f"Error loading positions for account {account_number}: {e}")
                self._positions[account_number] = {}
                return 0
    
    def get_positions_for_account(self, account_number: str) -> Dict[str, LongPosition]:
        """Get cached positions for a specific account"""
        with self._lock:
            return self._positions.get(account_number, {}).copy()
    
    def get_position(self, account_number: str, symbol: str) -> Optional[LongPosition]:
        """Get a specific position by symbol"""
        with self._lock:
            account_positions = self._positions.get(account_number, {})
            for position_key, position in account_positions.items():
                if position.symbol == symbol:
                    return position
            return None
    
    def refresh_prices(self, account_number: str) -> None:
        """Update current prices for all positions in an account"""
        with self._lock:
            account_positions = self._positions.get(account_number, {})
            for position in account_positions.values():
                self.calculate_pnl(position)
    
    def calculate_pnl(self, position: LongPosition) -> None:
        """Calculate current P&L for a position (same logic as BaseRiskManager)"""
        try:
            if not position.option_ids:
                return
            
            option_id = position.option_ids[0]
            market_data = r.get_option_market_data_by_id(option_id)
            
            if market_data and len(market_data) > 0:
                bid_price = float(market_data[0].get('bid_price', 0))
                ask_price = float(market_data[0].get('ask_price', 0))
                
                if bid_price > 0 and ask_price > 0:
                    current_price = (bid_price + ask_price) / 2
                    position.current_price = current_price
                    
                    current_value = current_price * position.quantity * 100
                    position.pnl = current_value - position.open_premium
                    
                    if position.open_premium > 0:
                        position.pnl_percent = (position.pnl / position.open_premium) * 100
                        
        except Exception as e:
            self.logger.error(f"Error calculating P&L for {position.symbol}: {e}")
    
    def enable_trailing_stop(self, account_number: str, symbol: str, percent: float) -> bool:
        """Enable trailing stop for a position"""
        with self._lock:
            position = self.get_position(account_number, symbol)
            if not position:
                return False
            
            # Update current price first
            self.calculate_pnl(position)
            
            if position.current_price <= 0:
                return False
            
            # Enable trailing stop
            trail_stop_data = {
                'enabled': True,
                'percent': percent,
                'highest_price': position.current_price,
                'trigger_price': position.current_price * (1 - percent / 100),
                'triggered': False,
                'order_submitted': False,
                'last_order_id': None
            }
            
            # Store trailing stop data on position
            setattr(position, 'trail_stop_data', trail_stop_data)
            
            self.logger.info(f"Enabled trailing stop for {symbol}: {percent}% at ${position.current_price:.3f}")
            return True
    
    def check_trailing_stops(self, account_number: str) -> None:
        """Check and update trailing stops for all positions in account"""
        with self._lock:
            account_positions = self._positions.get(account_number, {})
            
            for position in account_positions.values():
                trail_stop_data = getattr(position, 'trail_stop_data', {})
                
                if trail_stop_data.get('enabled', False) and position.current_price > 0:
                    # Update market data
                    self.calculate_pnl(position)
                    
                    # Check if price increased (ratchet up only)
                    if position.current_price > trail_stop_data['highest_price']:
                        trail_stop_data['highest_price'] = position.current_price
                        trail_stop_data['trigger_price'] = position.current_price * (1 - trail_stop_data['percent'] / 100)
                        self.logger.info(f"Trailing stop updated for {position.symbol}: New high ${position.current_price:.3f}")
                    
                    # Check if triggered
                    if position.current_price <= trail_stop_data['trigger_price'] and not trail_stop_data.get('triggered', False):
                        trail_stop_data['triggered'] = True
                        self.logger.warning(f"Trailing stop TRIGGERED for {position.symbol}! Price ${position.current_price:.3f} <= Trigger ${trail_stop_data['trigger_price']:.3f}")
    
    def set_take_profit(self, account_number: str, symbol: str, percent: float) -> bool:
        """Set take profit for a position"""
        with self._lock:
            position = self.get_position(account_number, symbol)
            if not position:
                return False
            
            # Update current price first
            self.calculate_pnl(position)
            
            if position.current_price <= 0:
                return False
            
            # Set take profit
            take_profit_data = {
                'enabled': True,
                'percent': percent,
                'trigger_price': position.current_price * (1 + percent / 100),
                'triggered': False
            }
            
            # Store take profit data on position
            setattr(position, 'take_profit_data', take_profit_data)
            
            self.logger.info(f"Set take profit for {symbol}: {percent}% at ${take_profit_data['trigger_price']:.3f}")
            return True

# Global instance
position_manager = PositionManager()