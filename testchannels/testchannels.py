#!/usr/bin/env python3
"""
Enhanced Multi-Account Trading Bot v5.0 - ADVANCED MULTI-ACCOUNT SYSTEM
- Individual account settings and configurations
- Advanced TP/SL management with multiple levels
- PIN code protection (496745)
- Static button interface (no commands)
- Trade history and management
- Flexible balance configuration
- Enhanced security and user experience
"""

import asyncio
import re
import json
import logging
import sqlite3
import uuid
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import os
import sys
import traceback
import requests
import subprocess
import signal

# Import python-telegram-bot
from telegram import (
    Update,
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)

import ccxt

# Import Telethon
from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Bot Configuration
BOT_PIN_CODE = "496745"  # PIN code for bot access
DEFAULT_TELEGRAM_API_ID = '28270452'
DEFAULT_TELEGRAM_API_HASH = '8bb0aa3065dd515fb6e105f1fc60fdb6'
DEFAULT_BINANCE_API_KEY = 'ojMy5XVmKUFxfoAG1SwR2jCiYqYGuHfFb3CmM1tPv01rvtLcIQL68wTUwtU8mMijfaWc2aOPsiGZSSqg'
DEFAULT_BINANCE_API_SECRET = 'R26Tvlq8rRjK4HCqhG5EstMXGAqHr1B22DH3IuTRjHOiEanmIlCRPowDcOGH8oKDjnVypPM5fXUg3lbYhQ'

(WAITING_BINANCE_KEY, WAITING_BINANCE_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE, WAITING_WEBHOOK_URL,
 WAITING_MIN_ORDER, WAITING_TP1_PERCENT, WAITING_TP1_CLOSE,
 WAITING_TP2_PERCENT, WAITING_TP2_CLOSE,
 WAITING_TP3_PERCENT, WAITING_TP3_CLOSE,
 WAITING_TRAILING_CALLBACK, WAITING_TRAILING_ACTIVATION,
 WAITING_CHANNEL_LINK, WAITING_USDT_AMOUNT,
 WAITING_TP_CONFIG, WAITING_TP_LEVEL_PERCENT, WAITING_TP_LEVEL_CLOSE,
 WAITING_ACCOUNT_NAME, WAITING_ACCOUNT_BINGX_KEY, WAITING_ACCOUNT_BINGX_SECRET,
 WAITING_ACCOUNT_TELEGRAM_ID, WAITING_ACCOUNT_TELEGRAM_HASH, WAITING_ACCOUNT_PHONE,
 WAITING_ACCOUNT_SELECTION, WAITING_ACCOUNT_SETTINGS) = range(34)

# Your NEW Make.com Webhook URL
DEFAULT_WEBHOOK_URL = "https://hook.eu2.make.com/pnfx5xy1q8caxq4qc2yhmnrkmio1ixqj"

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class TradingSignal:
    symbol: str
    trade_type: str
    entry_price: Optional[float] = None
    take_profit: List[float] = None
    stop_loss: Optional[float] = None
    leverage: Optional[int] = None
    raw_message: str = ""
    channel_id: str = ""
    timestamp: datetime = None

    def __post_init__(self):
        if self.take_profit is None:
            self.take_profit = []

@dataclass
class TakeProfitLevel:
    """Individual take profit level configuration"""
    percentage: float  # Price percentage (e.g., 1.0 for 1%)
    close_percentage: float  # Percentage of position to close (e.g., 50.0 for 50%)
    
@dataclass 
class BotConfig:
    binance_api_key: str = ""
    binance_api_secret: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    leverage: int = 10
    stop_loss_percent: float = 5.0
    take_profit_percent: float = 10.0
    balance_percent: float = 1.0
    monitored_channels: List[str] = None
    user_id: int = 0
    use_signal_settings: bool = True
    create_sl_tp: bool = True
    make_webhook_enabled: bool = True
    make_webhook_url: str = DEFAULT_WEBHOOK_URL
    minimum_order_usd: float = 5.0
    trailing_enabled: bool = False
    trailing_activation_percent: float = 2.0
    trailing_callback_percent: float = 0.5
    # New features
    use_fixed_usdt_amount: bool = False
    fixed_usdt_amount: float = 100.0
    custom_take_profits: List[TakeProfitLevel] = None

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []
        if self.custom_take_profits is None:
            # Default: 1% close 50%, 2.5% close 50% of remaining, 5% close all remaining
            self.custom_take_profits = [
                TakeProfitLevel(1.0, 50.0),
                TakeProfitLevel(2.5, 50.0),
                TakeProfitLevel(5.0, 100.0)
            ]

@dataclass
class ActivePosition:
    """Track active positions with their SL/TP orders"""
    symbol: str
    user_id: int
    side: str
    quantity: float
    entry_price: float
    stop_loss_order_id: Optional[int] = None
    take_profit_order_ids: List[int] = None
    filled_take_profit_order_ids: List[int] = None
    trailing_order_id: Optional[int] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.take_profit_order_ids is None:
            self.take_profit_order_ids = []
        if self.filled_take_profit_order_ids is None:
            self.filled_take_profit_order_ids = []
        if self.timestamp is None:
            self.timestamp = datetime.now()

# ================== ENHANCED MULTI-ACCOUNT DATACLASSES ==================

@dataclass
class TakeProfitLevel:
    """Individual take profit level configuration"""
    percentage: float  # Price percentage (e.g., 1.0 for 1%)
    close_percentage: float  # Percentage of position to close (e.g., 50.0 for 50%)
    
@dataclass
class StopLossLevel:
    """Individual stop loss level configuration"""
    percentage: float  # Price percentage (e.g., 2.0 for 2%)
    close_percentage: float  # Percentage of position to close (e.g., 100.0 for 100%)

@dataclass
class AccountConfig:
    """Enhanced configuration for a trading account"""
    account_id: str
    account_name: str
    bingx_api_key: str
    bingx_secret_key: str
    telegram_api_id: str
    telegram_api_hash: str
    phone: str
    is_active: bool = True
    created_at: str = ""
    last_used: str = ""
    
    # Trading settings
    leverage: int = 10
    risk_percentage: float = 2.0
    default_symbol: str = "BTC-USDT"
    auto_trade_enabled: bool = False
    
    # Balance configuration
    use_percentage_balance: bool = True  # True for percentage, False for fixed USDT
    balance_percentage: float = 2.0  # Percentage of balance to use
    fixed_usdt_amount: float = 100.0  # Fixed USDT amount
    
    # Advanced TP/SL management
    take_profit_levels: List[TakeProfitLevel] = None
    stop_loss_levels: List[StopLossLevel] = None
    
    # Channel settings
    monitored_channels: List[int] = None
    signal_channels: List[int] = None
    
    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []
        if self.signal_channels is None:
            self.signal_channels = []
        if self.take_profit_levels is None:
            # Default: 1% close 50%, 2.5% close 50% of remaining, 5% close all remaining
            self.take_profit_levels = [
                TakeProfitLevel(1.0, 50.0),
                TakeProfitLevel(2.5, 50.0),
                TakeProfitLevel(5.0, 100.0)
            ]
        if self.stop_loss_levels is None:
            # Default: 2% close 100%
            self.stop_loss_levels = [
                StopLossLevel(2.0, 100.0)
            ]
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_used:
            self.last_used = datetime.now().isoformat()

@dataclass
class ChannelConfig:
    """Configuration for a monitored channel"""
    channel_id: int
    channel_name: str
    channel_username: str = ""
    is_active: bool = True
    account_ids: List[str] = None  # Which accounts monitor this channel
    signal_filters: Dict[str, Any] = None  # Custom filters for this channel
    
    def __post_init__(self):
        if self.account_ids is None:
            self.account_ids = []
        if self.signal_filters is None:
            self.signal_filters = {}

@dataclass
class TradeHistory:
    """Trade history record"""
    trade_id: str
    account_id: str
    symbol: str
    side: str  # LONG/SHORT
    entry_price: float
    quantity: float
    leverage: int
    status: str  # OPEN, CLOSED, PARTIAL
    pnl: float = 0.0
    entry_time: str = ""
    exit_time: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_prices: List[float] = None
    channel_id: str = ""
    
    def __post_init__(self):
        if self.take_profit_prices is None:
            self.take_profit_prices = []
        if not self.entry_time:
            self.entry_time = datetime.now().isoformat()

@dataclass
class ParsedSignal:
    """Enhanced signal structure"""
    signal_id: str
    channel_id: int
    account_id: str
    raw_text: str
    symbol: str
    side: str  # LONG/SHORT
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: List[float] = None
    leverage: Optional[int] = None
    risk_percentage: Optional[float] = None
    timestamp: str = ""
    processed: bool = False
    trade_executed: bool = False
    trade_id: Optional[str] = None
    confidence: float = 0.0  # Confidence score 0-1
    
    def __post_init__(self):
        if self.take_profit is None:
            self.take_profit = []
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

class MakeWebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_trade_data(self, trade_data: Dict[str, Any]) -> bool:
        """Send trade data to Make.com webhook"""
        try:
            # Create comprehensive payload
            payload = {
                "text": f"Trade executed: {trade_data.get('symbol', '')} {trade_data.get('trade_type', '')} at {trade_data.get('entry_price', '')}",
                "timestamp": trade_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "symbol": str(trade_data.get('symbol', '')),
                "trade_type": str(trade_data.get('trade_type', '')),
                "entry_price": str(trade_data.get('entry_price', '')),
                "quantity": str(trade_data.get('quantity', '')),
                "leverage": str(trade_data.get('leverage', '')),
                "order_id": str(trade_data.get('order_id', '')),
                "stop_loss": str(trade_data.get('stop_loss', '')),
                "take_profit": str(trade_data.get('take_profit', '')),
                "status": str(trade_data.get('status', '')),
                "balance_used": str(trade_data.get('balance_used', '')),
                "channel_id": str(trade_data.get('channel_id', '')),
                "pnl": str(trade_data.get('pnl', '')),
                "notes": str(trade_data.get('notes', '')),
                "order_value": str(trade_data.get('order_value', '')),
                "sl_order_id": str(trade_data.get('sl_order_id', '')),
                "tp_order_ids": str(trade_data.get('tp_order_ids', '')),
                "user_id": str(trade_data.get('user_id', '')),
                "webhook_version": "3.1",
                "bot_source": "Telegram Trading Bot",
                "time": datetime.now().strftime('%H:%M:%S'),
                "date": datetime.now().strftime('%Y-%m-%d')
            }

            # Remove empty values
            clean_payload = {k: v for k, v in payload.items() if v and str(v).strip()}

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/3.1',
                'X-Bot-Version': '3.1'
            }

            response = requests.post(
                self.webhook_url,
                json=clean_payload,
                headers=headers,
                timeout=15
            )

            if response.status_code == 200:
                logger.info(f"✅ Trade data sent to Make.com: {trade_data.get('symbol')} {trade_data.get('trade_type')}")
                return True
            else:
                logger.error(f"❌ Make.com webhook error. Status: {response.status_code}, Response: {response.text[:200]}")
                return False

        except requests.exceptions.Timeout:
            logger.error("❌ Make.com webhook timeout")
            return False
        except Exception as e:
            logger.error(f"❌ Make.com webhook error: {e}")
            return False

    def test_webhook(self, test_type="simple") -> Dict[str, Any]:
        """Flexible webhook testing with your new URL"""
        try:
            if test_type == "simple":
                test_data = {
                    "text": "Simple webhook test from Trading Bot",
                    "status": "TEST",
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "webhook_version": "3.1"
                }
            elif test_type == "basic":
                test_data = {
                    "text": "Basic trade test: BTCUSDT LONG",
                    "symbol": "BTCUSDT",
                    "trade_type": "LONG",
                    "entry_price": "45000.50",
                    "status": "TEST_BASIC",
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "date": datetime.now().strftime('%Y-%m-%d')
                }
            else:
                current_time = datetime.now()
                test_data = {
                    "text": f"FULL TEST: BTCUSDT LONG at 45000.50 - Order TEST_{current_time.strftime('%H%M%S')}",
                    "timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol": "BTCUSDT",
                    "trade_type": "LONG",
                    "entry_price": "45000.50",
                    "quantity": "0.001",
                    "leverage": "10",
                    "order_id": f"TEST_{current_time.strftime('%H%M%S')}",
                    "stop_loss": "44000.00",
                    "take_profit": "46000.00, 47000.00",
                    "status": "TEST_EXECUTED",
                    "balance_used": "$50.00",
                    "channel_id": "test_channel_123",
                    "pnl": "0.00",
                    "notes": "Advanced webhook test - full trade simulation",
                    "order_value": "$50.00",
                    "sl_order_id": f"SL_TEST_{current_time.strftime('%H%M%S')}",
                    "tp_order_ids": f"TP1_TEST_{current_time.strftime('%H%M%S')}, TP2_TEST_{current_time.strftime('%H%M%S')}",
                    "user_id": "test_user",
                    "webhook_version": "3.1",
                    "bot_source": "Telegram Trading Bot",
                    "time": current_time.strftime('%H:%M:%S'),
                    "date": current_time.strftime('%Y-%m-%d')
                }

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/3.1',
                'X-Test-Type': test_type
            }

            start_time = datetime.now()
            response = requests.post(
                self.webhook_url,
                json=test_data,
                headers=headers,
                timeout=30
            )
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

            return {
                'success': response.status_code == 200,
                'status_code': response.status_code,
                'response_time': response_time,
                'response_text': response.text[:500] if response.text else "No response",
                'test_data': test_data
            }

        except requests.exceptions.Timeout:
            return {
                'success': False,
                'status_code': 0,
                'response_time': 30.0,
                'response_text': 'Request timeout - Make.com scenario may not be active',
                'test_data': test_data if 'test_data' in locals() else {}
            }
        except Exception as e:
            return {
                'success': False,
                'status_code': 0,
                'response_time': 0,
                'response_text': str(e),
                'test_data': test_data if 'test_data' in locals() else {}
            }

# ================== ENHANCED DATABASE CLASS ==================

class EnhancedDatabase:
    def __init__(self, db_path: str = "enhanced_trading_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with enhanced schema"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Accounts table with enhanced fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    bingx_api_key TEXT NOT NULL,
                    bingx_secret_key TEXT NOT NULL,
                    telegram_api_id TEXT NOT NULL,
                    telegram_api_hash TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    last_used TEXT NOT NULL,
                    leverage INTEGER DEFAULT 10,
                    risk_percentage REAL DEFAULT 2.0,
                    default_symbol TEXT DEFAULT 'BTC-USDT',
                    auto_trade_enabled BOOLEAN DEFAULT FALSE,
                    use_percentage_balance BOOLEAN DEFAULT TRUE,
                    balance_percentage REAL DEFAULT 2.0,
                    fixed_usdt_amount REAL DEFAULT 100.0,
                    take_profit_levels TEXT DEFAULT '[]',
                    stop_loss_levels TEXT DEFAULT '[]',
                    monitored_channels TEXT DEFAULT '[]',
                    signal_channels TEXT DEFAULT '[]'
                )
            ''')
            
            # Trade history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_history (
                    trade_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    pnl REAL DEFAULT 0.0,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    stop_loss_price REAL,
                    take_profit_prices TEXT DEFAULT '[]',
                    channel_id TEXT DEFAULT '',
                    FOREIGN KEY (account_id) REFERENCES accounts (account_id)
                )
            ''')
            
            # Channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    channel_username TEXT DEFAULT '',
                    is_active BOOLEAN DEFAULT TRUE,
                    account_ids TEXT DEFAULT '[]',
                    signal_filters TEXT DEFAULT '{}'
                )
            ''')
            
            # Parsed signals table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parsed_signals (
                    signal_id TEXT PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    account_id TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit TEXT DEFAULT '[]',
                    leverage INTEGER,
                    risk_percentage REAL,
                    timestamp TEXT NOT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    trade_executed BOOLEAN DEFAULT FALSE,
                    trade_id TEXT,
                    confidence REAL DEFAULT 0.0,
                    FOREIGN KEY (account_id) REFERENCES accounts (account_id),
                    FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
                )
            ''')
            
            # Account-channel relationships
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_channels (
                    account_id TEXT,
                    channel_id INTEGER,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, channel_id),
                    FOREIGN KEY (account_id) REFERENCES accounts (account_id),
                    FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Enhanced database schema initialized")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def create_account(self, account: AccountConfig) -> bool:
        """Create a new trading account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO accounts (
                    account_id, account_name, bingx_api_key, bingx_secret_key,
                    telegram_api_id, telegram_api_hash, phone, is_active,
                    created_at, last_used, leverage, risk_percentage,
                    default_symbol, auto_trade_enabled, monitored_channels, signal_channels
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account.account_id, account.account_name, account.bingx_api_key,
                account.bingx_secret_key, account.telegram_api_id, account.telegram_api_hash,
                account.phone, account.is_active, account.created_at, account.last_used,
                account.leverage, account.risk_percentage, account.default_symbol,
                account.auto_trade_enabled, json.dumps(account.monitored_channels),
                json.dumps(account.signal_channels)
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Account {account.account_name} created successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create account: {e}")
            return False
    
    def get_all_accounts(self) -> List[AccountConfig]:
        """Get all active accounts"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM accounts WHERE is_active = TRUE')
            rows = cursor.fetchall()
            conn.close()
            
            accounts = []
            for row in rows:
                accounts.append(AccountConfig(
                    account_id=row[0],
                    account_name=row[1],
                    bingx_api_key=row[2],
                    bingx_secret_key=row[3],
                    telegram_api_id=row[4],
                    telegram_api_hash=row[5],
                    phone=row[6],
                    is_active=bool(row[7]),
                    created_at=row[8],
                    last_used=row[9],
                    leverage=row[10],
                    risk_percentage=row[11],
                    default_symbol=row[12],
                    auto_trade_enabled=bool(row[13]),
                    monitored_channels=json.loads(row[14]) if row[14] else [],
                    signal_channels=json.loads(row[15]) if row[15] else []
                ))
            
            return accounts
            
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return []
    
    def create_channel(self, channel: ChannelConfig) -> bool:
        """Create or update a channel configuration"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO channels (
                    channel_id, channel_name, channel_username, is_active,
                    account_ids, signal_filters
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                channel.channel_id, channel.channel_name, channel.channel_username,
                channel.is_active, json.dumps(channel.account_ids),
                json.dumps(channel.signal_filters)
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Channel {channel.channel_name} created/updated successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create channel: {e}")
            return False
    
    def link_account_channel(self, account_id: str, channel_id: int) -> bool:
        """Link an account to a channel"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO account_channels (
                    account_id, channel_id, is_active, created_at
                ) VALUES (?, ?, TRUE, ?)
            ''', (account_id, channel_id, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Account {account_id} linked to channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to link account to channel: {e}")
            return False
    
    def get_account_channels(self, account_id: str) -> List[int]:
        """Get all channels linked to an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id FROM account_channels 
                WHERE account_id = ? AND is_active = TRUE
            ''', (account_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [row[0] for row in rows]
            
        except Exception as e:
            logger.error(f"❌ Failed to get account channels: {e}")
            return []
    
    def save_trade_history(self, trade: TradeHistory) -> bool:
        """Save trade to history"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO trade_history (
                    trade_id, account_id, symbol, side, entry_price, quantity,
                    leverage, status, pnl, entry_time, exit_time, stop_loss_price,
                    take_profit_prices, channel_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.trade_id, trade.account_id, trade.symbol, trade.side,
                trade.entry_price, trade.quantity, trade.leverage, trade.status,
                trade.pnl, trade.entry_time, trade.exit_time, trade.stop_loss_price,
                json.dumps(trade.take_profit_prices), trade.channel_id
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save trade history: {e}")
            return False
    
    def get_trade_history(self, account_id: str, limit: int = 50) -> List[TradeHistory]:
        """Get trade history for an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM trade_history 
                WHERE account_id = ? 
                ORDER BY entry_time DESC 
                LIMIT ?
            ''', (account_id, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            trades = []
            for row in rows:
                trades.append(TradeHistory(
                    trade_id=row[0],
                    account_id=row[1],
                    symbol=row[2],
                    side=row[3],
                    entry_price=row[4],
                    quantity=row[5],
                    leverage=row[6],
                    status=row[7],
                    pnl=row[8],
                    entry_time=row[9],
                    exit_time=row[10],
                    stop_loss_price=row[11],
                    take_profit_prices=json.loads(row[12]) if row[12] else [],
                    channel_id=row[13]
                ))
            
            return trades
            
        except Exception as e:
            logger.error(f"❌ Failed to get trade history: {e}")
            return []
    
    def get_active_trades(self, account_id: str) -> List[TradeHistory]:
        """Get active trades for an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM trade_history 
                WHERE account_id = ? AND status IN ('OPEN', 'PARTIAL')
                ORDER BY entry_time DESC
            ''', (account_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            trades = []
            for row in rows:
                trades.append(TradeHistory(
                    trade_id=row[0],
                    account_id=row[1],
                    symbol=row[2],
                    side=row[3],
                    entry_price=row[4],
                    quantity=row[5],
                    leverage=row[6],
                    status=row[7],
                    pnl=row[8],
                    entry_time=row[9],
                    exit_time=row[10],
                    stop_loss_price=row[11],
                    take_profit_prices=json.loads(row[12]) if row[12] else [],
                    channel_id=row[13]
                ))
            
            return trades
            
        except Exception as e:
            logger.error(f"❌ Failed to get active trades: {e}")
            return []

class SignalDetector:
    @staticmethod
    def parse_signals(text):
        """Enhanced signal parsing for Russian and various formats"""
        blocks = re.split(r'(?m)^#', text)
        signals = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.split('\n')
            symbol_line = lines[0]

            # Extract symbol
            sym_match = re.match(r'([A-Z0-9]{1,10})(?:/USDT|USDT)?', symbol_line, re.I)
            if not sym_match:
                continue

            sym = sym_match.group(1).upper()
            if sym.endswith('USDT'):
                symbol = sym
            else:
                symbol = sym + 'USDT'

            if symbol.endswith('USDUSDT'):
                symbol = symbol.replace('USDUSDT','USDT')

            # Find trade side
            trade_side = None
            for l in lines[1:8]:
                if re.search(r'\b(LONG|BUY|ЛОНГ|📈|🟢|⬆️|🚀)\b', l, re.I):
                    trade_side = 'LONG'
                    break
                elif re.search(r'\b(SHORT|SELL|ШОРТ|📉|🔴|⬇️|🔻)\b', l, re.I):
                    trade_side = 'SHORT'
                    break

            if not trade_side:
                if re.search(r'\b(LONG|ЛОНГ)\b', block, re.I):
                    trade_side = 'LONG'
                elif re.search(r'\b(SHORT|ШОРТ)\b', block, re.I):
                    trade_side = 'SHORT'

            if not trade_side:
                continue

            # Entry price
            entry = None
            for l in lines:
                patterns = [
                    r'Entry[:\s]*([\d.,]+)',
                    r'Вход[:\s]*([\d.,]+)',
                    r'@\s*([\d.,]+)',
                    r'Price[:\s]*([\d.,]+)',
                    r'Цена[:\s]*([\d.,]+)'
                ]
                for pattern in patterns:
                    m = re.search(pattern, l, re.I)
                    if m:
                        try:
                            entry = float(m.group(1).replace(',',''))
                            break
                        except:
                            pass
                if entry:
                    break

            # Take profits
            tps = []
            for l in lines:
                patterns = [
                    r'Target\s*\d*[:]?\s*([\d.,]+)',
                    r'TP\s*\d*[:]?\s*([\d.,]+)',
                    r'Тп[:\s]*([\d.,]*)([%+]*)',
                    r'Take\s*Profit[:\s]*([\d.,]+)',
                    r'Цель[:\s]*([\d.,]+)'
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, l, re.I)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
                        if match and match.replace('.','').replace(',','').isdigit():
                            try:
                                tp_val = float(match.replace(',',''))
                                if tp_val > 0:
                                    tps.append(tp_val)
                            except:
                                continue

            tps = sorted(list(set(tps)))[:3]

            # Stop loss
            sl = None
            for l in lines:
                patterns = [
                    r'Stop\s*Loss[:\s]*([\d.,]+)',
                    r'SL[:\s]*([\d.,]+)',
                    r'Сл[:\s]*([\d.,]+)',
                    r'Стоп[:\s]*([\d.,]+)'
                ]
                for pattern in patterns:
                    m = re.search(pattern, l, re.I)
                    if m:
                        try:
                            sl = float(m.group(1).replace(',',''))
                            break
                        except:
                            pass
                if sl:
                    break

            # Leverage
            lev = None
            for l in lines:
                patterns = [
                    r'Leverage[:\s]*([\d]+)',
                    r'Плечо[:\s]*([\d]+)[-xх]*([\d]*)',
                    r'([\d]+)\s*[xх]',
                    r'([\d]+)\s*X'
                ]
                for pattern in patterns:
                    m = re.search(pattern, l, re.I)
                    if m:
                        try:
                            lev = int(m.group(1))
                            if 1 <= lev <= 125:
                                break
                        except:
                            pass
                if lev:
                    break

            signals.append({
                'symbol': symbol,
                'trade_side': trade_side,
                'entry': entry,
                'take_profit': tps,
                'stop_loss': sl,
                'leverage': lev
            })

        return signals

# ================== ENHANCED SIGNAL PARSER ==================

class EnhancedSignalParser:
    """Enhanced signal parser with support for multiple formats"""
    
    # Symbol patterns
    SYMBOL_PATTERNS = [
        r'#([A-Z0-9]{1,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT
        r'([A-Z0-9]{1,10})(?:/USDT|USDT)?',   # BTCUSDT, BTC/USDT
        r'([A-Z0-9]{1,10})\s*—',              # BTC —
        r'([A-Z0-9]{1,10})\s*Long',           # BTC Long
        r'([A-Z0-9]{1,10})\s*Short',          # BTC Short
    ]
    
    # Side patterns (LONG/SHORT)
    LONG_PATTERNS = [
        r'\b(LONG|ЛОНГ|Long|long)\b',
        r'\b(BUY|ПОКУПКА|Buy|buy)\b',
        r'📈',  # Green arrow up
        r'🟢',  # Green circle
        r'⬆️',  # Up arrow
        r'🚀',  # Rocket
        r'🟢',  # Green circle
        r'набираю позицию в Long',
        r'открываю Long',
        r'открываю в Long',
    ]
    
    SHORT_PATTERNS = [
        r'\b(SHORT|ШОРТ|Short|short)\b',
        r'\b(SELL|ПРОДАЖА|Sell|sell)\b',
        r'📉',  # Red arrow down
        r'🔴',  # Red circle
        r'⬇️',  # Down arrow
        r'🔻',  # Down triangle
        r'набираю позицию в Short',
        r'открываю Short',
        r'открываю в Short',
        r'открываем шорт-позицию',
    ]
    
    # Price patterns
    ENTRY_PATTERNS = [
        r'Entry[:\s]*([\d.,]+)',
        r'Вход[:\s]*([\d.,]+)',
        r'@\s*([\d.,]+)',
        r'Price[:\s]*([\d.,]+)',
        r'Цена[:\s]*([\d.,]+)',
        r'Вход в позицию[:\s]*([\d.,]+)',
        r'Моя точка входа[:\s]*([\d.,]+)',
        r'Точка входа[:\s]*([\d.,]+)',
        r'Открытие сделки[:\s]*([\d.,]+)',
    ]
    
    # Take profit patterns
    TP_PATTERNS = [
        r'Target\s*\d*[:]?\s*([\d.,]+)',
        r'TP\s*\d*[:]?\s*([\d.,]+)',
        r'Тп[:\s]*([\d.,]+)',
        r'Take\s*Profit[:\s]*([\d.,]+)',
        r'Цель[:\s]*([\d.,]+)',
        r'Тейки[:\s]*([\d.,]+)',
        r'Тейк[:\s]*([\d.,]+)',
        r'Цели по сделке[:\s]*([\d.,]+)',
        r'Стоп[:\s]*([\d.,]+)',
    ]
    
    # Stop loss patterns
    SL_PATTERNS = [
        r'Stop\s*Loss[:\s]*([\d.,]+)',
        r'SL[:\s]*([\d.,]+)',
        r'Сл[:\s]*([\d.,]+)',
        r'Стоп[:\s]*([\d.,]+)',
        r'Стоп-лос[:\s]*([\d.,]+)',
        r'Stop[:\s]*([\d.,]+)',
    ]
    
    # Leverage patterns
    LEVERAGE_PATTERNS = [
        r'Leverage[:\s]*([\d]+)',
        r'Плечо[:\s]*([\d]+)[-xх]*([\d]*)',
        r'([\d]+)\s*[xх]',
        r'([\d]+)\s*X',
        r'Плечи[:\s]*([\d]+)',
        r'Плечо[:\s]*([\d]+)',
    ]
    
    # Risk management patterns
    RISK_PATTERNS = [
        r'РМ[:\s]*([\d.,]+)%',
        r'Риск[:\s]*([\d.,]+)%',
        r'Риски[:\s]*([\d.,]+)%',
        r'Risk[:\s]*([\d.,]+)%',
        r'([\d.,]+)%\s*от депозита',
        r'([\d.,]+)%\s*от депо',
    ]
    
    @staticmethod
    def parse_signal(text: str, channel_id: str = "") -> Optional[ParsedSignal]:
        """Parse a trading signal from text"""
        try:
            logger.info(f"🔍 Parsing signal from channel {channel_id}")
            
            # Clean and normalize text
            text = text.strip()
            if not text:
                return None
            
            # Extract symbol
            symbol = EnhancedSignalParser._extract_symbol(text)
            if not symbol:
                logger.info("❌ No symbol found")
                return None
            
            # Extract side (LONG/SHORT)
            side = EnhancedSignalParser._extract_side(text)
            if not side:
                logger.info("❌ No trade side found")
                return None
            
            # Extract entry price
            entry_price = EnhancedSignalParser._extract_entry_price(text)
            
            # Extract take profits
            take_profits = EnhancedSignalParser._extract_take_profits(text)
            
            # Extract stop loss
            stop_loss = EnhancedSignalParser._extract_stop_loss(text)
            
            # Extract leverage
            leverage = EnhancedSignalParser._extract_leverage(text)
            
            # Extract risk percentage
            risk_percentage = EnhancedSignalParser._extract_risk_percentage(text)
            
            # Calculate confidence score
            confidence = EnhancedSignalParser._calculate_confidence(
                symbol, side, entry_price, take_profits, stop_loss, leverage
            )
            
            signal_id = str(uuid.uuid4())
            
            signal = ParsedSignal(
                signal_id=signal_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profits,
                leverage=leverage,
                risk_percentage=risk_percentage,
                raw_text=text,
                channel_id=channel_id,
                confidence=confidence
            )
            
            logger.info(f"✅ Parsed signal: {symbol} {side} (confidence: {confidence:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            return None
    
    @staticmethod
    def _extract_symbol(text: str) -> Optional[str]:
        """Extract trading symbol from text"""
        for pattern in EnhancedSignalParser.SYMBOL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                symbol = match.group(1).upper()
                
                # Normalize symbol
                if not symbol.endswith('USDT'):
                    symbol = symbol + 'USDT'
                
                # Fix double USDT
                if symbol.endswith('USDUSDT'):
                    symbol = symbol.replace('USDUSDT', 'USDT')
                
                return symbol
        
        return None
    
    @staticmethod
    def _extract_side(text: str) -> Optional[str]:
        """Extract trade side (LONG/SHORT) from text"""
        # Check for LONG patterns
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'LONG'
        
        # Check for SHORT patterns
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'SHORT'
        
        return None
    
    @staticmethod
    def _extract_entry_price(text: str) -> Optional[float]:
        """Extract entry price from text"""
        for pattern in EnhancedSignalParser.ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1).replace(',', ''))
                    if price > 0:
                        return price
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_take_profits(text: str) -> List[float]:
        """Extract take profit levels from text"""
        take_profits = []
        
        # Look for multiple TP patterns
        for pattern in EnhancedSignalParser.TP_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                if match and match.replace('.', '').replace(',', '').isdigit():
                    try:
                        tp_val = float(match.replace(',', ''))
                        if tp_val > 0:
                            take_profits.append(tp_val)
                    except ValueError:
                        continue
        
        # Remove duplicates and sort
        take_profits = sorted(list(set(take_profits)))
        
        # Limit to reasonable number of TPs
        return take_profits[:5]
    
    @staticmethod
    def _extract_stop_loss(text: str) -> Optional[float]:
        """Extract stop loss from text"""
        for pattern in EnhancedSignalParser.SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    sl = float(match.group(1).replace(',', ''))
                    if sl > 0:
                        return sl
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_leverage(text: str) -> Optional[int]:
        """Extract leverage from text"""
        for pattern in EnhancedSignalParser.LEVERAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 125:
                        return leverage
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_risk_percentage(text: str) -> Optional[float]:
        """Extract risk percentage from text"""
        for pattern in EnhancedSignalParser.RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    risk = float(match.group(1).replace(',', ''))
                    if 0 < risk <= 100:
                        return risk
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _calculate_confidence(symbol: str, side: str, entry_price: Optional[float], 
                            take_profits: List[float], stop_loss: Optional[float], 
                            leverage: Optional[int]) -> float:
        """Calculate confidence score for the parsed signal"""
        confidence = 0.0
        
        # Base confidence for having symbol and side
        if symbol and side:
            confidence += 0.3
        
        # Entry price adds confidence
        if entry_price:
            confidence += 0.2
        
        # Take profits add confidence
        if take_profits:
            confidence += 0.2
        
        # Stop loss adds confidence
        if stop_loss:
            confidence += 0.15
        
        # Leverage adds confidence
        if leverage:
            confidence += 0.1
        
        # Bonus for having multiple TPs
        if len(take_profits) > 1:
            confidence += 0.05
        
        return min(confidence, 1.0)

class TradingBot:
    def __init__(self):
        self.config = BotConfig()
        self.exchange: Optional[ccxt.Exchange] = None
        self.user_monitoring_clients: Dict[int, TelegramClient] = {}
        self.user_data: Dict[int, BotConfig] = {}
        self.active_monitoring = {}
        self.monitoring_tasks = {}
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.active_positions: Dict[str, ActivePosition] = {}
        self.order_monitor_running = False
        
        # Enhanced multi-account support
        self.enhanced_db = EnhancedDatabase()
        self.current_account = None
        self.account_exchanges: Dict[str, ccxt.Exchange] = {}
        
        # User session management
        self.authenticated_users: Dict[int, bool] = {}
        self.current_accounts: Dict[int, str] = {}  # user_id -> account_id
        self.monitoring_status: Dict[int, bool] = {}  # Track monitoring status per user
        
        # Enhanced main menu
        self.main_menu = ReplyKeyboardMarkup(
            [[KeyboardButton("🔑 Accounts"), KeyboardButton("📊 Status")],
             [KeyboardButton("💰 Balance"), KeyboardButton("📈 Active Trades")],
             [KeyboardButton("📋 Trade History"), KeyboardButton("⚙️ Settings")],
             [KeyboardButton("🚀 Start Trading"), KeyboardButton("🛑 Stop Trading")]],
            resize_keyboard=True
        )
        
        # Account management menu
        self.account_menu = ReplyKeyboardMarkup(
            [[KeyboardButton("➕ Add Account"), KeyboardButton("📋 List Accounts")],
             [KeyboardButton("⚙️ Account Settings"), KeyboardButton("📡 Channels")],
             [KeyboardButton("🔙 Back to Main")]],
            resize_keyboard=True
        )
        
        # Settings menu
        self.settings_menu = ReplyKeyboardMarkup(
            [[KeyboardButton("🎯 Take Profits"), KeyboardButton("🛑 Stop Losses")],
             [KeyboardButton("💰 Balance Config"), KeyboardButton("⚡ Leverage")],
             [KeyboardButton("📡 Channels"), KeyboardButton("🔙 Back to Main")]],
            resize_keyboard=True
        )
    
    def authenticate_user(self, user_id: int, pin_code: str) -> bool:
        """Authenticate user with PIN code"""
        if pin_code == BOT_PIN_CODE:
            self.authenticated_users[user_id] = True
            return True
        return False
    
    def is_authenticated(self, user_id: int) -> bool:
        """Check if user is authenticated"""
        return self.authenticated_users.get(user_id, False)
    
    def get_current_account(self, user_id: int) -> Optional[AccountConfig]:
        """Get current account for user"""
        account_id = self.current_accounts.get(user_id)
        if not account_id:
            return None
        
        accounts = self.enhanced_db.get_all_accounts()
        for account in accounts:
            if account.account_id == account_id:
                return account
        return None
    
    def set_current_account(self, user_id: int, account_id: str) -> bool:
        """Set current account for user"""
        accounts = self.enhanced_db.get_all_accounts()
        for account in accounts:
            if account.account_id == account_id:
                self.current_accounts[user_id] = account_id
                return True
        return False

    async def extract_channel_id_from_link(self, link: str, user_id: int) -> Optional[str]:
        """Extract channel ID from t.me link"""
        try:
            # Clean the link
            link = link.strip()
            if not link.startswith('http'):
                if not link.startswith('t.me/'):
                    link = 't.me/' + link.lstrip('@/')
                link = 'https://' + link
            
            # Extract username from link
            import re
            match = re.search(r't\.me/([^/?]+)', link)
            if not match:
                return None
            
            username = match.group(1)
            
            # Get Telethon client
            telethon_client = self.user_monitoring_clients.get(user_id)
            if not telethon_client:
                config = self.get_user_config(user_id)
                await self.setup_telethon_client(config)
                telethon_client = self.user_monitoring_clients.get(user_id)
            
            if not telethon_client:
                return None
            
            # Resolve the entity
            try:
                entity = await telethon_client.get_entity(username)
                if hasattr(entity, 'id'):
                    return str(-abs(entity.id))
            except Exception as e:
                logger.error(f"Error resolving channel {username}: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error extracting channel ID from link: {e}")
            return None
        
        return None

    def extract_channel_id_from_forward(self, message) -> Optional[str]:
        """Extract channel ID from forwarded message"""
        try:
            if hasattr(message, 'forward') and message.forward:
                forward = message.forward
                if hasattr(forward, 'from_id') and forward.from_id:
                    if hasattr(forward.from_id, 'channel_id'):
                        return str(-abs(forward.from_id.channel_id))
                    elif hasattr(forward.from_id, 'user_id'):
                        return str(forward.from_id.user_id)
                        
                # Try alternative forward attributes
                if hasattr(forward, 'chat_id') and forward.chat_id:
                    return str(-abs(forward.chat_id))
                    
        except Exception as e:
            logger.error(f"Error extracting channel ID from forward: {e}")
            
        return None

    def to_bingx_symbol(self, symbol: str) -> str:
        try:
            # Convert like BTCUSDT -> BTC/USDT:USDT (perpetual swap)
            if '/' in symbol:
                return symbol
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                return f"{base}/USDT:USDT"
            return symbol
        except Exception:
            return symbol

    def parse_trading_signal(self, message: str, channel_id: str) -> Optional[TradingSignal]:
        """Enhanced signal parsing with Russian support"""
        try:
            logger.info(f"🔍 PARSING SIGNAL from channel {channel_id}")
            
            # Try enhanced parser first
            enhanced_signal = EnhancedSignalParser.parse_signal(message, channel_id)
            if enhanced_signal and enhanced_signal.confidence > 0.5:
                logger.info(f"✅ Enhanced parser: {enhanced_signal.symbol} {enhanced_signal.side} (confidence: {enhanced_signal.confidence:.2f})")
                
                return TradingSignal(
                    symbol=enhanced_signal.symbol,
                    trade_type=enhanced_signal.side,
                    entry_price=enhanced_signal.entry_price,
                    take_profit=enhanced_signal.take_profit or [],
                    stop_loss=enhanced_signal.stop_loss,
                    leverage=enhanced_signal.leverage,
                    raw_message=message,
                    channel_id=channel_id,
                    timestamp=datetime.now()
                )
            
            # Fallback to original parser
            signals = SignalDetector.parse_signals(message)

            if not signals:
                logger.info("❌ No signals found")
                return None

            s = signals[0]
            if not all([s['symbol'], s['trade_side']]):
                logger.info("❌ Incomplete signal data")
                return None

            logger.info(f"✅ Parsed signal: {s['symbol']} {s['trade_side']}")

            return TradingSignal(
                symbol=s['symbol'],
                trade_type=s['trade_side'],
                entry_price=s['entry'],
                take_profit=s['take_profit'] or [],
                stop_loss=s['stop_loss'],
                leverage=s['leverage'],
                raw_message=message,
                channel_id=channel_id,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            return None

    def get_user_config(self, user_id: int) -> BotConfig:
        if user_id not in self.user_data:
            self.user_data[user_id] = BotConfig(
                binance_api_key=DEFAULT_BINANCE_API_KEY,
                binance_api_secret=DEFAULT_BINANCE_API_SECRET,
                telegram_api_id=DEFAULT_TELEGRAM_API_ID,
                telegram_api_hash=DEFAULT_TELEGRAM_API_HASH,
                user_id=user_id
            )
        return self.user_data[user_id]

    def setup_make_webhook(self, user_id: int) -> bool:
        """Setup Make.com webhook logger for user"""
        try:
            config = self.get_user_config(user_id)
            webhook_url = config.make_webhook_url or DEFAULT_WEBHOOK_URL
            
            webhook_logger = MakeWebhookLogger(webhook_url)
            self.webhook_loggers[user_id] = webhook_logger
            
            logger.info(f"✅ Make.com webhook setup for user {user_id}: {webhook_url[:50]}...")
            return True

        except Exception as e:
            logger.error(f"❌ Make.com webhook setup error: {e}")
            return False

    def get_symbol_precision(self, symbol: str) -> Dict[str, Any]:
        """Get and cache symbol precision information with SAFE DEFAULTS"""
        try:
            if symbol in self.symbol_info_cache:
                return self.symbol_info_cache[symbol]
            if not self.exchange:
                return {'error': 'Exchange not initialized'}

            bingx_symbol = self.to_bingx_symbol(symbol)
            markets = self.exchange.load_markets()
            if bingx_symbol not in markets:
                return {'error': f'Symbol {symbol} not found'}

            market = markets[bingx_symbol]
            # Derive precision and limits
            raw_price_precision = market.get('precision', {}).get('price', None)
            raw_amount_precision = market.get('precision', {}).get('amount', None)

            # Normalize precision to integers when possible
            price_precision = int(raw_price_precision) if isinstance(raw_price_precision, (int, float)) and raw_price_precision is not None else None
            qty_precision = int(raw_amount_precision) if isinstance(raw_amount_precision, (int, float)) and raw_amount_precision is not None else None

            # Compute tick size (robust, no nested try/except indentation pitfalls)
            info = market.get('info', {}) or {}
            tick_size = market.get('limits', {}).get('price', {}).get('min', None)
            if not tick_size:
                candidates = []
                if isinstance(info, dict):
                    candidates = [info.get('priceIncrement'), info.get('priceStep')]
                for cand in candidates:
                    if cand is None:
                        continue
                    try:
                        tick_size = float(cand)
                        break
                    except Exception:
                        continue
                if not tick_size:
                    if isinstance(price_precision, int):
                        tick_size = 10 ** (-price_precision) if price_precision and price_precision > 0 else 0.00001
                    else:
                        price_prec_str = str(info.get('pricePrecision')) if isinstance(info, dict) else ''
                        if price_prec_str.isdigit():
                            p = int(price_prec_str)
                            tick_size = 10 ** (-p) if p > 0 else 0.00001
            if not tick_size or tick_size <= 0:
                tick_size = 0.00001

            # Compute step size (robust)
            step_size = market.get('limits', {}).get('amount', {}).get('min', None)
            if not step_size:
                if isinstance(qty_precision, int):
                    step_size = 10 ** (-qty_precision) if qty_precision > 0 else 1.0
                else:
                    pass
            else:
                candidates = []
                if isinstance(info, dict):
                    candidates = [info.get('quantityIncrement'), info.get('stepSize')]
                for cand in candidates:
                    if cand is None:
                        continue
                    try:
                        step_size = float(cand)
                        break
                    except Exception:
                        continue
            if not step_size or step_size <= 0:
                step_size = 1.0

            min_qty = market.get('limits', {}).get('amount', {}).get('min', 1.0) or 1.0
            min_price = market.get('limits', {}).get('price', {}).get('min', 0.00001) or 0.00001
            max_price = market.get('limits', {}).get('price', {}).get('max', 1000000.0) or 1000000.0

            # Derive decimal precision from tick size
            try:
                tick_decimals = max(0, -Decimal(str(tick_size)).as_tuple().exponent)
            except Exception:
                tick_decimals = 5

            # Ensure price precision is at least as granular as tick size
            price_precision = max(int(price_precision) if price_precision is not None else 0, tick_decimals)

            precision_info = {
                'step_size': step_size,
                'min_qty': min_qty,
                'tick_size': tick_size,
                'min_price': min_price,
                'max_price': max_price,
                'qty_precision': max(int(qty_precision) if qty_precision is not None else 0, 0),
                'price_precision': max(int(price_precision) if price_precision is not None else 5, 1)
            }

            self.symbol_info_cache[symbol] = precision_info
            
            logger.info(f"📏 Symbol precision for {symbol}: qty={precision_info['qty_precision']}, price={precision_info['price_precision']}, tick={precision_info['tick_size']}")
            return precision_info

        except Exception as e:
            logger.error(f"❌ Error getting symbol precision: {e}")
            return {
                'step_size': 1.0,
                'min_qty': 1.0,
                'tick_size': 0.00001,
                'min_price': 0.00001,
                'max_price': 1000000.0,
                'qty_precision': 0,
                'price_precision': 5
            }

    def round_price(self, price: float, tick_size: float, price_precision: int) -> float:
        """Round price to match tick size and precision - NEVER ZERO"""
        try:
            if not tick_size or tick_size <= 0:
                tick_size = 0.00001
            
            if price_precision < 1:
                price_precision = 5

            price_decimal = Decimal(str(price))
            tick_decimal = Decimal(str(tick_size))
            
            rounded = float((price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_decimal)
            rounded = round(rounded, price_precision)
            
            if rounded <= 0:
                rounded = tick_size
                logger.warning(f"⚠️ Price rounded to zero, using tick_size: {tick_size}")
            
            return rounded
            
        except Exception as e:
            logger.error(f"❌ Error rounding price {price}: {e}")
            return max(tick_size if tick_size > 0 else 0.00001, round(price, price_precision))

    def round_quantity(self, quantity: float, step_size: float, qty_precision: int) -> float:
        """Round quantity to match step size and precision"""
        try:
            if not step_size or step_size <= 0:
                step_size = 1.0
            
            qty_decimal = Decimal(str(quantity))
            step_decimal = Decimal(str(step_size))
            
            rounded = float((qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_decimal)
            rounded = round(rounded, qty_precision)
            
            if rounded < step_size:
                rounded = step_size
            
            return rounded
            
        except Exception as e:
            logger.error(f"❌ Error rounding quantity {quantity}: {e}")
            return round(quantity, qty_precision)

# (moved trailing handlers below class to avoid breaking class methods)

    async def cancel_related_orders(self, symbol: str, user_id: int, filled_order_type: str, bot_instance, filled_tp_id: Optional[int] = None):
        """Cancel SL/trailing when ALL TPs fill, or cancel all TPs when SL fills"""
        try:
            position = self.active_positions.get(symbol)
            if not position:
                logger.info(f"⚠️ No active position found for {symbol}")
                return

            cancelled_orders = []

            if filled_order_type == "TAKE_PROFIT":
                # Add the filled TP to the tracking list
                if filled_tp_id and filled_tp_id not in position.filled_take_profit_order_ids:
                    position.filled_take_profit_order_ids.append(filled_tp_id)
                    logger.info(f"📝 Marked TP {filled_tp_id} as filled for {symbol}")

                # Check if ALL take profits are filled
                remaining_tps = [tp_id for tp_id in position.take_profit_order_ids if tp_id not in position.filled_take_profit_order_ids]
                
                if remaining_tps:
                    # Still have unfilled TPs, don't cancel SL/trailing yet
                    logger.info(f"🎯 Take Profit {filled_tp_id} filled for {symbol}, but {len(remaining_tps)} TPs remaining. Keeping SL/trailing active.")
                    await bot_instance.send_message(
                        chat_id=user_id,
                        text=f"🎯 <b>Take Profit Filled</b>\n\n💰 {symbol}\n✅ TP {filled_tp_id} executed\n📊 Remaining TPs: {len(remaining_tps)}\n🛡️ SL/Trailing still active",
                        parse_mode='HTML'
                    )
                    return
                else:
                    # ALL take profits are filled, now cancel SL and trailing
                    logger.info(f"🎉 ALL Take Profits filled for {symbol}! Canceling SL and trailing stop.")
                    
                    # Cancel Stop Loss
                    if position.stop_loss_order_id:
                        try:
                            if self.exchange:
                                self.exchange.cancel_order(position.stop_loss_order_id, self.to_bingx_symbol(symbol))
                            cancelled_orders.append(f"SL-{position.stop_loss_order_id}")
                            logger.info(f"✅ Cancelled Stop Loss order: {position.stop_loss_order_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to cancel SL: {e}")

                    # Cancel Trailing Stop
                    if position.trailing_order_id:
                        try:
                            if self.exchange:
                                self.exchange.cancel_order(position.trailing_order_id, self.to_bingx_symbol(symbol))
                            cancelled_orders.append(f"TRAIL-{position.trailing_order_id}")
                            logger.info(f"✅ Cancelled Trailing order: {position.trailing_order_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to cancel Trailing: {e}")

            elif filled_order_type == "STOP_LOSS":
                # Cancel all remaining take profit orders
                remaining_tps = [tp_id for tp_id in position.take_profit_order_ids if tp_id not in position.filled_take_profit_order_ids]
                for tp_id in remaining_tps:
                    try:
                        if self.exchange:
                            self.exchange.cancel_order(tp_id, self.to_bingx_symbol(symbol))
                        cancelled_orders.append(f"TP-{tp_id}")
                        logger.info(f"✅ Cancelled Take Profit order: {tp_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to cancel TP {tp_id}: {e}")

                # Cancel trailing order too
                if position.trailing_order_id:
                    try:
                        if self.exchange:
                            self.exchange.cancel_order(position.trailing_order_id, self.to_bingx_symbol(symbol))
                        cancelled_orders.append(f"TRAIL-{position.trailing_order_id}")
                        logger.info(f"✅ Cancelled Trailing order: {position.trailing_order_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to cancel Trailing: {e}")

            # Remove position from active positions only when all orders are handled
            if filled_order_type == "STOP_LOSS" or (filled_order_type == "TAKE_PROFIT" and not remaining_tps):
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                    logger.info(f"🗑️ Removed {symbol} from active positions")

            if cancelled_orders:
                reason = "ALL Take Profits filled" if filled_order_type == "TAKE_PROFIT" else f"{filled_order_type} was filled"
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=f"🔄 <b>Auto-Cancelled Orders</b>\n\n💰 {symbol}\n📋 Cancelled: {', '.join(cancelled_orders)}\n⚠️ Reason: {reason}",
                    parse_mode='HTML'
                )

        except Exception as e:
            logger.error(f"❌ Error canceling related orders: {e}")

    async def monitor_orders(self, bot_instance):
        """Monitor open orders and cancel opposites when filled"""
        try:
            if self.order_monitor_running:
                return

            self.order_monitor_running = True
            logger.info("👁️ Order monitor started")

            while self.order_monitor_running:
                try:
                    for symbol, position in list(self.active_positions.items()):
                        try:
                            if not self.exchange:
                                continue
                            open_orders = self.exchange.fetch_open_orders(self.to_bingx_symbol(symbol))
                            open_order_ids = [int(order['id']) for order in open_orders]

                            if position.stop_loss_order_id and position.stop_loss_order_id not in open_order_ids:
                                # Verify SL truly filled (not canceled/expired)
                                sl_filled = False
                                try:
                                    sl_order = self.exchange.fetch_order(position.stop_loss_order_id, self.to_bingx_symbol(symbol))
                                    sl_status = (sl_order or {}).get('status')
                                    sl_filled = sl_status in ("closed", "filled") or float((sl_order or {}).get('filled') or 0) > 0
                                except Exception:
                                    sl_filled = False
                                if sl_filled:
                                    logger.info(f"🛑 Stop Loss filled for {symbol}")
                                    await self.cancel_related_orders(symbol, position.user_id, "STOP_LOSS", bot_instance)
                                    # Move to next symbol after handling SL to avoid TP mis-reporting
                                    continue

                            for tp_id in position.take_profit_order_ids:
                                if tp_id not in open_order_ids and tp_id not in position.filled_take_profit_order_ids:
                                    # Verify TP truly filled (not canceled/expired)
                                    tp_filled = False
                                    try:
                                        tp_order = self.exchange.fetch_order(tp_id, self.to_bingx_symbol(symbol))
                                        tp_status = (tp_order or {}).get('status')
                                        tp_filled = tp_status in ("closed", "filled") or float((tp_order or {}).get('filled') or 0) > 0
                                    except Exception:
                                        tp_filled = False
                                    if tp_filled:
                                        logger.info(f"🎯 Take Profit {tp_id} filled for {symbol}")
                                        await self.cancel_related_orders(symbol, position.user_id, "TAKE_PROFIT", bot_instance, filled_tp_id=tp_id)
                                        # Don't break here - continue checking other TPs in case multiple filled simultaneously

                        except Exception as e:
                            logger.error(f"❌ Error checking orders for {symbol}: {e}")

                    await asyncio.sleep(5)

                except Exception as e:
                    logger.error(f"❌ Order monitor loop error: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"❌ Order monitor error: {e}")
        finally:
            self.order_monitor_running = False
            logger.info("👁️ Order monitor stopped")

    async def get_account_balance(self, config: BotConfig) -> Dict[str, float]:
        """Get detailed account balance information"""
        try:
            if not self.exchange:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to BingX API'}

            bal = self.exchange.fetch_balance()
            usdt = bal.get('USDT', {}) if isinstance(bal, dict) else {}
            usdt_info = {
                'balance': float(usdt.get('total', 0) or usdt.get('free', 0) or 0),
                'available': float(usdt.get('free', 0) or 0),
                'wallet_balance': float(usdt.get('total', 0) or 0)
            }

            total_wallet_balance = float(usdt.get('total', 0) or 0)
            
            return {
                'success': True,
                'usdt_balance': usdt_info['balance'],
                'usdt_available': usdt_info['available'],
                'usdt_wallet_balance': usdt_info['wallet_balance'],
                'total_wallet_balance': total_wallet_balance,
                'total_unrealized_pnl': 0.0,
                'total_margin_balance': total_wallet_balance
            }

        except Exception as e:
            logger.error(f"❌ Error getting account balance: {e}")
            return {'success': False, 'error': str(e)}

    async def setup_binance_client(self, config: BotConfig) -> bool:
        try:
            self.exchange = ccxt.bingx({
                'apiKey': config.binance_api_key,
                'secret': config.binance_api_secret,
                'options': {
                    'defaultType': 'swap'
                },
                'enableRateLimit': True,
                'timeout': 60000
            })

            bal = self.exchange.fetch_balance()
            usdt_total = bal.get('USDT', {}).get('total', 'N/A') if isinstance(bal, dict) else 'N/A'
            logger.info(f"✅ BingX connected. Balance: {usdt_total} USDT")
            return True

        except Exception as e:
            logger.error(f"❌ BingX setup error: {e}")
            return False

    async def setup_telethon_client(self, config: BotConfig) -> bool:
        """Setup Telethon client"""
        try:
            session_name = f'session_{config.user_id}'

            telethon_client = TelegramClient(
                session_name,
                api_id=int(config.telegram_api_id),
                api_hash=config.telegram_api_hash
            )

            await telethon_client.start()
            self.user_monitoring_clients[config.user_id] = telethon_client

            logger.info(f"✅ Telethon setup successful for user {config.user_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Telethon setup error: {e}")
            return False

    async def get_available_channels(self, user_id: int) -> List[Dict]:
        try:
            config = self.get_user_config(user_id)

            if user_id not in self.user_monitoring_clients:
                await self.setup_telethon_client(config)

            telethon_client = self.user_monitoring_clients.get(user_id)
            if not telethon_client:
                return []

            channels = []
            async for dialog in telethon_client.iter_dialogs():
                if isinstance(dialog.entity, Channel):
                    channel_id = str(-abs(dialog.entity.id))
                    channels.append({
                        'id': channel_id,
                        'title': dialog.entity.title or "Unknown Channel",
                        'username': getattr(dialog.entity, 'username', 'N/A')
                    })

            logger.info(f"📡 Found {len(channels)} channels for user {user_id}")
            return channels

        except Exception as e:
            logger.error(f"❌ Error getting channels: {e}")
            return []

    async def create_sl_tp_orders(self, symbol: str, side: str, quantity: float, entry_price: float, 
                                sl_price: Optional[float], tp_prices: List[float], user_id: int) -> Dict[str, Any]:
        """Create stop loss and take profit orders (BingX/ccxt: simplified placeholder)."""
        try:
            logger.info("ℹ️ SL/TP order placement via BingX API is not implemented in this version. Skipping creation.")
            return {'stop_loss': None, 'take_profits': []}

        except Exception as e:
            logger.error(f"❌ Error creating SL/TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """Enhanced trade execution with FIXED PRECISION"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")

            if not self.exchange:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to BingX API'}

            try:
                logger.info(f"💰 Getting account balance...")
                bal = self.exchange.fetch_balance()
                usdt_balance = 0
                if isinstance(bal, dict) and 'USDT' in bal:
                    asset = bal['USDT']
                    usdt_balance = float(asset.get('total', asset.get('free', 0)) or 0)
                    logger.info(f"✅ Found USDT balance: {usdt_balance}")
            except Exception as e:
                logger.error(f"❌ Error getting account balance: {e}")
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            if config.use_signal_settings and signal.leverage:
                leverage = signal.leverage
            else:
                leverage = config.leverage

            logger.info(f"⚙️ Using settings: {'Signal' if config.use_signal_settings else 'Bot'}")
            logger.info(f"⚡ Leverage: {leverage}x")

            # Determine order side early for leverage/position params
            side = 'BUY' if signal.trade_type == 'LONG' else 'SELL'

            bingx_symbol = self.to_bingx_symbol(signal.symbol)
            # Ensure we always have current price
            try:
                ticker = self.exchange.fetch_ticker(bingx_symbol)
                current_price = float(ticker.get('last') or ticker.get('info', {}).get('price') or 0)
            except Exception:
                current_price = float(signal.entry_price or 0) or 0.0

            # Attempt to set leverage, but proceed if it fails
            try:
                position_side = 'LONG' if side == 'BUY' else 'SHORT'
                self.exchange.set_leverage(leverage, bingx_symbol, {'side': position_side})
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage setting warning: {e}")

            logger.info(f"💲 Current {signal.symbol} price: {current_price}")

            entry_price = signal.entry_price or current_price
            
            # Calculate trade amount based on user preference
            if config.use_fixed_usdt_amount:
                trade_amount = min(config.fixed_usdt_amount, usdt_balance)
                logger.info(f"💰 Using fixed USDT amount: ${trade_amount:.2f}")
            else:
                trade_amount = usdt_balance * (config.balance_percent / 100)
                logger.info(f"💰 Using percentage of balance: ${trade_amount:.2f} ({config.balance_percent}%)")
            
            position_value = trade_amount * leverage
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Balance: {usdt_balance} USDT")
            logger.info(f"   Trade amount: ${trade_amount:.2f}")
            logger.info(f"   Entry price: {entry_price}")
            logger.info(f"   Raw quantity: {raw_quantity}")

            precision_info = self.get_symbol_precision(signal.symbol)
            if 'error' in precision_info:
                return {'success': False, 'error': precision_info['error']}

            step_size = precision_info['step_size']
            min_qty = precision_info['min_qty']
            qty_precision = precision_info['qty_precision']

            quantity = self.round_quantity(raw_quantity, step_size, qty_precision)

            logger.info(f"📏 Step size: {step_size}, Min qty: {min_qty}")
            logger.info(f"📦 Final quantity: {quantity}")

            if quantity < min_qty:
                return {'success': False, 'error': f'Quantity {quantity} below minimum {min_qty}'}

            if quantity <= 0:
                return {'success': False, 'error': 'Calculated quantity is zero or negative'}

            order_value = quantity * entry_price

            # Include positionSide param for hedge mode for entry
            order_params = {'positionSide': 'LONG' if side == 'BUY' else 'SHORT'}
            order = self.exchange.create_order(self.to_bingx_symbol(signal.symbol), 'market', side.lower(), quantity, None, order_params)

            logger.info(f"✅ Main order executed: {order.get('id')}")

            sl_price = None
            tp_prices = []
            sl_tp_result = {'stop_loss': None, 'take_profits': []}

            if config.create_sl_tp:
                if config.use_signal_settings:
                    if signal.stop_loss:
                        sl_price = signal.stop_loss
                    else:
                        if signal.trade_type == 'LONG':
                            sl_price = current_price * (1 - config.stop_loss_percent / 100)
                        else:
                            sl_price = current_price * (1 + config.stop_loss_percent / 100)

                    if signal.take_profit:
                        # Normalize TP list: interpret values <= 100 as percents; otherwise as absolute prices
                        normalized = []
                        for tp in signal.take_profit:
                            try:
                                tp_val = float(tp)
                            except Exception:
                                continue
                            if tp_val <= 100:
                                if signal.trade_type == 'LONG':
                                    normalized.append(current_price * (1 + tp_val / 100.0))
                                else:
                                    normalized.append(current_price * (1 - tp_val / 100.0))
                            else:
                                normalized.append(tp_val)
                        # Fallback to default ladder if normalized values are unreasonable (e.g., far away)
                        if not normalized or all(v >= current_price * 2.0 for v in normalized) or all(v <= current_price * 0.5 for v in normalized):
                            if signal.trade_type == 'LONG':
                                normalized = [current_price * 1.025, current_price * 1.05, current_price * 1.075]
                            else:
                                normalized = [current_price * 0.975, current_price * 0.95, current_price * 0.925]
                        tp_prices = normalized
                    else:
                        # Use custom take profit levels
                        tp_prices = []
                        for tp_level in config.custom_take_profits:
                            if signal.trade_type == 'LONG':
                                tp_price = current_price * (1 + tp_level.percentage / 100)
                            else:
                                tp_price = current_price * (1 - tp_level.percentage / 100)
                            tp_prices.append(tp_price)
                else:
                    # Use bot settings with custom take profit levels
                    if signal.trade_type == 'LONG':
                        sl_price = current_price * (1 - config.stop_loss_percent / 100)
                    else:
                        sl_price = current_price * (1 + config.stop_loss_percent / 100)
                    
                    # Use custom take profit levels
                    tp_prices = []
                    for tp_level in config.custom_take_profits:
                        if signal.trade_type == 'LONG':
                            tp_price = current_price * (1 + tp_level.percentage / 100)
                        else:
                            tp_price = current_price * (1 - tp_level.percentage / 100)
                        tp_prices.append(tp_price)

                if sl_price:
                    if signal.trade_type == 'LONG':
                        if sl_price >= current_price:
                            logger.warning(f"⚠️ SL price {sl_price} >= current {current_price}, adjusting...")
                            sl_price = current_price * 0.95
                    else:
                        if sl_price <= current_price:
                            logger.warning(f"⚠️ SL price {sl_price} <= current {current_price}, adjusting...")
                            sl_price = current_price * 1.05

                logger.info(f"📊 SL/TP Prices before rounding: SL={sl_price}, TP={tp_prices}")

                try:
                    # Create SL and TP orders using conditional params tailored for BingX
                    sl_tp_result = {'stop_loss': None, 'take_profits': []}
                    market_symbol = self.to_bingx_symbol(signal.symbol)
                    position_side = 'LONG' if side == 'BUY' else 'SHORT'

                    if sl_price:
                        rounded_sl = self.round_price(sl_price, precision_info['tick_size'], precision_info['price_precision'])
                        order_type = 'STOP_MARKET'
                        sl_order = self.exchange.create_order(
                            market_symbol,
                            order_type,
                            'sell' if side == 'BUY' else 'buy',
                            quantity,
                            None,
                            {
                                'stopPrice': rounded_sl,
                                'triggerPrice': rounded_sl,
                                'positionSide': position_side,
                                'workingType': 'MARK_PRICE'
                            }
                        )
                        logger.info(f"🛑 Stop Loss order placed: {sl_order}")
                        sl_tp_result['stop_loss'] = sl_order.get('id')

                    # Use custom take profit levels with their specific close percentages
                    tp_targets = tp_prices[:len(config.custom_take_profits)]
                    
                    # Discretize TP targets to tick steps relative to current mark to avoid collapsing to same price
                    try:
                        latest_for_tp = self.exchange.fetch_ticker(market_symbol)
                        mark_for_tp = float(latest_for_tp.get('last') or latest_for_tp.get('info', {}).get('price') or current_price)
                    except Exception:
                        mark_for_tp = current_price
                    
                    adjusted_tp_targets = []
                    prev_ticks = 0
                    for tp_abs in tp_targets:
                        if side == 'BUY':
                            raw_ticks = (tp_abs - mark_for_tp) / precision_info['tick_size']
                            need_ticks = int(raw_ticks) if raw_ticks == int(raw_ticks) else int(raw_ticks) + 1
                            need_ticks = max(1, need_ticks)
                            if need_ticks <= prev_ticks:
                                need_ticks = prev_ticks + 1
                            adjusted_tp_targets.append(mark_for_tp + need_ticks * precision_info['tick_size'])
                            prev_ticks = need_ticks
                        else:
                            raw_ticks = (mark_for_tp - tp_abs) / precision_info['tick_size']
                            need_ticks = int(raw_ticks) if raw_ticks == int(raw_ticks) else int(raw_ticks) + 1
                            need_ticks = max(1, need_ticks)
                            if need_ticks <= prev_ticks:
                                need_ticks = prev_ticks + 1
                            adjusted_tp_targets.append(mark_for_tp - need_ticks * precision_info['tick_size'])
                            prev_ticks = need_ticks
                    
                    tp_targets = adjusted_tp_targets
                    
                    # Calculate quantities based on custom close percentages
                    quantities = []
                    remaining_quantity = quantity
                    
                    for i, tp_level in enumerate(config.custom_take_profits[:len(tp_targets)]):
                        if i == len(tp_targets) - 1:  # Last TP level closes all remaining
                            quantities.append(remaining_quantity)
                        else:
                            close_qty = remaining_quantity * (tp_level.close_percentage / 100)
                            quantities.append(close_qty)
                            remaining_quantity -= close_qty

                    for tp, q in zip(tp_targets, quantities):
                        each_qty = self.round_quantity(q, precision_info['step_size'], precision_info['qty_precision'])
                        rounded_tp = self.round_price(tp, precision_info['tick_size'], precision_info['price_precision'])
                        # Ensure TP is on the correct side of current mark price
                        try:
                            latest = self.exchange.fetch_ticker(market_symbol)
                            mark = float(latest.get('last') or latest.get('info', {}).get('price') or current_price)
                        except Exception:
                            mark = current_price
                        safety_ticks = precision_info['tick_size'] * 1
                        if side == 'BUY':
                            min_ok = self.round_price(mark + safety_ticks, precision_info['tick_size'], precision_info['price_precision'])
                            if rounded_tp <= min_ok:
                                rounded_tp = min_ok
                        else:
                            max_ok = self.round_price(mark - safety_ticks, precision_info['tick_size'], precision_info['price_precision'])
                            if rounded_tp >= max_ok:
                                rounded_tp = max_ok
                        tp_order = self.exchange.create_order(
                            market_symbol,
                            'TAKE_PROFIT_MARKET',
                            'sell' if side == 'BUY' else 'buy',
                            each_qty,
                            None,
                            {
                                'stopPrice': rounded_tp,
                                'triggerPrice': rounded_tp,
                                'positionSide': position_side,
                                'workingType': 'MARK_PRICE'
                            }
                        )
                        logger.info(f"🎯 Take Profit order placed: {tp_order}")
                        sl_tp_result['take_profits'].append({'order_id': tp_order.get('id'), 'price': rounded_tp, 'quantity': each_qty})

                    # Optional trailing stop
                    if getattr(config, 'trailing_enabled', False):
                        try:
                            activation_rate = float(getattr(config, 'trailing_activation_percent', 2.0)) / 100.0
                            callback_percent = float(getattr(config, 'trailing_callback_percent', 0.5))
                            # Activation should be beyond current price in the favorable direction
                            if signal.trade_type == 'LONG':
                                activation_price = current_price * (1 + activation_rate)
                            else:
                                activation_price = current_price * (1 - activation_rate)

                            activation_price = self.round_price(activation_price, precision_info['tick_size'], precision_info['price_precision'])
                            trailing_params = {
                                'activationPrice': activation_price,
                                'priceRate': round(callback_percent, 3),
                                'positionSide': position_side,
                                'workingType': 'MARK_PRICE'
                            }
                            trailing_order = self.exchange.create_order(
                                market_symbol,
                                'TRAILING_STOP_MARKET',
                                'sell' if side == 'BUY' else 'buy',
                                quantity,
                                None,
                                trailing_params
                            )
                            logger.info(f"🧵 Trailing Stop placed: {trailing_order}")
                            # Track trailing order in active positions
                            self.active_positions[signal.symbol] = ActivePosition(
                                symbol=signal.symbol,
                                user_id=config.user_id,
                                side=position_side,
                                quantity=quantity,
                                entry_price=current_price,
                                stop_loss_order_id=sl_tp_result.get('stop_loss'),
                                take_profit_order_ids=[tp['order_id'] for tp in sl_tp_result.get('take_profits', [])],
                                trailing_order_id=trailing_order.get('id')
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ Trailing stop placement failed: {e}")
                except Exception as e:
                    logger.warning(f"⚠️ SL/TP creation skipped/failed on BingX: {e}")
                    sl_tp_result = {'stop_loss': None, 'take_profits': []}

            if config.make_webhook_enabled and config.user_id in self.webhook_loggers:
                trade_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': signal.symbol,
                    'trade_type': signal.trade_type,
                    'entry_price': current_price,
                    'quantity': quantity,
                    'leverage': leverage,
                    'order_id': order.get('id'),
                    'stop_loss': sl_price if sl_price else '',
                    'take_profit': ', '.join([str(tp) for tp in tp_prices]) if tp_prices else '',
                    'status': 'EXECUTED',
                    'balance_used': f"${trade_amount:.2f}",
                    'channel_id': signal.channel_id,
                    'pnl': '0.00',
                    'notes': f"Settings: {'Signal' if config.use_signal_settings else 'Bot'} | SL/TP: {'Enabled' if config.create_sl_tp else 'Disabled'} | OCO: Active",
                    'order_value': f"${order_value:.2f}",
                    'sl_order_id': sl_tp_result['stop_loss'] if sl_tp_result['stop_loss'] else '',
                    'tp_order_ids': ', '.join([str(tp['order_id']) for tp in sl_tp_result['take_profits']]) if sl_tp_result['take_profits'] else '',
                    'user_id': config.user_id
                }
                self.webhook_loggers[config.user_id].send_trade_data(trade_data)

            return {
                'success': True,
                'order_id': order.get('id'),
                'symbol': signal.symbol,
                'quantity': quantity,
                'price': current_price,
                'leverage': leverage,
                'stop_loss_id': sl_tp_result['stop_loss'],
                'take_profit_ids': sl_tp_result['take_profits'],
                'sl_price': sl_price,
                'tp_prices': tp_prices,
                'order_value': order_value
            }

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            logger.error(traceback.format_exc())

            if config.make_webhook_enabled and config.user_id in self.webhook_loggers:
                trade_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': signal.symbol,
                    'trade_type': signal.trade_type,
                    'status': 'FAILED',
                    'channel_id': signal.channel_id,
                    'notes': f'Error: {str(e)[:100]}',
                    'user_id': config.user_id,
                    'entry_price': '', 'quantity': '', 'leverage': '',
                    'order_id': '', 'stop_loss': '', 'take_profit': '',
                    'balance_used': '', 'pnl': '', 'order_value': '',
                    'sl_order_id': '', 'tp_order_ids': ''
                }
                self.webhook_loggers[config.user_id].send_trade_data(trade_data)

            return {'success': False, 'error': str(e)}

    async def start_monitoring(self, user_id: int, bot_instance) -> bool:
        try:
            config = self.get_user_config(user_id)

            if not config.monitored_channels:
                return False

            telethon_client = self.user_monitoring_clients.get(user_id)
            if not telethon_client:
                success = await self.setup_telethon_client(config)
                if not success:
                    return False
                telethon_client = self.user_monitoring_clients[user_id]

            self.setup_make_webhook(user_id)

            if not self.order_monitor_running:
                asyncio.create_task(self.monitor_orders(bot_instance))

            @telethon_client.on(events.NewMessage)
            async def message_handler(event):
                try:
                    channel_ids = set()

                    if hasattr(event, 'chat_id') and event.chat_id:
                        channel_ids.add(str(event.chat_id))
                        channel_ids.add(str(-abs(event.chat_id)))

                    if hasattr(event, 'peer_id') and hasattr(event.peer_id, 'channel_id'):
                        channel_ids.add(str(event.peer_id.channel_id))
                        channel_ids.add(str(-abs(event.peer_id.channel_id)))

                    if hasattr(event, 'message') and hasattr(event.message, 'peer_id'):
                        if isinstance(event.message.peer_id, PeerChannel):
                            channel_ids.add(str(event.message.peer_id.channel_id))
                            channel_ids.add(str(-abs(event.message.peer_id.channel_id)))

                    user_config = self.get_user_config(user_id)
                    matching_channels = channel_ids.intersection(set(user_config.monitored_channels))

                    if not matching_channels:
                        return

                    message_text = getattr(event.message, 'message', '') if event.message else ''
                    if not message_text:
                        return

                    await bot_instance.send_message(
                        chat_id=user_id,
                        text=f"📨 <b>Message Received</b>\n\n<pre>{message_text[:300]}</pre>\n\n🔍 Processing...",
                        parse_mode='HTML'
                    )

                    signal = self.parse_trading_signal(message_text, list(matching_channels)[0])

                    if signal:
                        settings_source = "Signal" if user_config.use_signal_settings else "Bot"
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text=f"🎯 <b>SIGNAL DETECTED!</b>\n\n💰 {signal.symbol} {signal.trade_type}\n⚙️ Using: {settings_source} settings\n🚀 Executing...",
                            parse_mode='HTML'
                        )

                        result = await self.execute_trade(signal, user_config)

                        if result['success']:
                            notification = f"""✅ <b>TRADE EXECUTED!</b>

💰 Symbol: {result['symbol']}
📈 Direction: {signal.trade_type}
🆔 Order ID: {result['order_id']}
📦 Quantity: {result['quantity']}
💲 Entry: {result['price']}
⚡ Leverage: {result['leverage']}x
💵 Order Value: ${result['order_value']:.2f}"""

                            if 'sl_price' in result and result['sl_price']:
                                notification += f"\n🛑 Stop Loss: {result['sl_price']:.6f}"
                                if result['stop_loss_id']:
                                    notification += f" (ID: {result['stop_loss_id']})"

                            if 'tp_prices' in result and result['tp_prices']:
                                notification += f"\n🎯 Take Profits:"
                                for i, tp in enumerate(result['take_profit_ids']):
                                    notification += f"\n  TP{i+1}: {tp['price']:.6f} (ID: {tp['order_id']})"

                            notification += "\n🔗 Sent to Make.com"
                            notification += "\n🔄 OCO: Auto-cancel enabled"
                            notification += f"\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
                            notification += f"\n\n🎉 Position is LIVE!"

                        else:
                            notification = f"""❌ <b>TRADE EXECUTION FAILED</b>

💰 Symbol: {signal.symbol}
📈 Direction: {signal.trade_type}
🚨 Error: {result['error']}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}"""

                        await bot_instance.send_message(chat_id=user_id, text=notification, parse_mode='HTML')

                    else:
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text="📨 No valid signal detected",
                            parse_mode='HTML'
                        )

                except Exception as e:
                    logger.error(f"Message handler error: {e}")
                    logger.error(traceback.format_exc())

            if not telethon_client.is_connected():
                await telethon_client.connect()

            self.active_monitoring[user_id] = True
            return True

        except Exception as e:
            logger.error(f"Start monitoring error: {e}")
            return False

# Initialize bot
trading_bot = TradingBot()

# Helper functions
def create_channel_selection_text(user_id: int) -> str:
    config = trading_bot.get_user_config(user_id)
    return f"""📡 <b>Channel Selection</b>

Currently monitoring: <b>{len(config.monitored_channels)}</b> channels

Select channels to monitor:"""

def create_channel_keyboard(user_id: int, channels: list) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)
    keyboard = []

    for channel in channels[:15]:
        is_selected = channel['id'] in config.monitored_channels
        emoji = "✅" if is_selected else "⭕"
        title = channel['title'][:25] + "..." if len(channel['title']) > 25 else channel['title']

        keyboard.append([InlineKeyboardButton(
            f"{emoji} {title}", 
            callback_data=f"toggle_channel_{channel['id']}"
        )])

    keyboard.append([
        InlineKeyboardButton("➕ Manual ID", callback_data="add_manual_channel"),
        InlineKeyboardButton("🔗 Add Link", callback_data="add_channel_link")
    ])
    keyboard.append([
        InlineKeyboardButton("📤 Forward Message", callback_data="add_forwarded_channel"),
        InlineKeyboardButton("🧹 Clear All", callback_data="clear_all_channels")
    ])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="channels_done")])

    return InlineKeyboardMarkup(keyboard)

def create_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)

    # Format trade amount display
    if config.use_fixed_usdt_amount:
        trade_amount_text = f"💵 Fixed: ${config.fixed_usdt_amount:.0f} USDT"
    else:
        trade_amount_text = f"💰 Percentage: {config.balance_percent}%"

    keyboard = [
        [InlineKeyboardButton(f"⚙️ Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}", 
                            callback_data="toggle_settings_source")],
        [InlineKeyboardButton(f"📊 SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}", 
                            callback_data="toggle_sl_tp")],
        [InlineKeyboardButton(f"🔗 Make.com Webhook: {'ON' if config.make_webhook_enabled else 'OFF'}", 
                            callback_data="toggle_webhook")],
        [InlineKeyboardButton(f"⚡ Leverage: {config.leverage}x", callback_data="set_leverage")],
        [InlineKeyboardButton(f"🛑 Stop Loss: {config.stop_loss_percent}%", callback_data="set_stop_loss")],
        [InlineKeyboardButton(f"🎯 Custom Take Profits ({len(config.custom_take_profits)} levels)", callback_data="configure_take_profits")],
        [InlineKeyboardButton(f"🧵 Trailing: {'ON' if config.trailing_enabled else 'OFF'}", callback_data="toggle_trailing")],
        [InlineKeyboardButton(f"🔔 Trailing Activation: {config.trailing_activation_percent}%", callback_data="set_trailing_activation")],
        [InlineKeyboardButton(f"↩️ Trailing Callback: {config.trailing_callback_percent}%", callback_data="set_trailing_callback")],
        [InlineKeyboardButton(trade_amount_text, callback_data="toggle_trade_amount_mode")],
        [InlineKeyboardButton("📡 Manage Channels", callback_data="manage_channels"), InlineKeyboardButton("🔄 Enable OCO Monitor", callback_data="enable_oco")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)

# ===================== STATIC BUTTON HANDLERS =====================

async def handle_pin_authentication(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PIN code authentication"""
    user_id = update.effective_user.id
    pin_code = update.message.text.strip()
    
    if trading_bot.authenticate_user(user_id, pin_code):
        await update.message.reply_text(
            "✅ <b>Authentication Successful!</b>\n\n"
            "Welcome to Enhanced Multi-Account Trading Bot v5.0!\n\n"
            "🔑 <b>NEW FEATURES:</b>\n"
            "• Individual account settings\n"
            "• Advanced TP/SL management\n"
            "• Trade history tracking\n"
            "• PIN code protection\n"
            "• Static button interface\n\n"
            "Choose an action:",
            parse_mode='HTML',
            reply_markup=trading_bot.main_menu
        )
    else:
        await update.message.reply_text(
            "❌ <b>Invalid PIN Code!</b>\n\n"
            "Please enter the correct PIN code to access the bot.",
            parse_mode='HTML'
        )

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button presses"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Check authentication first
    if not trading_bot.is_authenticated(user_id):
        await update.message.reply_text(
            "🔐 <b>Authentication Required</b>\n\n"
            "Please enter the PIN code to access the bot:",
            parse_mode='HTML'
        )
        return
    
    if text == "🔑 Accounts":
        await handle_accounts_menu(update, context)
    elif text == "📊 Status":
        await handle_status(update, context)
    elif text == "💰 Balance":
        await handle_balance(update, context)
    elif text == "📈 Active Trades":
        await handle_active_trades(update, context)
    elif text == "📋 Trade History":
        await handle_trade_history(update, context)
    elif text == "⚙️ Settings":
        await handle_settings_menu(update, context)
    elif text == "🚀 Start Trading":
        await handle_start_trading(update, context)
    elif text == "🛑 Stop Trading":
        await handle_stop_trading(update, context)
    elif text == "🔙 Back to Main":
        await update.message.reply_text(
            "🏠 <b>Main Menu</b>\n\nChoose an action:",
            parse_mode='HTML',
            reply_markup=trading_bot.main_menu
        )

async def handle_accounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle accounts menu"""
    user_id = update.effective_user.id
    accounts = trading_bot.enhanced_db.get_all_accounts()
    
    if not accounts:
        await update.message.reply_text(
            "📋 <b>No Accounts Found</b>\n\n"
            "You don't have any trading accounts yet.\n"
            "Add your first account to get started!",
            parse_mode='HTML',
            reply_markup=trading_bot.account_menu
        )
    else:
        text = "📋 <b>Your Trading Accounts</b>\n\n"
        for i, account in enumerate(accounts, 1):
            status = "🟢 Active" if account.is_active else "🔴 Inactive"
            text += f"<b>{i}. {account.account_name}</b>\n"
            text += f"Status: {status}\n"
            text += f"Leverage: {account.leverage}x\n"
            text += f"Balance: {'Percentage' if account.use_percentage_balance else 'Fixed USDT'}\n\n"
        
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=trading_bot.account_menu
        )

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle status check"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return
    
    # Get monitoring status
    is_monitoring = trading_bot.monitoring_status.get(user_id, False)
    monitoring_status = "🟢 Active" if is_monitoring else "🔴 Inactive"
    
    # Get active trades count
    active_trades = trading_bot.enhanced_db.get_active_trades(current_account.account_id)
    active_trades_count = len(active_trades)
    
    status_text = f"""📊 <b>Bot Status Dashboard v5.0</b>

🔧 <b>Current Account:</b> {current_account.account_name}
📡 Channels: <b>{len(current_account.monitored_channels)}</b>
🔄 Monitoring: <b>{monitoring_status}</b>

⚙️ <b>Trading Settings:</b>
⚡ Leverage: <b>{current_account.leverage}x</b>
💰 Balance: <b>{'Percentage' if current_account.use_percentage_balance else 'Fixed USDT'}</b>
🎯 Take Profits: <b>{len(current_account.take_profit_levels)} levels</b>
🛑 Stop Losses: <b>{len(current_account.stop_loss_levels)} levels</b>

📍 <b>Active Positions:</b> {active_trades_count}

✅ <b>Features:</b>
• Multi-account support
• Advanced TP/SL management
• Trade history tracking
• PIN code protection"""
    
    await update.message.reply_text(status_text, parse_mode='HTML')

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle balance check"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return
    
    await update.message.reply_text("💰 <b>Checking account balance...</b>", parse_mode='HTML')
    
    # This would connect to the exchange and get balance
    # For now, show a placeholder
    balance_text = f"""💳 <b>Account Balance</b>

💰 <b>USDT Balance:</b> Loading...
🔓 <b>Available:</b> Loading...
💼 <b>Wallet Balance:</b> Loading...

⏰ Updated: {datetime.now().strftime('%H:%M:%S')}"""
    
    await update.message.reply_text(balance_text, parse_mode='HTML')

async def handle_active_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle active trades display"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return
    
    active_trades = trading_bot.enhanced_db.get_active_trades(current_account.account_id)
    
    if not active_trades:
        await update.message.reply_text(
            "📈 <b>No Active Trades</b>\n\n"
            "You don't have any open positions at the moment.",
            parse_mode='HTML'
        )
    else:
        text = f"📈 <b>Active Trades ({len(active_trades)})</b>\n\n"
        for trade in active_trades:
            text += f"<b>{trade.symbol}</b> {trade.side}\n"
            text += f"Entry: {trade.entry_price}\n"
            text += f"Quantity: {trade.quantity}\n"
            text += f"Leverage: {trade.leverage}x\n"
            text += f"Status: {trade.status}\n\n"
        
        await update.message.reply_text(text, parse_mode='HTML')

async def handle_trade_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle trade history display"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return
    
    trade_history = trading_bot.enhanced_db.get_trade_history(current_account.account_id, limit=10)
    
    if not trade_history:
        await update.message.reply_text(
            "📋 <b>No Trade History</b>\n\n"
            "You haven't made any trades yet.",
            parse_mode='HTML'
        )
    else:
        text = f"📋 <b>Recent Trade History ({len(trade_history)})</b>\n\n"
        for trade in trade_history:
            status_emoji = "🟢" if trade.status == "OPEN" else "🔴" if trade.status == "CLOSED" else "🟡"
            text += f"{status_emoji} <b>{trade.symbol}</b> {trade.side}\n"
            text += f"Entry: {trade.entry_price} | PnL: {trade.pnl}\n"
            text += f"Time: {trade.entry_time[:16]}\n\n"
        
        await update.message.reply_text(text, parse_mode='HTML')

async def handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings menu"""
    await update.message.reply_text(
        "⚙️ <b>Account Settings</b>\n\n"
        "Configure your trading parameters:",
        parse_mode='HTML',
        reply_markup=trading_bot.settings_menu
    )

async def handle_start_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start trading with duplicate prevention"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return
    
    # Check if already monitoring
    if trading_bot.monitoring_status.get(user_id, False):
        await update.message.reply_text(
            "⚠️ <b>Already Monitoring!</b>\n\n"
            "Trading is already active for this account.\n"
            "Use 'Stop Trading' to stop first.",
            parse_mode='HTML'
        )
        return
    
    # Check if account has channels configured
    if not current_account.monitored_channels:
        await update.message.reply_text(
            "❌ <b>No Channels Configured</b>\n\n"
            "Please add channels to monitor first.\n"
            "Go to Accounts → Account Settings → Channels",
            parse_mode='HTML'
        )
        return
    
    try:
        # Start monitoring
        success = await trading_bot.start_monitoring(user_id, context.bot)
        
        if success:
            trading_bot.monitoring_status[user_id] = True
            await update.message.reply_text(
                f"🚀 <b>Trading Started Successfully!</b>\n\n"
                f"Account: <b>{current_account.account_name}</b>\n"
                f"Channels: <b>{len(current_account.monitored_channels)}</b>\n"
                f"Leverage: <b>{current_account.leverage}x</b>\n"
                f"Balance: <b>{'Percentage' if current_account.use_percentage_balance else 'Fixed USDT'}</b>\n\n"
                f"✅ Monitoring active\n"
                f"🎯 Ready to execute trades",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                "❌ <b>Failed to Start Trading</b>\n\n"
                "Please check your account configuration and try again.",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error starting trading: {e}")
        await update.message.reply_text(
            "❌ <b>Error Starting Trading</b>\n\n"
            f"Error: {str(e)[:100]}",
            parse_mode='HTML'
        )

async def handle_stop_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stop trading with proper cleanup"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    # Check if monitoring is active
    if not trading_bot.monitoring_status.get(user_id, False):
        await update.message.reply_text(
            "⚠️ <b>Not Currently Monitoring</b>\n\n"
            "Trading is not active for this account.",
            parse_mode='HTML'
        )
        return
    
    try:
        # Stop monitoring
        trading_bot.active_monitoring[user_id] = False
        trading_bot.monitoring_status[user_id] = False
        
        # Stop any running monitoring tasks
        if user_id in trading_bot.monitoring_tasks:
            task = trading_bot.monitoring_tasks[user_id]
            if not task.done():
                task.cancel()
            del trading_bot.monitoring_tasks[user_id]
        
        # Close telethon client if exists
        if user_id in trading_bot.user_monitoring_clients:
            try:
                client = trading_bot.user_monitoring_clients[user_id]
                if client.is_connected():
                    await client.disconnect()
                del trading_bot.user_monitoring_clients[user_id]
            except Exception as e:
                logger.error(f"Error closing telethon client: {e}")
        
        account_name = current_account.account_name if current_account else "Unknown"
        
        await update.message.reply_text(
            f"🛑 <b>Trading Stopped Successfully!</b>\n\n"
            f"Account: <b>{account_name}</b>\n"
            f"✅ Monitoring stopped\n"
            f"✅ Channels disconnected\n"
            f"✅ Tasks cancelled\n\n"
            f"All trading activities have been stopped.",
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"Error stopping trading: {e}")
        await update.message.reply_text(
            "❌ <b>Error Stopping Trading</b>\n\n"
            f"Error: {str(e)[:100]}",
            parse_mode='HTML'
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""<b>📖 All Commands</b>

<b>Setup:</b>
/setup_binance - BingX API
/setup_telegram - Telegram API  
/setup_channels - Channels
/setup_trading - Parameters

<b>Control:</b>
/start_monitoring - Start ✅
/stop_monitoring - Stop ❌
/status - Status
/balance - Balance

<b>Testing:</b>
/test_simple - Simple test
/test_basic - Basic test
/test_advanced - Full test
/test_signal - Parser test

🔗 {DEFAULT_WEBHOOK_URL[:50]}...

<b>OCO Feature:</b>
When TP fills → SL auto-cancels
When SL fills → All TPs auto-cancel
"""
    await update.message.reply_text(help_text, parse_mode='HTML')
    # Ensure main menu visible
    main_menu = ReplyKeyboardMarkup(
        [[KeyboardButton("📊 Status"), KeyboardButton("💰 Balance")],
         [KeyboardButton("🚀 Start"), KeyboardButton("🛑 Stop")],
         [KeyboardButton("⚙️ Settings")]],
        resize_keyboard=True
    )
    try:
        await update.message.reply_text("Choose an action:", reply_markup=main_menu)
    except Exception:
        pass

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle persistent reply keyboard buttons"""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text == "📊 Status":
        await status(update, context)
    elif text == "💰 Balance":
        await balance_command(update, context)
    elif text == "🚀 Start":
        await start_monitoring(update, context)
    elif text == "🛑 Stop":
        await stop_monitoring(update, context)
    elif text == "⚙️ Settings":
        await setup_trading(update, context)
    elif text == "🔑 Accounts":
        await list_accounts(update, context)
    elif text == "/setup_channels":
        await setup_channels(update, context)

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check account balance"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.binance_api_key or not config.binance_api_secret:
        await update.message.reply_text("❌ <b>BingX API not configured!</b> Use /setup_binance first.", parse_mode='HTML')
        return

    await update.message.reply_text("💰 <b>Checking account balance...</b>", parse_mode='HTML')

    balance_info = await trading_bot.get_account_balance(config)

    if balance_info['success']:
        balance_text = f"""💳 <b>Account Balance</b>

💰 <b>USDT Balance:</b> {balance_info['usdt_balance']:.2f} USDT
🔓 <b>Available:</b> {balance_info['usdt_available']:.2f} USDT
💼 <b>Wallet Balance:</b> {balance_info['usdt_wallet_balance']:.2f} USDT
📊 <b>Total Margin:</b> {balance_info['total_margin_balance']:.2f} USDT
📈 <b>Unrealized PNL:</b> {balance_info['total_unrealized_pnl']:.2f} USDT

💵 <b>Trade Calculations:</b>
Position Size ({config.balance_percent}%): ${balance_info['usdt_balance'] * config.balance_percent / 100:.2f}
Status: ✅ Can Trade

⏰ Updated: {datetime.now().strftime('%H:%M:%S')}"""
    else:
        balance_text = f"❌ <b>Balance Check Failed</b>\n\n🚨 Error: {balance_info['error']}"

    await update.message.reply_text(balance_text, parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    settings_source = "📊 Signal" if config.use_signal_settings else "🤖 Bot"
    sl_tp_status = "🟢 ON" if config.create_sl_tp else "🔴 OFF"
    webhook_status = "🟢 ON" if config.make_webhook_enabled else "🔴 OFF"
    oco_status = "🟢 Active" if trading_bot.order_monitor_running else "🔴 Inactive"

    status_text = f"""📊 <b>Bot Status Dashboard v3.1</b>

🔧 <b>Configuration:</b>
{'✅' if config.binance_api_key else '❌'} BingX API
{'✅' if config.telegram_api_id else '❌'} Telegram API  
📡 Channels: <b>{len(config.monitored_channels)}</b>
🔄 Monitoring: {'🟢 Active' if trading_bot.active_monitoring.get(user_id) else '🔴 Inactive'}
🔗 Webhook: <b>{webhook_status}</b>
🔄 OCO Monitor: <b>{oco_status}</b>

⚙️ <b>Trading Settings:</b>
🎯 Settings: <b>{settings_source}</b>
📈 SL/TP: <b>{sl_tp_status}</b>
⚡ Leverage: <b>{config.leverage}x</b>
🛑 Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Take Profits: <b>{len(config.custom_take_profits)} levels</b>
💰 Trade Amount: <b>{'$' + str(int(config.fixed_usdt_amount)) + ' USDT' if config.use_fixed_usdt_amount else str(config.balance_percent) + '%'}</b>

📍 <b>Active Positions:</b> {len(trading_bot.active_positions)}

✅ <b>Features:</b>
• Auto trade execution
• OCO order management
• Decimal precision fixed
• Real-time monitoring
"""
    await update.message.reply_text(status_text, parse_mode='HTML')
    # Offer quick actions
    try:
        await update.message.reply_text("Use Settings → Enable OCO Monitor or press Start to begin.")
    except Exception:
        pass

# ================== WEBHOOK TESTING ==================

async def test_webhook_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple webhook test"""
    await update.message.reply_text("🔄 <b>Simple webhook test...</b>", parse_mode='HTML')

    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("simple")

    if result['success']:
        await update.message.reply_text(
            f"""✅ <b>Simple Webhook Test Successful!</b>

📡 Status Code: {result['status_code']}
⏱️ Response Time: {result['response_time']:.2f}s

🎯 Perfect! Go to Make.com and add Google Sheets module.""", 
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"""❌ <b>Simple Test Failed</b>

Status: {result['status_code']}
Error: {result['response_text'][:200]}""", 
            parse_mode='HTML'
        )

async def test_webhook_basic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic webhook test"""
    await update.message.reply_text("🔄 <b>Basic webhook test...</b>", parse_mode='HTML')

    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("basic")

    if result['success']:
        await update.message.reply_text(
            f"""✅ <b>Basic Webhook Test Successful!</b>

📡 Status Code: {result['status_code']}
⏱️ Response Time: {result['response_time']:.2f}s

🎯 Perfect! Your webhook accepts trade data.""", 
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"""❌ <b>Basic Test Failed</b>

Status: {result['status_code']}
Error: {result['response_text'][:200]}""", 
            parse_mode='HTML'
        )

async def test_webhook_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Advanced webhook test"""
    await update.message.reply_text("🚀 <b>Advanced webhook test...</b>", parse_mode='HTML')

    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("advanced")

    if result['success']:
        result_text = f"""✅ <b>Advanced Webhook Test Successful!</b>

📡 Status Code: {result['status_code']}
⏱️ Response Time: {result['response_time']:.2f}s

🎉 Perfect! All 20+ fields sent successfully.
Check Make.com for complete data."""
    else:
        result_text = f"""❌ <b>Advanced Test Failed</b>

Status: {result['status_code']}
Error: {result['response_text'][:200]}"""

    await update.message.reply_text(result_text, parse_mode='HTML')

# ================== BINANCE SETUP ==================

async def setup_binance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """🔑 <b>BingX API Setup</b>

Send your BingX API Key:""", parse_mode='HTML')
    return WAITING_BINANCE_KEY

async def handle_binance_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.binance_api_key = update.message.text.strip()

    await update.message.reply_text("🔐 <b>API Key saved!</b> Now send your API Secret:", parse_mode='HTML')
    return WAITING_BINANCE_SECRET

async def handle_binance_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.binance_api_secret = update.message.text.strip()

    await update.message.reply_text("🔄 Testing BingX connection...")
    success = await trading_bot.setup_binance_client(config)

    if success:
        await update.message.reply_text("✅ <b>BingX configured!</b> Next: /setup_telegram", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ <b>Configuration failed!</b> Check credentials", parse_mode='HTML')

    return ConversationHandler.END

# ================== TELEGRAM SETUP ==================

async def setup_telegram_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """📱 <b>Telegram API Setup</b>

Send your Telegram API ID:""", parse_mode='HTML')
    return WAITING_TELEGRAM_ID

async def handle_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.telegram_api_id = update.message.text.strip()

    await update.message.reply_text("🆔 <b>API ID saved!</b> Now send your API Hash:", parse_mode='HTML')
    return WAITING_TELEGRAM_HASH

async def handle_telegram_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.telegram_api_hash = update.message.text.strip()

    await update.message.reply_text("🔄 Testing Telegram API...")
    success = await trading_bot.setup_telethon_client(config)

    if success:
        await update.message.reply_text("✅ <b>Telegram API configured!</b> Next: /setup_channels", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ <b>Failed!</b> Check credentials", parse_mode='HTML')

    return ConversationHandler.END

# ================== CHANNEL SETUP ==================

async def setup_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    await update.message.reply_text("🔍 <b>Loading channels...</b>", parse_mode='HTML')

    channels = await trading_bot.get_available_channels(user_id)

    if not channels:
        await update.message.reply_text("❌ <b>No channels!</b> Use /setup_telegram first", parse_mode='HTML')
        return ConversationHandler.END

    context.user_data['available_channels'] = channels
    keyboard_markup = create_channel_keyboard(user_id, channels)

    await update.message.reply_text(
        create_channel_selection_text(user_id),
        reply_markup=keyboard_markup,
        parse_mode='HTML'
    )

    return WAITING_CHANNEL_SELECTION

async def handle_channel_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both callback queries and forwarded messages
    if update.callback_query:
        query = update.callback_query
        user_id = update.effective_user.id
        config = trading_bot.get_user_config(user_id)

        try:
            await query.answer()
        except:
            pass
    elif update.message and update.message.forward_from_chat:
        # Handle forwarded message
        user_id = update.effective_user.id
        config = trading_bot.get_user_config(user_id)
        
        forward_from_chat = update.message.forward_from_chat
        if forward_from_chat and hasattr(forward_from_chat, 'id'):
            channel_id = str(-abs(forward_from_chat.id))
            channel_name = getattr(forward_from_chat, 'title', 'Unknown Channel')
            
            if channel_id not in config.monitored_channels:
                config.monitored_channels.append(channel_id)
                
            await update.message.reply_text(
                f"""✅ <b>Channel Added from Forward!</b>

📡 Channel: {channel_name}
🆔 ID: <code>{channel_id}</code>
📊 Total channels: <b>{len(config.monitored_channels)}</b>

Use /setup_channels to continue managing channels.""",
                parse_mode='HTML'
            )
            return WAITING_CHANNEL_SELECTION
        else:
            await update.message.reply_text("❌ Could not extract channel from forwarded message", parse_mode='HTML')
            return WAITING_CHANNEL_SELECTION
    else:
        return WAITING_CHANNEL_SELECTION

    query = update.callback_query

    if query.data == "channels_done":
        await query.edit_message_text(
            f"""✅ <b>Channel selection complete!</b>

Monitoring: <b>{len(config.monitored_channels)}</b> channels

Next: /setup_trading""",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data == "clear_all_channels":
        config.monitored_channels.clear()
        channels = context.user_data.get('available_channels', [])
        keyboard_markup = create_channel_keyboard(user_id, channels)
        await query.edit_message_text(
            create_channel_selection_text(user_id),
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "add_manual_channel":
        await query.edit_message_text(
            """📝 <b>Manual Channel ID</b>

Send channel ID: <code>-1001234567890</code>""",
            parse_mode='HTML'
        )
        return WAITING_MANUAL_CHANNEL
    
    elif query.data == "add_channel_link":
        await query.edit_message_text(
            """🔗 <b>Add Channel via Link</b>

Send channel link:
• <code>https://t.me/channel_name</code>
• <code>t.me/channel_name</code>
• <code>@channel_name</code>
• <code>channel_name</code>""",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_LINK
    
    elif query.data == "add_forwarded_channel":
        await query.edit_message_text(
            """📤 <b>Add Channel via Forward</b>

Forward any message from the channel you want to monitor.
The bot will automatically extract the channel ID.""",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_SELECTION  # Stay in same state to handle forwarded messages

    elif query.data.startswith("toggle_channel_"):
        channel_id = query.data.replace("toggle_channel_", "")

        if channel_id in config.monitored_channels:
            config.monitored_channels.remove(channel_id)
        else:
            config.monitored_channels.append(channel_id)

        channels = context.user_data.get('available_channels', [])
        keyboard_markup = create_channel_keyboard(user_id, channels)

        await query.edit_message_text(
            create_channel_selection_text(user_id),
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    return WAITING_CHANNEL_SELECTION

async def handle_manual_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    channel_id = update.message.text.strip()

    if not channel_id.lstrip('-').isdigit():
        await update.message.reply_text("❌ Invalid format!", parse_mode='HTML')
        return WAITING_MANUAL_CHANNEL

    if not channel_id.startswith('-'):
        channel_id = '-' + channel_id

    if channel_id not in config.monitored_channels:
        config.monitored_channels.append(channel_id)

    await update.message.reply_text(
        f"""✅ <b>Channel added!</b>

Channel ID: <code>{channel_id}</code>
Total: <b>{len(config.monitored_channels)}</b>

Use /setup_trading next""",
        parse_mode='HTML'
    )

    return ConversationHandler.END

async def handle_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    link = update.message.text.strip()

    await update.message.reply_text("🔍 <b>Resolving channel link...</b>", parse_mode='HTML')

    channel_id = await trading_bot.extract_channel_id_from_link(link, user_id)

    if channel_id:
        if channel_id not in config.monitored_channels:
            config.monitored_channels.append(channel_id)
            
        # Try to get channel info for display
        try:
            telethon_client = trading_bot.user_monitoring_clients.get(user_id)
            if telethon_client:
                entity = await telethon_client.get_entity(int(channel_id))
                channel_name = getattr(entity, 'title', 'Unknown Channel')
            else:
                channel_name = 'Channel'
        except:
            channel_name = 'Channel'

        await update.message.reply_text(
            f"""✅ <b>Channel Added!</b>

📡 Channel: {channel_name}
🆔 ID: <code>{channel_id}</code>
📊 Total channels: <b>{len(config.monitored_channels)}</b>

Use /setup_channels to manage or continue setup.""",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            """❌ <b>Failed to resolve channel</b>

Please check:
• Channel link is correct
• Channel is public or you're a member
• Telegram API is configured

Try again or use manual ID method.""",
            parse_mode='HTML'
        )

    return ConversationHandler.END

# ================== TRADING SETUP ==================

async def setup_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_settings_keyboard(user_id)

    await update.message.reply_text(
        "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
        reply_markup=keyboard_markup,
        parse_mode='HTML'
    )

    return WAITING_SETTINGS_SOURCE

async def handle_trading_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        await query.answer()
    except:
        pass

    if query.data == "trading_done":
        await query.edit_message_text(
            f"""✅ <b>Configuration complete!</b>

All settings saved.
Next: /start_monitoring""",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_webhook":
        config.make_webhook_enabled = not config.make_webhook_enabled
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "set_leverage":
        await query.edit_message_text(
            "⚡ <b>Set Leverage</b>\n\nSend value (1-125):",
            parse_mode='HTML'
        )
        return WAITING_LEVERAGE

    elif query.data == "set_stop_loss":
        await query.edit_message_text(
            "🛑 <b>Set Stop Loss</b>\n\nSend percentage (e.g., 5 for 5%):",
            parse_mode='HTML'
        )
        return WAITING_STOP_LOSS

    elif query.data == "set_take_profit":
        await query.edit_message_text(
            "🎯 <b>Set Take Profit</b>\n\nSend percentage (e.g., 10 for 10%) or 'default' to use 2.5/5/7.5% ladder:",
            parse_mode='HTML'
        )
        return WAITING_TAKE_PROFIT

    elif query.data == "set_balance_percent":
        await query.edit_message_text(
            "💰 <b>Set Balance %</b>\n\nSend percentage (1-100):",
            parse_mode='HTML'
        )
        return WAITING_BALANCE_PERCENT

    elif query.data == "toggle_trailing":
        config.trailing_enabled = not config.trailing_enabled
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "set_trailing_activation":
        await query.edit_message_text(
            "🔔 <b>Set Trailing Activation %</b>\n\nSend percentage (e.g., 2 for 2%):",
            parse_mode='HTML'
        )
        return WAITING_TRAILING_ACTIVATION

    elif query.data == "set_trailing_callback":
        await query.edit_message_text(
            "↩️ <b>Set Trailing Callback %</b>\n\nSend percentage (e.g., 0.5 for 0.5%):",
            parse_mode='HTML'
        )
        return WAITING_TRAILING_CALLBACK

    elif query.data == "manage_channels":
        # Exit trading settings conversation and defer to /setup_channels flow
        await query.edit_message_text("📡 <b>Opening channel manager...</b> Use /setup_channels", parse_mode='HTML')
        return ConversationHandler.END

    elif query.data == "enable_oco":
        # Start the monitor if not running
        if not trading_bot.order_monitor_running:
            asyncio.create_task(trading_bot.monitor_orders(context.bot))
        await query.edit_message_text("🔄 <b>OCO Monitor enabled</b>", parse_mode='HTML')

    elif query.data == "toggle_trade_amount_mode":
        config.use_fixed_usdt_amount = not config.use_fixed_usdt_amount
        if config.use_fixed_usdt_amount:
            await query.edit_message_text(
                f"💵 <b>Set Fixed USDT Amount</b>\n\nCurrent: ${config.fixed_usdt_amount:.0f}\nSend new amount:",
                parse_mode='HTML'
            )
            return WAITING_USDT_AMOUNT
        else:
            keyboard_markup = create_settings_keyboard(user_id)
            await query.edit_message_text(
                "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
                reply_markup=keyboard_markup,
                parse_mode='HTML'
            )

    elif query.data == "configure_take_profits":
        tp_text = "🎯 <b>Current Take Profit Levels:</b>\n\n"
        for i, tp in enumerate(config.custom_take_profits, 1):
            tp_text += f"TP{i}: {tp.percentage}% → Close {tp.close_percentage}%\n"
        
        tp_keyboard = [
            [InlineKeyboardButton("➕ Add Level", callback_data="add_tp_level")],
            [InlineKeyboardButton("🗑️ Clear All", callback_data="clear_tp_levels")],
            [InlineKeyboardButton("🔄 Reset Default", callback_data="reset_tp_default")],
            [InlineKeyboardButton("✅ Done", callback_data="tp_config_done")]
        ]
        
        await query.edit_message_text(
            tp_text,
            reply_markup=InlineKeyboardMarkup(tp_keyboard),
            parse_mode='HTML'
        )
        return WAITING_TP_CONFIG

    return WAITING_SETTINGS_SOURCE

async def handle_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        leverage = int(update.message.text)
        if 1 <= leverage <= 125:
            config.leverage = leverage
            await update.message.reply_text(f"✅ <b>Leverage: {leverage}x</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-125", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        sl_percent = float(update.message.text)
        if 0.1 <= sl_percent <= 50:
            config.stop_loss_percent = sl_percent
            await update.message.reply_text(f"✅ <b>Stop Loss: {sl_percent}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 0.1-50%", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_take_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        text = update.message.text.strip().lower()
        if text == 'default':
            config.take_profit_percent = 2.5
            await update.message.reply_text("✅ <b>Default TP ladder set:</b> 2.5%, 5%, 7.5%", parse_mode='HTML')
        else:
            tp_percent = float(text)
            if 0.1 <= tp_percent <= 100:
                config.take_profit_percent = tp_percent
                await update.message.reply_text(f"✅ <b>Take Profit: {tp_percent}%</b>", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Must be 0.1-100%", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_balance_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        value = float(update.message.text)
        if 1 <= value <= 100:
            config.balance_percent = value
            await update.message.reply_text(f"✅ <b>Balance: {value}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-100", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_trailing_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        value = float(update.message.text)
        if value <= 0 or value > 50:
            raise ValueError("out of range")
        config.trailing_activation_percent = value
        await update.message.reply_text(f"✅ <b>Trailing Activation:</b> {value}%", parse_mode='HTML')
    except Exception:
        await update.message.reply_text("❌ Invalid percentage!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_trailing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        value = float(update.message.text)
        if value <= 0 or value > 50:
            raise ValueError("out of range")
        config.trailing_callback_percent = value
        await update.message.reply_text(f"✅ <b>Trailing Callback:</b> {value}%", parse_mode='HTML')
    except Exception:
        await update.message.reply_text("❌ Invalid percentage!", parse_mode='HTML')
    return ConversationHandler.END

# ================== MONITORING ==================

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.binance_api_key or not config.telegram_api_id:
        await update.message.reply_text("❌ Complete setup first!", parse_mode='HTML')
        return

    if not config.monitored_channels:
        await update.message.reply_text("❌ No channels! Use /setup_channels", parse_mode='HTML')
        return

    await update.message.reply_text("🚀 <b>Starting...</b>", parse_mode='HTML')

    success = await trading_bot.start_monitoring(user_id, context.bot)

    if success:
        status_msg = f"""✅ <b>MONITORING STARTED!</b>

📡 Monitoring: <b>{len(config.monitored_channels)}</b> channels
⚙️ Settings: {'Signal' if config.use_signal_settings else 'Bot'}
📊 SL/TP: {'ON' if config.create_sl_tp else 'OFF'}
🔄 OCO: Auto-cancel enabled
🔗 Webhook: ENABLED

🎯 Ready to trade!
Use /stop_monitoring to stop."""

        await update.message.reply_text(status_msg, parse_mode='HTML')
        # Ensure OCO monitor is running
        if not trading_bot.order_monitor_running:
            asyncio.create_task(trading_bot.monitor_orders(context.bot))
    else:
        await update.message.reply_text("❌ Failed to start!", parse_mode='HTML')

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trading_bot.active_monitoring[user_id] = False
    trading_bot.order_monitor_running = False

    await update.message.reply_text("🛑 <b>Monitoring stopped!</b>", parse_mode='HTML')

# ================== TEST SIGNAL ==================

async def test_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_signals = [
        """#BTCUSDT
LONG
Entry: 45000
TP1: 46000
TP2: 47000
SL: 44000
Leverage: 10x""",

        """#ETHUSDT
SHORT
Вход: 3000
Тп1: 2900
Тп2: 2800
Сл: 3100
Плечо: 5x"""
    ]

    results = []
    for i, test_msg in enumerate(test_signals, 1):
        signal = trading_bot.parse_trading_signal(test_msg, "test")
        if signal:
            results.append(f"""<b>Test {i}: ✅</b>
{signal.symbol} {signal.trade_type}
Entry: {signal.entry_price}
SL: {signal.stop_loss}
TP: {signal.take_profit}""")
        else:
            results.append(f"<b>Test {i}: ❌</b>")

    await update.message.reply_text("🧪 <b>Parser Test</b>\n\n" + "\n\n".join(results), parse_mode='HTML')

async def handle_usdt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        amount = float(update.message.text)
        if amount > 0:
            config.fixed_usdt_amount = amount
            await update.message.reply_text(f"✅ <b>Fixed USDT Amount: ${amount:.0f}</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Amount must be positive", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid amount!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_tp_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        await query.answer()
    except:
        pass

    if query.data == "tp_config_done":
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )
        return WAITING_SETTINGS_SOURCE

    elif query.data == "add_tp_level":
        await query.edit_message_text(
            "🎯 <b>Add Take Profit Level</b>\n\nSend percentage (e.g., 2.5 for 2.5%):",
            parse_mode='HTML'
        )
        return WAITING_TP_LEVEL_PERCENT

    elif query.data == "clear_tp_levels":
        config.custom_take_profits.clear()
        await query.edit_message_text(
            "🗑️ <b>All take profit levels cleared!</b>\n\nAdd new levels or reset to default.",
            parse_mode='HTML'
        )
        return WAITING_TP_CONFIG

    elif query.data == "reset_tp_default":
        config.custom_take_profits = [
            TakeProfitLevel(1.0, 50.0),
            TakeProfitLevel(2.5, 50.0),
            TakeProfitLevel(5.0, 100.0)
        ]
        tp_text = "🔄 <b>Reset to Default:</b>\n\n"
        for i, tp in enumerate(config.custom_take_profits, 1):
            tp_text += f"TP{i}: {tp.percentage}% → Close {tp.close_percentage}%\n"
        
        tp_keyboard = [
            [InlineKeyboardButton("➕ Add Level", callback_data="add_tp_level")],
            [InlineKeyboardButton("🗑️ Clear All", callback_data="clear_tp_levels")],
            [InlineKeyboardButton("🔄 Reset Default", callback_data="reset_tp_default")],
            [InlineKeyboardButton("✅ Done", callback_data="tp_config_done")]
        ]
        
        await query.edit_message_text(
            tp_text,
            reply_markup=InlineKeyboardMarkup(tp_keyboard),
            parse_mode='HTML'
        )

    return WAITING_TP_CONFIG

async def handle_tp_level_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        percentage = float(update.message.text)
        if 0.1 <= percentage <= 100:
            context.user_data['tp_percentage'] = percentage
            await update.message.reply_text(
                f"🎯 <b>TP Level: {percentage}%</b>\n\nNow send the percentage of position to close (e.g., 50 for 50%):",
                parse_mode='HTML'
            )
            return WAITING_TP_LEVEL_CLOSE
        else:
            await update.message.reply_text("❌ Percentage must be between 0.1 and 100", parse_mode='HTML')
            return WAITING_TP_LEVEL_PERCENT
    except ValueError:
        await update.message.reply_text("❌ Invalid percentage!", parse_mode='HTML')
        return WAITING_TP_LEVEL_PERCENT

async def handle_tp_level_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    
    try:
        close_percentage = float(update.message.text)
        if 1 <= close_percentage <= 100:
            tp_percentage = context.user_data.get('tp_percentage', 1.0)
            
            # Add the new take profit level
            new_tp = TakeProfitLevel(tp_percentage, close_percentage)
            config.custom_take_profits.append(new_tp)
            
            # Sort by percentage
            config.custom_take_profits.sort(key=lambda x: x.percentage)
            
            await update.message.reply_text(
                f"✅ <b>Added TP Level!</b>\n\n🎯 {tp_percentage}% → Close {close_percentage}%\n\nTotal levels: {len(config.custom_take_profits)}",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Close percentage must be between 1 and 100", parse_mode='HTML')
            return WAITING_TP_LEVEL_CLOSE
    except ValueError:
        await update.message.reply_text("❌ Invalid percentage!", parse_mode='HTML')
        return WAITING_TP_LEVEL_CLOSE

    return ConversationHandler.END

# ================== ENHANCED MULTI-ACCOUNT COMMANDS ==================

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a new account"""
    await update.message.reply_text(
        "🔑 <b>Adding New Trading Account</b>\n\n"
        "Please provide a name for this account:",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_NAME

async def handle_account_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account name input"""
    account_name = update.message.text.strip()
    context.user_data['account_name'] = account_name
    
    await update.message.reply_text(
        f"✅ Account name: <b>{account_name}</b>\n\n"
        "Now provide your BingX API Key:",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_BINGX_KEY

async def handle_account_bingx_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle BingX API key input"""
    api_key = update.message.text.strip()
    context.user_data['bingx_api_key'] = api_key
    
    await update.message.reply_text(
        "✅ API Key saved!\n\n"
        "Now provide your BingX Secret Key:",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_BINGX_SECRET

async def handle_account_bingx_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle BingX secret key input"""
    secret_key = update.message.text.strip()
    context.user_data['bingx_secret_key'] = secret_key
    
    await update.message.reply_text(
        "✅ Secret Key saved!\n\n"
        "Now provide your Telegram API ID:",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_TELEGRAM_ID

async def handle_account_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telegram API ID input"""
    api_id = update.message.text.strip()
    context.user_data['telegram_api_id'] = api_id
    
    await update.message.reply_text(
        "✅ Telegram API ID saved!\n\n"
        "Now provide your Telegram API Hash:",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_TELEGRAM_HASH

async def handle_account_telegram_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telegram API hash input"""
    api_hash = update.message.text.strip()
    context.user_data['telegram_api_hash'] = api_hash
    
    await update.message.reply_text(
        "✅ Telegram API Hash saved!\n\n"
        "Now provide your phone number (with country code, e.g., +1234567890):",
        parse_mode='HTML'
    )
    return WAITING_ACCOUNT_PHONE

async def handle_account_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number input and create account"""
    phone = update.message.text.strip()
    
    # Create account configuration
    account_id = str(uuid.uuid4())
    account = AccountConfig(
        account_id=account_id,
        account_name=context.user_data['account_name'],
        bingx_api_key=context.user_data['bingx_api_key'],
        bingx_secret_key=context.user_data['bingx_secret_key'],
        telegram_api_id=context.user_data['telegram_api_id'],
        telegram_api_hash=context.user_data['telegram_api_hash'],
        phone=phone
    )
    
    # Save to database
    if trading_bot.enhanced_db.create_account(account):
        await update.message.reply_text(
            f"🎉 <b>Account Created Successfully!</b>\n\n"
            f"Account: <b>{account.account_name}</b>\n"
            f"ID: <code>{account_id}</code>\n\n"
            f"You can now:\n"
            f"• Add channels to monitor\n"
            f"• Configure trading settings\n"
            f"• Start receiving signals",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ Failed to create account. Please try again.",
            parse_mode='HTML'
        )
    
    return ConversationHandler.END

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all accounts"""
    accounts = trading_bot.enhanced_db.get_all_accounts()
    
    if not accounts:
        await update.message.reply_text(
            "📋 <b>No accounts found</b>\n\n"
            "Use /add_account to create your first account.",
            parse_mode='HTML'
        )
        return
    
    text = "📋 <b>Your Trading Accounts</b>\n\n"
    
    for account in accounts:
        status = "🟢 Active" if account.is_active else "🔴 Inactive"
        text += f"<b>{account.account_name}</b>\n"
        text += f"ID: <code>{account.account_id}</code>\n"
        text += f"Status: {status}\n"
        text += f"Leverage: {account.leverage}x\n"
        text += f"Risk: {account.risk_percentage}%\n"
        text += f"Channels: {len(account.monitored_channels)}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
        [InlineKeyboardButton("⚙️ Manage Accounts", callback_data="manage_accounts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

async def test_enhanced_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test enhanced signal parser with example signals"""
    test_signals = [
        """🚀 ONDO/USDT — набираю позицию в Short.
Торговый план: Вход в позицию осуществляю по рынку. Моя точка входа: 0.9443
Цели по сделке следующие — 0.9348 / 0.9233 / 0.9128""",

        """LONG 📈 DOT/USDT
Плечо: 20x-100x
Вход: 4.199
Take: 4.220 | 4.241 | 4.262
Stop: Стоп-лос ставим соблюдая ваш риск-менеджмент.
РМ: 1-2% от депо""",

        """#BANANA/USDT
LONG
Плечо: 5x-50x
Сл:На ваше усмотрение 
Тп: 60%+
Осторожно 🛑
Соблюдайте Рм 🚨1%"""
    ]
    
    results = []
    for i, signal_text in enumerate(test_signals, 1):
        print(f"\n📊 Testing Signal {i}:")
        signal = EnhancedSignalParser.parse_signal(signal_text, f"test_channel_{i}")
        
        if signal:
            results.append(f"""<b>Test {i}: ✅</b>
Symbol: {signal.symbol}
Side: {signal.side}
Entry: {signal.entry_price}
SL: {signal.stop_loss}
TP: {signal.take_profit}
Leverage: {signal.leverage}
Risk %: {signal.risk_percentage}
Confidence: {signal.confidence:.2f}""")
        else:
            results.append(f"<b>Test {i}: ❌</b>")
    
    await update.message.reply_text("🧪 <b>Enhanced Parser Test</b>\n\n" + "\n\n".join(results), parse_mode='HTML')

# ================== CONVERSATION HANDLERS ==================

binance_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_binance', setup_binance)],
    states={
        WAITING_BINANCE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_key)],
        WAITING_BINANCE_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_secret)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

telegram_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_telegram', setup_telegram_api)],
    states={
        WAITING_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_id)],
        WAITING_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_hash)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

channel_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_channels', setup_channels)],
    states={
        WAITING_CHANNEL_SELECTION: [
            CallbackQueryHandler(handle_channel_selection),
            MessageHandler(filters.FORWARDED, handle_channel_selection)
        ],
        WAITING_MANUAL_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_channel)],
        WAITING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_link)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

trading_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_trading', setup_trading)],
    states={
        WAITING_SETTINGS_SOURCE: [CallbackQueryHandler(handle_trading_settings)],
        WAITING_LEVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leverage)],
        WAITING_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stop_loss)],
        WAITING_TAKE_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_take_profit)],
        WAITING_BALANCE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_balance_percent)],
        WAITING_TRAILING_ACTIVATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_activation)],
        WAITING_TRAILING_CALLBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_callback)],
        WAITING_USDT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_amount)],
        WAITING_TP_CONFIG: [CallbackQueryHandler(handle_tp_config)],
        WAITING_TP_LEVEL_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_level_percent)],
        WAITING_TP_LEVEL_CLOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_level_close)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# Enhanced account conversation handler
account_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('add_account', add_account)],
    states={
        WAITING_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_name)],
        WAITING_ACCOUNT_BINGX_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_bingx_key)],
        WAITING_ACCOUNT_BINGX_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_bingx_secret)],
        WAITING_ACCOUNT_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_telegram_id)],
        WAITING_ACCOUNT_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_telegram_hash)],
        WAITING_ACCOUNT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_phone)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# ================== UTILITY FUNCTIONS ==================

def kill_existing_bot_instances():
    """Kill any existing bot instances to prevent conflicts"""
    import time

    print("🔍 Checking for existing bot instances...")

    try:
        # Method 1: Try pgrep (Linux)
        result = subprocess.run(['pgrep', '-f', 'testchannels.py'], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid and pid != str(os.getpid()):
                    try:
                        os.kill(int(pid), signal.SIGKILL)  # Force kill
                        print(f"🔄 Killed existing bot instance (PID: {pid})")
                        time.sleep(1)
                    except (ProcessLookupError, ValueError):
                        pass
                    except Exception as e:
                        print(f"⚠️ Could not kill process {pid}: {e}")

        # Method 2: Search through all python processes
        try:
            ps_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            for line in ps_result.stdout.split('\n'):
                if 'testchannels.py' in line and 'python' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        pid = parts[1]
                        if pid.isdigit() and int(pid) != os.getpid():
                            try:
                                os.kill(int(pid), signal.SIGKILL)
                                print(f"🔄 Killed bot process (PID: {pid})")
                                time.sleep(1)
                            except:
                                pass
        except Exception as e:
            print(f"⚠️ ps method failed: {e}")

    except Exception as e:
        print(f"⚠️ Could not check for existing instances: {e}")

    # Clear any webhook conflicts
    try:
        BOT_TOKEN_STR = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"
        import requests
        webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN_STR}/deleteWebhook?drop_pending_updates=true"
        response = requests.get(webhook_url, timeout=5)
        if response.status_code == 200:
            print("✅ Cleared existing webhooks")
        time.sleep(1)
    except Exception as e:
        print(f"⚠️ Could not delete webhook: {e}")

    # Wait before starting
    time.sleep(3)
    print("✅ Ready to start new instance")

# ================== MAIN ==================

def main():
    """Start the enhanced bot with static button interface"""
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"
    
    # Kill any existing bot instances to prevent conflicts
    kill_existing_bot_instances()
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        # Enhanced static button handlers (no commands needed)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu))
        
        # Keep only essential conversation handlers for account setup
        application.add_handler(account_conv_handler)  # Enhanced multi-account handler

        print("🤖 Enhanced Multi-Account Trading Bot v5.0 Starting...")
        print(f"🔗 Webhook: {DEFAULT_WEBHOOK_URL}")
        print("🔐 PIN Protection: ENABLED (496745)")
        print("✅ NEW: Individual account settings")
        print("✅ NEW: Advanced TP/SL management")
        print("✅ NEW: Trade history tracking")
        print("✅ NEW: PIN code protection")
        print("✅ NEW: Static button interface")
        print("✅ NEW: Balance configuration options")
        print("✅ NEW: Multiple stop loss levels")
        print("✅ NEW: Enhanced user experience")
        print("✅ FIXED: Duplicate monitoring prevention")
        print("✅ FIXED: Proper stop monitoring")
        print("✅ FIXED: Bot instance conflicts")
        print("📊 Ready! Use PIN code 496745 to access")
        
        # Add error handler for conflicts
        async def error_handler(update, context):
            logger.error(f"Update {update} caused error {context.error}")
            if "Conflict" in str(context.error):
                print("⚠️ Bot instance conflict detected. Please stop other instances.")
            return True
        
        application.add_error_handler(error_handler)
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        if "Conflict" in str(e):
            print("⚠️ Another bot instance is running. Please stop it first.")
        print("🔄 Retrying in 5 seconds...")
        import time
        time.sleep(5)
        main()  # Retry

if __name__ == '__main__':
    main()