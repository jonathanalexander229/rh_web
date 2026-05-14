#!/usr/bin/env python3
"""
Position Manager - MVP
Centralized position data management and trading logic
"""

import robin_stocks.robinhood as r
import datetime
import time
import threading
import logging
from typing import Dict, Optional, List
from shared.position_types import LongPosition

class PositionManager:
    """Centralized position management for multi-account system"""

    def __init__(self):
        # Simple position storage by account
        self._positions: Dict[str, Dict[str, LongPosition]] = {}  # {account_number: {position_key: position}}
        self._lock = threading.RLock()  # Basic thread safety
        self.logger = logging.getLogger('position_manager')
        # Track submitted orders per account
        # {account_number: {order_id: {symbol, quantity, price, submit_time, order_type}}}
        self._tracked_orders: Dict[str, Dict[str, Dict]] = {}
        self._order_service = None
        self._risk_config_store = None
        # Symbol intelligence cache: {symbol: {next_earnings, news, fundamentals, last_fetched}}
        self._symbol_intelligence: Dict[str, dict] = {}
        # Live trading flag — must be set to True before auto-execution fires
        self.is_live: bool = False
        # Greeks refresh interval (seconds); configurable via set_greeks_refresh_interval()
        self._greeks_refresh_interval: float = 15.0

    def set_order_service(self, order_service) -> None:
        """Inject the order service dependency (live-only)."""
        self._order_service = order_service

    def set_live_mode(self, is_live: bool) -> None:
        """Enable or disable live order execution."""
        self.is_live = is_live
        self.logger.info(f"Live mode: {'ENABLED' if is_live else 'disabled'}")

    def set_risk_config_store(self, store) -> None:
        """Inject the risk config store for config persistence."""
        self._risk_config_store = store

    def set_greeks_refresh_interval(self, seconds: float) -> None:
        self._greeks_refresh_interval = float(seconds)

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
                        # Match BaseRiskManager logic: Robinhood provides average_price per contract in dollars
                        # and we treat total cost without multiplying by 100 here
                        average_price = float(position.get('average_price', 0))
                        open_premium = average_price * quantity

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

    def get_position_key(self, position: LongPosition) -> str:
        """Compute canonical position key from a LongPosition object."""
        return f"{position.symbol}_{position.expiration_date}_{position.strike_price}_{position.option_type}"

    def refresh_prices(self, account_number: str) -> None:
        """Update mark prices for all positions; throttle Greeks to configured interval."""
        with self._lock:
            account_positions = self._positions.get(account_number, {})
            for position in account_positions.values():
                self._refresh_mark_price(position)
                now = time.time()
                if now - position._last_greeks_refresh >= self._greeks_refresh_interval:
                    self._refresh_greeks(position)
                    position._last_greeks_refresh = now

    # -------------------- Price / Greeks helpers --------------------

    def _refresh_mark_price(self, position: LongPosition) -> None:
        """Fetch mark price, bid, ask and recompute P&L. Does not touch Greeks."""
        try:
            if not position.option_ids:
                return
            option_id = position.option_ids[0]
            market_data = r.get_option_market_data_by_id(option_id)
            if market_data:
                market_info = market_data[0] if isinstance(market_data, list) and market_data else market_data

                def _sf(val, default=0.0):
                    try:
                        return float(val) if val is not None else default
                    except (TypeError, ValueError):
                        return default

                new_price = _sf(market_info.get('adjusted_mark_price'))
                if new_price > 0:
                    position.current_price = new_price
                position.bid_price = _sf(market_info.get('bid_price'))
                position.ask_price = _sf(market_info.get('ask_price'))

            # Recompute P&L
            if position.current_price > 0:
                current_value = position.current_price * position.quantity * 100
                position.pnl = current_value - position.open_premium
                if position.open_premium > 0:
                    position.pnl_percent = (position.pnl / position.open_premium) * 100
            else:
                position.pnl = -position.open_premium
                position.pnl_percent = -100.0

        except Exception as e:
            self.logger.error(f"Error refreshing mark price for {position.symbol}: {e}")

    def _refresh_greeks(self, position: LongPosition) -> None:
        """Fetch Greeks, IV, underlying price, DTE, and moneyness. Called on a slower cadence."""
        try:
            if not position.option_ids:
                return
            option_id = position.option_ids[0]
            market_data = r.get_option_market_data_by_id(option_id)
            if market_data:
                market_info = market_data[0] if isinstance(market_data, list) and market_data else market_data

                def _sf(val, default=0.0):
                    try:
                        return float(val) if val is not None else default
                    except (TypeError, ValueError):
                        return default

                position.delta = _sf(market_info.get('delta'))
                position.gamma = _sf(market_info.get('gamma'))
                position.theta = _sf(market_info.get('theta'))
                position.vega = _sf(market_info.get('vega'))
                iv_raw = _sf(market_info.get('implied_volatility'))
                position.implied_volatility = iv_raw * 100 if iv_raw > 0 else 0.0

            # Underlying price
            try:
                up = r.get_latest_price(position.symbol, includeExtendedHours=False)
                position.underlying_price = float(up[0]) if up else 0.0
            except Exception:
                pass

            # DTE
            try:
                import datetime as _dt
                exp = _dt.datetime.strptime(position.expiration_date, '%Y-%m-%d').date()
                position.dte = max((exp - _dt.date.today()).days, 0)
            except Exception:
                position.dte = 0

            # Moneyness
            u = position.underlying_price
            k = position.strike_price
            if u > 0 and k > 0:
                if position.option_type.lower() == 'call':
                    diff_pct = (u - k) / k * 100
                    label = "ITM" if u > k else "OTM"
                else:
                    diff_pct = (k - u) / u * 100
                    label = "ITM" if u < k else "OTM"
                position.moneyness = f"{label} {abs(diff_pct):.1f}%"
            else:
                position.moneyness = ""

        except Exception as e:
            self.logger.error(f"Error refreshing Greeks for {position.symbol}: {e}")

    def calculate_pnl(self, position: LongPosition) -> None:
        """Full refresh: mark price + Greeks + derived fields. Used for initial load and explicit refresh."""
        try:
            if not position.option_ids:
                return

            option_id = position.option_ids[0]
            market_data = r.get_option_market_data_by_id(option_id)

            if market_data:
                # Handle list vs dict shapes
                market_info = market_data[0] if isinstance(market_data, list) and len(market_data) > 0 else market_data
                new_price = float(market_info.get('adjusted_mark_price', 0))
                if new_price > 0:
                    position.current_price = new_price

                def _safe_float(val, default=0.0):
                    try:
                        return float(val) if val is not None else default
                    except (TypeError, ValueError):
                        return default

                position.delta = _safe_float(market_info.get('delta'))
                position.gamma = _safe_float(market_info.get('gamma'))
                position.theta = _safe_float(market_info.get('theta'))
                position.vega = _safe_float(market_info.get('vega'))
                iv_raw = _safe_float(market_info.get('implied_volatility'))
                position.implied_volatility = iv_raw * 100 if iv_raw > 0 else 0.0
                position.bid_price = _safe_float(market_info.get('bid_price'))
                position.ask_price = _safe_float(market_info.get('ask_price'))

            # Underlying price and derived fields
            try:
                up = r.get_latest_price(position.symbol, includeExtendedHours=False)
                position.underlying_price = float(up[0]) if up else 0.0
            except Exception:
                pass

            # DTE
            try:
                import datetime as _dt
                exp = _dt.datetime.strptime(position.expiration_date, '%Y-%m-%d').date()
                position.dte = max((exp - _dt.date.today()).days, 0)
            except Exception:
                position.dte = 0

            # Moneyness
            u = position.underlying_price
            k = position.strike_price
            if u > 0 and k > 0:
                if position.option_type.lower() == 'call':
                    diff_pct = (u - k) / k * 100
                    label = "ITM" if u > k else "OTM"
                else:
                    diff_pct = (k - u) / u * 100
                    label = "ITM" if u < k else "OTM"
                position.moneyness = f"{label} {abs(diff_pct):.1f}%"
            else:
                position.moneyness = ""

            if position.current_price > 0:
                current_value = position.current_price * position.quantity * 100
                position.pnl = current_value - position.open_premium
                if position.open_premium > 0:
                    position.pnl_percent = (position.pnl / position.open_premium) * 100
            else:
                position.pnl = -position.open_premium
                position.pnl_percent = -100.0

            # Mark Greeks as freshly fetched
            position._last_greeks_refresh = time.time()

        except Exception as e:
            self.logger.error(f"Error calculating P&L for {position.symbol}: {e}")

    # -------------------- Order orchestration --------------------
    def _ensure_order_store(self, account_number: str) -> None:
        if account_number not in self._tracked_orders:
            self._tracked_orders[account_number] = {}

    def submit_close_order(self, account_number: str, position: LongPosition, limit_price: float) -> Dict[str, any]:
        """Submit a close order via order service and track it."""
        if not self._order_service:
            return {'success': False, 'error': 'Order service not configured'}
        result = self._order_service.submit_close(position, limit_price)
        if result.get('success') and result.get('order_id'):
            with self._lock:
                self._ensure_order_store(account_number)
                order_id = result['order_id']
                self._tracked_orders[account_number][order_id] = {
                    'symbol': position.symbol,
                    'quantity': position.quantity,
                    'price': limit_price,
                    'submit_time': datetime.datetime.now().timestamp(),
                    'order_type': 'limit'
                }
        return result

    def submit_trailing_stop(self, account_number: str, position: LongPosition, limit_price: float, stop_price: float) -> Dict[str, any]:
        """Submit a trailing stop as stop-limit; mark position state and track order."""
        if not self._order_service:
            return {'success': False, 'error': 'Order service not configured'}
        result = self._order_service.submit_trailing_stop(position, limit_price, stop_price)
        if result.get('success') and result.get('order_id'):
            with self._lock:
                if not hasattr(position, 'trail_stop_data'):
                    position.trail_stop_data = {}
                position.trail_stop_data['order_id'] = result['order_id']
                position.trail_stop_data['order_submitted'] = True
                self._ensure_order_store(account_number)
                order_id = result['order_id']
                self._tracked_orders[account_number][order_id] = {
                    'symbol': position.symbol,
                    'quantity': position.quantity,
                    'price': limit_price,
                    'submit_time': datetime.datetime.now().timestamp(),
                    'order_type': 'stop_limit'
                }
        return result

    def cancel_order(self, account_number: str, order_id: str) -> Dict[str, any]:
        if not self._order_service:
            return {'success': False, 'error': 'Order service not configured'}
        result = self._order_service.cancel_order(order_id)
        if result.get('success'):
            with self._lock:
                if account_number not in self._tracked_orders:
                    self._tracked_orders[account_number] = {}
        return result

    def list_open_orders(self) -> Dict[str, any]:
        """List open option orders via order service."""
        if not self._order_service:
            return {'success': False, 'error': 'Order service not configured'}
        return self._order_service.list_open_orders()

    def get_order_info(self, order_id: str) -> Dict[str, any]:
        """Fetch details for a specific option order via order service."""
        if not self._order_service:
            return {'success': False, 'error': 'Order service not configured'}
        return self._order_service.get_order_info(order_id)

    def get_tracked_order_ids(self, account_number: str) -> Dict[str, Dict]:
        """Return tracked orders dict for an account: {order_id: info}."""
        with self._lock:
            return dict(self._tracked_orders.get(account_number, {}))

    # -------------------- Trailing stop --------------------

    def prepare_trailing_stop_order(self, account_number: str, symbol: str) -> Dict[str, any]:
        """Compute trailing stop order prices from current trail_stop_data.
        Returns {success, limit_price, stop_price, config} or {success: False, error}
        """
        with self._lock:
            position = self.get_position(account_number, symbol)
            if not position:
                return {'success': False, 'error': f'Position {symbol} not found'}
            trail = getattr(position, 'trail_stop_data', None)
            if not trail or not trail.get('enabled'):
                return {'success': False, 'error': 'Trailing stop not enabled'}
            trigger = float(trail.get('trigger_price', 0.0) or 0.0)
            if trigger <= 0:
                # Best-effort fallback: derive from current price and percent
                pct = float(trail.get('percent', 0.0) or 0.0)
                if position.current_price > 0 and pct > 0:
                    trigger = position.current_price * (1 - pct / 100.0)
                else:
                    return {'success': False, 'error': 'Invalid trailing stop configuration'}
            limit_price = trigger
            stop_price = trigger / 0.97  # Slightly above limit
            return {
                'success': True,
                'limit_price': limit_price,
                'stop_price': stop_price,
                'config': trail
            }

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
                'order_id': None,
                'submitted_stop_price': 0.0,
                'last_update_time': 0.0,
                'last_order_id': None
            }

            setattr(position, 'trail_stop_data', trail_stop_data)
            self.logger.info(f"Enabled trailing stop for {symbol}: {percent}% at ${position.current_price:.3f}")

            # Persist to disk
            if self._risk_config_store:
                pos_key = self.get_position_key(position)
                tp = getattr(position, 'take_profit_data', None)
                self._risk_config_store.save_position(account_number, pos_key, trail_stop_data, tp)

            return True

    def update_trailing_stop_state(self, position: LongPosition) -> Dict[str, any]:
        """Ensure trail_stop_data exists and update highest/trigger/triggered flags.
        Always ratchets the high watermark regardless of order submission state.
        """
        if not hasattr(position, 'trail_stop_data') or not isinstance(position.trail_stop_data, dict):
            position.trail_stop_data = {
                'enabled': False,
                'percent': 20.0,
                'highest_price': position.current_price,
                'trigger_price': 0.0,
                'triggered': False,
                'order_submitted': False,
                'order_id': None,
                'submitted_stop_price': 0.0,
                'last_update_time': 0.0,
                'last_order_id': None
            }
        trail = position.trail_stop_data
        # Ensure submitted_stop_price field exists on older in-memory objects
        if 'submitted_stop_price' not in trail:
            trail['submitted_stop_price'] = 0.0

        if trail.get('enabled') and position.current_price:
            # Always ratchet — need to track even after order submitted for resubmit logic
            if position.current_price > (trail.get('highest_price') or 0):
                trail['highest_price'] = position.current_price
            pct = float(trail.get('percent', 20.0) or 20.0)
            trail['trigger_price'] = (trail.get('highest_price') or position.current_price) * (1 - pct / 100.0)
            trail['triggered'] = position.current_price <= trail['trigger_price']
            trail['last_update_time'] = datetime.datetime.now().timestamp()
        return trail

    def check_trailing_stops(self, account_number: str) -> None:
        """Check and update trailing stops for all positions in account.
        When is_live=True, auto-submits/cancels/resubmits stop-limit orders as the stop price ratchets.
        """
        with self._lock:
            account_positions = self._positions.get(account_number, {})

            for pos_key, position in account_positions.items():
                trail = self.update_trailing_stop_state(position)

                if trail.get('triggered'):
                    self.logger.warning(
                        f"Trailing stop TRIGGERED for {position.symbol}! "
                        f"Price ${position.current_price:.3f} <= Trigger ${trail.get('trigger_price', 0):.3f}"
                    )

                if not trail.get('enabled') or not self.is_live:
                    continue

                new_trigger = round(float(trail.get('trigger_price', 0) or 0), 2)
                if new_trigger <= 0:
                    continue

                # Case 1: triggered with no active order → fallback limit close
                if trail.get('triggered') and not trail.get('order_submitted'):
                    fallback_price = round(position.current_price * 0.95, 2)
                    result = self.submit_close_order(account_number, position, fallback_price)
                    if result.get('success'):
                        trail['order_submitted'] = True
                        trail['order_id'] = result.get('order_id')
                        self.logger.warning(
                            f"AUTO TRAIL STOP FALLBACK: {position.symbol} limit close at ${fallback_price:.2f}"
                        )
                    else:
                        self.logger.error(
                            f"Trail stop fallback close failed for {position.symbol}: {result.get('error')}"
                        )
                    continue

                # Case 2: price has ratcheted up — update the stop-limit on Robinhood
                submitted_stop = float(trail.get('submitted_stop_price', 0.0) or 0.0)
                existing_order_id = trail.get('order_id')

                if submitted_stop <= 0:
                    needs_submit = True  # No order yet
                else:
                    change_pct = abs(new_trigger - submitted_stop) / submitted_stop
                    needs_submit = change_pct > 0.005  # 0.5% threshold

                if needs_submit:
                    if existing_order_id and self._order_service:
                        cancel_result = self._order_service.cancel_order(existing_order_id)
                        if not cancel_result.get('success'):
                            self.logger.warning(
                                f"Cancel order {existing_order_id} for {position.symbol} "
                                f"returned: {cancel_result.get('error')}"
                            )
                    new_limit = round(new_trigger * 0.97, 2)
                    result = self.submit_trailing_stop(account_number, position, new_limit, new_trigger)
                    if result.get('success'):
                        trail['submitted_stop_price'] = new_trigger
                        trail['order_id'] = result['order_id']
                        trail['order_submitted'] = True
                        self.logger.info(
                            f"AUTO TRAIL STOP: {position.symbol} "
                            f"stop=${new_trigger:.2f} limit=${new_limit:.2f}"
                        )
                    else:
                        self.logger.error(
                            f"Trail stop submit failed for {position.symbol}: {result.get('error')}"
                        )

    # -------------------- Take profit --------------------

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
                'triggered': False,
                'order_submitted': False,
                'order_id': None
            }

            setattr(position, 'take_profit_data', take_profit_data)
            self.logger.info(f"Set take profit for {symbol}: {percent}% at ${take_profit_data['trigger_price']:.3f}")

            # Persist to disk
            if self._risk_config_store:
                pos_key = self.get_position_key(position)
                trail = getattr(position, 'trail_stop_data', None)
                self._risk_config_store.save_position(account_number, pos_key, trail, take_profit_data)

            return True

    def update_take_profit_state(self, position: LongPosition) -> Dict[str, any]:
        """Ensure take_profit_data exists and update its triggered flag based on pnl_percent."""
        if not hasattr(position, 'take_profit_data'):
            position.take_profit_data = {
                'enabled': False,
                'percent': 50.0,
                'target_pnl': 50.0,
                'triggered': False,
                'order_submitted': False,
                'order_id': None
            }
        tp = position.take_profit_data
        # Ensure order tracking fields exist on older in-memory objects
        if 'order_submitted' not in tp:
            tp['order_submitted'] = False
        if 'order_id' not in tp:
            tp['order_id'] = None

        if tp.get('enabled'):
            tp['target_pnl'] = float(tp.get('percent', 50.0))
            tp['triggered'] = position.pnl_percent >= float(tp['percent'])
        else:
            tp['triggered'] = False
        return tp

    def check_take_profits(self, account_number: str) -> None:
        """Auto-submit close orders when take profit is triggered (live mode only)."""
        if not self.is_live:
            return
        with self._lock:
            account_positions = self._positions.get(account_number, {})
            for pos_key, position in account_positions.items():
                tp = self.update_take_profit_state(position)
                if not tp.get('enabled') or not tp.get('triggered') or tp.get('order_submitted'):
                    continue
                # Compute target limit price
                target_value = position.open_premium * (1 + float(tp.get('percent', 50.0)) / 100.0)
                if position.quantity <= 0:
                    continue
                limit_price = round(target_value / (position.quantity * 100), 2)
                result = self.submit_close_order(account_number, position, limit_price)
                if result.get('success'):
                    tp['order_submitted'] = True
                    tp['order_id'] = result.get('order_id')
                    self.logger.warning(
                        f"AUTO TAKE PROFIT: {position.symbol} at ${limit_price:.2f} "
                        f"(pnl={position.pnl_percent:.1f}%)"
                    )
                else:
                    self.logger.error(
                        f"AUTO TAKE PROFIT failed for {position.symbol}: {result.get('error')}"
                    )

    def prepare_take_profit_order(self, account_number: str, symbol: str) -> Dict[str, any]:
        """Compute a conservative limit price to realize the configured take-profit percent.
        Returns {success, limit_price, estimated_proceeds} or {success: False, error}
        """
        with self._lock:
            position = self.get_position(account_number, symbol)
            if not position:
                return {'success': False, 'error': f'Position {symbol} not found'}
            tp = self.update_take_profit_state(position)
            if not tp.get('enabled'):
                return {'success': False, 'error': 'Take profit not enabled'}
            # Target account-level proceeds equals open_premium * (1 + percent/100)
            target_value = position.open_premium * (1 + float(tp['percent']) / 100.0)
            if position.quantity <= 0:
                return {'success': False, 'error': 'Invalid quantity for position'}
            limit_price = target_value / (position.quantity * 100)
            return {
                'success': True,
                'limit_price': round(limit_price, 2),
                'estimated_proceeds': round(target_value, 2),
                'config': tp
            }

    # -------------------- Symbol intelligence --------------------

    def _fetch_expected_move(self, symbol: str, underlying_price: float) -> dict | None:
        """Fetch ATM straddle price for the nearest weekly expiration (1–10 days out)."""
        import datetime as _dt
        try:
            chain = r.get_chains(symbol)
            if not chain:
                return None
            expirations = chain.get('expiration_dates', [])
            today = _dt.date.today()
            chosen = None
            for exp_str in sorted(expirations):
                exp = _dt.datetime.strptime(exp_str, '%Y-%m-%d').date()
                dte = (exp - today).days
                if 1 <= dte <= 10:
                    chosen = (exp_str, dte)
                    break
            if not chosen:
                return None
            exp_str, dte = chosen

            instruments = r.find_tradable_options(symbol, exp_str)
            if not instruments:
                return None
            strikes = sorted(set(
                float(i['strike_price']) for i in instruments
                if i and i.get('strike_price')
            ))
            if not strikes or underlying_price <= 0:
                return None
            atm_strike = min(strikes, key=lambda k: abs(k - underlying_price))

            calls = r.find_options_by_expiration_and_strike(symbol, exp_str, str(atm_strike), 'call')
            puts  = r.find_options_by_expiration_and_strike(symbol, exp_str, str(atm_strike), 'put')
            call_mark = float((calls[0] if calls else {}).get('adjusted_mark_price', 0) or 0)
            put_mark  = float((puts[0]  if puts  else {}).get('adjusted_mark_price', 0) or 0)

            if call_mark <= 0 or put_mark <= 0:
                return None

            amount = call_mark + put_mark
            return {
                'amount': round(amount, 2),
                'percent': round(amount / underlying_price * 100, 2),
                'expiration': exp_str,
                'dte': dte,
                'atm_strike': atm_strike,
                'call_mark': call_mark,
                'put_mark': put_mark,
            }
        except Exception as e:
            self.logger.error(f"Expected move fetch failed for {symbol}: {e}")
            return None

    def refresh_symbol_intelligence(self, symbols: List[str], underlying_prices: Dict[str, float] = None) -> None:
        """Fetch and cache earnings, news, and fundamentals for a list of symbols."""
        if underlying_prices is None:
            underlying_prices = {}
        for symbol in symbols:
            try:
                intelligence = {}

                # Earnings
                try:
                    earnings_data = r.get_earnings(symbol)
                    next_earnings = None
                    if earnings_data:
                        import datetime as _dt
                        today = _dt.date.today()
                        for e in earnings_data:
                            report_date = e.get('report') or {}
                            date_str = report_date.get('date') if isinstance(report_date, dict) else e.get('date')
                            if not date_str:
                                continue
                            try:
                                edate = _dt.datetime.strptime(date_str, '%Y-%m-%d').date()
                                if edate >= today:
                                    timing = report_date.get('timing', '') if isinstance(report_date, dict) else ''
                                    next_earnings = {'date': date_str, 'timing': timing.upper() if timing else ''}
                                    break
                            except ValueError:
                                continue
                    intelligence['next_earnings'] = next_earnings
                except Exception:
                    intelligence['next_earnings'] = None

                # News
                try:
                    news_data = r.get_news(symbol)
                    headlines = []
                    if news_data:
                        for item in news_data[:3]:
                            headlines.append({
                                'title': item.get('title', ''),
                                'source': item.get('source', ''),
                                'published_at': item.get('published_at', item.get('publishedAt', '')),
                                'url': item.get('url', item.get('source_url', ''))
                            })
                    intelligence['news'] = headlines
                except Exception:
                    intelligence['news'] = []

                # Fundamentals
                try:
                    fund_data = r.get_fundamentals(symbol)
                    fund = fund_data[0] if isinstance(fund_data, list) and fund_data else (fund_data or {})

                    def _fmt_large(val):
                        try:
                            v = float(val)
                            if v >= 1e12: return f"${v/1e12:.2f}T"
                            if v >= 1e9:  return f"${v/1e9:.2f}B"
                            if v >= 1e6:  return f"${v/1e6:.2f}M"
                            return f"${v:,.0f}"
                        except (TypeError, ValueError):
                            return None

                    intelligence['fundamentals'] = {
                        'sector': fund.get('sector') or None,
                        'industry': fund.get('industry') or None,
                        'pe_ratio': fund.get('pe_ratio') or None,
                        'pb_ratio': fund.get('pb_ratio') or None,
                        'dividend_yield': f"{float(fund.get('dividend_yield') or 0):.2f}%" if fund.get('dividend_yield') else None,
                        'market_cap': _fmt_large(fund.get('market_cap')),
                        'high_52_weeks': fund.get('high_52_weeks'),
                        'low_52_weeks': fund.get('low_52_weeks'),
                        'average_volume': fund.get('average_volume') or None,
                        'num_employees': fund.get('num_employees') or None,
                        'ceo': fund.get('ceo') or None,
                        'year_founded': fund.get('year_founded') or None,
                        'headquarters': (
                            f"{fund.get('headquarters_city')}, {fund.get('headquarters_state')}"
                            if fund.get('headquarters_city') and fund.get('headquarters_state') else None
                        ),
                    }
                except Exception:
                    intelligence['fundamentals'] = {}

                # Expected move (ATM straddle for nearest weekly expiration)
                underlying_price = underlying_prices.get(symbol, 0.0)
                intelligence['expected_move'] = self._fetch_expected_move(symbol, underlying_price) if underlying_price > 0 else None

                import datetime as _dt2
                intelligence['last_fetched'] = _dt2.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                with self._lock:
                    self._symbol_intelligence[symbol] = intelligence

                self.logger.info(f"Refreshed intelligence for {symbol}")
            except Exception as e:
                self.logger.error(f"Error refreshing intelligence for {symbol}: {e}")

    def get_symbol_intelligence(self, symbol: str) -> dict:
        """Return cached intelligence for a symbol, or empty dict."""
        with self._lock:
            return self._symbol_intelligence.get(symbol, {})


# Global instance
position_manager = PositionManager()
