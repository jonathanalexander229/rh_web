#!/usr/bin/env python3
"""
Position Data Types
Shared position classes to avoid circular imports
"""

from dataclasses import dataclass, field
from typing import List

@dataclass
class LongPosition:
    """Represents a long option position"""
    symbol: str
    strike_price: float
    option_type: str  # 'call' or 'put'
    expiration_date: str
    quantity: int
    open_premium: float
    current_price: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    option_ids: List[str] = None
    # Greeks and market data (populated by calculate_pnl)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    implied_volatility: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    underlying_price: float = 0.0
    dte: int = 0
    moneyness: str = ""

    # Runtime state flags (not persisted directly — tracked per-loop)
    _stop_loss_submitted: bool = False
    _stop_loss_order_id: str = None
    _last_greeks_refresh: float = 0.0

    def __post_init__(self):
        if self.option_ids is None:
            self.option_ids = []