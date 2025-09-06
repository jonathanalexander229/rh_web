#!/usr/bin/env python3
"""
Multi-Account Risk Manager
Orchestrates multiple isolated BaseRiskManager instances for different Robinhood accounts
"""

import robin_stocks.robinhood as r
from account_detector import AccountDetector
from base_risk_manager import BaseRiskManager
from position_manager import position_manager
import threading
import time
import logging
from typing import Dict, Optional
from datetime import datetime
import pytz

class AccountMonitoringThread:
    """Handles monitoring for a single account"""
    
    def __init__(self, account_number: str, account_info: Dict, stop_loss_percent: float = 50.0):
        self.account_number = account_number
        self.account_info = account_info
        self.risk_manager = BaseRiskManager(
            stop_loss_percent=stop_loss_percent,
            account_number=account_number
        )
        self.thread = None
        self.stop_event = threading.Event()
        self.initial_loading_complete = False
        self.logger = logging.getLogger(f'account_monitor_{account_number[-4:]}')
        self._last_reconcile = 0.0
        
    def start_monitoring(self):
        """Start the monitoring thread"""
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self.monitoring_loop,
                name=f"AccountMonitor-{self.account_number[-4:]}",
                daemon=True
            )
            self.thread.start()
            self.logger.info(f"Started monitoring for account {self.account_info['display_name']}")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=5)
            self.logger.info(f"Stopped monitoring for account {self.account_info['display_name']}")
    
    def monitoring_loop(self):
        """Main monitoring loop - runs independently per account"""
        et_tz = pytz.timezone('US/Eastern')
        
        # Load positions once at start of monitoring (auth already done globally)
        self.logger.info(f"Loading positions for account {self.account_info['display_name']}")
        position_count = self.risk_manager.load_long_positions()
        
        # Signal that initial loading is complete
        self.initial_loading_complete = True
        
        if position_count == 0:
            self.logger.info(f"No positions found for account {self.account_info['display_name']}, stopping monitoring")
            return
            
        self.logger.info(f"Monitoring {position_count} positions for account {self.account_info['display_name']}")
        
        while not self.stop_event.is_set():
            try:
                now_et = datetime.now(et_tz)
                current_time = now_et.time()
                
                # Market hours: 9:30 AM - 4:00 PM ET
                market_start = current_time.replace(hour=9, minute=30, second=0)
                market_end = current_time.replace(hour=16, minute=0, second=0)
                is_market_hours = market_start <= current_time <= market_end
                is_weekday = now_et.weekday() < 5  # Monday = 0, Sunday = 6
                
                # Periodic reconcile of positions to clear stale entries
                # More frequent during market hours, less frequent off-hours
                reconcile_interval = 60 if (is_market_hours and is_weekday) else 300
                now_ts = time.time()
                if now_ts - self._last_reconcile >= reconcile_interval:
                    try:
                        # Pull latest from Robinhood into PositionManager cache
                        position_manager.load_positions_for_account(self.account_number)
                        latest = position_manager.get_positions_for_account(self.account_number)
                        # Merge, preserving per-position configs
                        merged = {}
                        old_positions = self.risk_manager.positions or {}
                        for key, new_pos in latest.items():
                            old_pos = old_positions.get(key)
                            if old_pos:
                                if hasattr(old_pos, 'trail_stop_data'):
                                    setattr(new_pos, 'trail_stop_data', getattr(old_pos, 'trail_stop_data'))
                                if hasattr(old_pos, 'take_profit_data'):
                                    setattr(new_pos, 'take_profit_data', getattr(old_pos, 'take_profit_data'))
                            merged[key] = new_pos
                        self.risk_manager.positions = merged
                        self._last_reconcile = now_ts
                    except Exception as e:
                        self.logger.error(f"Reconcile error for account {self.account_number[-4:]}: {e}")

                if is_market_hours and is_weekday:
                    # High frequency updates during market hours only
                    self.risk_manager.check_trailing_stops()
                    time.sleep(1)  # 1-second updates during market hours
                else:
                    # Just check every minute if market has opened yet
                    time.sleep(60)  # 1-minute check when market is closed
                    
            except Exception as e:
                self.logger.error(f"Error in monitoring loop for account {self.account_number[-4:]}: {e}")
                time.sleep(5)  # Brief pause on error

class MultiAccountRiskManager:
    """Manages multiple isolated risk manager instances"""
    
    def __init__(self):
        self.logger = logging.getLogger('multi_account_manager')
        self.account_detector = AccountDetector()
        self.monitoring_threads: Dict[str, AccountMonitoringThread] = {}
        self._lock = threading.Lock()
    
    def initialize_accounts(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """Initialize and detect all available accounts"""
        try:
            accounts = self.account_detector.detect_accounts(force_refresh=force_refresh)
            self.logger.info(f"Initialized {len(accounts)} account(s)")
            return accounts
        except Exception as e:
            self.logger.error(f"Error initializing accounts: {e}")
            return {}
    
    def get_active_accounts(self) -> Dict[str, Dict]:
        """Get accounts that have positions or orders"""
        return self.account_detector.get_active_accounts()
    
    def start_account_monitoring(self, account_number: str, stop_loss_percent: float = 50.0):
        """Start monitoring for a specific account"""
        with self._lock:
            account_info = self.account_detector.get_account_info(account_number)
            if not account_info:
                self.logger.error(f"Account not found: {account_number[-4:]}")
                return False
            
            # Stop existing monitoring if running
            if account_number in self.monitoring_threads:
                self.monitoring_threads[account_number].stop_monitoring()
            
            # Create and start new monitoring thread
            monitor = AccountMonitoringThread(account_number, account_info, stop_loss_percent)
            monitor.start_monitoring()
            self.monitoring_threads[account_number] = monitor
            
            self.logger.info(f"Started monitoring for {account_info['display_name']}")
            return True
    
    def stop_account_monitoring(self, account_number: str):
        """Stop monitoring for a specific account"""
        with self._lock:
            if account_number in self.monitoring_threads:
                self.monitoring_threads[account_number].stop_monitoring()
                del self.monitoring_threads[account_number]
                self.logger.info(f"Stopped monitoring for account ...{account_number[-4:]}")
    
    def auto_start_active_accounts(self, stop_loss_percent: float = 50.0):
        """Automatically start monitoring for all accounts with positions/orders"""
        active_accounts = self.get_active_accounts()
        
        for account_prefix, account_info in active_accounts.items():
            # Pass full account number to monitoring to avoid using prefixes with APIs
            self.start_account_monitoring(account_info['number'], stop_loss_percent)
            
        self.logger.info(f"Auto-started monitoring for {len(active_accounts)} active account(s)")
        return len(active_accounts)
    
    def wait_for_initial_loading(self, timeout_seconds: int = 30):
        """Wait for all monitoring threads to complete their initial data loading"""
        import time
        
        self.logger.info("Waiting for all accounts to complete initial data loading...")
        print("Waiting for all accounts to complete initial data loading...")
        
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            all_loaded = True
            for account_number, monitor in self.monitoring_threads.items():
                if not monitor.initial_loading_complete:
                    all_loaded = False
                    break
            
            if all_loaded:
                self.logger.info("All accounts completed initial data loading")
                print("✅ All accounts completed initial data loading")
                return True
            
            time.sleep(0.5)  # Check every 500ms
        
        self.logger.warning(f"Timeout waiting for initial loading after {timeout_seconds}s")
        print(f"⚠️  Timeout waiting for initial loading after {timeout_seconds}s")
        return False
    
    def stop_all_monitoring(self):
        """Stop monitoring for all accounts"""
        with self._lock:
            for account_number in list(self.monitoring_threads.keys()):
                self.monitoring_threads[account_number].stop_monitoring()
            self.monitoring_threads.clear()
            self.logger.info("Stopped all account monitoring")
    
    def get_account_risk_manager(self, account_number: str) -> Optional[BaseRiskManager]:
        """Get the risk manager instance for a specific account"""
        if account_number in self.monitoring_threads:
            return self.monitoring_threads[account_number].risk_manager
        return None
    
    def get_monitoring_status(self) -> Dict[str, Dict]:
        """Get status of all monitored accounts"""
        status = {}
        for account_number, monitor in self.monitoring_threads.items():
            account_info = self.account_detector.get_account_info(account_number)
            is_alive = monitor.thread and monitor.thread.is_alive()
            
            status[account_number] = {
                'display_name': account_info['display_name'] if account_info else f"...{account_number[-4:]}",
                'monitoring_active': is_alive,
                'thread_name': monitor.thread.name if monitor.thread else None,
                'account_type': account_info['type'] if account_info else 'Unknown'
            }
        
        return status
    
    def list_accounts_summary(self) -> str:
        """Generate a summary of all accounts and their monitoring status"""
        accounts = self.account_detector.detect_accounts()
        if not accounts:
            return "No accounts detected"
        
        summary = f"Multi-Account Risk Manager Status ({len(accounts)} account(s)):\n"
        for account_number, info in accounts.items():
            monitoring_status = "🟢 Active" if account_number in self.monitoring_threads else "○ Inactive"
            has_activity = "✓" if self.account_detector.has_positions_or_orders(account_number) else "○"
            summary += f"  {has_activity} {info['display_name']} - {info['state']} - {monitoring_status}\n"
        
        return summary.strip()
