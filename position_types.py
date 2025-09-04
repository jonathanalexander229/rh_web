#!/usr/bin/env python3
"""
Position Data Types
Shared position classes to avoid circular imports
"""

from dataclasses import dataclass
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
    
    def __post_init__(self):
        if self.option_ids is None:
            self.option_ids = []