import types

import pytest
import os, sys

# Ensure repo root on path for module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from position_types import LongPosition
import position_manager as pm_mod
from base_risk_manager import BaseRiskManager


def _mock_market_price(monkeypatch, price: float):
    """Monkeypatch robin_stocks market data call to return a specific adjusted_mark_price."""
    def _get_option_market_data_by_id(_):
        return [{"adjusted_mark_price": str(price)}]

    # Patch in the position_manager module
    monkeypatch.setattr(pm_mod.r, "get_option_market_data_by_id", _get_option_market_data_by_id)


def test_calculate_pnl_position_manager(monkeypatch):
    # Given current mark price mocked to 2.50 and open_premium $200 on 1 contract
    _mock_market_price(monkeypatch, 2.50)

    lp = LongPosition(
        symbol="TEST",
        strike_price=100.0,
        option_type="call",
        expiration_date="2099-01-01",
        quantity=1,
        open_premium=200.0,
        option_ids=["abc"]
    )

    pm_mod.position_manager.calculate_pnl(lp)

    assert lp.current_price == 2.50
    # Current value = 2.50 * 1 * 100 = 250; PnL = 50; PnL% = 25%
    assert round(lp.pnl, 2) == 50.00
    assert round(lp.pnl_percent, 2) == 25.00


def test_trailing_stop_state_and_base_delegate(monkeypatch):
    # Mock current mark price sequence via patched function
    _mock_market_price(monkeypatch, 3.00)

    lp = LongPosition(
        symbol="TEST",
        strike_price=100.0,
        option_type="call",
        expiration_date="2099-01-01",
        quantity=1,
        open_premium=100.0,
        option_ids=["def"]
    )

    # Price refresh via BaseRiskManager.calculate_pnl delegates to PositionManager
    brm = BaseRiskManager(account_number="0000")
    brm.calculate_pnl(lp)
    assert lp.current_price == 3.00

    # Enable trailing stop at 20% and update state
    # Insert position into PositionManager store for account '0000'
    with pm_mod.position_manager._lock:
        pm_mod.position_manager._positions.setdefault("0000", {})["TEST_2099-01-01_100.0_call"] = lp
    pm_mod.position_manager.enable_trailing_stop("0000", "TEST", 20.0)
    trail = pm_mod.position_manager.update_trailing_stop_state(lp)
    assert trail["enabled"] is True
    # highest_price should at least be the current price
    assert round(trail["highest_price"], 2) == 3.00
    assert round(trail["trigger_price"], 2) == round(3.00 * (1 - 0.20), 2)
    assert trail["triggered"] is False

    # If price drops below trigger, triggered should become True
    _mock_market_price(monkeypatch, 2.30)  # Below 2.40 trigger
    pm_mod.position_manager.calculate_pnl(lp)  # refresh price
    trail = pm_mod.position_manager.update_trailing_stop_state(lp)
    assert trail["triggered"] is True
