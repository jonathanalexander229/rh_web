#!/usr/bin/env python3
"""
Market GEX (Gamma Exposure) calculator.

Net GEX at a strike = (call_gamma × call_OI - put_gamma × put_OI) × 100 × spot²

Positive net GEX → dealers net long gamma → market tends to mean-revert.
Negative net GEX → dealers net short gamma → moves tend to extend.
"""

from dataclasses import dataclass, field
import logging
import time
import robin_stocks.robinhood as r

logger = logging.getLogger(__name__)

_CONTRACT_SIZE = 100


@dataclass
class StrikeGex:
    strike: float
    call_gex: float    # positive contribution from calls
    put_gex: float     # negative contribution from puts (stored as negative value)
    net_gex: float     # call_gex + put_gex
    call_oi: int
    put_oi: int
    call_volume: int
    put_volume: int


@dataclass
class GexSnapshot:
    symbol: str
    underlying_price: float
    net_gex: float               # total net GEX across all strikes (dollars)
    zero_gamma_strike: float     # strike where cumulative GEX crosses zero (low→high)
    max_gex_strike: float        # strike with highest |net_gex|
    total_volume: int
    call_volume: int
    put_volume: int
    strikes: list = field(default_factory=list)   # list[StrikeGex], sorted ascending by strike
    refreshed_at: float = 0.0
    error: str = None


class GexCalculator:

    def __init__(self):
        self._cache: dict = {}   # symbol → GexSnapshot

    def get(self, symbol: str):
        return self._cache.get(symbol)

    def needs_refresh(self, symbol: str, interval_secs: float) -> bool:
        snap = self._cache.get(symbol)
        if snap is None or snap.error:
            return True
        return time.time() - snap.refreshed_at >= interval_secs

    def refresh(self, symbol: str, num_expirations: int = 3) -> GexSnapshot:
        """Fetch full option chain for up to num_expirations and compute GEX. Result is cached."""
        try:
            import datetime as _dt
            chain = r.get_chains(symbol)
            if not chain:
                raise ValueError(f"No chain returned for {symbol}")

            today = _dt.date.today()
            all_expirations = sorted(chain.get('expiration_dates', []))
            upcoming = [
                e for e in all_expirations
                if _dt.datetime.strptime(e, '%Y-%m-%d').date() >= today
            ]
            expirations = upcoming[:num_expirations]
            if not expirations:
                raise ValueError(f"No upcoming expirations for {symbol}")

            # Accumulate data per strike across all fetched expirations
            strike_data: dict = {}   # strike (float) → {call_gamma, call_oi, call_vol, put_gamma, put_oi, put_vol}
            underlying_price = 0.0

            for exp in expirations:
                for opt_type in ('call', 'put'):
                    try:
                        options = r.find_options_by_expiration(symbol, exp, optionType=opt_type) or []
                    except Exception as e:
                        logger.warning(f"GEX fetch failed {symbol} {exp} {opt_type}: {e}")
                        continue

                    for opt in options:
                        if not opt:
                            continue
                        # Extract underlying price from chain data on first occurrence
                        if underlying_price == 0.0:
                            try:
                                underlying_price = float(opt.get('last_trade_price') or 0)
                            except (TypeError, ValueError):
                                pass
                        try:
                            strike = float(opt.get('strike_price') or 0)
                            gamma = float(opt.get('gamma') or 0)
                            oi = int(float(opt.get('open_interest') or 0))
                            vol = int(float(opt.get('volume') or 0))
                        except (TypeError, ValueError):
                            continue

                        if strike <= 0:
                            continue

                        if strike not in strike_data:
                            strike_data[strike] = dict(
                                call_gamma=0.0, call_oi=0, call_vol=0,
                                put_gamma=0.0, put_oi=0, put_vol=0,
                            )
                        sd = strike_data[strike]
                        if opt_type == 'call':
                            sd['call_gamma'] += gamma
                            sd['call_oi'] += oi
                            sd['call_vol'] += vol
                        else:
                            sd['put_gamma'] += gamma
                            sd['put_oi'] += oi
                            sd['put_vol'] += vol

            if not strike_data:
                raise ValueError(f"No strike data returned for {symbol}")

            spot_sq = underlying_price ** 2
            strikes_list: list = []
            total_call_vol = 0
            total_put_vol = 0

            for strike in sorted(strike_data):
                sd = strike_data[strike]
                call_gex = sd['call_gamma'] * sd['call_oi'] * _CONTRACT_SIZE * spot_sq
                put_gex_abs = sd['put_gamma'] * sd['put_oi'] * _CONTRACT_SIZE * spot_sq
                strikes_list.append(StrikeGex(
                    strike=strike,
                    call_gex=call_gex,
                    put_gex=-put_gex_abs,   # negative for bar chart rendering
                    net_gex=call_gex - put_gex_abs,
                    call_oi=sd['call_oi'],
                    put_oi=sd['put_oi'],
                    call_volume=sd['call_vol'],
                    put_volume=sd['put_vol'],
                ))
                total_call_vol += sd['call_vol']
                total_put_vol += sd['put_vol']

            zero_gamma = _find_zero_crossing(strikes_list)
            max_gex_item = max(strikes_list, key=lambda s: abs(s.net_gex))

            snap = GexSnapshot(
                symbol=symbol,
                underlying_price=underlying_price,
                net_gex=sum(s.net_gex for s in strikes_list),
                zero_gamma_strike=zero_gamma,
                max_gex_strike=max_gex_item.strike,
                total_volume=total_call_vol + total_put_vol,
                call_volume=total_call_vol,
                put_volume=total_put_vol,
                strikes=strikes_list,
                refreshed_at=time.time(),
            )
            self._cache[symbol] = snap
            logger.info(
                f"GEX {symbol}: net={snap.net_gex / 1e6:.1f}M "
                f"zero_gamma={snap.zero_gamma_strike} max_gex={snap.max_gex_strike}"
            )
            return snap

        except Exception as e:
            logger.error(f"GEX refresh failed for {symbol}: {e}")
            snap = GexSnapshot(
                symbol=symbol, underlying_price=underlying_price,
                net_gex=0, zero_gamma_strike=0, max_gex_strike=0,
                total_volume=0, call_volume=0, put_volume=0,
                refreshed_at=time.time(), error=str(e),
            )
            self._cache[symbol] = snap
            return snap


def _find_zero_crossing(strikes: list) -> float:
    """Cumulative GEX from lowest to highest strike; interpolate where it crosses zero."""
    cumulative = 0.0
    prev_strike = None
    prev_cum = 0.0
    for s in sorted(strikes, key=lambda x: x.strike):
        cumulative += s.net_gex
        if prev_strike is not None and prev_cum != cumulative:
            crossed = (prev_cum <= 0 < cumulative) or (prev_cum >= 0 > cumulative)
            if crossed:
                span = abs(prev_cum) + abs(cumulative)
                return round(prev_strike + (s.strike - prev_strike) * abs(prev_cum) / span, 2)
        prev_strike = s.strike
        prev_cum = cumulative
    # No crossing found — return strike closest to zero net GEX
    return min(strikes, key=lambda s: abs(s.net_gex)).strike if strikes else 0.0


# Module-level singleton shared across all accounts
gex_calculator = GexCalculator()
