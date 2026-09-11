#!/usr/bin/env python3
"""
Market GEX (Gamma Exposure) calculator.

Net GEX at a strike = (call_gamma × call_OI - put_gamma × put_OI) × 100 × spot

Positive net GEX → dealers net long gamma → market tends to mean-revert.
Negative net GEX → dealers net short gamma → moves tend to extend.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import datetime
import logging
import threading
import time
import robin_stocks.robinhood as r
from robin_stocks.robinhood.helper import request_get
from robin_stocks.robinhood.urls import marketdata_options_url

logger = logging.getLogger('risk_manager')

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
        self._cache: dict = {}          # symbol → GexSnapshot
        self._in_progress: set = set()  # symbols currently being fetched
        self._lock = threading.Lock()

    def get(self, symbol: str):
        return self._cache.get(symbol)

    def needs_refresh(self, symbol: str, interval_secs: float) -> bool:
        snap = self._cache.get(symbol)
        if snap is None or snap.error:
            return True
        return time.time() - snap.refreshed_at >= interval_secs

    def refresh(self, symbol: str, expirations: list) -> GexSnapshot:
        """Fetch option chain for the given expiration dates and compute GEX. Result is cached."""
        with self._lock:
            if symbol in self._in_progress:
                logger.info(f"GEX {symbol}: fetch already in progress, skipping duplicate")
                return self._cache.get(symbol)
            self._in_progress.add(symbol)
        underlying_price = 0.0
        try:
            t0 = time.time()
            if not expirations:
                raise ValueError(f"No expirations provided for {symbol}")
            logger.info(f"GEX {symbol}: fetching {expirations}...")

            try:
                price_data = r.get_latest_price(symbol)
                underlying_price = float(price_data[0]) if price_data else 0.0
            except (TypeError, ValueError) as e:
                logger.warning(f"GEX {symbol}: get_latest_price failed: {e}")
                underlying_price = 0.0
            if underlying_price <= 0:
                logger.warning(f"GEX {symbol}: price=0 from get_latest_price, trying get_stock_quote_by_symbol")
                try:
                    quote = r.get_stock_quote_by_symbol(symbol)
                    underlying_price = float(quote.get('last_trade_price') or 0)
                except Exception as e:
                    logger.warning(f"GEX {symbol}: get_stock_quote_by_symbol failed: {e}")
            if underlying_price <= 0:
                raise ValueError(f"Could not get underlying price for {symbol}")

            strike_data: dict = {}

            def _fetch_exp(exp):
                """
                Fetch one expiration's full chain with ~3 API calls instead of ~200.
                find_options_by_expiration makes a separate marketdata call per option (N+1);
                this version batches them into a single request per 50 instruments.
                """
                try:
                    instruments = r.find_tradable_options(symbol, expirationDate=exp) or []
                    instruments = [o for o in instruments if o and o.get('expiration_date') == exp]
                    if not instruments:
                        return exp, []

                    # Batch-fetch market data (gamma, OI, volume) for all instruments at once
                    url_to_instrument = {o['url']: o for o in instruments if o.get('url')}
                    market_data: dict = {}
                    urls = list(url_to_instrument)
                    _batch_size = 50
                    for i in range(0, len(urls), _batch_size):
                        batch = urls[i:i + _batch_size]
                        try:
                            rows = request_get(
                                marketdata_options_url(), 'results',
                                {'instruments': ','.join(batch)}
                            ) or []
                            for row in rows:
                                if row and row.get('instrument'):
                                    market_data[row['instrument']] = row
                        except Exception as e:
                            logger.warning(f"GEX marketdata batch failed {symbol} {exp}: {e}")

                    merged = []
                    for inst in instruments:
                        md = market_data.get(inst.get('url'), {})
                        merged.append({**inst, **md})
                    return exp, merged
                except Exception as e:
                    logger.warning(f"GEX fetch failed {symbol} {exp}: {e}")
                    return exp, []

            with ThreadPoolExecutor(max_workers=len(expirations)) as pool:
                futures = {pool.submit(_fetch_exp, exp): exp for exp in expirations}
                for fut in as_completed(futures):
                    exp, options = fut.result()
                    for opt in options:
                        if not opt:
                            continue
                        try:
                            strike = float(opt.get('strike_price') or 0)
                            gamma = float(opt.get('gamma') or 0)
                            oi = int(float(opt.get('open_interest') or 0))
                            vol = int(float(opt.get('volume') or 0))
                            opt_type = (opt.get('type') or '').lower()
                        except (TypeError, ValueError):
                            continue

                        if strike <= 0 or opt_type not in ('call', 'put'):
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

            strikes_list: list = []
            total_call_vol = 0
            total_put_vol = 0

            for strike in sorted(strike_data):
                sd = strike_data[strike]
                call_gex = sd['call_gamma'] * sd['call_oi'] * _CONTRACT_SIZE * underlying_price
                put_gex_abs = sd['put_gamma'] * sd['put_oi'] * _CONTRACT_SIZE * underlying_price
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
                f"GEX {symbol}: net={snap.net_gex/1e6:.1f}M "
                f"zero_gamma={snap.zero_gamma_strike} max_gex={snap.max_gex_strike} "
                f"spot={snap.underlying_price} elapsed={time.time()-t0:.1f}s"
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
        finally:
            with self._lock:
                self._in_progress.discard(symbol)


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
