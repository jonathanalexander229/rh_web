import logging
import json
import datetime
import os
from typing import Dict, Any, Optional

class RiskManagerLogger:
    """Handles logging for the risk manager: actions and real orders"""
    
    def __init__(self, log_dir: str = 'logs'):
        self.log_dir = log_dir
        self._ensure_log_directory()
        self._setup_loggers()
    
    def _ensure_log_directory(self):
        """Ensure the logs directory exists"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
    
    def _setup_loggers(self):
        """Set up all three loggers"""
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        
        # Main risk manager logger
        self.main_logger = logging.getLogger('risk_manager')
        if not self.main_logger.handlers:  # Only setup once
            self.main_logger.setLevel(logging.INFO)
            main_handler = logging.FileHandler(os.path.join(self.log_dir, f'risk_manager_{date_str}.log'))
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            main_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            self.main_logger.addHandler(main_handler)
            self.main_logger.addHandler(console_handler)
        
        # Real orders logger
        self.real_orders_logger = logging.getLogger('real_orders')
        if not self.real_orders_logger.handlers:  # Only setup once
            self.real_orders_logger.setLevel(logging.INFO)
            real_handler = logging.FileHandler(os.path.join(self.log_dir, f'real_orders_{date_str}.log'))
            real_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
            self.real_orders_logger.addHandler(real_handler)
            self.real_orders_logger.propagate = False
        
        # Simulation logging removed
    
    def log_session_start(self):
        """Log the start of a risk manager session"""
        self.main_logger.info("="*60)
        self.main_logger.info("RISK MANAGER SESSION STARTED")
        self.main_logger.info("="*60)
    
    def log_action(self, message: str, level: str = 'info'):
        """Log general risk manager actions"""
        if level == 'info':
            self.main_logger.info(message)
        elif level == 'warning':
            self.main_logger.warning(message)
        elif level == 'error':
            self.main_logger.error(message)
    
    def log_real_order(self, 
                      order_id: str,
                      symbol: str,
                      time_sent: datetime.datetime,
                      time_confirmed: datetime.datetime,
                      request_params: Dict[str, Any],
                      response: Dict[str, Any],
                      order_type: str = 'limit'):
        """Log a real Robinhood order (non-blocking)"""
        try:
            order_data = {
                'order_id': order_id,
                'symbol': symbol,
                'time_sent': time_sent.isoformat(),
                'time_confirmed': time_confirmed.isoformat(),
                'order_type': order_type,
                'request': request_params,
                'response': response
            }
            self.real_orders_logger.info(json.dumps(order_data))
        except Exception:
            pass  # Don't let logging errors block order processing
    
    # Simulation logging removed
    
    def log_order_update(self, order_id: str, status: str, details: Optional[Dict] = None):
        """Log order status updates"""
        try:
            message = f"Order {order_id}: {status}"
            if details:
                message += f" - {json.dumps(details)}"
            self.main_logger.info(message)
        except Exception:
            pass
