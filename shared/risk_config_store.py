#!/usr/bin/env python3
"""
Disk persistence for per-position risk configurations.
Stores trail stop and take profit settings so they survive app restarts.
"""

import json
import os
import logging
from typing import Dict, Optional

_CONFIG_DIR = os.path.expanduser("~/.rh_risk_configs")


class RiskConfigStore:
    def __init__(self):
        self.logger = logging.getLogger('risk_config_store')
        os.makedirs(_CONFIG_DIR, exist_ok=True)

    def _path(self, account_number: str) -> str:
        return os.path.join(_CONFIG_DIR, f"{account_number}.json")

    def load(self, account_number: str) -> Dict[str, dict]:
        """Load all risk configs for an account.
        Returns {position_key: {'trail_stop': {...}, 'take_profit': {...}}}
        """
        path = self._path(account_number)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load risk config for ...{account_number[-4:]}: {e}")
            return {}

    def save_position(
        self,
        account_number: str,
        position_key: str,
        trail_stop_data: Optional[dict],
        take_profit_data: Optional[dict],
    ) -> None:
        """Persist trail stop and take profit configs for a single position.
        Only saves config fields — runtime state (order_id, triggered) is excluded.
        """
        all_configs = self.load(account_number)
        entry: dict = {}
        if trail_stop_data:
            entry['trail_stop'] = {
                'enabled': trail_stop_data.get('enabled', False),
                'percent': trail_stop_data.get('percent', 20.0),
                'highest_price': trail_stop_data.get('highest_price', 0.0),
            }
        if take_profit_data:
            entry['take_profit'] = {
                'enabled': take_profit_data.get('enabled', False),
                'percent': take_profit_data.get('percent', 50.0),
            }
        all_configs[position_key] = entry
        self._write(account_number, all_configs)

    def clear_position(self, account_number: str, position_key: str) -> None:
        """Remove saved config for a position (e.g. after it's been closed)."""
        all_configs = self.load(account_number)
        if position_key in all_configs:
            all_configs.pop(position_key)
            self._write(account_number, all_configs)

    def _write(self, account_number: str, data: dict) -> None:
        path = self._path(account_number)
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write risk config for ...{account_number[-4:]}: {e}")


# Module-level singleton
risk_config_store = RiskConfigStore()
