"""
Tests for auto-execution features introduced in the risk manager:
- Configurable intervals loaded from config.json
- LongPosition new runtime fields
- RiskConfigStore save / load / clear
- Trailing stop watermark ratchet and auto-execution logic
- Take profit auto-execution
- Stop loss auto-execution
- Greeks throttle via _last_greeks_refresh
"""

import os
import logging
import sys
import time
import tempfile
import json
import types
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.position_types import LongPosition
from shared.risk_config_store import RiskConfigStore
import shared.position_manager as pm_mod
from risk_manager.multi_account_manager import _load_rm_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(**kwargs) -> LongPosition:
    defaults = dict(
        symbol="QQQ",
        strike_price=500.0,
        option_type="call",
        expiration_date="2099-06-20",
        quantity=1,
        open_premium=300.0,
        current_price=3.0,
        option_ids=["fake-id"],
    )
    defaults.update(kwargs)
    return LongPosition(**defaults)


def _mock_market_price(monkeypatch, price: float):
    def _get_option_market_data_by_id(_):
        return [{"adjusted_mark_price": str(price)}]
    monkeypatch.setattr(pm_mod.r, "get_option_market_data_by_id", _get_option_market_data_by_id)


def _mock_underlying(monkeypatch, price: float):
    monkeypatch.setattr(pm_mod.r, "get_latest_price", lambda *a, **kw: [str(price)])


# ---------------------------------------------------------------------------
# config.json — risk_manager section
# ---------------------------------------------------------------------------

def test_rm_config_loads_from_config_json():
    cfg = _load_rm_config()
    assert isinstance(cfg, dict)
    assert "price_refresh_interval_seconds" in cfg
    assert "greeks_refresh_interval_seconds" in cfg
    assert "reconciliation_interval_seconds" in cfg
    assert "reconciliation_interval_after_hours_seconds" in cfg
    assert "order_fill_check_interval_seconds" in cfg


def test_rm_config_values_are_positive():
    cfg = _load_rm_config()
    for key, val in cfg.items():
        # Boolean feature flags (e.g. auto_stop_loss_enabled) are not magnitudes
        if isinstance(val, bool):
            continue
        assert float(val) > 0, f"{key} must be positive"


# ---------------------------------------------------------------------------
# LongPosition new fields
# ---------------------------------------------------------------------------

def test_longposition_new_runtime_fields():
    pos = _make_position()
    assert hasattr(pos, "_stop_loss_submitted")
    assert pos._stop_loss_submitted is False
    assert hasattr(pos, "_stop_loss_order_id")
    assert pos._stop_loss_order_id is None
    assert hasattr(pos, "_last_greeks_refresh")
    assert pos._last_greeks_refresh == 0.0


# ---------------------------------------------------------------------------
# RiskConfigStore
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_config_store(tmp_path, monkeypatch):
    """Return a RiskConfigStore that writes to a temp dir."""
    monkeypatch.setattr("shared.risk_config_store._CONFIG_DIR", str(tmp_path))
    store = RiskConfigStore()
    return store


def test_risk_config_store_save_and_load(temp_config_store):
    trail = {"enabled": True, "percent": 20.0, "highest_price": 4.5}
    tp = {"enabled": True, "percent": 50.0}
    temp_config_store.save_position("ACC123", "QQQ_2026-06-20_500.0_call", trail, tp)

    loaded = temp_config_store.load("ACC123")
    assert "QQQ_2026-06-20_500.0_call" in loaded
    entry = loaded["QQQ_2026-06-20_500.0_call"]
    assert entry["trail_stop"]["enabled"] is True
    assert entry["trail_stop"]["percent"] == 20.0
    assert entry["trail_stop"]["highest_price"] == 4.5
    assert entry["take_profit"]["enabled"] is True
    assert entry["take_profit"]["percent"] == 50.0


def test_risk_config_store_load_missing_account(temp_config_store):
    result = temp_config_store.load("NONEXISTENT")
    assert result == {}


def test_risk_config_store_clear_position(temp_config_store):
    trail = {"enabled": True, "percent": 15.0, "highest_price": 3.0}
    temp_config_store.save_position("ACC123", "SPY_2026-12-20_600.0_put", trail, None)
    assert "SPY_2026-12-20_600.0_put" in temp_config_store.load("ACC123")

    temp_config_store.clear_position("ACC123", "SPY_2026-12-20_600.0_put")
    assert "SPY_2026-12-20_600.0_put" not in temp_config_store.load("ACC123")


def test_risk_config_store_omits_runtime_state(temp_config_store):
    """order_id, triggered, order_submitted must not be saved."""
    trail = {
        "enabled": True, "percent": 20.0, "highest_price": 4.5,
        "order_id": "should-not-persist", "triggered": True, "order_submitted": True,
    }
    temp_config_store.save_position("ACC123", "QQQ_2026-06-20_500.0_call", trail, None)
    entry = temp_config_store.load("ACC123")["QQQ_2026-06-20_500.0_call"]["trail_stop"]
    assert "order_id" not in entry
    assert "triggered" not in entry
    assert "order_submitted" not in entry


def test_risk_config_store_multiple_positions(temp_config_store):
    for sym, strike in [("QQQ", "500.0"), ("SPY", "600.0")]:
        trail = {"enabled": True, "percent": 20.0, "highest_price": 4.0}
        temp_config_store.save_position("ACC123", f"{sym}_2026-06-20_{strike}_call", trail, None)

    loaded = temp_config_store.load("ACC123")
    assert len(loaded) == 2


# ---------------------------------------------------------------------------
# PositionManager — is_live flag and set_live_mode
# ---------------------------------------------------------------------------

def test_set_live_mode():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    assert pm.is_live is False
    pm.set_live_mode(True)
    assert pm.is_live is True
    pm.set_live_mode(False)
    assert pm.is_live is False


# ---------------------------------------------------------------------------
# Trailing stop watermark ratchet
# ---------------------------------------------------------------------------

def _setup_position_with_trail(pm, account="ACCT", price=4.0, percent=20.0):
    pos = _make_position(current_price=price)
    with pm._lock:
        pm._positions.setdefault(account, {})[
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"
        ] = pos
    pm.enable_trailing_stop(account, pos.symbol, percent)
    return pos


def test_trail_stop_ratchets_on_price_rise():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=4.0, percent=20.0)

    pos.current_price = 5.0
    trail = pm.update_trailing_stop_state(pos)
    assert trail["highest_price"] == 5.0
    assert round(trail["trigger_price"], 4) == round(5.0 * 0.8, 4)
    assert trail["triggered"] is False


def test_trail_stop_does_not_lower_high():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=4.0)

    pos.current_price = 5.0
    pm.update_trailing_stop_state(pos)

    pos.current_price = 3.5  # price drops
    trail = pm.update_trailing_stop_state(pos)
    assert trail["highest_price"] == 5.0  # watermark unchanged


def test_trail_stop_triggered_on_drop():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=5.0, percent=20.0)

    # Drop below 5.0 * 0.8 = 4.0
    pos.current_price = 3.9
    trail = pm.update_trailing_stop_state(pos)
    assert trail["triggered"] is True


def test_trail_stop_not_triggered_above_threshold():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=5.0, percent=20.0)

    pos.current_price = 4.1  # above 4.0 trigger
    trail = pm.update_trailing_stop_state(pos)
    assert trail["triggered"] is False


def test_trail_stop_ratchets_after_order_submitted():
    """Watermark must keep rising even after a stop-limit order has been submitted."""
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=4.0)

    # Simulate submitted state
    pos.trail_stop_data["order_submitted"] = True
    pos.trail_stop_data["submitted_stop_price"] = 3.2

    pos.current_price = 6.0
    trail = pm.update_trailing_stop_state(pos)
    assert trail["highest_price"] == 6.0  # ratcheted despite order_submitted=True
    assert round(trail["trigger_price"], 4) == round(6.0 * 0.8, 4)


# ---------------------------------------------------------------------------
# Trailing stop auto-execution (live mode)
# ---------------------------------------------------------------------------

def _make_pm_with_order_service():
    """Return a PositionManager with a fake order service for order capture."""
    from shared.position_manager import PositionManager

    submitted = []
    cancelled = []

    class FakeOrderService:
        def submit_close(self, position, limit_price):
            submitted.append(("close", limit_price))
            return {"success": True, "order_id": f"close-{len(submitted)}"}

        def submit_trailing_stop(self, position, limit_price, stop_price):
            submitted.append(("stop_limit", limit_price, stop_price))
            return {"success": True, "order_id": f"stop-{len(submitted)}"}

        def cancel_order(self, order_id):
            cancelled.append(order_id)
            return {"success": True}

        def list_open_orders(self, **kw):
            return {"success": True, "orders": []}

        def get_order_info(self, order_id):
            return {"success": True, "details": {"state": "queued"}}

    pm = PositionManager()
    svc = FakeOrderService()
    pm.set_order_service(svc)
    pm.set_live_mode(True)
    return pm, submitted, cancelled, svc


def test_trail_stop_submits_initial_stop_limit():
    pm, submitted, cancelled, _ = _make_pm_with_order_service()
    pos = _setup_position_with_trail(pm, price=4.0, percent=20.0)

    pm.check_trailing_stops("ACCT")

    assert len(submitted) == 1
    order_type, limit_price, stop_price = submitted[0]
    assert order_type == "stop_limit"
    assert round(stop_price, 2) == round(4.0 * 0.8, 2)       # trigger = 3.2
    assert round(limit_price, 2) == round(3.2 * 0.97, 2)     # limit  = 3.104 → 3.1


def test_trail_stop_resubmits_when_stop_price_changes():
    pm, submitted, cancelled, _ = _make_pm_with_order_service()
    pos = _setup_position_with_trail(pm, price=4.0, percent=20.0)

    # First submission
    pm.check_trailing_stops("ACCT")
    first_order_id = pos.trail_stop_data["order_id"]

    # Price ratchets up significantly (>0.5% change in trigger)
    pos.current_price = 5.0
    pm.update_trailing_stop_state(pos)
    pm.check_trailing_stops("ACCT")

    assert len(submitted) == 2                     # resubmitted
    assert len(cancelled) == 1                     # old order cancelled
    assert cancelled[0] == first_order_id
    assert pos.trail_stop_data["submitted_stop_price"] == round(5.0 * 0.8, 2)


def test_trail_stop_no_resubmit_on_tiny_change():
    """Less than 0.5% change in trigger price must not trigger a cancel+resubmit."""
    pm, submitted, cancelled, _ = _make_pm_with_order_service()
    pos = _setup_position_with_trail(pm, price=4.0, percent=20.0)

    pm.check_trailing_stops("ACCT")  # initial submit

    # Tiny price change: 4.001 → trigger 3.2008 vs submitted 3.2 → 0.025% change
    pos.current_price = 4.001
    pm.update_trailing_stop_state(pos)
    pm.check_trailing_stops("ACCT")

    assert len(submitted) == 1   # no resubmit
    assert len(cancelled) == 0


def test_trail_stop_fallback_limit_close_when_triggered_with_no_order():
    """When triggered but no stop-limit order active, a regular limit close is submitted."""
    pm, submitted, cancelled, _ = _make_pm_with_order_service()
    pos = _setup_position_with_trail(pm, price=5.0, percent=20.0)

    # Manually trigger without submitting a stop-limit first
    pos.current_price = 3.9  # below 5.0 * 0.8 = 4.0
    pm.update_trailing_stop_state(pos)  # sets triggered=True

    pm.check_trailing_stops("ACCT")

    assert len(submitted) == 1
    order_type, limit_price = submitted[0]
    assert order_type == "close"
    assert limit_price == round(3.9 * 0.95, 2)


def test_trail_stop_no_execution_in_readonly_mode():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _setup_position_with_trail(pm, price=4.0)
    # is_live stays False (default)

    pm.check_trailing_stops("ACCT")
    # No order service — would raise if called
    assert pos.trail_stop_data.get("order_submitted") is False


# ---------------------------------------------------------------------------
# Take profit auto-execution
# ---------------------------------------------------------------------------

def test_take_profit_auto_executes_when_triggered():
    pm, submitted, cancelled, _ = _make_pm_with_order_service()
    pos = _make_position(open_premium=300.0, quantity=1, current_price=3.0)
    with pm._lock:
        pm._positions.setdefault("ACCT", {})[
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"
        ] = pos
    pm.set_take_profit("ACCT", pos.symbol, 50.0)

    # P&L at 100%  (> 50% target)
    pos.pnl_percent = 100.0
    pm.check_take_profits("ACCT")

    assert len(submitted) == 1
    order_type, limit_price = submitted[0]
    assert order_type == "close"
    # Expected limit = open_premium * 1.5 / (qty * 100) = 450 / 100 = 4.50
    assert round(limit_price, 2) == 4.50


def test_take_profit_not_triggered_below_target():
    pm, submitted, _, _ = _make_pm_with_order_service()
    pos = _make_position(open_premium=300.0, quantity=1, current_price=3.0)
    with pm._lock:
        pm._positions.setdefault("ACCT", {})[
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"
        ] = pos
    pm.set_take_profit("ACCT", pos.symbol, 50.0)

    pos.pnl_percent = 30.0  # below 50% target
    pm.check_take_profits("ACCT")

    assert len(submitted) == 0


def test_take_profit_not_resubmitted():
    pm, submitted, _, _ = _make_pm_with_order_service()
    pos = _make_position(open_premium=300.0, quantity=1, current_price=3.0)
    with pm._lock:
        pm._positions.setdefault("ACCT", {})[
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"
        ] = pos
    pm.set_take_profit("ACCT", pos.symbol, 50.0)
    pos.pnl_percent = 100.0

    pm.check_take_profits("ACCT")
    pm.check_take_profits("ACCT")  # second call

    assert len(submitted) == 1   # order_submitted=True prevents double-submit


def test_take_profit_no_execution_in_readonly_mode():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _make_position(open_premium=300.0, quantity=1, pnl_percent=100.0)
    with pm._lock:
        pm._positions.setdefault("ACCT", {})[
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"
        ] = pos
    pm.set_take_profit("ACCT", pos.symbol, 50.0)
    pos.pnl_percent = 100.0

    pm.check_take_profits("ACCT")   # is_live=False — nothing submitted


# ---------------------------------------------------------------------------
# Greeks throttle
# ---------------------------------------------------------------------------

def test_greeks_throttled_by_interval(monkeypatch):
    """refresh_prices should skip Greeks when last refresh was within the interval."""
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pm.set_greeks_refresh_interval(60.0)   # 60-second throttle

    greeks_calls = []

    def _get_market_data(_):
        greeks_calls.append(1)
        return [{"adjusted_mark_price": "3.0", "bid_price": "2.9", "ask_price": "3.1"}]

    monkeypatch.setattr(pm_mod.r, "get_option_market_data_by_id", _get_market_data)
    monkeypatch.setattr(pm_mod.r, "get_latest_price", lambda *a, **kw: ["500.0"])

    pos = _make_position()
    pos._last_greeks_refresh = time.time() - 10   # refreshed 10s ago (within 60s)
    with pm._lock:
        pm._positions["ACCT"] = {
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}": pos
        }

    before = len(greeks_calls)
    pm.refresh_prices("ACCT")   # mark price call happens; Greeks skipped
    # The mark price fetch calls _get_market_data once
    assert len(greeks_calls) == before + 1   # exactly 1 call (mark price only)


def test_greeks_fetched_after_interval(monkeypatch):
    """refresh_prices should call Greeks fetch when interval has elapsed."""
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pm.set_greeks_refresh_interval(5.0)

    greeks_calls = []

    def _get_market_data(_):
        greeks_calls.append(1)
        return [{"adjusted_mark_price": "3.0", "bid_price": "2.9", "ask_price": "3.1",
                 "delta": "0.5", "gamma": "0.01", "theta": "-0.05", "vega": "0.2",
                 "implied_volatility": "0.3"}]

    monkeypatch.setattr(pm_mod.r, "get_option_market_data_by_id", _get_market_data)
    monkeypatch.setattr(pm_mod.r, "get_latest_price", lambda *a, **kw: ["500.0"])

    pos = _make_position()
    pos._last_greeks_refresh = 0.0   # never refreshed → interval always elapsed
    with pm._lock:
        pm._positions["ACCT"] = {
            f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}": pos
        }

    pm.refresh_prices("ACCT")
    # _refresh_mark_price + _refresh_greeks each call get_option_market_data_by_id once
    assert len(greeks_calls) == 2
    assert pos._last_greeks_refresh > 0


# ---------------------------------------------------------------------------
# get_position_key helper
# ---------------------------------------------------------------------------

def test_get_position_key():
    from shared.position_manager import PositionManager
    pm = PositionManager()
    pos = _make_position()
    key = pm.get_position_key(pos)
    assert key == f"{pos.symbol}_{pos.expiration_date}_{pos.strike_price}_{pos.option_type}"


# ---------------------------------------------------------------------------
# Order fill handling — partial fills must not drop the residual position
# ---------------------------------------------------------------------------

def _make_monitor(monkeypatch, position, pos_key="POS1", order_state="filled",
                  open_ids=None, cancel_ok=True):
    """Build an AccountMonitoringThread without running __init__ (no broker I/O),
    wired to a fake position_manager so no real endpoint is ever touched.
    """
    import risk_manager.multi_account_manager as mam

    monitor = object.__new__(mam.AccountMonitoringThread)
    monitor.account_number = "ACCT1234"
    monitor.logger = logging.getLogger("test_monitor")
    monitor.risk_manager = types.SimpleNamespace(positions={pos_key: position})

    cancelled = []
    cleared = []

    class FakePositionManager:
        def get_order_info(self, order_id):
            return {"success": True, "details": {"state": order_state}}

        def cancel_order(self, account_number, order_id):
            cancelled.append((account_number, order_id))
            return {"success": True} if cancel_ok else {"success": False, "error": "nope"}

    monkeypatch.setattr(mam, "position_manager", FakePositionManager())
    monkeypatch.setattr(
        mam.risk_config_store, "clear_position",
        lambda acct, key: cleared.append((acct, key)),
    )
    return monitor, cancelled, cleared


def test_stop_loss_full_fill_removes_position(monkeypatch):
    pos = _make_position()
    pos._stop_loss_order_id = "sl-1"
    monitor, _, cleared = _make_monitor(monkeypatch, pos, order_state="filled")

    monitor._check_stop_loss_fill("POS1", pos, open_ids=set())

    assert "POS1" not in monitor.risk_manager.positions
    assert cleared == [("ACCT1234", "POS1")]


def test_stop_loss_partial_fill_keeps_residual_and_rearms(monkeypatch):
    pos = _make_position(quantity=10)
    pos._stop_loss_submitted = True
    pos._stop_loss_order_id = "sl-1"
    pos._stop_loss_order_time = time.time()
    monitor, _, cleared = _make_monitor(monkeypatch, pos, order_state="partially_filled")

    monitor._check_stop_loss_fill("POS1", pos, open_ids=set())

    # Residual contracts stay under monitoring and the saved config survives
    assert "POS1" in monitor.risk_manager.positions
    assert cleared == []
    # Re-armed so the next _check_stop_loss pass can protect the remainder
    assert pos._stop_loss_submitted is False
    assert pos._stop_loss_order_id is None


def test_trail_stop_partial_fill_keeps_residual_and_rearms(monkeypatch):
    pos = _make_position(quantity=10)
    pos.trail_stop_data = {
        "enabled": True, "order_id": "ts-1",
        "order_submitted": True, "submitted_stop_price": 3.2,
    }
    monitor, _, cleared = _make_monitor(monkeypatch, pos, order_state="partially_filled")

    monitor._check_trail_stop_fill("POS1", pos, open_ids=set())

    assert "POS1" in monitor.risk_manager.positions
    assert cleared == []
    assert pos.trail_stop_data["order_submitted"] is False
    assert pos.trail_stop_data["order_id"] is None
    assert pos.trail_stop_data["submitted_stop_price"] == 0.0


def test_take_profit_partial_fill_keeps_residual_and_rearms(monkeypatch):
    pos = _make_position(quantity=10)
    pos.take_profit_data = {"enabled": True, "order_id": "tp-1", "order_submitted": True}
    monitor, _, cleared = _make_monitor(monkeypatch, pos, order_state="partially_filled")

    monitor._check_take_profit_fill("POS1", pos, open_ids=set())

    assert "POS1" in monitor.risk_manager.positions
    assert cleared == []
    assert pos.take_profit_data["order_submitted"] is False
    assert pos.take_profit_data["order_id"] is None


# ---------------------------------------------------------------------------
# Order fill handling — a resting stop-loss limit must be re-priced
# ---------------------------------------------------------------------------

def test_resting_stop_loss_cancelled_after_timeout(monkeypatch):
    import risk_manager.multi_account_manager as mam

    pos = _make_position()
    pos._stop_loss_submitted = True
    pos._stop_loss_order_id = "sl-1"
    pos._stop_loss_order_time = time.time() - (mam.AccountMonitoringThread._STOP_LOSS_ORDER_TIMEOUT + 1)
    monitor, cancelled, _ = _make_monitor(monkeypatch, pos)

    monitor._check_stop_loss_fill("POS1", pos, open_ids={"sl-1"})

    assert cancelled == [("ACCT1234", "sl-1")]
    # Cleared so the next _check_stop_loss re-prices against the current mark
    assert pos._stop_loss_submitted is False
    assert pos._stop_loss_order_id is None


def test_resting_stop_loss_left_alone_within_timeout(monkeypatch):
    pos = _make_position()
    pos._stop_loss_submitted = True
    pos._stop_loss_order_id = "sl-1"
    pos._stop_loss_order_time = time.time()
    monitor, cancelled, _ = _make_monitor(monkeypatch, pos)

    monitor._check_stop_loss_fill("POS1", pos, open_ids={"sl-1"})

    assert cancelled == []
    assert pos._stop_loss_submitted is True
    assert pos._stop_loss_order_id == "sl-1"


def test_failed_cancel_leaves_stop_loss_flags_intact(monkeypatch):
    import risk_manager.multi_account_manager as mam

    pos = _make_position()
    pos._stop_loss_submitted = True
    pos._stop_loss_order_id = "sl-1"
    pos._stop_loss_order_time = time.time() - (mam.AccountMonitoringThread._STOP_LOSS_ORDER_TIMEOUT + 1)
    monitor, cancelled, _ = _make_monitor(monkeypatch, pos, cancel_ok=False)

    monitor._check_stop_loss_fill("POS1", pos, open_ids={"sl-1"})

    assert cancelled == [("ACCT1234", "sl-1")]
    # Cancel failed — do not clear flags, or we would double-submit against a live order
    assert pos._stop_loss_submitted is True
    assert pos._stop_loss_order_id == "sl-1"
