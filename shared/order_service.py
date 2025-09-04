#!/usr/bin/env python3
"""
Order Service (Live Only)
Encapsulates robin_stocks order submissions and logging.
"""

import datetime
from typing import Optional, Dict, Any
import robin_stocks.robinhood as r
import robin_stocks.robinhood.helper as helper
from robin_stocks.robinhood.urls import option_orders_url


class OrderService:
    def __init__(self, rm_logger):
        """rm_logger: instance of RiskManagerLogger for structured logging"""
        self.rm_logger = rm_logger

    def submit_close(self, position, limit_price: float) -> Dict[str, Any]:
        """Submit a sell-to-close limit order for a long option position."""
        try:
            time_sent = datetime.datetime.now()

            order_result = r.order_sell_option_limit(
                positionEffect='close',
                creditOrDebit='credit',
                price=round(limit_price, 2),
                symbol=position.symbol,
                quantity=position.quantity,
                expirationDate=position.expiration_date,
                strike=position.strike_price,
                optionType=position.option_type,
                timeInForce='gtc'
            )

            if order_result and 'id' in order_result:
                order_id = order_result['id']
                time_confirmed = datetime.datetime.now()

                request_params = {
                    'positionEffect': 'close',
                    'creditOrDebit': 'credit',
                    'limitPrice': round(limit_price, 2),
                    'stopPrice': None,
                    'symbol': position.symbol,
                    'quantity': position.quantity,
                    'expirationDate': position.expiration_date,
                    'strike': position.strike_price,
                    'optionType': position.option_type,
                    'timeInForce': 'gtc'
                }

                self.rm_logger.log_real_order(
                    order_id=order_id,
                    symbol=position.symbol,
                    time_sent=time_sent,
                    time_confirmed=time_confirmed,
                    request_params=request_params,
                    response=order_result,
                    order_type='limit'
                )

                return {
                    'success': True,
                    'order_id': order_id,
                    'order_result': order_result
                }

            return {
                'success': False,
                'error': 'No order ID returned',
                'order_result': order_result
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def submit_trailing_stop(self, position, limit_price: float, stop_price: float) -> Dict[str, Any]:
        """Submit a stop-limit order for a long option position (trailing stop execution)."""
        try:
            time_sent = datetime.datetime.now()

            order_result = r.order_sell_option_stop_limit(
                positionEffect='close',
                creditOrDebit='credit',
                limitPrice=round(limit_price, 2),
                stopPrice=round(stop_price, 2),
                symbol=position.symbol,
                quantity=position.quantity,
                expirationDate=position.expiration_date,
                strike=position.strike_price,
                optionType=position.option_type,
                timeInForce='gtc'
            )

            if order_result and 'id' in order_result:
                order_id = order_result['id']
                time_confirmed = datetime.datetime.now()

                request_params = {
                    'positionEffect': 'close',
                    'creditOrDebit': 'credit',
                    'limitPrice': round(limit_price, 2),
                    'stopPrice': round(stop_price, 2),
                    'symbol': position.symbol,
                    'quantity': position.quantity,
                    'expirationDate': position.expiration_date,
                    'strike': position.strike_price,
                    'optionType': position.option_type,
                    'timeInForce': 'gtc'
                }

                self.rm_logger.log_real_order(
                    order_id=order_id,
                    symbol=position.symbol,
                    time_sent=time_sent,
                    time_confirmed=time_confirmed,
                    request_params=request_params,
                    response=order_result,
                    order_type='stop_limit'
                )

                return {
                    'success': True,
                    'order_id': order_id,
                    'order_result': order_result
                }

            return {
                'success': False,
                'error': 'No order ID returned',
                'order_result': order_result
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Attempt to cancel an existing option order by ID."""
        try:
            # robin_stocks exposes a cancel function for option orders
            result = r.cancel_option_order(order_id)
            # Some versions return None on success; treat absence of error as success
            if result is None or (isinstance(result, dict) and result.get('state') in (None, 'canceled', 'cancelled')):
                return {'success': True, 'message': f'Order {order_id} cancellation requested'}
            # If API returns a dict with details, pass it through
            return {'success': True, 'message': f'Order {order_id} cancellation requested', 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_order_info(self, order_id: str) -> Dict[str, Any]:
        """Fetch details for a specific option order id."""
        try:
            details = r.get_option_order_info(order_id)
            return {'success': True, 'details': details}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def list_open_orders(self, max_pages: int = 5) -> Dict[str, Any]:
        """List open option orders by paging the Robinhood API (limited pages)."""
        try:
            url = option_orders_url()
            all_orders = []
            for _ in range(max_pages):
                data = helper.request_get(url, 'regular')
                if data and 'results' in data:
                    all_orders.extend(data['results'])
                    if data.get('next'):
                        url = data['next']
                    else:
                        break
                else:
                    break
            open_states = {'queued', 'confirmed', 'partially_filled'}
            filtered = [o for o in all_orders if o.get('state') in open_states]
            return {'success': True, 'orders': filtered}
        except Exception as e:
            return {'success': False, 'error': str(e)}
