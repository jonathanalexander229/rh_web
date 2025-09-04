#!/usr/bin/env python3
"""
Account Detection Module
Handles detection and management of multiple Robinhood accounts (Regular, Roth IRA, etc.)
"""

import robin_stocks.robinhood as r
from typing import Dict, List, Optional
import logging

class AccountDetector:
    """Detects and manages information about available Robinhood accounts"""
    
    def __init__(self):
        self.logger = logging.getLogger('account_detector')
        self._accounts_cache = None
        self._account_prefix_map = {}  # Maps account_prefix -> full_account_number
    
    def _generate_account_prefix(self, account_number: str, account_type: str) -> str:
        """Generate a safe account prefix from type and last 4 digits"""
        last_four = account_number[-4:]
        
        # Map account types to short prefixes
        type_prefixes = {
            'Standard': 'STD',
            'Roth IRA': 'ROTH', 
            'Traditional IRA': 'TRAD',
            'Cash': 'CASH'
        }
        
        prefix = type_prefixes.get(account_type, 'ACC')
        return f"{prefix}-{last_four}"
    
    def get_account_number_from_prefix(self, account_prefix: str) -> Optional[str]:
        """Get full account number from account prefix"""
        return self._account_prefix_map.get(account_prefix)
    
    def detect_accounts(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Detect all available Robinhood accounts
        
        Args:
            force_refresh: Force refresh of cached account data
            
        Returns:
            Dict with account_number as key and account info as value
        """
        if self._accounts_cache and not force_refresh:
            return self._accounts_cache
            
        try:
            self.logger.info("Detecting available Robinhood accounts...")
            
            # Get all accounts using robin-stocks
            all_accounts_data = r.load_account_profile(dataType="regular")
            
            if not all_accounts_data or 'results' not in all_accounts_data:
                self.logger.error("Failed to retrieve account data from Robinhood")
                return {}
            
            accounts = {}
            for account_data in all_accounts_data['results']:
                account_number = account_data.get('account_number')
                if not account_number:
                    continue
                    
                # Only include active accounts
                if account_data.get('state') != 'active':
                    self.logger.warning(f"Skipping inactive account: {account_number}")
                    continue
                
                # Determine account type
                account_type = account_data.get('type', 'Standard')
                
                # Generate account prefix (e.g., STD-1234, ROTH-5678)
                account_prefix = self._generate_account_prefix(account_number, account_type)
                
                # Store mapping from prefix to full account number
                self._account_prefix_map[account_prefix] = account_number
                
                # Create display name with last 4 digits
                display_name = f"{account_type} (...{account_number})"
                
                accounts[account_prefix] = {
                    'number': account_number,
                    'prefix': account_prefix,
                    'type': account_type,
                    'display_name': display_name,
                    'state': account_data.get('state', 'unknown'),
                    'raw_data': account_data
                }
                
                self.logger.info(f"Found account: {display_name}")
            
            self._accounts_cache = accounts
            self.logger.info(f"Successfully detected {len(accounts)} active account(s)")
            return accounts
            
        except Exception as e:
            self.logger.error(f"Error detecting accounts: {e}")
            return {}
    
    def has_positions_or_orders(self, account_identifier: str) -> bool:
        """
        Check if an account has open positions
        
        Args:
            account_identifier: Either account prefix (STD-1234) or full account number
            
        Returns:
            True if account has positions, False otherwise
        """
        # Convert prefix to full account number if needed
        if '-' in account_identifier and len(account_identifier) <= 10:
            account_number = self.get_account_number_from_prefix(account_identifier)
            if not account_number:
                self.logger.error(f"Account prefix not found: {account_identifier}")
                return False
        else:
            account_number = account_identifier
        try:
            # Check for open option positions (efficient - no historical data)
            option_positions = r.get_open_option_positions(account_number=account_number)
            if option_positions and len(option_positions) > 0:
                self.logger.info(f"Account ...{account_number[-4:]} has {len(option_positions)} open option positions")
                return True
                
            # Check for open stock positions
            stock_positions = r.get_open_stock_positions(account_number=account_number)
            if stock_positions and len(stock_positions) > 0:
                self.logger.info(f"Account ...{account_number[-4:]} has {len(stock_positions)} open stock positions")
                return True
                
            self.logger.info(f"Account ...{account_number[-4:]} has no open positions")
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking positions for account ...{account_number[-4:]}: {e}")
            return False
    
    def get_active_accounts(self) -> Dict[str, Dict]:
        """
        Get accounts that have positions or orders (should have active risk managers)
        
        Returns:
            Dict of accounts that should have active risk managers
        """
        all_accounts = self.detect_accounts()
        active_accounts = {}
        
        for account_prefix, account_info in all_accounts.items():
            if self.has_positions_or_orders(account_prefix):
                active_accounts[account_prefix] = account_info
                self.logger.info(f"Account {account_info['display_name']} marked as active")
        
        return active_accounts
    
    def get_account_info(self, account_identifier: str) -> Optional[Dict]:
        """
        Get information for a specific account
        
        Args:
            account_identifier: Either account prefix (STD-1234) or full account number
            
        Returns:
            Account info dict or None if not found
        """
        accounts = self.detect_accounts()
        
        # If it looks like a prefix, use it directly
        if '-' in account_identifier and len(account_identifier) <= 10:
            return accounts.get(account_identifier)
        
        # Otherwise, find by full account number
        for account_prefix, account_info in accounts.items():
            if account_info['number'] == account_identifier:
                return account_info
        
        return None
    
    def list_accounts_summary(self) -> str:
        """
        Generate a summary string of all detected accounts
        
        Returns:
            Formatted string summarizing all accounts
        """
        accounts = self.detect_accounts()
        if not accounts:
            return "No accounts detected"
        
        summary = f"Detected {len(accounts)} account(s):\n"
        for account_number, info in accounts.items():
            has_activity = "✓" if self.has_positions_or_orders(account_number) else "○"
            summary += f"  {has_activity} {info['display_name']} - {info['state']}\n"
        
        return summary.strip()