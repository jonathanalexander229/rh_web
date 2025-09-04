import os, sys
import pytest

# Ensure repo root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import account_detector as ad_mod


def _fake_accounts():
    return {
        "results": [
            {
                "account_number": "AAAA00001234",
                "state": "active",
                "type": "Standard",
            },
            {
                "account_number": "BBBB99997315",
                "state": "active",
                "type": "Roth IRA",
            },
        ]
    }


def test_detect_accounts_and_prefixes(monkeypatch):
    # Stub robin_stocks load_account_profile
    monkeypatch.setattr(ad_mod.r, "load_account_profile", lambda dataType="regular": _fake_accounts())

    det = ad_mod.AccountDetector()
    accounts = det.detect_accounts()

    # Keys are prefixes like STD-1234 and ROTH-7315
    assert any(k.startswith("STD-") for k in accounts.keys())
    assert any(k.startswith("ROTH-") for k in accounts.keys())

    # Map prefix -> full number exists
    for prefix, info in accounts.items():
        assert det.get_account_number_from_prefix(prefix) == info["number"]


def test_has_positions_or_orders_with_prefix_and_number(monkeypatch):
    # Stub accounts
    monkeypatch.setattr(ad_mod.r, "load_account_profile", lambda dataType="regular": _fake_accounts())

    # Stub positions: options for ...1234 -> 1 item, stocks for ...7315 -> 0 items
    def fake_get_open_options(account_number=None):
        return [{}] if str(account_number).endswith("1234") else []

    def fake_get_open_stocks(account_number=None):
        return []

    # Patch stock query used as fallback
    monkeypatch.setattr(ad_mod.r, "get_open_stock_positions", fake_get_open_stocks)
    # Patch PositionManager to report 1 option position for ...1234 without requiring deeper API
    import position_manager as pm_mod
    monkeypatch.setattr(
        pm_mod.position_manager,
        "load_positions_for_account",
        lambda account_number: 1 if str(account_number).endswith("1234") else 0,
    )

    det = ad_mod.AccountDetector()
    accounts = det.detect_accounts()

    # Pick out prefixes and numbers
    items = list(accounts.items())
    prefix1, info1 = items[0]
    prefix2, info2 = items[1]

    # Account ending 1234 should have activity due to options
    if info1["number"].endswith("1234"):
        active_prefix, active_info = prefix1, info1
        inactive_prefix, inactive_info = prefix2, info2
    else:
        active_prefix, active_info = prefix2, info2
        inactive_prefix, inactive_info = prefix1, info1

    # Validate using full account numbers (most reliable path)
    assert det.has_positions_or_orders(active_info["number"]) is True
    assert det.has_positions_or_orders(inactive_info["number"]) is False
