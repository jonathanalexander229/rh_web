#!/usr/bin/env python3
"""
Multi-Account Risk Manager
Orchestrates multiple isolated BaseRiskManager instances for different Robinhood accounts
"""

import json
import os
import robin_stocks.robinhood as r
from shared.account_detector import AccountDetector
from risk_manager.base_risk_manager import BaseRiskManager
from shared.position_manager import position_manager
from shared.risk_config_store import risk_config_store
from shared.gex_calculator import gex_calculator
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from datetime import datetime
import pytz


def _load_rm_config() -> dict:
    """Load risk_manager section from config.json at project root."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    try:
        with open(config_path) as f:
            return json.load(f).get('risk_manager', {})
    except Exception:
        return {}


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
        self._last_intelligence_refresh = 0.0
        self._last_fill_check = 0.0
        self._last_gex_refresh = 0.0

        # Load timing config
        rm_cfg = _load_rm_config()
        self.price_refresh_interval = float(rm_cfg.get('price_refresh_interval_seconds', 1))
        self.greeks_refresh_interval = float(rm_cfg.get('greeks_refresh_interval_seconds', 15))
        self.reconciliation_interval = float(rm_cfg.get('reconciliation_interval_seconds', 60))
        self.reconciliation_interval_after_hours = float(rm_cfg.get('reconciliation_interval_after_hours_seconds', 300))
        self.fill_check_interval = float(rm_cfg.get('order_fill_check_interval_seconds', 30))
        self.auto_stop_loss_enabled = bool(rm_cfg.get('auto_stop_loss_enabled', False))
        self.auto_stop_loss_threshold_pct = float(rm_cfg.get('auto_stop_loss_threshold_pct', 50))
        self.gex_refresh_interval = float(rm_cfg.get('gex_refresh_interval_seconds', 300))
        self.gex_expirations = int(rm_cfg.get('gex_expirations_to_fetch', 3))

        # Propagate Greeks interval to position_manager
        position_manager.set_greeks_refresh_interval(self.greeks_refresh_interval)

        # Non-blocking I/O executor
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix=f"rm_worker_{account_number[-4:]}"
        )
        self._check_in_progress = threading.Event()

        # Saved configs from disk (loaded once at startup)
        self._saved_configs: Dict[str, dict] = {}

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
        self._executor.shutdown(wait=False)

    def monitoring_loop(self):
        """Main monitoring loop - runs independently per account"""
        et_tz = pytz.timezone('US/Eastern')

        # Load persisted risk configs from disk (for app-restart recovery)
        self._saved_configs = risk_config_store.load(self.account_number)
        self.logger.info(
            f"Loaded {len(self._saved_configs)} saved risk configs for account ...{self.account_number[-4:]}"
        )

        # Load positions once at start of monitoring (auth already done globally)
        self.logger.info(f"Loading positions for account {self.account_info['display_name']}")
        position_count = self.risk_manager.load_long_positions()

        # Apply any saved configs to freshly loaded positions
        self._apply_saved_configs_to_positions(self.risk_manager.positions)

        # Signal that initial loading is complete
        self.initial_loading_complete = True

        if position_count == 0:
            self.logger.info(
                f"No positions found for account {self.account_info['display_name']}, stopping monitoring"
            )
            return

        self.logger.info(f"Monitoring {position_count} positions for account {self.account_info['display_name']}")

        # Populate GEX cache immediately so it's available on first page load
        try:
            underlying_prices = {
                pos.symbol: pos.underlying_price
                for pos in self.risk_manager.positions.values()
                if hasattr(pos, 'underlying_price') and pos.underlying_price
            }
            for symbol, spot in underlying_prices.items():
                gex_calculator.refresh(symbol, spot, self.gex_expirations)
            self._last_gex_refresh = time.time()
        except Exception as e:
            self.logger.error(f"Initial GEX refresh error: {e}")

        while not self.stop_event.is_set():
            try:
                now_et = datetime.now(et_tz)
                current_time = now_et.time()

                market_start = current_time.replace(hour=9, minute=30, second=0)
                market_end = current_time.replace(hour=16, minute=0, second=0)
                is_market_hours = market_start <= current_time <= market_end
                is_weekday = now_et.weekday() < 5

                # Periodic reconcile of positions
                reconcile_interval = (
                    self.reconciliation_interval if (is_market_hours and is_weekday)
                    else self.reconciliation_interval_after_hours
                )
                now_ts = time.time()
                if now_ts - self._last_reconcile >= reconcile_interval:
                    try:
                        self._reconcile_positions()
                        self._last_reconcile = now_ts
                    except Exception as e:
                        self.logger.error(f"Reconcile error for account {self.account_number[-4:]}: {e}")

                # Refresh symbol intelligence every 30 minutes
                if now_ts - self._last_intelligence_refresh >= 1800:
                    try:
                        symbols = list({pos.symbol for pos in self.risk_manager.positions.values()})
                        if symbols:
                            underlying_prices = {
                                pos.symbol: pos.underlying_price
                                for pos in self.risk_manager.positions.values()
                                if hasattr(pos, 'underlying_price') and pos.underlying_price
                            }
                            position_manager.refresh_symbol_intelligence(symbols, underlying_prices)
                        self._last_intelligence_refresh = now_ts
                    except Exception as e:
                        self.logger.error(f"Intelligence refresh error: {e}")

                # Refresh GEX at configured interval (default 5 minutes)
                if now_ts - self._last_gex_refresh >= self.gex_refresh_interval:
                    try:
                        underlying_prices = {
                            pos.symbol: pos.underlying_price
                            for pos in self.risk_manager.positions.values()
                            if hasattr(pos, 'underlying_price') and pos.underlying_price
                        }
                        for symbol, spot in underlying_prices.items():
                            gex_calculator.refresh(symbol, spot, self.gex_expirations)
                        self._last_gex_refresh = now_ts
                    except Exception as e:
                        self.logger.error(f"GEX refresh error: {e}")

                if is_market_hours and is_weekday:
                    # Dispatch work to executor; skip if previous check still running
                    if not self._check_in_progress.is_set():
                        self._executor.submit(self._refresh_and_check)
                    time.sleep(self.price_refresh_interval)
                else:
                    time.sleep(60)

            except Exception as e:
                self.logger.error(f"Error in monitoring loop for account {self.account_number[-4:]}: {e}")
                time.sleep(5)

    # -------------------- Worker (runs in executor thread) --------------------

    def _refresh_and_check(self):
        """Price refresh + all risk checks. Runs in executor thread so the main loop never blocks."""
        if self._check_in_progress.is_set():
            return
        self._check_in_progress.set()
        try:
            # Refresh prices and run trailing stop auto-execution
            self.risk_manager.check_trailing_stops()
            # Take profit auto-execution
            position_manager.check_take_profits(self.account_number)
            # Auto stop loss — only fires when enabled in config.json
            if self.auto_stop_loss_enabled:
                self._check_stop_loss()
            # Periodic fill check
            now_ts = time.time()
            if now_ts - self._last_fill_check >= self.fill_check_interval:
                self._check_order_fills()
                self._last_fill_check = now_ts
        except Exception as e:
            self.logger.error(f"Error in _refresh_and_check for {self.account_number[-4:]}: {e}")
        finally:
            self._check_in_progress.clear()

    # Seconds to wait between stop-loss submission attempts after a failure
    _STOP_LOSS_RETRY_COOLDOWN = 60.0

    def _check_stop_loss(self):
        """Auto-submit close when the configured loss threshold is breached.
        Only runs when auto_stop_loss_enabled=true in config.json.
        Uses auto_stop_loss_threshold_pct from config, not the display-only BaseRiskManager value.
        """
        if not position_manager.is_live:
            return
        now = time.time()
        positions = self.risk_manager.positions or {}
        for pos_key, position in list(positions.items()):
            # Skip if any close order is already in flight for this position
            if getattr(position, '_stop_loss_submitted', False):
                continue
            trail = getattr(position, 'trail_stop_data', {})
            if trail.get('order_submitted'):
                continue
            tp = getattr(position, 'take_profit_data', {})
            if tp.get('order_submitted'):
                continue
            # Skip positions with no current price — likely closed/expired at broker
            if not position.current_price or position.current_price <= 0:
                continue
            # Skip near-worthless positions — a sub-penny limit price will be rejected
            limit_price = max(round(position.current_price * 0.95, 2), 0.01)
            if position.current_price < 0.02:
                self.logger.debug(
                    f"Skipping auto stop loss for {position.symbol} — mark ${position.current_price:.3f} too low to submit"
                )
                continue
            # Cooldown: don't hammer Robinhood after a failed/rate-limited attempt
            last_attempt = getattr(position, '_stop_loss_last_attempt', 0.0)
            if now - last_attempt < self._STOP_LOSS_RETRY_COOLDOWN:
                continue
            # Use config threshold, not the display-only risk_manager.stop_loss_percent
            if position.pnl_percent > -self.auto_stop_loss_threshold_pct:
                continue
            reason = f"Auto Stop Loss: {position.pnl_percent:.1f}% (threshold -{self.auto_stop_loss_threshold_pct}%)"
            # Stamp attempt time BEFORE submitting so any failure path still applies the cooldown
            position._stop_loss_last_attempt = now
            result = position_manager.submit_close_order(self.account_number, position, limit_price)
            if result.get('success'):
                position._stop_loss_submitted = True
                position._stop_loss_order_id = result.get('order_id')
                self.logger.warning(
                    f"AUTO STOP LOSS: {position.symbol} reason={reason} "
                    f"limit=${limit_price:.2f}"
                )
            else:
                self.logger.error(
                    f"AUTO STOP LOSS failed for {position.symbol}: {result.get('error')} "
                    f"(will retry in {int(self._STOP_LOSS_RETRY_COOLDOWN)}s)"
                )

    def _check_order_fills(self):
        """Poll open orders and clear/remove positions whose orders have been filled or cancelled."""
        result = position_manager.list_open_orders()
        if not result.get('success'):
            self.logger.debug(f"list_open_orders failed: {result.get('error')}")
            return

        open_ids = {o.get('id') for o in result.get('orders', []) if o.get('id')}
        positions = self.risk_manager.positions or {}

        for pos_key, position in list(positions.items()):
            self._check_trail_stop_fill(pos_key, position, open_ids)
            self._check_take_profit_fill(pos_key, position, open_ids)
            self._check_stop_loss_fill(pos_key, position, open_ids)

    def _check_trail_stop_fill(self, pos_key: str, position, open_ids: set):
        trail = getattr(position, 'trail_stop_data', {})
        order_id = trail.get('order_id')
        if not order_id or order_id in open_ids:
            return
        info = position_manager.get_order_info(order_id)
        if not info.get('success'):
            return
        state = (info.get('details') or {}).get('state', '')
        if state in ('filled', 'partially_filled'):
            self.logger.info(f"Trail stop order FILLED for {position.symbol} — removing from monitoring")
            self._remove_position(pos_key)
        else:
            self.logger.warning(
                f"Trail stop order {order_id} for {position.symbol} "
                f"is {state!r} — clearing for resubmit"
            )
            trail['order_id'] = None
            trail['order_submitted'] = False
            trail['submitted_stop_price'] = 0.0

    def _check_take_profit_fill(self, pos_key: str, position, open_ids: set):
        tp = getattr(position, 'take_profit_data', {})
        order_id = tp.get('order_id')
        if not order_id or order_id in open_ids:
            return
        info = position_manager.get_order_info(order_id)
        if not info.get('success'):
            return
        state = (info.get('details') or {}).get('state', '')
        if state in ('filled', 'partially_filled'):
            self.logger.info(f"Take profit order FILLED for {position.symbol} — removing from monitoring")
            self._remove_position(pos_key)
        else:
            self.logger.warning(
                f"Take profit order {order_id} for {position.symbol} "
                f"is {state!r} — clearing for resubmit"
            )
            tp['order_submitted'] = False
            tp['order_id'] = None

    def _check_stop_loss_fill(self, pos_key: str, position, open_ids: set):
        order_id = getattr(position, '_stop_loss_order_id', None)
        if not order_id or order_id in open_ids:
            return
        info = position_manager.get_order_info(order_id)
        if not info.get('success'):
            return
        state = (info.get('details') or {}).get('state', '')
        if state in ('filled', 'partially_filled'):
            self.logger.info(f"Stop loss order FILLED for {position.symbol} — removing from monitoring")
            self._remove_position(pos_key)
        else:
            self.logger.warning(
                f"Stop loss order {order_id} for {position.symbol} "
                f"is {state!r} — clearing for resubmit"
            )
            position._stop_loss_submitted = False
            position._stop_loss_order_id = None

    def _remove_position(self, pos_key: str):
        """Remove a filled position from monitoring and clear its saved config."""
        positions = self.risk_manager.positions or {}
        pos = positions.pop(pos_key, None)
        if pos:
            self.logger.info(f"Position {pos.symbol} removed from monitoring (order filled)")
            risk_config_store.clear_position(self.account_number, pos_key)

    # -------------------- Reconcile helpers --------------------

    def _reconcile_positions(self):
        """Reload positions from Robinhood, merge with in-memory configs."""
        position_manager.load_positions_for_account(self.account_number)
        latest = position_manager.get_positions_for_account(self.account_number)
        merged = {}
        old_positions = self.risk_manager.positions or {}
        for key, new_pos in latest.items():
            old_pos = old_positions.get(key)
            if old_pos:
                # Preserve in-memory risk configs and runtime flags
                for attr in ('trail_stop_data', 'take_profit_data'):
                    if hasattr(old_pos, attr):
                        setattr(new_pos, attr, getattr(old_pos, attr))
                for attr in ('_stop_loss_submitted', '_stop_loss_order_id'):
                    if hasattr(old_pos, attr):
                        setattr(new_pos, attr, getattr(old_pos, attr))
            else:
                # New position (e.g. app restart) — restore from disk
                self._apply_saved_config(new_pos, key)
            merged[key] = new_pos
        self.risk_manager.positions = merged

    def _apply_saved_configs_to_positions(self, positions: dict):
        """Apply disk-saved configs to a freshly loaded positions dict (startup only)."""
        for key, pos in positions.items():
            if not hasattr(pos, 'trail_stop_data') and not hasattr(pos, 'take_profit_data'):
                self._apply_saved_config(pos, key)

    def _apply_saved_config(self, position, pos_key: str):
        """Restore trail stop / take profit from the disk-saved config for this position."""
        saved = self._saved_configs.get(pos_key, {})
        if not saved:
            return
        if 'trail_stop' in saved:
            ts = saved['trail_stop']
            position.trail_stop_data = {
                'enabled': ts.get('enabled', False),
                'percent': ts.get('percent', 20.0),
                'highest_price': ts.get('highest_price', position.current_price or 0),
                'trigger_price': 0.0,   # recomputed on first check_trailing_stops call
                'triggered': False,
                'order_submitted': False,
                'order_id': None,
                'submitted_stop_price': 0.0,
                'last_update_time': 0.0,
                'last_order_id': None
            }
            self.logger.info(f"Restored trail stop config for {pos_key} from disk")
        if 'take_profit' in saved:
            tp = saved['take_profit']
            position.take_profit_data = {
                'enabled': tp.get('enabled', False),
                'percent': tp.get('percent', 50.0),
                'target_pnl': tp.get('percent', 50.0),
                'triggered': False,
                'order_submitted': False,
                'order_id': None
            }
            self.logger.info(f"Restored take profit config for {pos_key} from disk")


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

            time.sleep(0.5)

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
