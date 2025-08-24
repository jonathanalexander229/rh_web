#!/usr/bin/env python3
"""
High-Frequency Risk Manager for Options Trading
Monitors positions every second with strategic API usage to avoid rate limits
"""

import time
import datetime
import threading
from typing import Dict, List, Optional
import robin_stocks.robinhood as r
from database import OptionsDatabase
from dataclasses import dataclass, field
import json

@dataclass
class CachedPosition:
    """Cached position data for high-frequency monitoring"""
    symbol: str
    quantity: int
    option_type: str
    strike_price: float
    expiration_date: str
    strategy: str
    direction: str
    open_price: float
    open_premium: float
    current_price: float = 0.0
    current_premium: float = 0.0
    last_price_update: datetime.datetime = field(default_factory=datetime.datetime.now)
    pnl: float = 0.0
    pnl_percent: float = 0.0
    option_ids: List[str] = field(default_factory=list)

class HighFrequencyRiskManager:
    def __init__(self, db_path: str = "options.db", debug_mode: bool = True):
        self.db = OptionsDatabase(db_path)
        self.debug_mode = debug_mode
        self.dry_run = True  # Start in dry-run mode
        
        # Cached data for high-frequency monitoring
        self.cached_positions: Dict[str, CachedPosition] = {}
        self.market_quotes: Dict[str, float] = {}  # symbol -> current price
        
        # Timing controls
        self.last_position_refresh = datetime.datetime.min
        self.last_price_update = datetime.datetime.min
        self.position_refresh_interval = 30  # seconds
        self.price_update_interval = 8      # seconds
        self.monitoring_interval = 1        # seconds
        
        # Risk thresholds
        self.stop_loss_percent = 0.50      # 50% stop loss
        self.profit_target_percent = 0.50   # 50% profit target
        self.emergency_close_dte = 1       # Close at 1 DTE
        
        # State tracking
        self.is_running = False
        self.active_orders: Dict[str, str] = {}  # position_key -> order_id
        
        # Threading
        self.monitor_thread = None
        self.price_thread = None
        
    def log(self, message: str, level: str = "INFO"):
        """Enhanced logging with timestamps"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {level}: {message}")
        
    def debug(self, message: str):
        """Debug logging"""
        if self.debug_mode:
            self.log(message, "DEBUG")
            
    def is_market_hours(self) -> bool:
        """Check if market is currently open"""
        now = datetime.datetime.now()
        # Simple check - 9:30 AM to 4:00 PM ET on weekdays
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        
        # Convert to market time (simplified - assumes ET)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now <= market_close
    
    def load_open_positions(self) -> bool:
        """Load open positions from database into cache"""
        try:
            positions = self.db.get_positions_by_status('open')
            self.cached_positions.clear()
            
            for pos in positions:
                position_key = f"{pos['symbol']}_{pos['expiration_date']}_{pos['strike_price']}"
                
                # Parse option_ids if available
                option_ids = []
                if 'option_ids' in pos and pos['option_ids']:
                    try:
                        option_ids = json.loads(pos['option_ids']) if isinstance(pos['option_ids'], str) else pos['option_ids']
                    except:
                        option_ids = []
                
                cached_pos = CachedPosition(
                    symbol=pos['symbol'],
                    quantity=pos['quantity'] or 0,
                    option_type=pos['option_type'] or '',
                    strike_price=float(pos['strike_price'] or 0),
                    expiration_date=pos['expiration_date'],
                    strategy=pos['strategy'] or '',
                    direction=pos['direction'] or '',
                    open_price=float(pos['open_price'] or 0),
                    open_premium=float(pos['open_premium'] or 0),
                    option_ids=option_ids
                )
                
                self.cached_positions[position_key] = cached_pos
                
            self.last_position_refresh = datetime.datetime.now()
            self.log(f"Loaded {len(self.cached_positions)} open positions into cache")
            return True
            
        except Exception as e:
            self.log(f"Error loading positions: {e}", "ERROR")
            return False
    
    def update_market_quotes(self) -> bool:
        """Update current market prices for underlying symbols"""
        try:
            symbols = list(set([pos.symbol for pos in self.cached_positions.values()]))
            if not symbols:
                return True
                
            self.debug(f"Fetching quotes for {len(symbols)} symbols: {symbols}")
            
            # Get current quotes from robin-stocks
            quotes = r.get_quotes(symbols)
            if not quotes:
                self.log("No quotes received from API", "WARNING")
                return False
                
            # Update market quotes cache
            for quote in quotes:
                if quote and 'symbol' in quote and 'last_trade_price' in quote:
                    symbol = quote['symbol']
                    price = float(quote['last_trade_price'] or 0)
                    self.market_quotes[symbol] = price
                    
            self.last_price_update = datetime.datetime.now()
            self.debug(f"Updated quotes: {self.market_quotes}")
            return True
            
        except Exception as e:
            self.log(f"Error updating market quotes: {e}", "WARNING")
            return False
    
    def calculate_position_pnl(self, position: CachedPosition) -> None:
        """Calculate current P&L for a position using cached market data"""
        try:
            # Get current underlying price
            current_underlying = self.market_quotes.get(position.symbol, 0)
            if current_underlying == 0:
                return
                
            # Simplified P&L calculation (would need more sophisticated options pricing)
            # This is a basic approximation - in production would use Black-Scholes or similar
            
            if position.direction == 'debit':  # Long positions
                # Rough estimate: if underlying moved favorably, position gained value
                if position.option_type.lower() == 'call':
                    price_change = current_underlying - position.strike_price
                else:  # put
                    price_change = position.strike_price - current_underlying
                    
                # Very simplified - assume $0.50 per $1 underlying move
                estimated_current_premium = position.open_premium + (price_change * 0.5 * position.quantity)
                position.pnl = estimated_current_premium - position.open_premium
                
            else:  # Credit positions (short)
                # For short positions, we want the premium to decay
                # Simplified: assume time decay helps short positions
                estimated_current_premium = position.open_premium * 0.8  # Rough time decay
                position.pnl = position.open_premium - estimated_current_premium
                
            # Calculate percentage
            if position.open_premium != 0:
                position.pnl_percent = (position.pnl / abs(position.open_premium)) * 100
            else:
                position.pnl_percent = 0
                
        except Exception as e:
            self.debug(f"Error calculating P&L for {position.symbol}: {e}")
    
    def check_risk_rules(self, position: CachedPosition) -> bool:
        """Check if position violates risk rules and needs to be closed"""
        try:
            # Stop loss check
            if position.pnl_percent <= -self.stop_loss_percent * 100:
                self.log(f"STOP LOSS triggered for {position.symbol}: {position.pnl_percent:.1f}%")
                return True
                
            # Profit target check (mainly for short positions)
            if position.direction == 'credit' and position.pnl_percent >= self.profit_target_percent * 100:
                self.log(f"PROFIT TARGET hit for {position.symbol}: {position.pnl_percent:.1f}%")
                return True
                
            # Days to expiration check
            if position.expiration_date:
                try:
                    exp_date = datetime.datetime.strptime(position.expiration_date, '%Y-%m-%d')
                    dte = (exp_date - datetime.datetime.now()).days
                    if dte <= self.emergency_close_dte:
                        self.log(f"EMERGENCY CLOSE triggered for {position.symbol}: {dte} DTE")
                        return True
                except:
                    pass
                    
            return False
            
        except Exception as e:
            self.log(f"Error checking risk rules for {position.symbol}: {e}", "ERROR")
            return False
    
    def close_position(self, position: CachedPosition) -> bool:
        """Close a position with limit order (DRY RUN MODE)"""
        try:
            position_key = f"{position.symbol}_{position.expiration_date}_{position.strike_price}"
            
            if self.dry_run:
                self.log(f"DRY RUN: Would close position {position.symbol} {position.strike_price} {position.option_type} {position.expiration_date}")
                self.log(f"  Strategy: {position.strategy}, Direction: {position.direction}")  
                self.log(f"  Current P&L: ${position.pnl:.2f} ({position.pnl_percent:.1f}%)")
                return True
            
            # In live mode, would place actual order here
            self.log(f"LIVE MODE: Placing close order for {position.symbol}")
            # TODO: Implement actual order placement with robin-stocks
            
            return True
            
        except Exception as e:
            self.log(f"Error closing position {position.symbol}: {e}", "ERROR")
            return False
    
    def monitor_positions_once(self) -> None:
        """Single iteration of position monitoring"""
        try:
            current_time = datetime.datetime.now()
            
            # Check if we need to refresh positions from database
            if (current_time - self.last_position_refresh).seconds >= self.position_refresh_interval:
                self.debug("Refreshing positions from database...")
                self.load_open_positions()
            
            # Check if we need to update market prices
            if (current_time - self.last_price_update).seconds >= self.price_update_interval:
                self.debug("Updating market quotes...")
                self.update_market_quotes()
            
            # Monitor each position (using cached data - very fast)
            positions_at_risk = 0
            for position_key, position in self.cached_positions.items():
                # Calculate current P&L
                self.calculate_position_pnl(position)
                
                # Check risk rules
                if self.check_risk_rules(position):
                    positions_at_risk += 1
                    if position_key not in self.active_orders:
                        self.close_position(position)
                        self.active_orders[position_key] = f"order_{int(time.time())}"
            
            # Debug output every 10 seconds
            if int(time.time()) % 10 == 0:
                self.debug(f"Monitoring {len(self.cached_positions)} positions, {positions_at_risk} at risk, Market: {self.is_market_hours()}")
                
                # Print position summary
                for pos_key, pos in self.cached_positions.items():
                    underlying_price = self.market_quotes.get(pos.symbol, 0)
                    self.debug(f"  {pos.symbol} {pos.strike_price}C {pos.expiration_date}: P&L ${pos.pnl:.2f} ({pos.pnl_percent:.1f}%) | Underlying: ${underlying_price:.2f}")
                    
        except Exception as e:
            self.log(f"Error in monitoring iteration: {e}", "ERROR")
    
    def start_monitoring(self) -> None:
        """Start the high-frequency monitoring system"""
        self.log("Starting High-Frequency Risk Manager...")
        self.log(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE TRADING'}")
        self.log(f"Debug: {'ON' if self.debug_mode else 'OFF'}")
        
        # Initial setup
        if not self.load_open_positions():
            self.log("Failed to load positions. Exiting.", "ERROR")
            return
            
        if len(self.cached_positions) == 0:
            self.log("No open positions found. Nothing to monitor.")
            return
        
        self.is_running = True
        
        # Main monitoring loop
        try:
            while self.is_running:
                if self.is_market_hours():
                    self.monitor_positions_once()
                    time.sleep(self.monitoring_interval)
                else:
                    self.debug("Market closed. Sleeping for 60 seconds...")
                    time.sleep(60)
                    
        except KeyboardInterrupt:
            self.log("Received interrupt signal. Shutting down...")
        except Exception as e:
            self.log(f"Unexpected error in main loop: {e}", "ERROR")
        finally:
            self.is_running = False
            self.log("Risk Manager stopped.")
    
    def stop_monitoring(self) -> None:
        """Stop the monitoring system"""
        self.is_running = False

def main():
    """Main entry point"""
    print("High-Frequency Options Risk Manager")
    print("===================================")
    
    # Create risk manager instance
    risk_manager = HighFrequencyRiskManager(debug_mode=True)
    
    try:
        # Start monitoring
        risk_manager.start_monitoring()
    except KeyboardInterrupt:
        print("\nShutting down risk manager...")
        risk_manager.stop_monitoring()

if __name__ == "__main__":
    main()