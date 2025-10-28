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
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import os
import sys
import traceback
import requests
import signal
import shutil

# Suppress PTBUserWarning for ConversationHandler CallbackQueryHandler warnings
import warnings
from telegram.warnings import PTBUserWarning
warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*CallbackQueryHandler.*per_message.*")

# Import python-telegram-bot
from telegram import (
    Update,
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
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
from telethon.errors import ApiIdInvalidError, SessionPasswordNeededError

# [Rest of your code remains exactly the same...]


# Bot Configuration
BOT_PIN_CODE = os.getenv('BOT_PIN_CODE')  # PIN code for bot access
DEFAULT_TELEGRAM_API_ID = os.getenv('DEFAULT_TELEGRAM_API_ID')
DEFAULT_TELEGRAM_API_HASH = os.getenv('DEFAULT_TELEGRAM_API_HASH')
DEFAULT_TELEGRAM_PHONE = os.getenv('DEFAULT_TELEGRAM_PHONE')
# Shared Telethon session file for all accounts (pre-authorized)
SHARED_TELETHON_SESSION = os.getenv('SHARED_TELETHON_SESSION')
# Defaults are empty; real keys are loaded per-account or via settings UI
DEFAULT_BINANCE_API_KEY = os.getenv('BINGX_API_KEY', '')
DEFAULT_BINANCE_API_SECRET = os.getenv('BINGX_API_SECRET', '')

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
 WAITING_ACCOUNT_SELECTION, WAITING_ACCOUNT_SETTINGS,
 WAITING_AUTH_CODE, WAITING_AUTH_PASSWORD) = range(36)

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
    # Unique identifier for the trade (typically the entry order id)
    trade_id: Optional[str] = None
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
    user_id: int = 0  # Telegram user ID who owns this account
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
    
    # Additional trading settings
    use_signal_settings: bool = False
    create_sl_tp: bool = True
    make_webhook_enabled: bool = False
    trailing_enabled: bool = False
    trailing_activation_percent: float = 2.0
    trailing_callback_percent: float = 0.5
    cooldown_enabled: bool = False
    cooldown_hours: int = 24
    trading_type: str = "swap"  # 'spot' or 'swap' (futures/perpetual)
    
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
    account_id: str = ""
    
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
        # Choose a persistent database path when available
        try:
            # Prefer explicit configuration first
            configured_path = os.getenv('ENHANCED_DB_PATH') or os.getenv('DB_PATH')
            # Then try common Railway volume envs
            if not configured_path:
                volume_envs = [
                    os.getenv('RAILWAY_VOLUME_MOUNT_PATH'),
                    os.getenv('RAILWAY_VOLUME_DIR'),
                    os.getenv('RAILWAY_VOLUME_PATH')
                ]
                for v in volume_envs:
                    if v and v.strip():
                        configured_path = os.path.join(v.strip(), 'enhanced_trading_bot.db')
                        break
            if configured_path and isinstance(configured_path, str) and configured_path.strip():
                db_path = configured_path.strip()
            elif db_path == "enhanced_trading_bot.db" and os.path.isdir('/data'):
                # Prefer a typical persistent mount path if present (e.g., Railway volume)
                db_path = "/data/enhanced_trading_bot.db"
            # Ensure parent directory exists
            parent_dir = os.path.dirname(db_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            # If the chosen DB path does not exist but we can find an existing DB
            # in common previous locations, migrate it so accounts persist across redeploys
            try:
                if not os.path.exists(db_path):
                    candidate_old_paths = [
                        os.path.join(os.getcwd(), 'enhanced_trading_bot.db'),
                        os.path.join('/workspace', 'enhanced_trading_bot.db'),
                        os.path.join(os.path.dirname(__file__), 'enhanced_trading_bot.db'),
                    ]
                    for old_path in candidate_old_paths:
                        if old_path != db_path and os.path.exists(old_path):
                            try:
                                shutil.copy2(old_path, db_path)
                                logger.info(f"📦 Migrated database from {old_path} -> {db_path}")
                                break
                            except Exception as mig_e:
                                logger.warning(f"⚠️ Database migration attempt failed from {old_path}: {mig_e}")
            except Exception as mig_outer:
                logger.debug(f"DB migration check error: {mig_outer}")
        except Exception:
            # Fall back silently to provided db_path
            pass

        self.db_path = db_path
        logger.info(f"🗄️ Using database at: {self.db_path}")
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
                    user_id INTEGER DEFAULT 0,
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
                    signal_channels TEXT DEFAULT '[]',
                    use_signal_settings BOOLEAN DEFAULT FALSE,
                    create_sl_tp BOOLEAN DEFAULT TRUE,
                    make_webhook_enabled BOOLEAN DEFAULT FALSE,
                    trailing_enabled BOOLEAN DEFAULT FALSE,
                    trailing_activation_percent REAL DEFAULT 2.0,
                    trailing_callback_percent REAL DEFAULT 0.5,
                    cooldown_enabled BOOLEAN DEFAULT FALSE,
                    cooldown_hours INTEGER DEFAULT 24,
                    trading_type TEXT DEFAULT 'swap'
                )
            ''')
            
            # Add new columns if they don't exist (for existing databases)
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN user_id INTEGER DEFAULT 0")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN use_signal_settings BOOLEAN DEFAULT FALSE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN cooldown_enabled BOOLEAN DEFAULT FALSE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN cooldown_hours INTEGER DEFAULT 24")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN create_sl_tp BOOLEAN DEFAULT TRUE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN make_webhook_enabled BOOLEAN DEFAULT FALSE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN trailing_enabled BOOLEAN DEFAULT FALSE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN trailing_activation_percent REAL DEFAULT 2.0")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN trailing_callback_percent REAL DEFAULT 0.5")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE accounts ADD COLUMN trading_type TEXT DEFAULT 'swap'")
            except:
                pass
            
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
            
            # Application-wide settings table (for editable defaults)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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

            # Ensure timestamps are set
            if not account.created_at:
                account.created_at = datetime.now().isoformat()
            if not account.last_used:
                account.last_used = datetime.now().isoformat()

            cursor.execute('''
                INSERT OR REPLACE INTO accounts (
                    account_id, account_name, bingx_api_key, bingx_secret_key,
                    telegram_api_id, telegram_api_hash, phone, user_id, is_active,
                    created_at, last_used, leverage, risk_percentage,
                    default_symbol, auto_trade_enabled, use_percentage_balance,
                    balance_percentage, fixed_usdt_amount,
                    take_profit_levels, stop_loss_levels,
                    monitored_channels, signal_channels,
                    use_signal_settings, create_sl_tp, make_webhook_enabled,
                    trailing_enabled, trailing_activation_percent, trailing_callback_percent,
                    cooldown_enabled, cooldown_hours, trading_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account.account_id, account.account_name, account.bingx_api_key,
                account.bingx_secret_key, account.telegram_api_id, account.telegram_api_hash,
                account.phone, account.user_id, account.is_active, account.created_at, account.last_used,
                account.leverage, account.risk_percentage, account.default_symbol,
                account.auto_trade_enabled, account.use_percentage_balance,
                account.balance_percentage, account.fixed_usdt_amount,
                json.dumps([{'percentage': tp.percentage, 'close_percentage': tp.close_percentage} 
                           for tp in account.take_profit_levels]),
                json.dumps([{'percentage': sl.percentage, 'close_percentage': sl.close_percentage} 
                           for sl in account.stop_loss_levels]),
                json.dumps(account.monitored_channels),
                json.dumps(account.signal_channels),
                account.use_signal_settings, account.create_sl_tp, account.make_webhook_enabled,
                account.trailing_enabled, account.trailing_activation_percent, account.trailing_callback_percent,
                account.cooldown_enabled, account.cooldown_hours, account.trading_type
            ))

            conn.commit()
            conn.close()
            logger.info(f"✅ Account {account.account_name} created successfully in database")
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
                try:
                    # Parse TP levels
                    tp_levels = []
                    if row[18]:  # take_profit_levels column (shifted by 1)
                        tp_data = json.loads(row[18])
                        tp_levels = [TakeProfitLevel(tp['percentage'], tp['close_percentage']) 
                                    for tp in tp_data]

                    # Parse SL levels
                    sl_levels = []
                    if row[19]:  # stop_loss_levels column (shifted by 1)
                        sl_data = json.loads(row[19])
                        sl_levels = [StopLossLevel(sl['percentage'], sl['close_percentage']) 
                                    for sl in sl_data]

                    account = AccountConfig(
                        account_id=row[0],
                        account_name=row[1],
                        bingx_api_key=row[2],
                        bingx_secret_key=row[3],
                        telegram_api_id=row[4],
                        telegram_api_hash=row[5],
                        phone=row[6],
                        user_id=int(row[7]) if len(row) > 7 and row[7] else 0,
                        is_active=bool(row[8]),
                        created_at=row[9],
                        last_used=row[10],
                        leverage=row[11],
                        risk_percentage=row[12],
                        default_symbol=row[13],
                        auto_trade_enabled=bool(row[14]),
                        use_percentage_balance=bool(row[15]),
                        balance_percentage=row[16],
                        fixed_usdt_amount=row[17],
                        take_profit_levels=tp_levels,
                        stop_loss_levels=sl_levels,
                        monitored_channels=json.loads(row[20]) if row[20] else [],
                        signal_channels=json.loads(row[21]) if row[21] else [],
                        use_signal_settings=bool(row[22]) if len(row) > 22 else False,
                        create_sl_tp=bool(row[23]) if len(row) > 23 else True,
                        make_webhook_enabled=bool(row[24]) if len(row) > 24 else False,
                        trailing_enabled=bool(row[25]) if len(row) > 25 else False,
                        trailing_activation_percent=float(row[26]) if len(row) > 26 else 2.0,
                        trailing_callback_percent=float(row[27]) if len(row) > 27 else 0.5,
                        cooldown_enabled=bool(row[28]) if len(row) > 28 else False,
                        cooldown_hours=int(row[29]) if len(row) > 29 and row[29] is not None else 24,
                        trading_type=str(row[30]) if len(row) > 30 and row[30] else 'swap'
                    )
                    accounts.append(account)
                except Exception as e:
                    logger.error(f"❌ Error parsing account row: {e}")
                    continue

            logger.info(f"✅ Retrieved {len(accounts)} accounts from database")
            return accounts
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return []

    # =============== Settings and Accounts Update Helpers ===============

    def set_app_setting(self, key: str, value: Any) -> bool:
        """Upsert a key/value setting in app_settings table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', (key, json.dumps(value)))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save app setting {key}: {e}")
            return False

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM app_settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0] is not None:
                try:
                    return json.loads(row[0])
                except Exception:
                    return row[0]
            return default
        except Exception as e:
            logger.error(f"❌ Failed to read app setting {key}: {e}")
            return default

    def get_default_settings(self) -> Dict[str, Any]:
        """Return editable default settings (with DB overrides if present)."""
        try:
            # Start with hard-coded defaults
            defaults = {
                'leverage': DEFAULT_SETTINGS.get('leverage', 10),
                'risk_percentage': DEFAULT_SETTINGS.get('risk_percentage', 2.0),
                'sl_level': DEFAULT_SETTINGS.get('sl_level', -10.0),
                'tp_levels': DEFAULT_SETTINGS.get('tp_levels', [50.0, 100.0, 150.0]),
            }
            # Overlay DB values when present
            for k in list(defaults.keys()):
                stored = self.get_app_setting(f'default_{k}', None)
                if stored is not None:
                    defaults[k] = stored
            return defaults
        except Exception as e:
            logger.error(f"❌ Failed to build default settings: {e}")
            return DEFAULT_SETTINGS

    def update_account_name(self, account_id: str, new_name: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET account_name = ? WHERE account_id = ?', (new_name, account_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to rename account {account_id}: {e}")
            return False

    def soft_delete_account(self, account_id: str) -> bool:
        """Soft delete by setting is_active = FALSE."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET is_active = FALSE WHERE account_id = ?', (account_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete account {account_id}: {e}")
            return False

    def update_account_settings(self, account_id: str, **kwargs) -> bool:
        """Update basic scalar settings on an account row.
        Allowed keys: leverage, risk_percentage, use_percentage_balance, balance_percentage, fixed_usdt_amount,
        use_signal_settings, create_sl_tp, make_webhook_enabled, trailing_enabled, 
        trailing_activation_percent, trailing_callback_percent, trading_type
        """
        allowed = {
            'leverage', 'risk_percentage', 'use_percentage_balance', 'balance_percentage', 'fixed_usdt_amount',
            'use_signal_settings', 'create_sl_tp', 'make_webhook_enabled', 'trailing_enabled',
            'trailing_activation_percent', 'trailing_callback_percent',
            'cooldown_enabled', 'cooldown_hours', 'trading_type'
        }
        set_clauses = []
        values: List[Any] = []
        for key, val in kwargs.items():
            if key in allowed:
                set_clauses.append(f"{key} = ?")
                values.append(val)
        if not set_clauses:
            return True
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            sql = f"UPDATE accounts SET {', '.join(set_clauses)} WHERE account_id = ?"
            values.append(account_id)
            cursor.execute(sql, tuple(values))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update account settings for {account_id}: {e}")
            return False

    def update_account_take_profit_levels(self, account_id: str, tp_levels: List[TakeProfitLevel]) -> bool:
        try:
            payload = json.dumps([{'percentage': tp.percentage, 'close_percentage': tp.close_percentage} for tp in tp_levels])
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET take_profit_levels = ? WHERE account_id = ?', (payload, account_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update TP levels for {account_id}: {e}")
            return False

    def update_account_stop_loss_levels(self, account_id: str, sl_levels: List[StopLossLevel]) -> bool:
        try:
            payload = json.dumps([{'percentage': sl.percentage, 'close_percentage': sl.close_percentage} for sl in sl_levels])
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET stop_loss_levels = ? WHERE account_id = ?', (payload, account_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update SL levels for {account_id}: {e}")
            return False

    def update_monitored_channels(self, account_id: str, channels: List[Union[str, int]]) -> bool:
        try:
            payload = json.dumps([int(str(c)) for c in channels if str(c).lstrip('-').isdigit()])
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET monitored_channels = ? WHERE account_id = ?', (payload, account_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update monitored channels for {account_id}: {e}")
            return False
    
    def update_account_user_id(self, account_id: str, user_id: int) -> bool:
        """Update the user_id for an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET user_id = ? WHERE account_id = ?', (user_id, account_id))
            conn.commit()
            conn.close()
            logger.info(f"✅ Updated user_id={user_id} for account {account_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update user_id for {account_id}: {e}")
            return False
    
    def get_user_accounts(self, user_id: int) -> List[AccountConfig]:
        """Get all accounts for a specific user"""
        try:
            all_accounts = self.get_all_accounts()
            user_accounts = [acc for acc in all_accounts if acc.user_id == user_id]
            return user_accounts
        except Exception as e:
            logger.error(f"❌ Failed to get user accounts for user {user_id}: {e}")
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
    
    def get_trade_history(self, account_id: str, limit: int = 50, only_closed: bool = False) -> List[TradeHistory]:
        """Get trade history for an account
        
        Args:
            account_id: The account ID to filter trades
            limit: Maximum number of trades to return
            only_closed: If True, only return closed/inactive trades (not OPEN)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if only_closed:
                cursor.execute('''
                    SELECT * FROM trade_history 
                    WHERE account_id = ? AND status != 'OPEN'
                    ORDER BY entry_time DESC 
                    LIMIT ?
                ''', (account_id, limit))
            else:
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
                WHERE account_id = ? AND status = 'OPEN'
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

    def can_trade_symbol(self, account_id: str, symbol: str, cooldown_hours: int = 24) -> bool:
        """Check if a symbol can be traded (24-hour cooldown per symbol per account)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get the most recent trade for this symbol and account
            cursor.execute('''
                SELECT entry_time FROM trade_history 
                WHERE account_id = ? AND symbol = ? 
                ORDER BY entry_time DESC 
                LIMIT 1
            ''', (account_id, symbol))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                # No previous trade, can trade
                return True
            
            # Parse the entry_time and check if cooldown has passed
            from datetime import datetime, timedelta
            last_trade_time = datetime.fromisoformat(row[0])
            current_time = datetime.now()
            time_diff = current_time - last_trade_time
            
            can_trade = time_diff >= timedelta(hours=cooldown_hours)
            
            if not can_trade:
                remaining_hours = cooldown_hours - (time_diff.total_seconds() / 3600)
                logger.info(f"⏳ Symbol {symbol} is in cooldown. {remaining_hours:.1f} hours remaining.")
            
            return can_trade
            
        except Exception as e:
            logger.error(f"❌ Failed to check trade cooldown: {e}")
            # On error, allow the trade to proceed
            return True
    
    def update_trade_status(self, trade_id: str, status: Optional[str] = None,
                             pnl: Optional[float] = None, exit_time: Optional[str] = None) -> bool:
        """Update trade status/PnL/exit_time for an existing trade id."""
        try:
            if not trade_id:
                return False
            set_clauses = []
            values: List[Any] = []
            if status is not None:
                set_clauses.append("status = ?")
                values.append(status)
            if pnl is not None:
                set_clauses.append("pnl = ?")
                values.append(pnl)
            if exit_time is not None:
                set_clauses.append("exit_time = ?")
                values.append(exit_time)
            if not set_clauses:
                return True
            sql = f"UPDATE trade_history SET {', '.join(set_clauses)} WHERE trade_id = ?"
            values.append(trade_id)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(sql, tuple(values))
            conn.commit()
            conn.close()
            logger.info(f"📝 Trade {trade_id} updated: {', '.join(set_clauses)}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update trade {trade_id}: {e}")
            return False

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
    
    # Symbol patterns - prioritize crypto symbols over numbers
    SYMBOL_PATTERNS = [
        # Handle #SYMBOL SHORT/LONG format first
        r'#([A-Z]{2,10})\s+(SHORT|LONG)',  # #SOL SHORT, #BTC LONG
        r'#([A-Z]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT (letters only)
        r'\b(LONG|SHORT)\s*#?\s*([A-Z]{2,10})(?:/USDT|USDT)?',  # LONG BTCUSDT or SHORT BTC (letters only)
        r'([A-Z]{2,10})(?:/USDT|USDT)?',   # BTCUSDT, BTC/USDT (letters only)
        r'([A-Z]{2,10})\s*—',              # BTC —
        r'([A-Z]{2,10})\s*Long',           # BTC Long
        r'([A-Z]{2,10})\s*Short',          # BTC Short
        # Fallback for mixed alphanumeric (but avoid pure numbers)
        r'\b(LONG|SHORT)\s*#?\s*([A-Z0-9]{2,10})(?:/USDT|USDT)?',  # LONG BTCUSDT or SHORT BTC
        r'#([A-Z0-9]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT
        r'([A-Z0-9]{2,10})(?:/USDT|USDT)?',   # BTCUSDT, BTC/USDT
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
                # Handle different pattern formats
                if len(match.groups()) >= 2:
                    # Check if first group is LONG/SHORT
                    if re.match(r"LONG|SHORT", match.group(1), re.IGNORECASE):
                        symbol = match.group(2).upper()
                    # Check if second group is LONG/SHORT (for #SYMBOL SHORT format)
                    elif re.match(r"LONG|SHORT", match.group(2), re.IGNORECASE):
                        symbol = match.group(1).upper()
                    else:
                        symbol = match.group(1).upper()
                else:
                    symbol = match.group(1).upper()
                
                # Skip if symbol is just numbers (like "25x" -> "25")
                if symbol.isdigit():
                    continue
                    
                # Skip if symbol is too short or looks like leverage
                if len(symbol) < 2 or symbol in ['X', 'XX', 'XXX']:
                    continue
                
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
        # First, check for explicit SHORT/LONG words anywhere in text (highest priority)
        if re.search(r'\bSHORT\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bLONG\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Check for Russian equivalents
        if re.search(r'\bШОРТ\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bЛОНГ\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Check for BUY/SELL
        if re.search(r'\bSELL\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bBUY\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Only check emojis if no explicit words found
        # Check for SHORT patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'SHORT'
        
        # Check for LONG patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'LONG'
        
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
        self.active_monitoring = {}  # Deprecated - use account_monitoring_status instead
        self.monitoring_tasks: Dict[str, Any] = {}  # account_id -> monitoring task
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.active_positions: Dict[str, ActivePosition] = {}
        self.order_monitor_running = False
        self.bot_instances: Dict[int, Any] = {}  # Store bot instance per user for notifications
        
        # Enhanced multi-account support
        self.enhanced_db = EnhancedDatabase()
        self.current_account = None
        self.account_exchanges: Dict[str, ccxt.Exchange] = {}
        
        # User session management
        self.authenticated_users: Dict[int, bool] = {}
        self.current_accounts: Dict[int, str] = {}  # user_id -> account_id
        self.monitoring_status: Dict[int, bool] = {}  # Track monitoring status per user (deprecated)
        self.account_monitoring_status: Dict[str, bool] = {}  # Track monitoring status per account_id
        self.channel_name_cache: Dict[str, str] = {}  # channel_id -> channel_name for display
        
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
        
        # Load accounts from database on startup
        logger.info("🔄 Loading accounts from database on startup...")
        self.load_accounts_from_db()
        logger.info("✅ Accounts loaded successfully")
    

    def load_accounts_from_db(self):
        """Load all accounts from database on startup and restore current account selections"""
        try:
            accounts = self.enhanced_db.get_all_accounts()
            logger.info(f"📂 Loaded {len(accounts)} accounts from database")

            # Restore current account selections from database
            for account in accounts:
                logger.info(f"  ✅ {account.account_name} ({account.account_id[:8]}...)")
                
                # If this account has a user_id set, restore it as the current account for that user
                if account.user_id and account.user_id > 0:
                    self.current_accounts[account.user_id] = account.account_id
                    logger.info(f"  🔄 Restored current account for user {account.user_id}: {account.account_name}")

            return accounts
        except Exception as e:
            logger.error(f"❌ Error loading accounts from database: {e}")
            return []

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
        """Get current account for user - always fresh from database"""
        account_id = self.current_accounts.get(user_id)
        if not account_id:
            return None
        
        # Always reload from database to ensure we have latest settings
        accounts = self.enhanced_db.get_all_accounts()
        for account in accounts:
            if account.account_id == account_id:
                return account
        return None
    
    def set_current_account(self, user_id: int, account_id: str) -> bool:
        """Set current account for user and bind per-account exchange client"""
        accounts = self.enhanced_db.get_all_accounts()
        for account in accounts:
            if account.account_id == account_id:
                self.current_accounts[user_id] = account_id
                # Update the user_id in the database for persistence
                self.enhanced_db.update_account_user_id(account_id, user_id)
                # Prepare a dedicated ccxt client for this account using its BingX keys
                try:
                    if account.bingx_api_key and account.bingx_secret_key:
                        trading_type = getattr(account, 'trading_type', 'swap')  # Default to swap for backwards compatibility
                        self.account_exchanges[account.account_id] = ccxt.bingx({
                            'apiKey': account.bingx_api_key,
                            'secret': account.bingx_secret_key,
                            'options': {'defaultType': trading_type},
                            'enableRateLimit': True,
                            'timeout': 60000
                        })
                        logger.info(f"✅ Bound BingX client to account {account.account_name} (type: {trading_type})")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to bind exchange for account {account.account_name}: {e}")
                return True
        return False

    async def get_channel_display_name(self, channel_id: str, user_id: int) -> str:
        """Get channel display name with caching for better UX"""
        # Check cache first
        if channel_id in self.channel_name_cache:
            return self.channel_name_cache[channel_id]
        
        # Try to resolve from Telethon client
        try:
            # First try to get the current account's telethon client
            current_account = self.get_current_account(user_id)
            telethon_client = None
            
            if current_account:
                telethon_client = self.user_monitoring_clients.get(current_account.account_id)
            
            # If no client found for current account, try any account for this user
            if not telethon_client:
                accounts = self.enhanced_db.get_all_accounts()
                for acc in accounts:
                    if int(acc.user_id or 0) == int(user_id):
                        telethon_client = self.user_monitoring_clients.get(acc.account_id)
                        if telethon_client:
                            break
            
            if telethon_client and channel_id:
                try:
                    # Handle special case for "Test Private" - saved messages or private chats
                    channel_id_int = int(channel_id)
                    
                    # Check if it's a saved messages ID (user's own ID)
                    if channel_id_int == user_id:
                        display_name = "Test Private"
                        self.channel_name_cache[channel_id] = display_name
                        return display_name
                    
                    # Try to get entity normally
                    entity = await telethon_client.get_entity(channel_id_int)
                    
                    # Check different entity types
                    if hasattr(entity, 'title') and entity.title:
                        display_name = entity.title
                    elif hasattr(entity, 'first_name') and entity.first_name:
                        # For private chats/users
                        display_name = "Test Private"
                    elif hasattr(entity, 'username') and entity.username:
                        display_name = entity.username
                    else:
                        display_name = f'Channel {channel_id}'
                    
                    # Cache the result
                    self.channel_name_cache[channel_id] = display_name
                    return display_name
                except ValueError:
                    # Invalid channel ID format, might be a test message
                    logger.debug(f"Invalid channel ID format: {channel_id}")
                except Exception as e:
                    logger.debug(f"Could not resolve channel name for {channel_id}: {e}")
        except Exception as e:
            logger.debug(f"Error in get_channel_display_name: {e}")
        
        # Fallback: check if this looks like a test/private message ID
        try:
            if channel_id and int(channel_id) == user_id:
                return "Test Private"
        except:
            pass
        
        # Final fallback to channel ID
        fallback_name = f"Channel {channel_id}" if channel_id else "Unknown Channel"
        self.channel_name_cache[channel_id] = fallback_name
        return fallback_name

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
        """Convert symbol to BingX perpetual swap format (e.g., BTC-USDT)"""
        try:
            # BingX uses hyphen format for perpetual swaps: BTC-USDT
            # Remove any existing separators and reconstruct
            if '/' in symbol or ':' in symbol or '-' in symbol:
                # Clean up to base-USDT format
                base = symbol.split('/')[0].split('-')[0].split(':')[0]
                return f"{base}-USDT"
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                return f"{base}-USDT"
            return symbol
        except Exception:
            return symbol

    def parse_trading_signal(self, message: str, channel_id: str) -> Optional[TradingSignal]:
        """Enhanced signal parsing with Russian support"""
        try:
            logger.info(f"🔍 PARSING SIGNAL from channel {channel_id}")
            logger.info(f"📝 Message preview: {message[:300]}")
            
            # Try enhanced parser first
            enhanced_signal = EnhancedSignalParser.parse_signal(message, channel_id)
            if enhanced_signal:
                logger.info(f"🔎 Enhanced parser result - Symbol: {enhanced_signal.symbol}, Side: {enhanced_signal.side}, Confidence: {enhanced_signal.confidence:.2f}")
                if enhanced_signal.confidence > 0.5:
                    logger.info(f"✅ Enhanced parser SUCCESS: {enhanced_signal.symbol} {enhanced_signal.side} (confidence: {enhanced_signal.confidence:.2f})")
                    
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
                else:
                    logger.info(f"⚠️ Enhanced parser confidence too low: {enhanced_signal.confidence:.2f} < 0.5")
            else:
                logger.info("⚠️ Enhanced parser returned None")
            
            # Fallback to original parser
            logger.info("🔄 Trying fallback SignalDetector parser...")
            signals = SignalDetector.parse_signals(message)

            if not signals:
                logger.info("❌ SignalDetector: No signals found in message")
                logger.info("💡 TIP: Check if message contains required keywords (BUY/SELL/LONG/SHORT and symbol)")
                return None

            logger.info(f"✅ SignalDetector found {len(signals)} signal(s)")
            s = signals[0]
            logger.info(f"📊 First signal - Symbol: {s.get('symbol')}, Side: {s.get('trade_side')}, Entry: {s.get('entry')}")
            
            if not all([s['symbol'], s['trade_side']]):
                logger.info(f"❌ Incomplete signal data - Symbol: {s.get('symbol')}, Side: {s.get('trade_side')}")
                return None

            logger.info(f"✅ SIGNAL PARSED SUCCESSFULLY: {s['symbol']} {s['trade_side']}")

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
            logger.error(traceback.format_exc())
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
        # Always layer current account settings onto session config so trades use account config
        config = self.user_data[user_id]
        try:
            current_account = self.get_current_account(user_id)
            if current_account:
                # Map account BingX API keys into session config so all flows use correct credentials
                if getattr(current_account, 'bingx_api_key', None):
                    config.binance_api_key = current_account.bingx_api_key
                if getattr(current_account, 'bingx_secret_key', None):
                    config.binance_api_secret = current_account.bingx_secret_key
                config.leverage = int(current_account.leverage)
                # Stop loss percent: prefer first stop loss level if any
                if current_account.stop_loss_levels:
                    try:
                        # If stored as positive percent, treat as absolute percent
                        config.stop_loss_percent = float(current_account.stop_loss_levels[0].percentage)
                    except Exception:
                        pass
                # Balance mode
                if bool(current_account.use_percentage_balance):
                    config.use_fixed_usdt_amount = False
                    config.balance_percent = float(current_account.balance_percentage)
                else:
                    config.use_fixed_usdt_amount = True
                    config.fixed_usdt_amount = float(current_account.fixed_usdt_amount)
                # Custom TP levels from account
                if current_account.take_profit_levels:
                    config.custom_take_profits = [
                        TakeProfitLevel(tp.percentage, tp.close_percentage)
                        for tp in current_account.take_profit_levels
                    ]
                # Channels
                config.monitored_channels = [str(cid) for cid in (current_account.monitored_channels or [])]
                # Additional settings
                config.use_signal_settings = bool(current_account.use_signal_settings)
                config.create_sl_tp = bool(current_account.create_sl_tp)
                config.make_webhook_enabled = bool(current_account.make_webhook_enabled)
                config.trailing_enabled = bool(current_account.trailing_enabled)
                config.trailing_activation_percent = float(current_account.trailing_activation_percent)
                config.trailing_callback_percent = float(current_account.trailing_callback_percent)
        except Exception as e:
            logger.warning(f"⚠️ Failed to overlay account config: {e}")
        return config

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
            
            # Try multiple symbol formats to find the market
            market = None
            tried_symbols = [bingx_symbol]
            
            # Try the primary format first
            if bingx_symbol in markets:
                market = markets[bingx_symbol]
                logger.info(f"✅ Found market for {bingx_symbol}")
            else:
                # Try alternative formats
                # Extract base symbol (e.g., COAI from COAI-USDT)
                base = symbol.replace('-USDT', '').replace('/USDT', '').replace('USDT', '').replace(':', '').replace('/', '')
                
                alternative_formats = [
                    f"{base}/USDT",      # Slash format
                    f"{base}-USDT",      # Hyphen format (already tried)
                    f"{base}USDT",       # No separator
                    f"{base}/USDT:USDT", # Perpetual format
                    symbol               # Original symbol as-is
                ]
                
                for alt_symbol in alternative_formats:
                    if alt_symbol in tried_symbols:
                        continue
                    tried_symbols.append(alt_symbol)
                    if alt_symbol in markets:
                        market = markets[alt_symbol]
                        bingx_symbol = alt_symbol  # Update to the working format
                        logger.info(f"✅ Found market using alternative format: {alt_symbol}")
                        break
                
                if not market:
                    # Symbol not found in any format - log warning and use safe defaults
                    logger.warning(f"⚠️ Symbol {symbol} not found in markets (tried: {', '.join(tried_symbols)})")
                    logger.warning(f"⚠️ Using safe default precision values for {symbol}")
                    # Return safe defaults instead of error - this allows trade to proceed
                    default_precision = {
                        'step_size': 1.0,
                        'min_qty': 1.0,
                        'tick_size': 0.00001,
                        'min_price': 0.00001,
                        'max_price': 1000000.0,
                        'qty_precision': 0,
                        'price_precision': 5
                    }
                    self.symbol_info_cache[symbol] = default_precision
                    return default_precision
            
            # If we found the market, continue with precision extraction
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
            
            # First, round to the nearest step multiple (not floor)
            rounded_decimal = (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * step_decimal

            # Then, round to declared precision (use HALF_UP for better precision)
            if isinstance(qty_precision, int) and qty_precision >= 0:
                precision_quant = Decimal('1').scaleb(-qty_precision)
                rounded_decimal = Decimal(rounded_decimal).quantize(precision_quant, rounding=ROUND_HALF_UP)
            rounded = float(rounded_decimal)
            
            # Ensure we don't go below step_size unless precision allows smaller values
            if rounded < step_size:
                try:
                    if isinstance(qty_precision, int) and qty_precision > 0:
                        min_allowed = float(Decimal('1').scaleb(-qty_precision))
                        # Allow very small values if precision supports it
                        if min_allowed < step_size:
                            rounded = max(rounded, min_allowed)
                        else:
                            rounded = step_size
                    else:
                        rounded = step_size
                except Exception:
                    rounded = step_size
            
            # Additional check: if the original quantity was very small but non-zero,
            # ensure we don't round it to zero
            if quantity > 0 and rounded == 0:
                # Use the minimum allowed precision
                if isinstance(qty_precision, int) and qty_precision > 0:
                    min_allowed = float(Decimal('1').scaleb(-qty_precision))
                    rounded = min_allowed
                else:
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
                    # Mark position PARTIAL in history
                    try:
                        self.enhanced_db.update_trade_status(getattr(position, 'trade_id', ''), status="PARTIAL")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to mark trade PARTIAL: {e}")
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

            # Update history on closure
            if filled_order_type == "STOP_LOSS" or (filled_order_type == "TAKE_PROFIT" and not remaining_tps):
                try:
                    # Calculate PnL for the closed trade
                    pnl = 0.0
                    try:
                        if hasattr(position, 'entry_price') and position.entry_price:
                            # Get current price for PnL calculation
                            ticker = self.exchange.fetch_ticker(self.to_bingx_symbol(symbol))
                            current_price = ticker.get('last', position.entry_price)
                            
                            # Calculate PnL based on position side
                            if position.side == 'LONG':
                                pnl = (current_price - position.entry_price) * position.quantity
                            else:  # SHORT
                                pnl = (position.entry_price - current_price) * position.quantity
                    except Exception as e:
                        logger.warning(f"⚠️ Could not calculate PnL: {e}")
                    
                    self.enhanced_db.update_trade_status(getattr(position, 'trade_id', ''), status="CLOSED", exit_time=datetime.now().isoformat(), pnl=pnl)
                    
                    # Send PnL notification to user
                    try:
                        user_id = getattr(position, 'user_id', None)
                        if user_id and user_id in self.bot_instances:
                            bot_instance = self.bot_instances[user_id]
                            
                            # Get account stats for win rate
                            account_id = getattr(position, 'account_id', None)
                            if account_id:
                                trade_history = self.enhanced_db.get_trade_history(account_id, limit=100)
                                # Only count trades that were properly closed with actual win/lose data
                                closed_trades = [t for t in trade_history if t.status == "CLOSED" and t.exit_time is not None]
                                total_trades = len(closed_trades)
                                winning_trades = len([t for t in closed_trades if t.pnl and float(t.pnl) > 0])
                                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                                
                                pnl_emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
                                await bot_instance.send_message(
                                    chat_id=user_id,
                                    text=f"{pnl_emoji} <b>TRADE CLOSED</b>\n\n"
                                         f"💰 {symbol} {position.side}\n"
                                         f"💵 PnL: {pnl:.2f} USDT\n"
                                         f"📊 Win Rate: {win_rate:.1f}%\n"
                                         f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                                    parse_mode='HTML'
                                )
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to send PnL notification: {e}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Failed to close trade in history: {e}")
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
                            
                            # Check if position still exists on exchange (detect manual closes)
                            try:
                                positions = self.exchange.fetch_positions([self.to_bingx_symbol(symbol)])
                                position_exists = False
                                for pos in positions:
                                    if pos.get('contracts', 0) > 0 or abs(float(pos.get('contractSize', 0))) > 0:
                                        position_exists = True
                                        break
                                
                                # If position doesn't exist on exchange, mark as closed
                                if not position_exists:
                                    logger.info(f"📭 Position {symbol} closed manually on exchange")
                                    try:
                                        # Calculate PnL for manually closed trade
                                        pnl = 0.0
                                        try:
                                            if hasattr(position, 'entry_price') and position.entry_price:
                                                ticker = self.exchange.fetch_ticker(self.to_bingx_symbol(symbol))
                                                current_price = ticker.get('last', position.entry_price)
                                                
                                                if position.side == 'LONG':
                                                    pnl = (current_price - position.entry_price) * position.quantity
                                                else:  # SHORT
                                                    pnl = (position.entry_price - current_price) * position.quantity
                                        except Exception as e:
                                            logger.warning(f"⚠️ Could not calculate PnL for manual close: {e}")
                                        
                                        self.enhanced_db.update_trade_status(
                                            getattr(position, 'trade_id', ''), 
                                            status="CLOSED", 
                                            exit_time=datetime.now().isoformat(),
                                            pnl=pnl
                                        )
                                        
                                        # Send PnL notification for manual close
                                        try:
                                            user_id = getattr(position, 'user_id', None)
                                            if user_id and user_id in self.bot_instances:
                                                bot_instance = self.bot_instances[user_id]
                                                
                                                account_id = getattr(position, 'account_id', None)
                                                if account_id:
                                                    trade_history = self.enhanced_db.get_trade_history(account_id, limit=100)
                                                    # Only count trades that were properly closed with actual win/lose data
                                                    closed_trades = [t for t in trade_history if t.status == "CLOSED" and t.exit_time is not None]
                                                    total_trades = len(closed_trades)
                                                    winning_trades = len([t for t in closed_trades if t.pnl and float(t.pnl) > 0])
                                                    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                                                    
                                                    pnl_emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
                                                    await bot_instance.send_message(
                                                        chat_id=user_id,
                                                        text=f"{pnl_emoji} <b>TRADE CLOSED (Manual)</b>\n\n"
                                                             f"💰 {symbol} {position.side}\n"
                                                             f"💵 PnL: {pnl:.2f} USDT\n"
                                                             f"📊 Win Rate: {win_rate:.1f}%\n"
                                                             f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                                                        parse_mode='HTML'
                                                    )
                                        except Exception as e:
                                            logger.warning(f"⚠️ Failed to send manual close PnL notification: {e}")
                                            
                                    except Exception as e:
                                        logger.warning(f"⚠️ Failed to close trade in history: {e}")
                                    
                                    # Remove from active positions
                                    if symbol in self.active_positions:
                                        del self.active_positions[symbol]
                                        logger.info(f"🗑️ Removed {symbol} from active positions (manual close)")
                                    continue
                            except Exception as e:
                                logger.debug(f"Could not check position status for {symbol}: {e}")
                            
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
            # Prefer per-account exchange client
            current_account = self.get_current_account(config.user_id)
            account_key = current_account.account_id if current_account else None

            if account_key and account_key in self.account_exchanges:
                self.exchange = self.account_exchanges[account_key]

            if not self.exchange:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to BingX API'}
                if account_key:
                    self.account_exchanges[account_key] = self.exchange

            # Explicitly use 'swap' type for futures trading
            current_trading_type = getattr(current_account, 'trading_type', 'swap') if current_account else 'swap'
            bal = self.exchange.fetch_balance({'type': current_trading_type})
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
            # If this user has a bound account/exchange, reuse it
            current_account = self.get_current_account(config.user_id)
            if current_account and current_account.account_id in self.account_exchanges:
                self.exchange = self.account_exchanges[current_account.account_id]
            else:
                trading_type = getattr(current_account, 'trading_type', 'swap') if current_account else 'swap'
                self.exchange = ccxt.bingx({
                    'apiKey': config.binance_api_key,
                    'secret': config.binance_api_secret,
                    'options': {
                        'defaultType': trading_type
                    },
                    'enableRateLimit': True,
                    'timeout': 60000
                })
                if current_account:
                    self.account_exchanges[current_account.account_id] = self.exchange

            # Explicitly use 'swap' type for futures trading
            bal = self.exchange.fetch_balance({'type': trading_type})
            usdt_total = bal.get('USDT', {}).get('total', 'N/A') if isinstance(bal, dict) else 'N/A'
            logger.info(f"✅ BingX connected. Balance: {usdt_total} USDT (type: {trading_type})")
            return True

        except Exception as e:
            logger.error(f"❌ BingX setup error: {e}")
            return False

    async def setup_telethon_client(self, config: BotConfig, authorize_if_needed: bool = False) -> bool:
        """Setup Telethon client
        
        Args:
            config: Bot configuration
            authorize_if_needed: If True and not authorized, will attempt to send auth code
        
        Returns:
            True if client is setup and authorized, False otherwise
        """
        try:
            # Get current account to use account-specific credentials
            current_account = self.get_current_account(config.user_id)
            if not current_account:
                logger.error("❌ No current account set for Telethon setup")
                return False
            
            # Use account-specific session file to avoid database locks
            # Each account needs its own session to prevent SQLite concurrency issues
            session_name = f"session_{current_account.account_id}"
            phone = current_account.phone if hasattr(current_account, 'phone') else None
            
            # Migrate from shared session if it exists and account session doesn't
            shared_session_file = f"{SHARED_TELETHON_SESSION}.session"
            account_session_file = f"{session_name}.session"
            if os.path.exists(shared_session_file) and not os.path.exists(account_session_file):
                try:
                    shutil.copy2(shared_session_file, account_session_file)
                    logger.info(f"✅ Migrated shared session to account-specific session: {account_session_file}")
                except Exception as copy_err:
                    logger.warning(f"⚠️ Could not migrate shared session: {copy_err}")
            
            # Use account-specific Telegram credentials (or defaults)
            api_id = current_account.telegram_api_id
            api_hash = current_account.telegram_api_hash

            telethon_client = TelegramClient(
                session_name,
                api_id=int(api_id),
                api_hash=api_hash
            )

            # Connect to Telegram
            try:
                await telethon_client.connect()
                
                # Check if already authorized
                if await telethon_client.is_user_authorized():
                    logger.info(f"✅ Telethon client already authorized for account {current_account.account_id}")
                    self.user_monitoring_clients[current_account.account_id] = telethon_client
                    return True
                else:
                    # Not authorized - log warning but store the client
                    logger.warning(f"⚠️ Telethon client not authorized for account {current_account.account_id}")
                    logger.warning(f"⚠️ Shared session file '{session_name}.session' may be missing or invalid")
                    logger.info(f"ℹ️ Please ensure the session file exists or authorize through the bot interface")
                    self.user_monitoring_clients[current_account.account_id] = telethon_client
                    return False
                    
            except Exception as start_err:
                logger.error(f"❌ Error starting Telethon client: {start_err}")
                logger.error(traceback.format_exc())
                return False

        except Exception as e:
            logger.error(f"❌ Telethon setup error: {e}")
            logger.error(traceback.format_exc())
            return False

    async def get_available_channels(self, user_id: int) -> List[Dict]:
        try:
            # Get current account to use account-specific Telethon client
            current_account = self.get_current_account(user_id)
            if not current_account:
                logger.error("❌ No current account set for getting channels")
                return []
            
            config = self.get_user_config(user_id)
            account_id = current_account.account_id

            # Check if Telethon client exists for this account
            if account_id not in self.user_monitoring_clients:
                await self.setup_telethon_client(config)

            telethon_client = self.user_monitoring_clients.get(account_id)
            if not telethon_client:
                logger.error(f"❌ Failed to get Telethon client for account {account_id}")
                return []

            # Check if the client is authorized before attempting to get channels
            if not await telethon_client.is_user_authorized():
                logger.error(f"❌ Telethon client not authorized for account {account_id}")
                logger.info(f"ℹ️ Please authorize the account through the bot interface")
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

            logger.info(f"📡 Found {len(channels)} channels for account {account_id}")
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
        """
        Enhanced trade execution with FIXED PRECISION
        
        NOTE: This method is independent of user's current menu location.
        Trades are executed automatically when signals are detected from monitored channels,
        regardless of where the user is navigating in the bot interface.
        """
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")

            # Ensure we are using the exchange client tied to the current account (originating user)
            # Account is determined by user_id and channel mapping, not by menu state
            current_account = self.get_current_account(config.user_id)
            account_key = current_account.account_id if current_account else None

            # Check symbol cooldown if enabled on the account
            cooldown_hours = 0
            if current_account and getattr(current_account, 'cooldown_enabled', False):
                try:
                    cooldown_hours = int(getattr(current_account, 'cooldown_hours', 24) or 24)
                except Exception:
                    cooldown_hours = 24
            if cooldown_hours and account_key and not self.enhanced_db.can_trade_symbol(account_key, signal.symbol, cooldown_hours=cooldown_hours):
                logger.warning(f"⏳ Trade blocked: {signal.symbol} is in 24-hour cooldown for account {current_account.account_name if current_account else account_key}")
                return {
                    'success': False, 
                    'error': f'Symbol {signal.symbol} is in cooldown for {cooldown_hours}h.'
                }

            if account_key and account_key in self.account_exchanges:
                self.exchange = self.account_exchanges[account_key]
            
            if not self.exchange:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to BingX API'}
                # Cache the exchange per account for future orders
                if account_key:
                    self.account_exchanges[account_key] = self.exchange

            try:
                logger.info(f"💰 Getting account balance...")
                # If per-account API keys are configured, switch keys before fetching balance
                if current_account and current_account.bingx_api_key and current_account.bingx_secret_key:
                    # Build a per-account client (ccxt is lightweight for this usage)
                    trading_type = getattr(current_account, 'trading_type', 'swap')
                    self.account_exchanges[account_key] = ccxt.bingx({
                        'apiKey': current_account.bingx_api_key,
                        'secret': current_account.bingx_secret_key,
                        'options': {'defaultType': trading_type},
                        'enableRateLimit': True,
                        'timeout': 60000
                    })
                    self.exchange = self.account_exchanges[account_key]

                bal = self.exchange.fetch_balance({'type': trading_type})
                usdt_balance = 0
                if isinstance(bal, dict) and 'USDT' in bal:
                    asset = bal['USDT']
                    # Use 'free' balance instead of 'total' to avoid using locked funds
                    usdt_balance = float(asset.get('free', 0) or 0)
                    logger.info(f"✅ Found USDT balance - Free: {usdt_balance}, Total: {float(asset.get('total', 0) or 0)}")
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
            # Ensure we always have current price with proper precision handling
            current_price = 0.0
            try:
                ticker = self.exchange.fetch_ticker(bingx_symbol)
                logger.info(f"📊 Raw ticker response for {bingx_symbol}: last={ticker.get('last')}, price={ticker.get('info', {}).get('price')}")
                
                # Use Decimal for precision-sensitive prices to avoid float precision loss
                price_str = str(ticker.get('last') or ticker.get('info', {}).get('price') or '0')
                current_price = float(Decimal(price_str)) if price_str and price_str != '0' else 0.0
                
                # Log with full precision for debugging small decimals
                logger.info(f"📊 Fetched current price for {bingx_symbol}: {current_price} (precision preserved: {price_str})")
                
                # Validate extremely small but valid prices
                if 0 < current_price < 0.00001:
                    logger.info(f"✅ Very small price detected for {bingx_symbol}: {current_price:.12f} - meme coin trading enabled")
            except Exception as e:
                logger.warning(f"⚠️ Error fetching ticker for {bingx_symbol}: {e}")
                # Try alternative symbol format as fallback
                try:
                    # If hyphen format failed, the symbol might already be in a different format
                    alt_symbol = signal.symbol if '/' not in signal.symbol else signal.symbol.replace('/', '-').split(':')[0]
                    logger.info(f"🔄 Trying alternative symbol format: {alt_symbol}")
                    ticker = self.exchange.fetch_ticker(alt_symbol)
                    price_str = str(ticker.get('last') or ticker.get('info', {}).get('price') or '0')
                    current_price = float(Decimal(price_str)) if price_str and price_str != '0' else 0.0
                    logger.info(f"✅ Found price with alternative format: {current_price}")
                    bingx_symbol = alt_symbol  # Update to working symbol
                except Exception as e2:
                    logger.warning(f"⚠️ Alternative ticker fetch also failed: {e2}")
                    # Last resort: use signal entry price or minimal fallback
                    if signal.entry_price and signal.entry_price > 0:
                        price_str = str(signal.entry_price)
                        current_price = float(Decimal(price_str))
                        logger.info(f"📊 Using signal entry price as fallback: {current_price}")
                    else:
                        # For very small meme coins, use a minimal non-zero fallback
                        current_price = 0.00000001
                        logger.warning(f"⚠️ Using minimal fallback price: {current_price} - trade will proceed with caution")

            # Attempt to set leverage, but proceed if it fails
            try:
                position_side = 'LONG' if side == 'BUY' else 'SHORT'
                self.exchange.set_leverage(leverage, bingx_symbol, {'side': position_side})
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage setting warning: {e}")

            # Determine entry price with fallback logic and precision handling
            if signal.entry_price:
                entry_price = float(Decimal(str(signal.entry_price)))
                logger.info(f"💲 Using signal entry price: {entry_price} (original: {signal.entry_price})")
            else:
                entry_price = current_price
                logger.info(f"💲 No signal entry price, using current price: {entry_price}")
            
            # Validate extremely small but valid entry prices
            if 0 < entry_price < 0.00001:
                logger.info(f"✅ Very small entry price for {signal.symbol}: {entry_price:.12f} - meme coin trading")
            
            # If we still don't have a valid price, try to fetch it again with different methods
            if not entry_price or entry_price <= 0:
                logger.warning(f"⚠️ No valid entry price found, attempting alternative price fetch...")
                try:
                    # Try different ticker fields
                    ticker = self.exchange.fetch_ticker(bingx_symbol)
                    alternative_prices = [
                        ticker.get('last'),
                        ticker.get('close'),
                        ticker.get('bid'),
                        ticker.get('ask'),
                        ticker.get('info', {}).get('price'),
                        ticker.get('info', {}).get('lastPrice')
                    ]
                    
                    for price in alternative_prices:
                        if price:
                            try:
                                # Use Decimal to preserve precision for very small numbers
                                price_decimal = Decimal(str(price))
                                price_float = float(price_decimal)
                                if price_float > 0:
                                    entry_price = price_float
                                    logger.info(f"✅ Found alternative price: {entry_price}")
                                    break
                            except Exception:
                                continue
                    
                    # If still no price, try orderbook
                    if not entry_price or entry_price <= 0:
                        orderbook = self.exchange.fetch_order_book(bingx_symbol, limit=1)
                        if orderbook.get('bids') and orderbook['bids'][0][0] > 0:
                            entry_price = orderbook['bids'][0][0]
                            logger.info(f"✅ Found price from orderbook: {entry_price}")
                        elif orderbook.get('asks') and orderbook['asks'][0][0] > 0:
                            entry_price = orderbook['asks'][0][0]
                            logger.info(f"✅ Found price from orderbook asks: {entry_price}")
                            
                except Exception as e:
                    logger.error(f"❌ Failed to fetch alternative price: {e}")
                    logger.error(f"❌ Alternative price fetch error: {traceback.format_exc()}")

            logger.info(f"💲 Final entry price for {signal.symbol}: {entry_price} (full precision: {entry_price:.12f})")
            
            # Additional validation for very small prices (meme coins with many zeros)
            if entry_price > 0 and entry_price < 0.00000001:
                logger.info(f"✅ Detected very small price ({entry_price:.12f}) for {signal.symbol}")
                logger.info(f"📊 This appears to be a meme coin with many decimal places - proceeding with trade")
                # Allow trading even with very small prices - DO NOT reject
            
            # Final price validation - only reject if truly zero, None, or invalid
            # IMPORTANT: Allow very small prices like 0.0000004 (meme coins)
            # Use a more robust check that handles float precision issues
            if entry_price is None or (isinstance(entry_price, (int, float)) and entry_price <= 0):
                error_msg = (
                    f"❌ Unable to determine valid price for {signal.symbol} ({bingx_symbol}). "
                    f"Please verify:\n"
                    f"1. Symbol is valid and actively trading on BingX\n"
                    f"2. Symbol format is correct (e.g., BTC/USDT for spot, BTC-USDT for perpetuals)\n"
                    f"3. Exchange ticker data is available for this pair"
                )
                logger.error(error_msg)
                return {'success': False, 'error': f'Invalid or zero price for {signal.symbol}. Symbol may not be supported or not trading.'}
            
            # Calculate trade amount based on user preference
            logger.info(f"💰 Balance calculation mode: {'Fixed USDT' if config.use_fixed_usdt_amount else 'Percentage'}")
            logger.info(f"💰 Config values - Fixed: ${config.fixed_usdt_amount}, Percentage: {config.balance_percent}%")
            
            if config.use_fixed_usdt_amount:
                trade_amount = min(config.fixed_usdt_amount, usdt_balance)
                logger.info(f"💰 Using fixed USDT amount: ${trade_amount:.2f} (min of ${config.fixed_usdt_amount} and ${usdt_balance})")
            else:
                # Ensure percentage is in correct format (e.g., 10 for 10%, not 0.10)
                percentage = float(config.balance_percent)
                if percentage > 1:
                    # Percentage is in format like 10 for 10%
                    trade_amount = usdt_balance * (percentage / 100)
                else:
                    # Percentage might be in decimal format like 0.10 for 10% - convert it
                    logger.warning(f"⚠️ Percentage {percentage} seems to be in decimal format, converting to standard format")
                    trade_amount = usdt_balance * percentage
                    percentage = percentage * 100  # For logging
                
                logger.info(f"💰 Using percentage of balance: ${trade_amount:.2f} ({percentage}% of ${usdt_balance})")
                logger.info(f"💰 Calculation: ${usdt_balance} × {percentage}% = ${trade_amount:.2f}")
                
                # Safety check: if trade_amount is more than 50% of balance, something is wrong
                if trade_amount > usdt_balance * 0.5:
                    logger.error(f"❌ SAFETY CHECK FAILED: Trade amount ${trade_amount:.2f} is more than 50% of balance ${usdt_balance}")
                    logger.error(f"❌ This suggests incorrect percentage value. Expected: {config.balance_percent}%")
                    return {'success': False, 'error': f'Trade amount calculation error: ${trade_amount:.2f} exceeds safety limit (50% of ${usdt_balance}). Check your balance percentage setting.'}
            
            position_value = trade_amount * leverage
            
            # Check for valid entry price to avoid division by zero
            if not entry_price or entry_price <= 0:
                return {'success': False, 'error': f'Invalid entry price: {entry_price}. Cannot calculate quantity.'}
            
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Available Balance: ${usdt_balance:.2f} USDT")
            logger.info(f"   Trade Amount: ${trade_amount:.2f} USDT ({(trade_amount/usdt_balance*100):.2f}% of balance)")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Position Value: ${trade_amount * leverage:.2f}")
            logger.info(f"   Entry Price: {entry_price}")
            logger.info(f"   Raw Quantity: {raw_quantity}")

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

            # Get trading type for this account (futures/swap vs spot)
            current_trading_type = getattr(current_account, 'trading_type', 'swap') if current_account else 'swap'
            
            # Include positionSide param for hedge mode for entry + explicit type for BingX futures
            # Note: positionSide is only valid for futures/swap trading, not spot
            order_params = {'type': current_trading_type}  # Explicitly specify swap (futures) or spot
            if current_trading_type == 'swap':
                order_params['positionSide'] = 'LONG' if side == 'BUY' else 'SHORT'
            # Create order with simple retry if exchange is transiently busy
            attempt = 0
            last_err = None
            while attempt < 2:
                try:
                    order = self.exchange.create_order(self.to_bingx_symbol(signal.symbol), 'market', side.lower(), quantity, None, order_params)
                    break
                except Exception as e:
                    last_err = e
                    await asyncio.sleep(0.5)
                    attempt += 1
            if 'order' not in locals():
                return {'success': False, 'error': f'Order creation failed: {last_err}'}

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
                                'workingType': 'MARK_PRICE',
                                'type': current_trading_type  # Explicitly specify swap (futures) or spot
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
                    
                    # Calculate quantities based on custom close percentages, then cap and floor so sum <= position
                    requested_quantities: List[float] = []
                    remaining_unrounded = quantity
                    for i, tp_level in enumerate(config.custom_take_profits[:len(tp_targets)]):
                        if i == len(tp_targets) - 1:
                            requested_quantities.append(remaining_unrounded)
                        else:
                            desired_close = max(0.0, remaining_unrounded * (tp_level.close_percentage / 100.0))
                            requested_quantities.append(desired_close)
                            remaining_unrounded -= desired_close

                    rounded_quantities: List[float] = []
                    cumulative_assigned = 0.0
                    total_levels = len(requested_quantities)
                    step_size = precision_info['step_size']
                    
                    # IMPROVED: Ensure ALL configured TP levels are created
                    # First pass: try to distribute according to percentages
                    for i, requested in enumerate(requested_quantities):
                        remaining_levels = total_levels - i
                        remaining_capacity = max(quantity - cumulative_assigned, 0.0)
                        # Keep room for at least step_size for remaining levels
                        min_reserved_for_rest = step_size * max(remaining_levels - 1, 0)
                        alloc = min(requested, max(remaining_capacity - min_reserved_for_rest, 0.0))
                        each_qty = self.round_quantity(alloc, step_size, precision_info['qty_precision'])
                        
                        # If quantity is too small but we still have levels to create, use minimum
                        if each_qty < step_size:
                            if i == total_levels - 1:
                                # Last level gets all remaining
                                each_qty = self.round_quantity(max(quantity - cumulative_assigned, 0.0), step_size, precision_info['qty_precision'])
                            else:
                                # Use minimum step_size to ensure this level is created
                                each_qty = step_size
                        
                        if cumulative_assigned + each_qty > quantity:
                            each_qty = self.round_quantity(max(quantity - cumulative_assigned, 0.0), step_size, precision_info['qty_precision'])
                        
                        # Only skip if quantity is truly 0 or negative
                        if each_qty <= 0:
                            continue
                            
                        rounded_quantities.append(each_qty)
                        cumulative_assigned += each_qty
                        if cumulative_assigned >= quantity - (step_size * 1e-9):
                            break
                    
                    # If we don't have enough TPs, redistribute more evenly
                    if len(rounded_quantities) < len(tp_targets):
                        logger.warning(f"⚠️ Only {len(rounded_quantities)} TPs created, but {len(tp_targets)} configured. Redistributing...")
                        # Redistribute quantity evenly across all TP levels
                        rounded_quantities = []
                        qty_per_level = quantity / len(tp_targets)
                        cumulative_assigned = 0.0
                        for i in range(len(tp_targets)):
                            if i == len(tp_targets) - 1:
                                # Last TP gets remainder
                                each_qty = self.round_quantity(quantity - cumulative_assigned, step_size, precision_info['qty_precision'])
                            else:
                                each_qty = self.round_quantity(qty_per_level, step_size, precision_info['qty_precision'])
                                # Ensure minimum quantity
                                if each_qty < step_size:
                                    each_qty = step_size
                            
                            if each_qty > 0:
                                rounded_quantities.append(each_qty)
                                cumulative_assigned += each_qty

                    # Align number of TP targets with actual rounded quantities
                    effective_tp_pairs = list(zip(tp_targets[:len(rounded_quantities)], rounded_quantities))
                    logger.info(f"🎯 Creating {len(effective_tp_pairs)} take profit orders")

                    for tp, each_qty in effective_tp_pairs:
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
                                'workingType': 'MARK_PRICE',
                                'type': current_trading_type  # Explicitly specify swap (futures) or spot
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
                            trailing_params['type'] = current_trading_type  # Explicitly specify swap (futures) or spot
                            trailing_order = self.exchange.create_order(
                                market_symbol,
                                'TRAILING_STOP_MARKET',
                                'sell' if side == 'BUY' else 'buy',
                                quantity,
                                None,
                                trailing_params
                            )
                            logger.info(f"🧵 Trailing Stop placed: {trailing_order}")
                            # Track trailing order in active positions (trade_id will be attached below)
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

            # Ensure active position is tracked even when trailing disabled, and attach trade id
            try:
                pos = self.active_positions.get(signal.symbol)
                if not pos:
                    self.active_positions[signal.symbol] = ActivePosition(
                        symbol=signal.symbol,
                        user_id=config.user_id,
                        side='LONG' if side == 'BUY' else 'SHORT',
                        quantity=quantity,
                        entry_price=current_price,
                        stop_loss_order_id=sl_tp_result.get('stop_loss'),
                        take_profit_order_ids=[tp['order_id'] for tp in sl_tp_result.get('take_profits', [])]
                    )
                # Attach trade id for DB updates later
                self.active_positions[signal.symbol].trade_id = str(order.get('id')) if order.get('id') is not None else None
            except Exception as e:
                logger.warning(f"⚠️ Failed to register active position: {e}")

            # Persist trade to history as OPEN
            try:
                account_id_for_history = current_account.account_id if current_account else ""
                history_record = TradeHistory(
                    trade_id=str(order.get('id')),
                    account_id=account_id_for_history,
                    symbol=signal.symbol,
                    side=signal.trade_type,
                    entry_price=float(entry_price),
                    quantity=float(quantity),
                    leverage=int(leverage),
                    status="OPEN",
                    pnl=0.0,
                    stop_loss_price=float(sl_price) if sl_price else None,
                    take_profit_prices=[float(p) for p in (tp_prices or [])],
                    channel_id=str(signal.channel_id)
                )
                self.enhanced_db.save_trade_history(history_record)
            except Exception as e:
                logger.warning(f"⚠️ Failed to save trade history: {e}")

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
            current_account = self.get_current_account(user_id)
            
            if not current_account:
                logger.error("❌ No current account set for monitoring")
                return False

            if not config.monitored_channels:
                return False

            # Store bot instance for notifications
            self.bot_instances[user_id] = bot_instance
            
            account_id = current_account.account_id

            telethon_client = self.user_monitoring_clients.get(account_id)
            if not telethon_client:
                success = await self.setup_telethon_client(config)
                if not success:
                    return False
                telethon_client = self.user_monitoring_clients[account_id]

            self.setup_make_webhook(user_id)

            if not self.order_monitor_running:
                asyncio.create_task(self.monitor_orders(bot_instance))

            # Note: We're now using manual polling instead of event handlers
            # The old event handler approach has been completely removed to prevent duplicate trade execution
            # All message handling is now done through _run_telethon_client() polling loop
            # which calls _handle_new_message() for each new message

            if not telethon_client.is_connected():
                await telethon_client.connect()
                logger.info(f"✅ Connected Telethon client for user {user_id}")

            # Set active monitoring BEFORE starting the task
            self.active_monitoring[user_id] = True
            logger.info(f"🔛 Set active_monitoring[{user_id}] = True")
            
            # Set account monitoring status - this is critical for message processing
            self.account_monitoring_status[account_id] = True
            logger.info(f"🔛 Set account_monitoring_status[{account_id}] = True")

            # Start background task to process Telethon events for THIS ACCOUNT if not already running
            # Each account gets its own monitoring task for true background monitoring
            if account_id not in self.monitoring_tasks or self.monitoring_tasks[account_id].done():
                self.monitoring_tasks[account_id] = asyncio.create_task(self._run_telethon_client(account_id, user_id))
                logger.info(f"✅ Started Telethon event loop task for account {account_id} (user {user_id})")
            else:
                logger.info(f"ℹ️ Telethon event loop task already running for account {account_id}")

            logger.info(f"📡 Monitoring now ACTIVE for user {user_id}")
            logger.info(f"📡 Monitored channels: {config.monitored_channels}")
            logger.info(f"🔔 Client connected: {telethon_client.is_connected()}")
            logger.info(f"🔔 Active monitoring status: {self.active_monitoring.get(user_id, False)}")
            logger.info(f"🔔 Account monitoring status: {self.account_monitoring_status.get(account_id, False)}")
            return True

        except Exception as e:
            logger.error(f"❌ Start monitoring error: {e}")
            logger.error(f"❌ Start monitoring error details: {traceback.format_exc()}")
            return False
    
    async def _run_telethon_client(self, account_id: str, user_id: int):
        """Actively poll Telethon for new messages for a specific account.
        
        This function manually checks for new messages in monitored channels for ONE account.
        Each account runs its own monitoring task, enabling true background monitoring.
        
        Args:
            account_id: The account ID to monitor
            user_id: The user ID that owns this account
        """
        try:
            # Get account from database
            accounts = self.enhanced_db.get_all_accounts()
            account = None
            for acc in accounts:
                if acc.account_id == account_id:
                    account = acc
                    break
            
            if not account:
                logger.error(f"❌ Account {account_id} not found")
                return
            
            telethon_client = self.user_monitoring_clients.get(account_id)
            if not telethon_client:
                logger.error(f"❌ No Telethon client found for account {account_id}")
                return
            
            logger.info(f"🔄 [_run_telethon_client] Starting message polling for account {account.account_name} (ID: {account_id})")
            logger.info(f"🔄 [_run_telethon_client] Account monitoring status: {self.account_monitoring_status.get(account_id, False)}")
            
            # Ensure connection is established
            if not telethon_client.is_connected():
                logger.info(f"🔌 [_run_telethon_client] Connecting Telethon client for account {account.account_name}...")
                await telethon_client.connect()
            
            logger.info(f"✅ [_run_telethon_client] Telethon client connected for account {account.account_name}, actively polling for new messages")
            logger.info(f"✅ [_run_telethon_client] Entering polling loop...")
            
            # Track last message ID for each channel to detect new messages
            last_message_ids = {}
            
            # Keep polling while THIS ACCOUNT's monitoring is active
            while self.account_monitoring_status.get(account_id, False):
                try:
                    # Check if client is still connected
                    if not telethon_client.is_connected():
                        logger.warning(f"⚠️ Telethon client disconnected for account {account.account_name}, reconnecting...")
                        await telethon_client.connect()
                    
                    # Get fresh account data from database to check monitored channels
                    accounts = self.enhanced_db.get_all_accounts()
                    account = None
                    for acc in accounts:
                        if acc.account_id == account_id:
                            account = acc
                            break
                    
                    if not account or not account.monitored_channels:
                        logger.debug(f"⏸️ No channels configured for account {account_id}, waiting...")
                        await asyncio.sleep(10)
                        continue
                    
                    logger.debug(f"🔍 Polling {len(account.monitored_channels)} channels for account {account.account_name}: {account.monitored_channels}")
                    
                    # Monitor only THIS account's channels
                    channels_to_check = [str(ch) for ch in account.monitored_channels]
                    
                    if not channels_to_check:
                        logger.debug(f"⏸️ No active channels to check for account {account_id}")
                        await asyncio.sleep(10)
                        continue
                    
                    logger.debug(f"🔍 Monitoring {len(channels_to_check)} channels for account {account.account_name}")
                    
                    # Check each monitored channel for new messages
                    for channel_id_str in channels_to_check:
                        try:
                            # Convert string channel ID to entity
                            channel_id = int(channel_id_str)
                            
                            logger.debug(f"🔎 Checking channel {channel_id_str} for new messages...")
                            
                            # Get entity first to avoid ChatIdInvalidError
                            # Use PeerChannel for proper channel/megagroup handling
                            try:
                                from telethon.tl.types import PeerChannel
                                # For channels/megagroups, use PeerChannel with positive ID
                                peer = PeerChannel(abs(channel_id))
                                entity = await telethon_client.get_entity(peer)
                            except Exception as entity_error:
                                # Fallback to direct int if PeerChannel fails
                                try:
                                    entity = await telethon_client.get_entity(channel_id)
                                except Exception as e2:
                                    logger.warning(f"⚠️ Could not get entity for channel {channel_id_str}: {entity_error}, fallback also failed: {e2}")
                                    continue
                            
                            # Get the latest message from this channel
                            messages = await telethon_client.get_messages(entity, limit=1)
                            
                            if not messages:
                                logger.debug(f"📭 No messages found in channel {channel_id_str}")
                                continue
                            
                            latest_msg = messages[0]
                            msg_id = latest_msg.id
                            
                            logger.debug(f"📬 Latest message in channel {channel_id_str}: ID={msg_id}")
                            
                            # Initialize last_message_ids for this channel if needed
                            if channel_id_str not in last_message_ids:
                                # Initialize with current msg_id to skip existing messages
                                # Only process NEW messages that arrive AFTER bot startup
                                last_message_ids[channel_id_str] = msg_id
                                logger.info(f"📝 Initialized tracking for channel {channel_id_str}, starting from message ID: {msg_id}")
                                logger.info(f"📝 Latest message preview: {latest_msg.message[:100] if latest_msg.message else '(no text)'}")
                                logger.info(f"⏭️ Skipping existing messages, will only process new messages from now on")
                                continue  # Skip to next channel, don't process existing messages
                            
                            # Check if this is a new message
                            if msg_id > last_message_ids[channel_id_str]:
                                logger.info(f"🆕 New message detected in channel {channel_id_str}! ID: {msg_id} (previous: {last_message_ids[channel_id_str]})")
                                
                                # Get all new messages since last check
                                new_messages = await telethon_client.get_messages(
                                    channel_id,
                                    min_id=last_message_ids[channel_id_str],
                                    limit=10
                                )
                                
                                logger.info(f"📥 Retrieved {len(new_messages)} new messages from channel {channel_id_str}")
                                
                                # Process each new message (in chronological order)
                                for msg in reversed(new_messages):
                                    if msg.id > last_message_ids[channel_id_str] and msg.message:
                                        logger.info(f"📨 Processing new message ID {msg.id}: {msg.message[:100]}...")
                                        await self._handle_new_message(msg, channel_id_str, user_id, account_id)
                                    elif msg.id > last_message_ids[channel_id_str]:
                                        logger.debug(f"⏭️ Skipping message ID {msg.id} (no text content)")
                                
                                # Update last seen message ID
                                last_message_ids[channel_id_str] = msg_id
                                logger.info(f"✅ Updated last message ID for channel {channel_id_str} to {msg_id}")
                            else:
                                logger.debug(f"✓ No new messages in channel {channel_id_str} (current: {msg_id}, last: {last_message_ids[channel_id_str]})")
                                
                        except ValueError as e:
                            logger.error(f"❌ Invalid channel ID format: {channel_id_str}: {e}")
                        except Exception as e:
                            logger.error(f"❌ Error checking channel {channel_id_str}: {e}")
                            logger.error(traceback.format_exc())
                    
                    # Poll every 5 seconds to catch new messages quickly
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"❌ Error in message polling loop for account {account_id}: {e}")
                    logger.error(f"❌ Message polling loop error: {traceback.format_exc()}")
                    await asyncio.sleep(10)
            
            logger.info(f"🛑 Message polling stopped for account {account.account_name} (ID: {account_id})")
            
        except Exception as e:
            logger.error(f"❌ Fatal error in message polling for account {account_id}: {e}")
            logger.error(f"❌ Message polling fatal error: {traceback.format_exc()}")
    
    async def _handle_new_message(self, message, channel_id: str, user_id: int, account_id: str = None):
        """Handle a new message from a monitored channel
        
        Args:
            message: The Telethon message object
            channel_id: The channel ID where the message was received
            user_id: The Telegram user ID
            account_id: The account ID to use for this message (if known from background monitoring)
        """
        try:
            logger.info(f"🔔 [_handle_new_message] Called for user {user_id}, channel {channel_id}, account {account_id}")

            # Route to the correct trading account
            # If account_id is provided (from background monitoring), use it directly
            if account_id:
                logger.info(f"🔗 [_handle_new_message] Using provided account ID: {account_id}")
                self.set_current_account(user_id, account_id)
            else:
                # Fallback: search for matching account based on channel
                try:
                    accounts = self.enhanced_db.get_all_accounts()
                    matching = None
                    for acc in accounts:
                        if int(acc.user_id or 0) != int(user_id):
                            continue
                        try:
                            if channel_id and int(channel_id) in [int(str(c)) for c in (acc.monitored_channels or [])]:
                                matching = acc
                                break
                        except Exception:
                            continue
                    if matching:
                        current = self.get_current_account(user_id)
                        if not current or current.account_id != matching.account_id:
                            logger.info(f"🔗 [_handle_new_message] Switching current account to '{matching.account_name}' based on channel {channel_id}")
                            self.set_current_account(user_id, matching.account_id)
                    else:
                        logger.info(f"ℹ️ [_handle_new_message] No specific account matched for channel {channel_id}; using current account")
                except Exception as e:
                    logger.warning(f"⚠️ [_handle_new_message] Account routing by channel failed: {e}")
            
            config = self.get_user_config(user_id)
            logger.info(f"🔧 [_handle_new_message] Config loaded - monitored channels: {config.monitored_channels}")
            
            bot_instance = self.bot_instances.get(user_id)
            logger.info(f"🤖 [_handle_new_message] Bot instance {'found' if bot_instance else 'NOT FOUND'}")
            
            message_text = message.message
            
            if not message_text:
                logger.warning(f"⚠️ [_handle_new_message] Message has no text content, skipping")
                return
            
            logger.info(f"📨 [_handle_new_message] Processing message from channel {channel_id}")
            logger.info(f"📨 [_handle_new_message] Message text: {message_text[:200]}")
            
            # Get channel name for display using cached helper method
            channel_name = await self.get_channel_display_name(channel_id, user_id)
            
            # Send notification about received message
            if bot_instance:
                try:
                    await bot_instance.send_message(
                        chat_id=user_id,
                        text=f"📨 <b>New Message Received</b>\n\n<b>From:</b> {channel_name}\n\n<pre>{message_text[:300]}</pre>\n\n🔍 Processing...",
                        parse_mode='HTML'
                    )
                    logger.info(f"✅ [_handle_new_message] Sent notification to user {user_id}")
                except Exception as e:
                    logger.error(f"❌ [_handle_new_message] Error sending message notification: {e}")
            else:
                logger.warning(f"⚠️ [_handle_new_message] No bot instance to send notification")
            
            # Parse the signal
            logger.info(f"🔍 [_handle_new_message] Starting signal parsing...")
            signal = self.parse_trading_signal(message_text, channel_id)
            logger.info(f"📊 [_handle_new_message] Signal parsing result: {'Signal detected' if signal else 'No signal detected'}")
            
            if signal:
                logger.info(f"🎯 SIGNAL DETECTED! {signal.symbol} {signal.trade_type}")
                
                # Check if the current account is actually monitoring
                current_account = self.get_current_account(user_id)
                if current_account and not self.account_monitoring_status.get(current_account.account_id, False):
                    logger.warning(f"⏸️ Account {current_account.account_name} received signal but monitoring is not active - skipping trade")
                    logger.warning(f"⏸️ Current monitoring status: {dict(self.account_monitoring_status)}")
                    logger.info(f"ℹ️ Note: Trades execute in background regardless of user's current menu location")
                    if bot_instance:
                        try:
                            await bot_instance.send_message(
                                chat_id=user_id,
                                text=f"⏸️ <b>Signal Received</b>\n\n💰 {signal.symbol} {signal.trade_type}\n\n⚠️ Account <b>{current_account.account_name}</b> is not monitoring.\nTrade skipped.\n\nUse '🚀 Start' to enable trading for this account.\n\n💡 Tip: Once started, trades execute automatically from anywhere in the bot!",
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.error(f"Error sending skip notification: {e}")
                    return
                
                settings_source = "Signal" if config.use_signal_settings else "Bot"
                if bot_instance:
                    try:
                        # Get consistent channel name using the cache
                        channel_info = ""
                        try:
                            channel_display = await self.get_channel_display_name(signal.channel_id, user_id) if signal.channel_id else None
                            if channel_display:
                                channel_info = f"\n📡 Source: {channel_display}"
                        except Exception:
                            pass
                        
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text=f"🎯 <b>SIGNAL DETECTED!</b>\n\n💰 {signal.symbol} {signal.trade_type}\n⚙️ Using: {settings_source} settings{channel_info}\n🚀 Executing...",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Error sending signal notification: {e}")
                
                # Execute the trade
                result = await self.execute_trade(signal, config)
                
                logger.info(f"Trade execution result: {result}")
                
                # Send result notification
                if bot_instance:
                    try:
                        if result.get('success'):
                            # Get channel name for success notification
                            channel_display = await self.get_channel_display_name(signal.channel_id, user_id) if signal.channel_id else "Unknown"
                            notification = f"""✅ <b>TRADE EXECUTED!</b>

💰 Symbol: {result['symbol']}
📈 Direction: {signal.trade_type}
📡 From: {channel_display}
🆔 Order ID: {result['order_id']}
📦 Quantity: {result['quantity']}
💲 Entry: {result['price']}
⚡ Leverage: {result['leverage']}x
💵 Order Value: ${result['order_value']:.2f}"""

                            if 'sl_price' in result and result['sl_price']:
                                notification += f"\n🛑 Stop Loss: {result['sl_price']:.6f}"
                                if result.get('stop_loss_id'):
                                    notification += f" (ID: {result['stop_loss_id']})"

                            if 'tp_prices' in result and result['tp_prices']:
                                notification += f"\n🎯 Take Profits:"
                                for i, tp in enumerate(result.get('take_profit_ids', [])):
                                    notification += f"\n  TP{i+1}: {tp['price']:.6f} (ID: {tp['order_id']})"

                            notification += "\n🔗 Sent to Make.com"
                            notification += "\n🔄 OCO: Auto-cancel enabled"
                            notification += f"\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
                            notification += f"\n\n🎉 Position is LIVE!"

                        else:
                            # Get channel name for failed trade notification
                            channel_display = await self.get_channel_display_name(signal.channel_id, user_id) if signal.channel_id else "Unknown"
                            notification = f"""❌ <b>TRADE EXECUTION FAILED</b>

💰 Symbol: {signal.symbol}
📈 Direction: {signal.trade_type}
📡 From: {channel_display}
🚨 Error: {result.get('error', 'Unknown error')}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}"""

                        await bot_instance.send_message(chat_id=user_id, text=notification, parse_mode='HTML')
                    except Exception as e:
                        logger.error(f"Error sending trade result notification: {e}")
                
            else:
                logger.info(f"📨 No valid signal detected in message")
                if bot_instance:
                    try:
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text="📨 Message received but no valid signal detected",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Error sending no-signal notification: {e}")
                
        except Exception as e:
            logger.error(f"Error handling new message: {e}")
            logger.error(traceback.format_exc())

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
    current_account = trading_bot.get_current_account(user_id)

    # Format trade amount display
    if config.use_fixed_usdt_amount:
        trade_amount_text = f"💵 Fixed: ${config.fixed_usdt_amount:.0f} USDT"
    else:
        trade_amount_text = f"💰 Percentage: {config.balance_percent}%"
    
    # Get monitored channel names
    channel_names = []
    if current_account and current_account.monitored_channels:
        # For now, show channel IDs. To show names, we'd need to fetch from Telethon
        channel_names = [str(ch_id) for ch_id in current_account.monitored_channels[:3]]  # Show first 3
    
    if channel_names:
        channels_text = f"📡 Channels: {', '.join(channel_names)}" + (f" +{len(current_account.monitored_channels) - 3} more" if len(current_account.monitored_channels) > 3 else "")
    else:
        channels_text = "📡 No channels configured"

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
        [InlineKeyboardButton(channels_text, callback_data="manage_channels")],
        [InlineKeyboardButton("📋 History in account", callback_data="account_history")],
        [InlineKeyboardButton("✏️ Rename Account", callback_data="rename_account"), InlineKeyboardButton("🗑️ Delete Account", callback_data="delete_account")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)

# ===================== STATIC BUTTON HANDLERS =====================


# ==================== ENHANCED UI SYSTEM ====================

def render_trading_config_text(user_id: int) -> str:
    """Build a clear, comprehensive configuration summary for the settings screen."""
    # Get fresh account data to ensure sync
    current_account = trading_bot.get_current_account(user_id)
    config = trading_bot.get_user_config(user_id)
    
    settings_source = "📊 Signal" if config.use_signal_settings else "🤖 Bot"
    sl_tp_status = "🟢 ON" if config.create_sl_tp else "🔴 OFF"
    trailing_status = "🟢 ON" if config.trailing_enabled else "🔴 OFF"
    trade_amount = f"${int(config.fixed_usdt_amount)} USDT" if config.use_fixed_usdt_amount else f"{config.balance_percent}%"
    tp_lines = [f"TP{i}: {lvl.percentage}% → Close {lvl.close_percentage}%" for i, lvl in enumerate(config.custom_take_profits, 1)]
    if not tp_lines:
        tp_lines = ["None configured"]
    
    account_info = ""
    if current_account:
        account_info = f"📋 <b>Account:</b> {current_account.account_name}\n\n"
    
    text = (
        "⚙️ <b>Trading Configuration</b>\n\n"
        + account_info +
        f"🎯 Settings: <b>{settings_source}</b>\n"
        f"📊 SL/TP Orders: <b>{sl_tp_status}</b>\n"
        f"⚡ Leverage: <b>{config.leverage}x</b>\n"
        f"🛑 Stop Loss: <b>{config.stop_loss_percent}%</b>\n"
        f"🧵 Trailing: <b>{trailing_status}</b> (Act: {config.trailing_activation_percent}%, Cb: {config.trailing_callback_percent}%)\n"
        f"💰 Trade Amount: <b>{trade_amount}</b>\n"
        f"🎯 Take Profits: <b>{len(config.custom_take_profits)} levels</b>\n"
        + ("\n" + "\n".join(tp_lines) if tp_lines else "")
    )
    return text

# Default settings for new accounts
DEFAULT_SETTINGS = {
    'leverage': 10,
    'risk_percentage': 2.0,
    'tp_levels': [50.0, 100.0, 150.0],
    'sl_level': -10.0,
    'trailing_stop_enabled': False
}

# Trade tracker for duplicate prevention
class TradeTracker:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_table()

    def init_table(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS trade_tracking (
                id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, 
                channel_id TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, symbol, channel_id, date(timestamp)))""")
            conn.commit()
            conn.close()
        except: pass

    def can_open_trade(self, account_id: str, symbol: str, channel_id: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trade_tracking WHERE account_id=? AND symbol=? AND channel_id=? AND timestamp > datetime('now','-24 hours')", (account_id, symbol, channel_id))
            return cursor.fetchone()[0] == 0
        except: return True

    def record_trade(self, account_id: str, symbol: str, channel_id: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO trade_tracking (account_id,symbol,channel_id) VALUES (?,?,?)", (account_id,symbol,channel_id))
            conn.commit()
            conn.close()
        except: pass

trade_tracker = TradeTracker("enhancedtradingbot.db")

# Keyboard builders
def build_main_menu():
    return ReplyKeyboardMarkup([
        ["🔑 Accounts", "📊 Stats"],
        ["🚀 Start All", "🛑 Stop All"],
        ["📋 All History", "📈 All Trades"],
        ["⚙️ Default Settings"]
    ], resize_keyboard=True)

def build_accounts_menu(accounts):
    kb = [["➕ Add Account"]]
    for i in range(0, len(accounts), 2):
        row = [f"📋 {accounts[i].account_name}"]
        if i+1 < len(accounts): row.append(f"📋 {accounts[i+1].account_name}")
        kb.append(row)
    kb.append(["🔙 Main Menu"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def build_account_page():
    return ReplyKeyboardMarkup([
        ["🚀 Start", "🛑 Stop"],
        ["📋 History", "📈 Trades"],
        ["📊 Account Stats"],
        ["⚙️ Settings", "📡 Channels"],
        ["🔙 Accounts"]
    ], resize_keyboard=True)

def build_settings_menu():
    return ReplyKeyboardMarkup([
        ["🔮 Trading Type", "⚡ Leverage", "💰 Risk %"],
        ["💵 Trade Amount", "🎯 Take Profits", "🛡️ Stop Loss"],
        ["📉 Trailing", "⏰ Cooldown", "📡 Channels"],
        ["🔧 Advanced", "✏️ Rename Account", "🗑️ Delete Account"],
        ["🔙 Account"]
    ], resize_keyboard=True)

def build_advanced_settings_menu():
    return ReplyKeyboardMarkup([
        ["🎯 Signal Settings", "🛡️ SL/TP Orders"],
        ["🔗 Webhook", "📊 Balance Mode"],
        ["🔙 Settings"]
    ], resize_keyboard=True)

def build_take_profit_levels_menu():
    return ReplyKeyboardMarkup([
        ["➕ Add Level", "✏️ Edit Level"],
        ["🗑️ Remove Level", "📋 View Levels"],
        ["🔙 Settings"]
    ], resize_keyboard=True)

def build_cooldown_menu():
    return ReplyKeyboardMarkup([
        ["🟢 Enable", "🔴 Disable"],
        ["⏰ Set Hours", "📊 Status"],
        ["🔙 Settings"]
    ], resize_keyboard=True)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start: welcome and prompt for PIN or show menu"""
    user_id = update.effective_user.id
    if trading_bot.is_authenticated(user_id):
        await update.message.reply_text(
            "🏠 Main Menu",
            parse_mode='HTML',
            reply_markup=build_main_menu()
        )
    else:
        await update.message.reply_text(
            "👋 <b>Welcome!</b>\n\nPlease enter your PIN to access the bot.",
            parse_mode='HTML'
        )

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete navigation system"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Auth check
    if not trading_bot.is_authenticated(user_id):
        if trading_bot.authenticate_user(user_id, text):
            await update.message.reply_text("✅ <b>Authenticated!</b>", parse_mode='HTML', reply_markup=build_main_menu())
            return
        else:
            await update.message.reply_text("❌ Invalid PIN:", parse_mode='HTML')
            return

    # Restore current account context from persistent state if not already set
    if 'current_account_id' not in context.user_data:
        current_account = trading_bot.get_current_account(user_id)
        if current_account:
            context.user_data['current_account_id'] = current_account.account_id
            context.user_data['current_account_name'] = current_account.account_name

    # Account creation states
    if context.user_data.get('state') == 'WAIT_ACC_NAME':
        context.user_data['acc_name'] = text
        context.user_data['state'] = 'WAIT_ACC_KEY'
        await update.message.reply_text(f"📝 {text}\n\nBingX API Key:", parse_mode='HTML')
        return
    elif context.user_data.get('state') == 'WAIT_ACC_KEY':
        context.user_data['acc_key'] = text
        context.user_data['state'] = 'WAIT_ACC_SEC'
        await update.message.reply_text("🔑 Saved!\n\nBingX Secret:", parse_mode='HTML')
        return
    elif context.user_data.get('state') == 'WAIT_ACC_SEC':
        defaults = trading_bot.enhanced_db.get_default_settings()
        acc = AccountConfig(
            account_id=str(uuid.uuid4()), account_name=context.user_data.get('acc_name'),
            bingx_api_key=context.user_data.get('acc_key'), bingx_secret_key=text,
            telegram_api_id=DEFAULT_TELEGRAM_API_ID, telegram_api_hash=DEFAULT_TELEGRAM_API_HASH,
            phone="", user_id=user_id, is_active=True, created_at=datetime.now().isoformat(),
            last_used=datetime.now().isoformat(), leverage=int(defaults.get('leverage', DEFAULT_SETTINGS['leverage'])),
            risk_percentage=float(defaults.get('risk_percentage', DEFAULT_SETTINGS['risk_percentage'])), use_percentage_balance=True,
            monitored_channels=[], signal_channels=[]
        )
        try:
            trading_bot.enhanced_db.create_account(acc)
            await update.message.reply_text(f"✅ Account created with default settings!", parse_mode='HTML', reply_markup=build_accounts_menu(trading_bot.enhanced_db.get_all_accounts()))
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}", parse_mode='HTML')
        context.user_data.clear()
        return

    # Parse quick commands to update default settings
    lower = text.lower()
    if lower.startswith('default '):
        try:
            _, key, *rest = lower.split(' ')
            value_str = ' '.join(rest).strip()
            if key == 'leverage':
                lev = int(value_str)
                trading_bot.enhanced_db.set_app_setting('default_leverage', lev)
                await update.message.reply_text(f"✅ Default leverage set to {lev}x")
            elif key == 'risk':
                risk = float(value_str)
                trading_bot.enhanced_db.set_app_setting('default_risk_percentage', risk)
                await update.message.reply_text(f"✅ Default risk set to {risk}%")
            elif key == 'sl':
                sl = float(value_str)
                trading_bot.enhanced_db.set_app_setting('default_sl_level', sl)
                await update.message.reply_text(f"✅ Default SL set to {sl}%")
            elif key == 'tp':
                # Parse CSV of floats
                parts = [p.strip() for p in value_str.split(',') if p.strip()]
                tps = [float(p) for p in parts][:8]
                trading_bot.enhanced_db.set_app_setting('default_tp_levels', tps)
                await update.message.reply_text(f"✅ Default TP levels set to {tps}")
            else:
                await update.message.reply_text("❌ Unknown default key. Use leverage|risk|sl|tp")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not update defaults: {str(e)[:80]}")
        return

    # Settings states
    if context.user_data.get('state') == 'WAIT_LEVERAGE':
        try:
            lev = int(text)
            if 1 <= lev <= 125:
                acc_id = context.user_data.get('current_account_id')
                # Update leverage in DB
                await update.message.reply_text(f"✅ Leverage set to {lev}x", parse_mode='HTML', reply_markup=build_settings_menu())
            else:
                await update.message.reply_text("❌ Use 1-125", parse_mode='HTML')
        except:
            await update.message.reply_text("❌ Invalid number", parse_mode='HTML')
        context.user_data.pop('state', None)
        return

    # Main menu buttons
    if text == "🔑 Accounts":
        accs = trading_bot.enhanced_db.get_all_accounts()
        await update.message.reply_text("🔑 <b>Accounts</b>", parse_mode='HTML', reply_markup=build_accounts_menu(accs))

    elif text == "📊 Stats":
        # Show comprehensive stats for all accounts
        accs = trading_bot.enhanced_db.get_all_accounts()
        msg = "📊 <b>Overall Statistics</b>\n\n"
        msg += f"📋 Total Accounts: <b>{len(accs)}</b>\n"
        
        active_count = sum(1 for acc in accs if trading_bot.monitoring_status.get(user_id, False))
        msg += f"🟢 Active Monitoring: <b>{active_count}</b>\n\n"
        
        # Per-account stats (compact format)
        msg += "💼 <b>Account Details:</b>\n\n"
        
        accounts_shown = 0
        for acc in accs:
            # Check message length to avoid exceeding Telegram's limit
            if len(msg) > 3500:
                msg += f"<i>... and {len(accs) - accounts_shown} more accounts</i>\n"
                break
            
            # Get active trades and history for this account
            active_trades = trading_bot.enhanced_db.get_active_trades(acc.account_id)
            trade_history = trading_bot.enhanced_db.get_trade_history(acc.account_id, limit=100)
            
            # Calculate PnL and win rate
            total_pnl = sum(float(t.pnl) if t.pnl else 0 for t in trade_history)
            
            # Calculate win rate from closed trades only
            closed_trades = [t for t in trade_history if t.status == "CLOSED"]
            winning_trades = [t for t in closed_trades if float(t.pnl or 0) > 0]
            win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0
            
            monitor_status = "🟢" if trading_bot.monitoring_status.get(user_id, False) else "🔴"
            
            # Compact format
            acc_name = acc.account_name
            if len(acc_name) > 20:
                acc_name = acc_name[:17] + "..."
            
            msg += f"<b>{acc_name}</b> {monitor_status}\n"
            msg += f"  {acc.leverage}x | Active: {len(active_trades)} | Total: {len(trade_history)}\n"
            msg += f"  WR: {win_rate:.1f}% | PnL: {total_pnl:.2f} USDT\n\n"
            accounts_shown += 1
        
        # Ensure we don't exceed Telegram's limit
        if len(msg) > 4000:
            msg = msg[:3950] + "\n\n<i>... (truncated)</i>"
        
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "🚀 Start All":
        # Start monitoring all accounts
        accs = trading_bot.enhanced_db.get_all_accounts()
        started_count = 0
        failed_accounts = []
        
        for acc in accs:
            if not acc.monitored_channels:
                continue  # Skip accounts without channels
            
            try:
                # Set current account temporarily
                trading_bot.set_current_account(user_id, acc.account_id)
                success = await trading_bot.start_monitoring(user_id, context.bot)
                if success:
                    trading_bot.monitoring_status[user_id] = True
                    trading_bot.account_monitoring_status[acc.account_id] = True
                    started_count += 1
                else:
                    failed_accounts.append(acc.account_name)
            except Exception as e:
                logger.error(f"Error starting {acc.account_name}: {e}")
                failed_accounts.append(acc.account_name)
        
        msg = f"🚀 <b>Start All Accounts</b>\n\n"
        msg += f"✅ Successfully started: {started_count}\n"
        if failed_accounts:
            msg += f"❌ Failed: {len(failed_accounts)}\n"
            msg += f"Failed accounts: {', '.join(failed_accounts[:5])}"
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "🛑 Stop All":
        # Stop monitoring all accounts
        accs = trading_bot.enhanced_db.get_user_accounts(user_id)
        stopped_count = 0
        
        for acc in accs:
            try:
                # Stop monitoring for this account
                trading_bot.account_monitoring_status[acc.account_id] = False
                
                # Stop account-specific monitoring task
                if acc.account_id in trading_bot.monitoring_tasks:
                    task = trading_bot.monitoring_tasks[acc.account_id]
                    if not task.done():
                        task.cancel()
                    del trading_bot.monitoring_tasks[acc.account_id]
                
                # Close telethon client if exists for this account
                if acc.account_id in trading_bot.user_monitoring_clients:
                    try:
                        client = trading_bot.user_monitoring_clients[acc.account_id]
                        if client.is_connected():
                            await client.disconnect()
                        del trading_bot.user_monitoring_clients[acc.account_id]
                    except Exception:
                        pass
                
                stopped_count += 1
            except Exception as e:
                logger.error(f"Error stopping {acc.account_name}: {e}")
        
        # Stop user-level monitoring (legacy)
        trading_bot.active_monitoring[user_id] = False
        trading_bot.monitoring_status[user_id] = False
        
        msg = f"🛑 <b>Stop All Accounts</b>\n\n"
        msg += f"✅ Successfully stopped: {stopped_count}\n"
        msg += f"All trading activities have been stopped."
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "📋 All History":
        # Show trade history from all accounts (only closed/inactive trades)
        accs = trading_bot.enhanced_db.get_all_accounts()
        all_trades = []
        
        for acc in accs:
            trades = trading_bot.enhanced_db.get_trade_history(acc.account_id, limit=20, only_closed=True)
            for trade in trades:
                all_trades.append((acc.account_name, trade))
        
        if not all_trades:
            await update.message.reply_text(
                "📋 <b>No Trade History</b>\n\n"
                "No trades found across all accounts.",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
        else:
            # Sort by entry time (most recent first)
            all_trades.sort(key=lambda x: x[1].entry_time if x[1].entry_time else "", reverse=True)
            text = f"📋 <b>All Accounts Trade History ({len(all_trades)})</b>\n\n"
            
            for acc_name, trade in all_trades[:20]:  # Limit to 20 most recent
                status_emoji = "🟢" if trade.status == "OPEN" else "🔴" if trade.status == "CLOSED" else "🟡"
                text += f"{status_emoji} <b>{trade.symbol}</b> {trade.side}\n"
                text += f"Account: {acc_name}\n"
                text += f"Entry: {trade.entry_price} | PnL: {trade.pnl if trade.pnl else '0'}\n"
                text += f"Time: {trade.entry_time[:16] if trade.entry_time else 'N/A'}\n\n"
            
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "📈 All Trades":
        # Show active trades from all accounts
        accs = trading_bot.enhanced_db.get_all_accounts()
        all_active_trades = []
        
        for acc in accs:
            trades = trading_bot.enhanced_db.get_active_trades(acc.account_id)
            for trade in trades:
                all_active_trades.append((acc.account_name, trade))
        
        if not all_active_trades:
            await update.message.reply_text(
                "📈 <b>No Active Trades</b>\n\n"
                "No open positions across all accounts.",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
        else:
            text = f"📈 <b>All Active Trades ({len(all_active_trades)})</b>\n\n"
            
            for acc_name, trade in all_active_trades:
                text += f"<b>{trade.symbol}</b> {trade.side}\n"
                text += f"Account: {acc_name}\n"
                text += f"Entry: {trade.entry_price}\n"
                text += f"Quantity: {trade.quantity}\n"
                text += f"Leverage: {trade.leverage}x\n\n"
            
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "⚙️ Default Settings":
        # Show editable defaults matching account settings format
        current = trading_bot.enhanced_db.get_default_settings()
        
        msg = "⚙️ <b>Default Settings for New Accounts</b>\n\n"
        msg += "These settings will be applied to newly created accounts:\n\n"
        
        # Trading Settings
        msg += f"📊 <b>Trading Settings:</b>\n"
        msg += f"⚡ Leverage: <b>{current['leverage']}x</b>\n"
        msg += f"💰 Risk %: <b>{current['risk_percentage']}%</b>\n"
        msg += f"💵 Balance Mode: <b>Percentage</b>\n"
        msg += f"💵 Trade Amount: <b>2.0%</b>\n\n"
        
        # Cooldown Settings
        msg += f"⏰ <b>Cooldown Settings:</b>\n"
        msg += f"Status: <b>🔴 OFF</b> (Default)\n"
        msg += f"Hours: <b>24h</b> (When enabled)\n\n"
        
        # Commands
        msg += f"📝 <b>Commands:</b>\n"
        msg += f"• <code>default leverage [1-125]</code> - Set default leverage\n"
        msg += f"• <code>default risk [%]</code> - Set default risk\n"
        msg += f"• <code>default balance [%]</code> - Set default balance %\n"
        msg += f"• <code>default amount [USDT]</code> - Set default fixed amount\n"
        msg += f"• <code>default cooldown [hours]</code> - Set default cooldown\n"
        msg += f"• <code>default cooldown off</code> - Disable default cooldown\n\n"
        
        msg += f"💡 <i>Tip: These settings only affect new accounts. Existing accounts keep their current settings.</i>"
        
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_main_menu())

    # Accounts menu buttons
    elif text == "➕ Add Account":
        await update.message.reply_text("➕ <b>New Account</b>\n\nAccount name:", parse_mode='HTML')
        context.user_data['state'] = 'WAIT_ACC_NAME'

    elif text.startswith("📋 ") and text != "📋 All History":
        acc_name = text[2:].strip()
        accs = trading_bot.enhanced_db.get_all_accounts()
        acc = next((a for a in accs if a.account_name == acc_name), None)
        if acc:
            context.user_data['current_account_id'] = acc.account_id
            context.user_data['current_account_name'] = acc.account_name
            try:
                trading_bot.set_current_account(user_id, acc.account_id)
            except Exception:
                pass
            
            # Display complete account settings with all details
            balance_mode = "Percentage" if acc.use_percentage_balance else "Fixed USDT"
            balance_value = f"{acc.balance_percentage}%" if acc.use_percentage_balance else f"${acc.fixed_usdt_amount}"
            
            # Get stats for this account
            active_trades = trading_bot.enhanced_db.get_active_trades(acc.account_id)
            trade_history = trading_bot.enhanced_db.get_trade_history(acc.account_id, limit=100)
            total_pnl = sum(float(t.pnl) if t.pnl else 0 for t in trade_history)
            
            # Get balance from exchange
            balance = 0.0
            try:
                if acc.account_id in trading_bot.account_exchanges:
                    exchange = trading_bot.account_exchanges[acc.account_id]
                    acc_trading_type = getattr(acc, 'trading_type', 'swap')
                    bal = exchange.fetch_balance({'type': acc_trading_type})
                    balance = bal.get('USDT', {}).get('total', 0.0) if isinstance(bal, dict) else 0.0
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch balance for account {acc.account_name}: {e}")
            
            msg = f"📋 <b>{acc.account_name}</b>\n\n"
            
            # Account Status
            monitor_status = "🟢 Active" if trading_bot.monitoring_status.get(user_id, False) else "🔴 Inactive"
            msg += f"🔄 <b>Monitoring:</b> {monitor_status}\n"
            msg += f"📡 <b>Channels:</b> {len(acc.monitored_channels)}\n\n"
            
            # Trading Statistics
            msg += f"📊 <b>Statistics:</b>\n"
            msg += f"💰 Balance: <b>{balance:.2f} USDT</b>\n"
            msg += f"📈 Active Trades: <b>{len(active_trades)}</b>\n"
            msg += f"📋 Total Trades: <b>{len(trade_history)}</b>\n"
            msg += f"💵 Total PnL: <b>{total_pnl:.2f} USDT</b>\n\n"
            
            # Trading Settings
            msg += f"⚙️ <b>Trading Settings:</b>\n"
            msg += f"⚡ Leverage: <b>{acc.leverage}x</b>\n"
            msg += f"💰 Risk %: <b>{acc.risk_percentage}%</b>\n"
            msg += f"💵 Balance Mode: <b>{balance_mode}</b>\n"
            msg += f"💵 Trade Amount: <b>{balance_value}</b>\n\n"
            
            # TP/SL Configuration
            msg += f"🎯 <b>TP/SL Configuration:</b>\n"
            msg += f"🎯 Take Profit Levels: <b>{len(acc.take_profit_levels)}</b>\n"
            if acc.take_profit_levels:
                for i, tp in enumerate(acc.take_profit_levels[:3], 1):
                    msg += f"  TP{i}: {tp.percentage}% → Close {tp.close_percentage}%\n"
            msg += f"🛑 Stop Loss Levels: <b>{len(acc.stop_loss_levels)}</b>\n"
            if acc.stop_loss_levels:
                for i, sl in enumerate(acc.stop_loss_levels[:3], 1):
                    msg += f"  SL{i}: {sl.percentage}% → Close {sl.close_percentage}%\n"
            msg += "\n"
            
            # Trailing Stop Settings
            trailing_status = "🟢 ON" if acc.trailing_enabled else "🔴 OFF"
            msg += f"📉 <b>Trailing Stop:</b> {trailing_status}\n"
            if acc.trailing_enabled:
                msg += f"  🔔 Activation: <b>{acc.trailing_activation_percent}%</b>\n"
                msg += f"  ↩️ Callback: <b>{acc.trailing_callback_percent}%</b>\n"
            msg += "\n"
            
            # Advanced Features
            msg += f"✅ <b>Features:</b>\n"
            msg += f"  Signal Settings: <b>{'ON' if acc.use_signal_settings else 'OFF'}</b>\n"
            msg += f"  Create SL/TP: <b>{'ON' if acc.create_sl_tp else 'OFF'}</b>\n"
            msg += f"  Make Webhook: <b>{'ON' if acc.make_webhook_enabled else 'OFF'}</b>\n"
            
            # Cooldown Settings
            cooldown_status = "🟢 ON" if getattr(acc, 'cooldown_enabled', False) else "🔴 OFF"
            cooldown_hours = getattr(acc, 'cooldown_hours', 24)
            msg += f"  Cooldown: <b>{cooldown_status}</b>"
            if getattr(acc, 'cooldown_enabled', False):
                msg += f" ({cooldown_hours}h)"
            msg += "\n\n"
            
            msg += "Use the buttons below to manage this account."
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_account_page())

    elif text == "🔙 Main Menu":
        context.user_data.clear()
        await update.message.reply_text("🏠 Main Menu", parse_mode='HTML', reply_markup=build_main_menu())

    elif text == "🔙 Accounts":
        accs = trading_bot.enhanced_db.get_all_accounts()
        await update.message.reply_text("🔑 Accounts", parse_mode='HTML', reply_markup=build_accounts_menu(accs))

    # Account page buttons
    elif text == "🚀 Start":
        # Delegate to start trading handler to actually start monitoring
        await handle_start_trading(update, context)

    elif text == "🛑 Stop":
        # Delegate to stop trading handler to actually stop monitoring
        await handle_stop_trading(update, context)

    elif text == "📋 History":
        # COMPLETELY REWRITTEN: Show trade history for current account
        try:
            # Step 1: Get current account with multiple fallback methods
            current_account = None
            account_id = None
            account_name = None
            
            # Method 1: Try from trading_bot's current_accounts dict
            try:
                current_account = trading_bot.get_current_account(user_id)
                if current_account:
                    account_id = current_account.account_id
                    account_name = current_account.account_name
            except Exception as e:
                logger.warning(f"Failed to get current account from trading_bot: {e}")
            
            # Method 2: Try from context.user_data
            if not current_account and 'current_account_id' in context.user_data:
                account_id = context.user_data.get('current_account_id')
                account_name = context.user_data.get('current_account_name', 'Account')
                try:
                    all_accounts = trading_bot.enhanced_db.get_all_accounts()
                    current_account = next((a for a in all_accounts if a.account_id == account_id), None)
                    if current_account:
                        trading_bot.set_current_account(user_id, account_id)
                except Exception as e:
                    logger.warning(f"Failed to load account from user_data: {e}")
            
            # Step 2: Validate we have an account
            if not current_account or not account_id:
                await update.message.reply_text(
                    "❌ <b>No Account Selected</b>\n\n"
                    "Please select an account first from the Accounts menu.\n\n"
                    "Go to: 🔙 Main Menu → 🔑 Accounts → Select your account",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
                return
            
            # Step 3: Fetch trade history
            trade_history = trading_bot.enhanced_db.get_trade_history(
                account_id, 
                limit=50, 
                only_closed=True
            )
            
            # Step 4: Handle empty history
            if not trade_history:
                await update.message.reply_text(
                    f"📋 <b>No Trade History</b>\n\n"
                    f"Account: <b>{account_name}</b>\n\n"
                    f"No closed trades found for this account.\n"
                    f"Start trading to see your history here!",
                    parse_mode='HTML',
                    reply_markup=build_account_page()
                )
                return
            
            # Step 5: Build comprehensive history display
            # Calculate overall statistics
            # Only count trades that were properly closed with actual win/lose data
            closed_trades = [t for t in trade_history if t.status == "CLOSED" and t.exit_time is not None]
            total_trades = len(closed_trades)
            winning_trades = sum(1 for t in closed_trades if t.pnl and float(t.pnl) > 0)
            losing_trades = total_trades - winning_trades
            total_pnl = sum(float(t.pnl) if t.pnl else 0 for t in trade_history)
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # Resolve channel names
            channel_name_map = {}
            unique_channels = set(t.channel_id for t in trade_history if t.channel_id)
            for ch_id in unique_channels:
                try:
                    channel_name_map[ch_id] = await trading_bot.get_channel_display_name(ch_id, user_id)
                except Exception as e:
                    logger.debug(f"Could not resolve channel name for {ch_id}: {e}")
                    channel_name_map[ch_id] = f"Channel {ch_id[:8]}..."
            
            # Build per-channel statistics
            channel_stats = {}
            for trade in trade_history:
                ch_id = trade.channel_id or 'unknown'
                if ch_id not in channel_stats:
                    channel_stats[ch_id] = {
                        'count': 0,
                        'wins': 0,
                        'losses': 0,
                        'pnl': 0.0
                    }
                
                channel_stats[ch_id]['count'] += 1
                pnl_value = float(trade.pnl) if trade.pnl else 0
                channel_stats[ch_id]['pnl'] += pnl_value
                
                if pnl_value > 0:
                    channel_stats[ch_id]['wins'] += 1
                else:
                    channel_stats[ch_id]['losses'] += 1
            
            # Build message header with summary
            text = f"📋 <b>Trade History</b>\n"
            text += f"Account: <b>{account_name}</b>\n\n"
            
            text += f"📊 <b>Summary Statistics:</b>\n"
            text += f"Total Trades: <b>{total_trades}</b>\n"
            text += f"✅ Winning: <b>{winning_trades}</b>\n"
            text += f"❌ Losing: <b>{losing_trades}</b>\n"
            text += f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
            text += f"💵 Total PnL: <b>{total_pnl:.2f} USDT</b>\n\n"
            
            # Display individual trades (most recent first)
            # Limit to fewer trades to avoid message length issues
            trades_to_show = min(10, total_trades)
            text += f"📝 <b>Recent Trades (Last {trades_to_show}):</b>\n\n"
            
            for i, trade in enumerate(trade_history[:trades_to_show]):
                # Check if adding this trade would exceed Telegram's limit
                if len(text) > 3500:  # Leave room for channel stats
                    text += f"<i>... and {total_trades - i} more trades</i>\n\n"
                    break
                
                # Determine emoji based on PnL
                pnl_value = float(trade.pnl) if trade.pnl else 0
                if pnl_value > 0:
                    status_emoji = "✅"
                elif pnl_value < 0:
                    status_emoji = "❌"
                else:
                    status_emoji = "⚪"
                
                # Get channel name (shortened)
                ch_id = trade.channel_id
                ch_display = ""
                if ch_id and ch_id in channel_name_map:
                    ch_name = channel_name_map[ch_id]
                    # Truncate long channel names
                    if len(ch_name) > 20:
                        ch_name = ch_name[:17] + "..."
                    ch_display = f" | {ch_name}"
                
                # Format trade entry (compact)
                text += f"{status_emoji} <b>{trade.symbol}</b> {trade.side}{ch_display}\n"
                text += f"  Entry: {trade.entry_price}"
                if trade.exit_price:
                    text += f" → {trade.exit_price}"
                text += f" | PnL: <b>{pnl_value:.2f}</b>\n\n"
            
            # Add per-channel analytics (compact)
            if channel_stats and len(channel_stats) > 1 and len(text) < 3800:
                text += f"📡 <b>Per-Channel:</b>\n"
                for ch_id, stats in sorted(channel_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)[:5]:
                    if len(text) > 3900:
                        break
                    ch_name = channel_name_map.get(ch_id, 'Unknown') if ch_id != 'unknown' else 'Unknown'
                    if len(ch_name) > 15:
                        ch_name = ch_name[:12] + "..."
                    ch_wr = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
                    text += f"• {ch_name}: {stats['count']} trades, {ch_wr:.0f}% WR, {stats['pnl']:.1f} PnL\n"
            
            # Ensure we don't exceed Telegram's limit
            if len(text) > 4000:
                text = text[:3950] + "\n\n<i>... (truncated)</i>"
            
            # Send the message
            await update.message.reply_text(
                text, 
                parse_mode='HTML', 
                reply_markup=build_account_page()
            )
            
        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR in History button handler: {e}")
            logger.error(traceback.format_exc())
            await update.message.reply_text(
                "❌ <b>Error Loading History</b>\n\n"
                f"Something went wrong while loading your trade history.\n\n"
                f"Error: <code>{str(e)[:100]}</code>\n\n"
                "Please try again. If the problem persists:\n"
                "1. Go back to Main Menu\n"
                "2. Select your account again\n"
                "3. Try History button again",
                parse_mode='HTML',
                reply_markup=build_account_page()
            )

    elif text == "📈 Trades" and 'current_account_id' in context.user_data:
        # Show active trades for current account only
        acc_id = context.user_data.get('current_account_id')
        acc_name = context.user_data.get('current_account_name', 'Account')
        
        active_trades = trading_bot.enhanced_db.get_active_trades(acc_id)
        
        if not active_trades:
            await update.message.reply_text(
                f"📈 <b>No Active Trades</b>\n\n"
                f"Account: {acc_name}\n\n"
                f"You don't have any open positions on this account.",
                parse_mode='HTML',
                reply_markup=build_account_page()
            )
        else:
            text = f"📈 <b>Active Trades - {acc_name}</b>\n\n"
            text += f"Open positions ({len(active_trades)}):\n\n"
            
            trades_shown = 0
            for trade in active_trades:
                # Check message length to avoid exceeding Telegram's limit
                if len(text) > 3500:
                    text += f"<i>... and {len(active_trades) - trades_shown} more trades</i>\n"
                    break
                
                text += f"<b>{trade.symbol}</b> {trade.side}\n"
                text += f"Entry: {trade.entry_price} | Qty: {trade.quantity}\n"
                text += f"Leverage: {trade.leverage}x | Status: {trade.status}\n\n"
                trades_shown += 1
            
            # Ensure we don't exceed Telegram's limit
            if len(text) > 4000:
                text = text[:3950] + "\n\n<i>... (truncated)</i>"
            
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=build_account_page())

    elif text == "📊 Account Stats" and 'current_account_id' in context.user_data:
        # Show detailed stats for current account
        acc_id = context.user_data.get('current_account_id')
        acc_name = context.user_data.get('current_account_name', 'Account')
        
        # Get account from database
        accs = trading_bot.enhanced_db.get_all_accounts()
        acc = next((a for a in accs if a.account_id == acc_id), None)
        
        if not acc:
            await update.message.reply_text(
                "❌ Account not found",
                parse_mode='HTML',
                reply_markup=build_account_page()
            )
            return
        
        # Get trades and calculate stats
        active_trades = trading_bot.enhanced_db.get_active_trades(acc_id)
        trade_history = trading_bot.enhanced_db.get_trade_history(acc_id, limit=100)
        
            # Calculate statistics
        # Only count trades that were properly closed with actual win/lose data
        closed_trades = [t for t in trade_history if t.status == "CLOSED" and t.exit_time is not None]
        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if t.pnl and float(t.pnl) > 0)
        # Count all non-winning trades as losing (including break-even trades)
        losing_trades = total_trades - winning_trades
        total_pnl = sum(float(t.pnl) if t.pnl else 0 for t in trade_history)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Build stats message
        msg = f"📊 <b>Account Statistics - {acc_name}</b>\n\n"
        
        # Trading Performance
        msg += f"📈 <b>Trading Performance:</b>\n"
        msg += f"Total Trades: <b>{total_trades}</b>\n"
        msg += f"✅ Winning Trades: <b>{winning_trades}</b>\n"
        msg += f"❌ Losing Trades: <b>{losing_trades}</b>\n"
        msg += f"📊 Win Rate: <b>{win_rate:.1f}%</b>\n"
        msg += f"💵 Total PnL: <b>{total_pnl:.2f} USDT</b>\n\n"
        
        # Active Positions
        msg += f"📍 <b>Active Positions:</b>\n"
        msg += f"Open Trades: <b>{len(active_trades)}</b>\n"
        if active_trades:
            active_pnl = sum(float(t.pnl) if t.pnl else 0 for t in active_trades)
            msg += f"Active PnL: <b>{active_pnl:.2f} USDT</b>\n"
        msg += "\n"
        
        # Account Configuration
        balance_mode = "Percentage" if acc.use_percentage_balance else "Fixed USDT"
        balance_value = f"{acc.balance_percentage}%" if acc.use_percentage_balance else f"${acc.fixed_usdt_amount}"
        
        msg += f"⚙️ <b>Configuration:</b>\n"
        msg += f"⚡ Leverage: <b>{acc.leverage}x</b>\n"
        msg += f"💰 Risk: <b>{acc.risk_percentage}%</b>\n"
        msg += f"💵 Trade Amount: <b>{balance_value}</b>\n"
        msg += f"🎯 TP Levels: <b>{len(acc.take_profit_levels)}</b>\n"
        msg += f"🛑 SL Levels: <b>{len(acc.stop_loss_levels)}</b>\n"
        msg += f"📉 Trailing Stop: <b>{'ON' if acc.trailing_enabled else 'OFF'}</b>\n\n"
        
        # Monitoring Status
        monitor_status = "🟢 Active" if trading_bot.monitoring_status.get(user_id, False) else "🔴 Inactive"
        msg += f"🔄 <b>Status:</b>\n"
        msg += f"Monitoring: <b>{monitor_status}</b>\n"
        msg += f"📡 Channels: <b>{len(acc.monitored_channels)}</b>\n"
        
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_account_page())

    elif text == "⚙️ Settings" and 'current_account_id' in context.user_data:
        # Show account settings with cooldown options
        acc_id = context.user_data.get('current_account_id')
        acc_name = context.user_data.get('current_account_name', 'Account')
        
        # Get account from database
        accs = trading_bot.enhanced_db.get_all_accounts()
        acc = next((a for a in accs if a.account_id == acc_id), None)
        
        if not acc:
            await update.message.reply_text("❌ Account not found", parse_mode='HTML', reply_markup=build_account_page())
            return
        
        # Build settings message
        msg = f"⚙️ <b>Account Settings - {acc_name}</b>\n\n"
        
        # Trading Settings
        msg += f"📊 <b>Trading Settings:</b>\n"
        msg += f"⚡ Leverage: <b>{acc.leverage}x</b>\n"
        msg += f"💰 Risk %: <b>{acc.risk_percentage}%</b>\n"
        balance_mode = "Percentage" if acc.use_percentage_balance else "Fixed USDT"
        balance_value = f"{acc.balance_percentage}%" if acc.use_percentage_balance else f"${acc.fixed_usdt_amount}"
        msg += f"💵 Trade Amount: <b>{balance_value}</b>\n\n"
        
        # Cooldown Settings
        cooldown_status = "🟢 ON" if getattr(acc, 'cooldown_enabled', False) else "🔴 OFF"
        cooldown_hours = getattr(acc, 'cooldown_hours', 24)
        msg += f"⏰ <b>Cooldown Settings:</b>\n"
        msg += f"Status: <b>{cooldown_status}</b>\n"
        if getattr(acc, 'cooldown_enabled', False):
            msg += f"Hours: <b>{cooldown_hours}h</b>\n"
        msg += "\n"
        
        # Commands
        msg += f"📝 <b>Commands:</b>\n"
        msg += f"• <code>cooldown on [hours]</code> - Enable cooldown\n"
        msg += f"• <code>cooldown off</code> - Disable cooldown\n"
        msg += f"• <code>cooldown status</code> - Check settings\n"
        msg += f"• <code>leverage [1-125]</code> - Set leverage\n"
        msg += f"• <code>risk [%]</code> - Set risk percentage\n"
        msg += f"• <code>balance [%]</code> - Set balance percentage\n"
        msg += f"• <code>amount [USDT]</code> - Set fixed amount\n"
        
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_account_page())

    elif text == "📡 Channels" and 'current_account_id' in context.user_data:
        # This will be handled by the conversation handler
        pass

    elif text == "🔙 Account":
        acc_name = context.user_data.get('current_account_name', 'Account')
        await update.message.reply_text(f"📋 {acc_name}", parse_mode='HTML', reply_markup=build_account_page())

    # Settings menu buttons
    elif text == "📊 Leverage":
        await update.message.reply_text("📊 Enter leverage (1-125):", parse_mode='HTML')
        context.user_data['state'] = 'WAIT_LEVERAGE'

    elif text == "💰 Risk %":
        await update.message.reply_text("💰 Enter risk % per trade:", parse_mode='HTML')

    elif text == "🎯 Take Profits":
        await update.message.reply_text("🎯 Configure TP levels", parse_mode='HTML')

    elif text == "🛡️ Stop Loss":
        await update.message.reply_text("🛡️ Configure SL level", parse_mode='HTML')

    elif text == "📉 Trailing":
        await update.message.reply_text("📉 Trailing stop settings", parse_mode='HTML')
    
    # New comprehensive settings handlers
    elif text == "🔮 Trading Type":
        await handle_trading_type_setting(update, context)
    
    elif text == "⚡ Leverage":
        await handle_leverage_setting(update, context)
    
    elif text == "💰 Risk %":
        await handle_risk_setting(update, context)
    
    elif text == "💵 Trade Amount":
        await handle_trade_amount_setting(update, context)
    
    elif text == "🎯 Take Profits":
        await handle_take_profits_setting(update, context)
    
    elif text == "🛡️ Stop Loss":
        await handle_stop_loss_setting(update, context)
    
    elif text == "⏰ Cooldown":
        await handle_cooldown_setting(update, context)
    
    elif text == "📡 Channels":
        await handle_channels_setting(update, context)
    
    elif text == "🔧 Advanced":
        await handle_advanced_settings(update, context)
    
    elif text == "🗑️ Delete Account":
        await handle_delete_account(update, context)
    
    elif text == "✏️ Rename Account":
        await handle_rename_account(update, context)

    # Cooldown commands
    elif text.startswith("cooldown on") and 'current_account_id' in context.user_data:
        acc_id = context.user_data.get('current_account_id')
        parts = text.split()
        hours = 24  # default
        if len(parts) > 2:
            try:
                hours = int(parts[2])
                if hours < 1 or hours > 168:  # max 1 week
                    hours = 24
            except ValueError:
                hours = 24
        
        success = trading_bot.enhanced_db.update_account_settings(acc_id, cooldown_enabled=True, cooldown_hours=hours)
        if success:
            await update.message.reply_text(f"✅ Cooldown enabled: {hours} hours", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Failed to update cooldown settings", parse_mode='HTML')

    elif text == "cooldown off" and 'current_account_id' in context.user_data:
        acc_id = context.user_data.get('current_account_id')
        success = trading_bot.enhanced_db.update_account_settings(acc_id, cooldown_enabled=False)
        if success:
            await update.message.reply_text("✅ Cooldown disabled", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Failed to update cooldown settings", parse_mode='HTML')

    elif text == "cooldown status" and 'current_account_id' in context.user_data:
        acc_id = context.user_data.get('current_account_id')
        accs = trading_bot.enhanced_db.get_all_accounts()
        acc = next((a for a in accs if a.account_id == acc_id), None)
        if acc:
            status = "ON" if getattr(acc, 'cooldown_enabled', False) else "OFF"
            hours = getattr(acc, 'cooldown_hours', 24)
            await update.message.reply_text(f"📊 Cooldown: {status} ({hours}h)", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Account not found", parse_mode='HTML')

    # Additional settings commands
    elif text.startswith("leverage ") and 'current_account_id' in context.user_data:
        try:
            leverage = int(text.split()[1])
            if 1 <= leverage <= 125:
                acc_id = context.user_data.get('current_account_id')
                success = trading_bot.enhanced_db.update_account_settings(acc_id, leverage=leverage)
                if success:
                    await update.message.reply_text(f"✅ Leverage set to {leverage}x", parse_mode='HTML')
                else:
                    await update.message.reply_text("❌ Failed to update leverage", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Leverage must be between 1-125", parse_mode='HTML')
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid leverage format. Use: leverage [1-125]", parse_mode='HTML')

    elif text.startswith("risk ") and 'current_account_id' in context.user_data:
        try:
            risk = float(text.split()[1])
            if 0 < risk <= 100:
                acc_id = context.user_data.get('current_account_id')
                success = trading_bot.enhanced_db.update_account_settings(acc_id, risk_percentage=risk)
                if success:
                    await update.message.reply_text(f"✅ Risk percentage set to {risk}%", parse_mode='HTML')
                else:
                    await update.message.reply_text("❌ Failed to update risk percentage", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Risk must be between 0-100%", parse_mode='HTML')
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid risk format. Use: risk [%]", parse_mode='HTML')

    elif text.startswith("balance ") and 'current_account_id' in context.user_data:
        try:
            balance = float(text.split()[1])
            if 0 < balance <= 100:
                acc_id = context.user_data.get('current_account_id')
                success = trading_bot.enhanced_db.update_account_settings(acc_id, balance_percentage=balance, use_percentage_balance=True)
                if success:
                    await update.message.reply_text(f"✅ Balance percentage set to {balance}%", parse_mode='HTML')
                else:
                    await update.message.reply_text("❌ Failed to update balance percentage", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Balance must be between 0-100%", parse_mode='HTML')
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid balance format. Use: balance [%]", parse_mode='HTML')

    elif text.startswith("amount ") and 'current_account_id' in context.user_data:
        try:
            amount = float(text.split()[1])
            if amount > 0:
                acc_id = context.user_data.get('current_account_id')
                success = trading_bot.enhanced_db.update_account_settings(acc_id, fixed_usdt_amount=amount, use_percentage_balance=False)
                if success:
                    await update.message.reply_text(f"✅ Fixed amount set to ${amount} USDT", parse_mode='HTML')
                else:
                    await update.message.reply_text("❌ Failed to update fixed amount", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Amount must be greater than 0", parse_mode='HTML')
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid amount format. Use: amount [USDT]", parse_mode='HTML')

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
            balance_value = f"{account.balance_percentage}%" if account.use_percentage_balance else f"${account.fixed_usdt_amount}"
            text += f"<b>{i}. {account.account_name}</b>\n"
            text += f"Status: {status}\n"
            text += f"⚡ Leverage: {account.leverage}x\n"
            text += f"💰 Trade Amount: {balance_value}\n"
            text += f"📡 Channels: {len(account.monitored_channels)}\n\n"
        
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
💰 Trade Amount: <b>{f"{current_account.balance_percentage}%" if current_account.use_percentage_balance else f"${current_account.fixed_usdt_amount}"}</b>
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
        
        trades_shown = 0
        for trade in active_trades:
            # Check message length to avoid exceeding Telegram's limit
            if len(text) > 3500:
                text += f"<i>... and {len(active_trades) - trades_shown} more trades</i>\n"
                break
            
            text += f"<b>{trade.symbol}</b> {trade.side}\n"
            text += f"Entry: {trade.entry_price} | Qty: {trade.quantity}\n"
            text += f"Leverage: {trade.leverage}x | Status: {trade.status}\n\n"
            trades_shown += 1
        
        # Ensure we don't exceed Telegram's limit
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>... (truncated)</i>"
        
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
        
        trades_shown = 0
        for trade in trade_history:
            # Check message length to avoid exceeding Telegram's limit
            if len(text) > 3500:
                text += f"<i>... and {len(trade_history) - trades_shown} more trades</i>\n"
                break
            
            status_emoji = "🟢" if trade.status == "OPEN" else "🔴" if trade.status == "CLOSED" else "🟡"
            text += f"{status_emoji} <b>{trade.symbol}</b> {trade.side}\n"
            text += f"Entry: {trade.entry_price} | PnL: {trade.pnl}\n"
            
            # Get and display channel name (compact)
            if trade.channel_id:
                try:
                    telethon_client = trading_bot.user_monitoring_clients.get(user_id)
                    if telethon_client:
                        try:
                            entity = await telethon_client.get_entity(int(trade.channel_id))
                            channel_name = getattr(entity, 'title', f'Ch {trade.channel_id[:8]}')
                            if len(channel_name) > 20:
                                channel_name = channel_name[:17] + "..."
                            text += f"📡 {channel_name}\n"
                        except Exception:
                            text += f"📡 Ch {trade.channel_id[:8]}\n"
                    else:
                        text += f"📡 Ch {trade.channel_id[:8]}\n"
                except Exception as e:
                    logger.debug(f"Could not get channel name for {trade.channel_id}: {e}")
            
            text += f"Time: {trade.entry_time[:16]}\n\n"
            trades_shown += 1
        
        # Ensure we don't exceed Telegram's limit
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>... (truncated)</i>"
        
        await update.message.reply_text(text, parse_mode='HTML')

async def handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle comprehensive settings menu"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML',
            reply_markup=build_main_menu()
        )
        return
    
    # Build comprehensive settings display
    msg = f"⚙️ <b>Account Settings - {current_account.account_name}</b>\n\n"
    
    # Trading Configuration
    msg += f"📊 <b>Trading Configuration:</b>\n"
    trading_type_display = "🔮 Futures/Swap" if getattr(current_account, 'trading_type', 'swap') == 'swap' else "💱 Spot"
    msg += f"  {trading_type_display}\n"
    msg += f"  ⚡ Leverage: <b>{current_account.leverage}x</b>\n"
    msg += f"  💰 Risk: <b>{current_account.risk_percentage}%</b>\n"
    
    # Balance Configuration
    balance_mode = "Percentage" if current_account.use_percentage_balance else "Fixed USDT"
    balance_value = f"{current_account.balance_percentage}%" if current_account.use_percentage_balance else f"${current_account.fixed_usdt_amount}"
    msg += f"  💵 Trade Amount: <b>{balance_value}</b> ({balance_mode})\n\n"
    
    # Take Profit Levels
    msg += f"🎯 <b>Take Profit Levels:</b>\n"
    if current_account.take_profit_levels:
        for i, tp in enumerate(current_account.take_profit_levels, 1):
            msg += f"  {i}. <b>{tp.percentage}%</b> - Close <b>{tp.close_percentage}%</b>\n"
    else:
        msg += f"  No levels configured\n"
    
    # Stop Loss Levels
    msg += f"\n🛡️ <b>Stop Loss Levels:</b>\n"
    if current_account.stop_loss_levels:
        for i, sl in enumerate(current_account.stop_loss_levels, 1):
            msg += f"  {i}. <b>{sl.percentage}%</b> - Close <b>{sl.close_percentage}%</b>\n"
    else:
        msg += f"  No levels configured\n"
    
    # Trailing Stop
    msg += f"\n📉 <b>Trailing Stop:</b>\n"
    trailing_status = "🟢 ON" if current_account.trailing_enabled else "🔴 OFF"
    msg += f"  Status: <b>{trailing_status}</b>\n"
    if current_account.trailing_enabled:
        msg += f"  Activation: <b>{current_account.trailing_activation_percent}%</b>\n"
        msg += f"  Callback: <b>{current_account.trailing_callback_percent}%</b>\n"
    
    # Cooldown
    msg += f"\n⏰ <b>Cooldown:</b>\n"
    cooldown_status = "🟢 ON" if getattr(current_account, 'cooldown_enabled', False) else "🔴 OFF"
    cooldown_hours = getattr(current_account, 'cooldown_hours', 24)
    msg += f"  Status: <b>{cooldown_status}</b>\n"
    if getattr(current_account, 'cooldown_enabled', False):
        msg += f"  Duration: <b>{cooldown_hours} hours</b>\n"
    
    # Advanced Features
    msg += f"\n🔧 <b>Advanced Features:</b>\n"
    msg += f"  Signal Settings: <b>{'ON' if current_account.use_signal_settings else 'OFF'}</b>\n"
    msg += f"  Create SL/TP: <b>{'ON' if current_account.create_sl_tp else 'OFF'}</b>\n"
    msg += f"  Webhook: <b>{'ON' if current_account.make_webhook_enabled else 'OFF'}</b>\n"
    
    # Channels
    msg += f"\n📡 <b>Monitored Channels:</b> <b>{len(current_account.monitored_channels)}</b>\n"
    
    msg += f"\nUse the buttons below to modify settings:"
    
    await update.message.reply_text(msg, parse_mode='HTML', reply_markup=build_settings_menu())

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
    
    account_id = current_account.account_id
    
    # Check if already monitoring THIS account
    if trading_bot.account_monitoring_status.get(account_id, False):
        await update.message.reply_text(
            "⚠️ <b>Already Monitoring!</b>\n\n"
            f"Trading is already active for account: <b>{current_account.account_name}</b>\n"
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
        # Start monitoring (this sets up the Telethon client for the user if needed)
        success = await trading_bot.start_monitoring(user_id, context.bot)
        
        if success:
            # Mark THIS account as monitoring
            trading_bot.account_monitoring_status[account_id] = True
            trading_bot.monitoring_status[user_id] = True  # Keep for backward compatibility
            
            await update.message.reply_text(
                f"🚀 <b>Trading Started Successfully!</b>\n\n"
                f"Account: <b>{current_account.account_name}</b>\n"
                f"Channels: <b>{len(current_account.monitored_channels)}</b>\n"
                f"⚡ Leverage: <b>{current_account.leverage}x</b>\n"
                f"💰 Trade Amount: <b>{f"{current_account.balance_percentage}%" if current_account.use_percentage_balance else f"${current_account.fixed_usdt_amount}"}</b>\n\n"
                f"✅ Monitoring active for this account only\n"
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
    
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first.",
            parse_mode='HTML'
        )
        return
    
    account_id = current_account.account_id
    
    # Check if monitoring is active for THIS account
    if not trading_bot.account_monitoring_status.get(account_id, False):
        await update.message.reply_text(
            "⚠️ <b>Not Currently Monitoring</b>\n\n"
            f"Trading is not active for account: <b>{current_account.account_name}</b>",
            parse_mode='HTML'
        )
        return
    
    try:
        # Stop monitoring for THIS account only
        trading_bot.account_monitoring_status[account_id] = False
        
        # Stop account-specific monitoring task
        if account_id in trading_bot.monitoring_tasks:
            task = trading_bot.monitoring_tasks[account_id]
            if not task.done():
                task.cancel()
            del trading_bot.monitoring_tasks[account_id]
        
        # Close telethon client for this account
        if account_id in trading_bot.user_monitoring_clients:
            try:
                client = trading_bot.user_monitoring_clients[account_id]
                if client.is_connected():
                    await client.disconnect()
                del trading_bot.user_monitoring_clients[account_id]
            except Exception as e:
                logger.error(f"Error closing telethon client for account {account_id}: {e}")
        
        # Check if any other accounts for this user are still monitoring
        user_accounts = trading_bot.enhanced_db.get_user_accounts(user_id)
        any_monitoring = False
        for acc in user_accounts:
            if acc.account_id != account_id and trading_bot.account_monitoring_status.get(acc.account_id, False):
                any_monitoring = True
                break
        
        # Update legacy user-level flags
        if not any_monitoring:
            trading_bot.active_monitoring[user_id] = False
            trading_bot.monitoring_status[user_id] = False
        
        await update.message.reply_text(
            f"🛑 <b>Trading Stopped Successfully!</b>\n\n"
            f"Account: <b>{current_account.account_name}</b>\n"
            f"✅ Monitoring stopped for this account\n"
            f"{'✅ Telegram client still active for other accounts\n' if any_monitoring else '✅ Telegram client disconnected\n'}"
            f"✅ Tasks cancelled\n\n"
            f"Trading stopped for this account.",
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
    help_text = (
        "<b>🤖 Bot Controls</b>\n\n"
        "Use the on-screen buttons to control the bot.\n"
        "Only /start command is available to open the menu.\n\n"
        "- 🔑 Accounts: manage accounts\n"
        "- ⚙️ Settings: configure trading\n"
        "- 📡 Channels: choose channels\n"
        "- 🚀 Start / 🛑 Stop: control monitoring\n"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')
    # Ensure main menu visible
    main_menu = build_main_menu()
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

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check account balance"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.binance_api_key or not config.binance_api_secret:
        await update.message.reply_text("❌ <b>BingX API not configured!</b> Open ⚙️ Settings to configure.", parse_mode='HTML')
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
    # Support being called from both message and callback contexts
    if update.message and hasattr(update.message, 'reply_text'):
        async def send_text(text: str, **kwargs):
            return await update.message.reply_text(text, **kwargs)
    else:
        async def send_text(text: str, **kwargs):
            return await context.bot.send_message(chat_id=user_id, text=text, **kwargs)

    await send_text("🔍 <b>Loading channels...</b>", parse_mode='HTML')

    channels = await trading_bot.get_available_channels(user_id)

    if not channels:
        await send_text("❌ <b>No channels!</b> Add an account and configure 📡 Channels from the account page.", parse_mode='HTML')
        return ConversationHandler.END

    context.user_data['available_channels'] = channels
    keyboard_markup = create_channel_keyboard(user_id, channels)

    await send_text(
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

Open 📡 Channels again to continue managing.""",
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

Next: open ⚙️ Settings""",
            parse_mode='HTML'
        )
        # Persist monitored channels to the current account if available
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_monitored_channels(acc.account_id, config.monitored_channels)
                # Reload config to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist monitored channels: {e}")
        return ConversationHandler.END

    elif query.data == "clear_all_channels":
        config.monitored_channels.clear()
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_monitored_channels(acc.account_id, config.monitored_channels)
                # Reload config to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist monitored channels: {e}")
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

        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_monitored_channels(acc.account_id, config.monitored_channels)
                # Reload config to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist monitored channels: {e}")

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
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_monitored_channels(acc.account_id, config.monitored_channels)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist monitored channels: {e}")

            await update.message.reply_text(
                f"""✅ <b>Channel added!</b>

Channel ID: <code>{channel_id}</code>
Total: <b>{len(config.monitored_channels)}</b>

Next: open ⚙️ Settings""",
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

        # Persist if possible
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_monitored_channels(acc.account_id, config.monitored_channels)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist monitored channels: {e}")

            await update.message.reply_text(
                f"""✅ <b>Channel Added!</b>

📡 Channel: {channel_name}
🆔 ID: <code>{channel_id}</code>
📊 Total channels: <b>{len(config.monitored_channels)}</b>

Open 📡 Channels to manage or continue setup.""",
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
        render_trading_config_text(user_id),
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
Next: press 🚀 Start on the account page""",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings
        # Persist to database
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, use_signal_settings=config.use_signal_settings)
                # Reload config from database to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist settings source: {e}")
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            render_trading_config_text(user_id),
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp
        # Persist to database
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, create_sl_tp=config.create_sl_tp)
                # Reload config from database to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist SL/TP setting: {e}")
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            render_trading_config_text(user_id),
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_webhook":
        config.make_webhook_enabled = not config.make_webhook_enabled
        # Persist to database
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, make_webhook_enabled=config.make_webhook_enabled)
                # Reload config from database to ensure fresh data
                config = trading_bot.get_user_config(user_id)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist webhook setting: {e}")
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            render_trading_config_text(user_id),
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
        # Shortcut to TP configurator
        total_close = 0.0
        lines = []
        for i, tp in enumerate(config.custom_take_profits, 1):
            total_close += tp.close_percentage if i < len(config.custom_take_profits) else (100.0 - min(total_close, 100.0))
            lines.append(f"TP{i}: {tp.percentage}% → Close {tp.close_percentage}%")
        summary = f"Total planned close (pre-cap): {sum(l.close_percentage for l in config.custom_take_profits):.1f}%"
        tp_text = "\n".join(["🎯 <b>Current Take Profit Levels:</b>", "", *lines, "", summary, "", "Add, clear, or reset below."])
        tp_keyboard = [
            [InlineKeyboardButton("➕ Add Level", callback_data="add_tp_level")],
            [InlineKeyboardButton("🗑️ Clear All", callback_data="clear_tp_levels")],
            [InlineKeyboardButton("🔄 Reset Default", callback_data="reset_tp_default")],
            [InlineKeyboardButton("✅ Done", callback_data="tp_config_done")]
        ]
        await query.edit_message_text(tp_text, reply_markup=InlineKeyboardMarkup(tp_keyboard), parse_mode='HTML')
        return WAITING_TP_CONFIG

    elif query.data == "set_balance_percent":
        await query.edit_message_text(
            "💰 <b>Set Balance %</b>\n\nSend percentage (1-100):",
            parse_mode='HTML'
        )
        return WAITING_BALANCE_PERCENT

    elif query.data == "toggle_trailing":
        config.trailing_enabled = not config.trailing_enabled
        # Persist to database
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, trailing_enabled=config.trailing_enabled)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist trailing setting: {e}")
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            render_trading_config_text(user_id),
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
        await query.edit_message_text("📡 <b>Opening channel manager...</b>", parse_mode='HTML')
        # Directly open channels manager via button flow
        await setup_channels(update, context)
        return ConversationHandler.END

    elif query.data == "rename_account":
        # Ask for new account name
        await query.edit_message_text(
            "✏️ <b>Rename Account</b>\n\nSend a new name for this account:",
            parse_mode='HTML'
        )
        context.user_data['awaiting_rename'] = True
        return WAITING_ACCOUNT_SETTINGS

    elif query.data == "delete_account":
        # Ask for confirmation
        await query.edit_message_text(
            "🗑️ <b>Delete Account</b>\n\nType 'DELETE' to confirm. This disables the account (soft delete).",
            parse_mode='HTML'
        )
        context.user_data['awaiting_delete'] = True
        return WAITING_ACCOUNT_SETTINGS

    # Removed enable_oco callback - OCO monitoring is now automatic

    elif query.data == "toggle_trade_amount_mode":
        # Show inline buttons to choose between percentage and USDT amount
        keyboard = [
            [InlineKeyboardButton("💰 Percentage", callback_data="choose_percentage")],
            [InlineKeyboardButton("💵 Fixed USDT", callback_data="choose_fixed_usdt")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")]
        ]
        await query.edit_message_text(
            "💰 <b>Choose Trade Amount Mode:</b>\n\n"
            "Select how you want to configure your trade amount:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_SETTINGS_SOURCE
    
    elif query.data == "choose_percentage":
        config.use_fixed_usdt_amount = False
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, use_percentage_balance=True)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist trade amount mode: {e}")
        await query.edit_message_text(
            f"💰 <b>Set Balance Percentage</b>\n\nCurrent: {config.balance_percent}%\n\nSend percentage (1-100):",
            parse_mode='HTML'
        )
        return WAITING_BALANCE_PERCENT
    
    elif query.data == "choose_fixed_usdt":
        config.use_fixed_usdt_amount = True
        try:
            current_account = trading_bot.get_current_account(user_id)
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, use_percentage_balance=False)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist trade amount mode: {e}")
        await query.edit_message_text(
            f"💵 <b>Set Fixed USDT Amount</b>\n\nCurrent: ${config.fixed_usdt_amount:.0f}\n\nSend new amount:",
            parse_mode='HTML'
        )
        return WAITING_USDT_AMOUNT
    
    elif query.data == "back_to_settings":
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            render_trading_config_text(user_id),
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )
        return WAITING_SETTINGS_SOURCE

    elif query.data == "configure_take_profits":
        # Render TP levels with totals for clarity
        total_close = 0.0
        lines = []
        for i, tp in enumerate(config.custom_take_profits, 1):
            total_close += tp.close_percentage if i < len(config.custom_take_profits) else (100.0 - min(total_close, 100.0))
            lines.append(f"TP{i}: {tp.percentage}% → Close {tp.close_percentage}%")
        summary = f"Total planned close (pre-cap): {sum(l.close_percentage for l in config.custom_take_profits):.1f}%"
        tp_text = "\n".join(["🎯 <b>Current Take Profit Levels:</b>", "", *lines, "", summary, "", "Add, clear, or reset below."])

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
    current_account = trading_bot.get_current_account(user_id)

    try:
        leverage = int(update.message.text)
        if 1 <= leverage <= 125:
            config.leverage = leverage
            try:
                if current_account:
                    trading_bot.enhanced_db.update_account_settings(current_account.account_id, leverage=leverage)
            except Exception as e:
                logger.warning(f"⚠️ Failed to persist leverage: {e}")
            await update.message.reply_text(f"✅ <b>Leverage: {leverage}x</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-125", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_account_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle rename/delete confirmations in settings flow."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    acc = trading_bot.get_current_account(user_id)
    if not acc:
        await update.message.reply_text("❌ No current account selected.")
        return ConversationHandler.END

    # Rename flow
    if context.user_data.get('awaiting_rename'):
        new_name = text[:50]
        ok = trading_bot.enhanced_db.update_account_name(acc.account_id, new_name)
        context.user_data.pop('awaiting_rename', None)
        if ok:
            await update.message.reply_text(f"✅ Account renamed to <b>{new_name}</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Failed to rename account")
        return ConversationHandler.END

    # Delete flow
    if context.user_data.get('awaiting_delete'):
        if text.upper() == 'DELETE':
            ok = trading_bot.enhanced_db.soft_delete_account(acc.account_id)
            context.user_data.pop('awaiting_delete', None)
            if ok:
                await update.message.reply_text("✅ Account disabled (soft-deleted).", parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Failed to delete account", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Deletion cancelled.", parse_mode='HTML')
            context.user_data.pop('awaiting_delete', None)
        return ConversationHandler.END

    return ConversationHandler.END

async def handle_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    current_account = trading_bot.get_current_account(user_id)

    try:
        sl_percent = float(update.message.text)
        if 0.1 <= sl_percent <= 50:
            config.stop_loss_percent = sl_percent
            try:
                if current_account:
                    # Store as first/only stop loss level for account defaults
                    trading_bot.enhanced_db.update_account_stop_loss_levels(current_account.account_id, [StopLossLevel(abs(sl_percent), 100.0)])
            except Exception as e:
                logger.warning(f"⚠️ Failed to persist stop loss: {e}")
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
    current_account = trading_bot.get_current_account(user_id)

    try:
        value = float(update.message.text)
        if 1 <= value <= 100:
            config.balance_percent = value
            try:
                if current_account:
                    trading_bot.enhanced_db.update_account_settings(current_account.account_id, balance_percentage=value, use_percentage_balance=True)
            except Exception as e:
                logger.warning(f"⚠️ Failed to persist balance %: {e}")
            await update.message.reply_text(f"✅ <b>Balance: {value}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-100", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')

    return ConversationHandler.END

async def handle_trailing_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    current_account = trading_bot.get_current_account(user_id)
    try:
        value = float(update.message.text)
        if value <= 0 or value > 50:
            raise ValueError("out of range")
        config.trailing_activation_percent = value
        # Persist to database
        try:
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, trailing_activation_percent=value)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist trailing activation: {e}")
        await update.message.reply_text(f"✅ <b>Trailing Activation:</b> {value}%", parse_mode='HTML')
    except Exception:
        await update.message.reply_text("❌ Invalid percentage!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_trailing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    current_account = trading_bot.get_current_account(user_id)
    try:
        value = float(update.message.text)
        if value <= 0 or value > 50:
            raise ValueError("out of range")
        config.trailing_callback_percent = value
        # Persist to database
        try:
            if current_account:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, trailing_callback_percent=value)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist trailing callback: {e}")
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
        await update.message.reply_text("❌ No channels configured. Open 📡 Channels in the account.", parse_mode='HTML')
        return

    await update.message.reply_text("🚀 <b>Starting...</b>", parse_mode='HTML')

    success = await trading_bot.start_monitoring(user_id, context.bot)

    if success:
        trading_bot.monitoring_status[user_id] = True
        status_msg = (
            f"✅ <b>MONITORING STARTED!</b>\n\n"
            f"📡 Monitoring: <b>{len(config.monitored_channels)}</b> channels\n"
            f"⚙️ Settings: {'Signal' if config.use_signal_settings else 'Bot'}\n"
            f"📊 SL/TP: {'ON' if config.create_sl_tp else 'OFF'}\n"
            f"🔄 OCO: Auto-cancel enabled\n"
            f"🔗 Webhook: {'ENABLED' if config.make_webhook_enabled else 'DISABLED'}\n\n"
            f"🎯 Ready to trade!"
        )

        await update.message.reply_text(status_msg, parse_mode='HTML')
        # Ensure OCO monitor is running
        if not trading_bot.order_monitor_running:
            asyncio.create_task(trading_bot.monitor_orders(context.bot))
    else:
        await update.message.reply_text("❌ Failed to start!", parse_mode='HTML')

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy stop monitoring function - stops all accounts for the user"""
    user_id = update.effective_user.id
    
    # Stop all accounts for this user
    accs = trading_bot.enhanced_db.get_user_accounts(user_id)
    stopped_count = 0
    
    for acc in accs:
        try:
            # Stop monitoring for this account
            trading_bot.account_monitoring_status[acc.account_id] = False
            
            # Stop account-specific monitoring task
            if acc.account_id in trading_bot.monitoring_tasks:
                task = trading_bot.monitoring_tasks[acc.account_id]
                if not task.done():
                    task.cancel()
                del trading_bot.monitoring_tasks[acc.account_id]
            
            stopped_count += 1
        except Exception as e:
            logger.error(f"Error stopping {acc.account_name}: {e}")
    
    # Update legacy flags
    trading_bot.active_monitoring[user_id] = False
    trading_bot.monitoring_status[user_id] = False
    trading_bot.order_monitor_running = False

    await update.message.reply_text(f"🛑 <b>Monitoring stopped!</b>\n\nStopped {stopped_count} account(s).", parse_mode='HTML')

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
    current_account = trading_bot.get_current_account(user_id)

    try:
        amount = float(update.message.text)
        if amount > 0:
            config.fixed_usdt_amount = amount
            try:
                if current_account:
                    trading_bot.enhanced_db.update_account_settings(current_account.account_id, fixed_usdt_amount=amount, use_percentage_balance=False)
            except Exception as e:
                logger.warning(f"⚠️ Failed to persist usdt amount: {e}")
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
            render_trading_config_text(user_id),
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
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_account_take_profit_levels(acc.account_id, config.custom_take_profits)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist TP clear: {e}")
        
        tp_keyboard = [
            [InlineKeyboardButton("➕ Add Level", callback_data="add_tp_level")],
            [InlineKeyboardButton("🔄 Reset Default", callback_data="reset_tp_default")],
            [InlineKeyboardButton("✅ Done", callback_data="tp_config_done")]
        ]
        
        await query.edit_message_text(
            "🗑️ <b>All take profit levels cleared!</b>\n\nAdd new levels or reset to default.",
            reply_markup=InlineKeyboardMarkup(tp_keyboard),
            parse_mode='HTML'
        )
        return WAITING_TP_CONFIG

    elif query.data == "reset_tp_default":
        config.custom_take_profits = [
            TakeProfitLevel(1.0, 50.0),
            TakeProfitLevel(2.5, 50.0),
            TakeProfitLevel(5.0, 100.0)
        ]
        try:
            acc = trading_bot.get_current_account(user_id)
            if acc:
                trading_bot.enhanced_db.update_account_take_profit_levels(acc.account_id, config.custom_take_profits)
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist TP reset: {e}")
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
    current_account = trading_bot.get_current_account(user_id)
    
    try:
        close_percentage = float(update.message.text)
        if 1 <= close_percentage <= 100:
            tp_percentage = context.user_data.get('tp_percentage', 1.0)
            
            # Add the new take profit level
            new_tp = TakeProfitLevel(tp_percentage, close_percentage)
            config.custom_take_profits.append(new_tp)
            
            # Sort by percentage
            config.custom_take_profits.sort(key=lambda x: x.percentage)
            # Persist for current account if available
            try:
                if current_account:
                    trading_bot.enhanced_db.update_account_take_profit_levels(current_account.account_id, config.custom_take_profits)
            except Exception as e:
                logger.warning(f"⚠️ Failed to persist TP levels: {e}")
            
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
    """Handle BingX secret key input and create account (using default Telegram credentials)"""
    secret_key = update.message.text.strip()
    
    # Create account configuration using default Telegram credentials
    account_id = str(uuid.uuid4())
    user_id = update.effective_user.id
    
    # Get default settings
    defaults = trading_bot.enhanced_db.get_default_settings()
    
    account = AccountConfig(
        account_id=account_id,
        account_name=context.user_data['account_name'],
        bingx_api_key=context.user_data['bingx_api_key'],
        bingx_secret_key=secret_key,
        telegram_api_id=DEFAULT_TELEGRAM_API_ID,
        telegram_api_hash=DEFAULT_TELEGRAM_API_HASH,
        phone="",  # Not required when using default credentials
        user_id=user_id,
        is_active=True,
        created_at=datetime.now().isoformat(),
        last_used=datetime.now().isoformat(),
        leverage=int(defaults.get('leverage', DEFAULT_SETTINGS['leverage'])),
        risk_percentage=float(defaults.get('risk_percentage', DEFAULT_SETTINGS['risk_percentage'])),
        use_percentage_balance=True,
        monitored_channels=[],
        signal_channels=[]
    )
    
    # Save to database
    if trading_bot.enhanced_db.create_account(account):
        await update.message.reply_text(
            f"🎉 <b>Account Created Successfully!</b>\n\n"
            f"Account: <b>{account.account_name}</b>\n"
            f"ID: <code>{account_id}</code>\n\n"
            f"Default settings applied:\n"
            f"⚡ Leverage: {account.leverage}x\n"
            f"💰 Risk: {account.risk_percentage}%\n\n"
            f"You can now:\n"
            f"• Configure account settings\n"
            f"• Add channels to monitor\n"
            f"• Start receiving signals",
            parse_mode='HTML',
            reply_markup=build_accounts_menu(trading_bot.enhanced_db.get_all_accounts())
        )
    else:
        await update.message.reply_text(
            "❌ Failed to create account. Please try again.",
            parse_mode='HTML'
        )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

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
    user_id = update.effective_user.id
    account = AccountConfig(
        account_id=account_id,
        account_name=context.user_data['account_name'],
        bingx_api_key=context.user_data['bingx_api_key'],
        bingx_secret_key=context.user_data['bingx_secret_key'],
        telegram_api_id=context.user_data['telegram_api_id'],
        telegram_api_hash=context.user_data['telegram_api_hash'],
        phone=phone,
        user_id=user_id
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

async def authorize_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the authorization process for a Telegram account"""
    user_id = update.effective_user.id
    
    # Get the current account
    current_account = trading_bot.get_current_account(user_id)
    if not current_account:
        await update.message.reply_text(
            "❌ <b>No Account Selected</b>\n\n"
            "Please select an account first from the Accounts menu.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    # Store account info in context
    context.user_data['auth_account_id'] = current_account.account_id
    context.user_data['auth_phone'] = current_account.phone
    
    # Get or create Telethon client
    config = trading_bot.get_user_config(user_id)
    account_id = current_account.account_id
    
    # Setup client if not exists
    if account_id not in trading_bot.user_monitoring_clients:
        await trading_bot.setup_telethon_client(config)
    
    telethon_client = trading_bot.user_monitoring_clients.get(account_id)
    if not telethon_client:
        await update.message.reply_text(
            "❌ <b>Failed to initialize Telegram client</b>\n\n"
            "Please try again or contact support.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    # Check if already authorized
    try:
        if await telethon_client.is_user_authorized():
            await update.message.reply_text(
                "✅ <b>Already Authorized</b>\n\n"
                "This account is already authorized with Telegram.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
    
    # Send verification code
    try:
        phone = current_account.phone
        await update.message.reply_text(
            f"📱 <b>Sending verification code to {phone}...</b>",
            parse_mode='HTML'
        )
        
        result = await telethon_client.send_code_request(phone)
        context.user_data['auth_phone_code_hash'] = result.phone_code_hash
        
        await update.message.reply_text(
            "✉️ <b>Verification Code Sent!</b>\n\n"
            f"A verification code has been sent to <code>{phone}</code>\n\n"
            "Please enter the code you received:",
            parse_mode='HTML'
        )
        
        return WAITING_AUTH_CODE
        
    except Exception as e:
        logger.error(f"Error sending code: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            f"❌ <b>Error Sending Code</b>\n\n"
            f"Error: {str(e)}\n\n"
            "Please check your phone number and try again.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the verification code input"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    account_id = context.user_data.get('auth_account_id')
    phone = context.user_data.get('auth_phone')
    phone_code_hash = context.user_data.get('auth_phone_code_hash')
    
    if not all([account_id, phone, phone_code_hash]):
        await update.message.reply_text(
            "❌ <b>Session Expired</b>\n\n"
            "Please start the authorization process again.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    telethon_client = trading_bot.user_monitoring_clients.get(account_id)
    if not telethon_client:
        await update.message.reply_text(
            "❌ <b>Client Not Found</b>\n\n"
            "Please start the authorization process again.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    try:
        await update.message.reply_text(
            "🔄 <b>Verifying code...</b>",
            parse_mode='HTML'
        )
        
        # Sign in with the code
        await telethon_client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        
        # Check if authorized
        if await telethon_client.is_user_authorized():
            await update.message.reply_text(
                "🎉 <b>Authorization Successful!</b>\n\n"
                "Your Telegram account is now authorized.\n"
                "You can now access channels and receive signals.\n\n"
                "Try using 📡 Channels to see your channels!",
                parse_mode='HTML'
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "❌ <b>Authorization Failed</b>\n\n"
                "Something went wrong. Please try again.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
            
    except SessionPasswordNeededError:
        # 2FA is enabled, need password
        await update.message.reply_text(
            "🔐 <b>Two-Factor Authentication Enabled</b>\n\n"
            "Please enter your 2FA password:",
            parse_mode='HTML'
        )
        return WAITING_AUTH_PASSWORD
        
    except Exception as e:
        logger.error(f"Error signing in: {e}")
        logger.error(traceback.format_exc())
        error_msg = str(e)
        
        if "PHONE_CODE_INVALID" in error_msg:
            await update.message.reply_text(
                "❌ <b>Invalid Code</b>\n\n"
                "The verification code you entered is incorrect.\n"
                "Please start the authorization process again.",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                f"❌ <b>Error During Authorization</b>\n\n"
                f"Error: {error_msg}\n\n"
                "Please try again or contact support.",
                parse_mode='HTML'
            )
        return ConversationHandler.END

async def handle_auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password input"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    
    account_id = context.user_data.get('auth_account_id')
    
    if not account_id:
        await update.message.reply_text(
            "❌ <b>Session Expired</b>\n\n"
            "Please start the authorization process again.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    telethon_client = trading_bot.user_monitoring_clients.get(account_id)
    if not telethon_client:
        await update.message.reply_text(
            "❌ <b>Client Not Found</b>\n\n"
            "Please start the authorization process again.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    try:
        await update.message.reply_text(
            "🔄 <b>Verifying password...</b>",
            parse_mode='HTML'
        )
        
        # Sign in with password
        await telethon_client.sign_in(password=password)
        
        # Check if authorized
        if await telethon_client.is_user_authorized():
            await update.message.reply_text(
                "🎉 <b>Authorization Successful!</b>\n\n"
                "Your Telegram account is now authorized.\n"
                "You can now access channels and receive signals.\n\n"
                "Try using 📡 Channels to see your channels!",
                parse_mode='HTML'
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "❌ <b>Authorization Failed</b>\n\n"
                "Something went wrong. Please try again.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error with 2FA: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            f"❌ <b>Error During Authorization</b>\n\n"
            f"Error: {str(e)}\n\n"
            "Please try again or contact support.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

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

# ================== COMPREHENSIVE SETTINGS HANDLERS ==================

async def handle_trading_type_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle trading type setting (spot vs futures)"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    current_type = getattr(current_account, 'trading_type', 'swap')
    current_display = "🔮 Futures/Swap" if current_type == 'swap' else "💱 Spot"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 Futures/Swap", callback_data="set_trading_type_swap")],
        [InlineKeyboardButton("💱 Spot", callback_data="set_trading_type_spot")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")]
    ])
    
    await update.message.reply_text(
        f"🔮 <b>Trading Type</b>\n\n"
        f"Current: <b>{current_display}</b>\n\n"
        f"⚠️ <b>Important:</b> Make sure your BingX API key has the correct permissions:\n"
        f"• Futures/Swap: Requires <b>Futures Trading</b> permission\n"
        f"• Spot: Requires <b>Spot Trading</b> permission\n\n"
        f"Select trading type:",
        parse_mode='HTML',
        reply_markup=keyboard
    )

async def handle_leverage_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle leverage setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    await update.message.reply_text(
        f"⚡ <b>Leverage Setting</b>\n\n"
        f"Current: <b>{current_account.leverage}x</b>\n\n"
        f"Enter new leverage (1-125):",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'WAIT_LEVERAGE'

async def handle_risk_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle risk percentage setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    await update.message.reply_text(
        f"💰 <b>Risk Percentage</b>\n\n"
        f"Current: <b>{current_account.risk_percentage}%</b>\n\n"
        f"Enter new risk percentage (0.1-100):",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'WAIT_RISK'

async def handle_trade_amount_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle trade amount setting with inline buttons"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Percentage", callback_data="trade_amount_percentage")],
        [InlineKeyboardButton("💵 Fixed USDT", callback_data="trade_amount_fixed")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")]
    ])
    
    balance_mode = "Percentage" if current_account.use_percentage_balance else "Fixed USDT"
    balance_value = f"{current_account.balance_percentage}%" if current_account.use_percentage_balance else f"${current_account.fixed_usdt_amount}"
    
    await update.message.reply_text(
        f"💵 <b>Trade Amount Setting</b>\n\n"
        f"Current: <b>{balance_value}</b> ({balance_mode})\n\n"
        f"Choose mode:",
        parse_mode='HTML',
        reply_markup=keyboard
    )

async def handle_take_profits_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle take profits levels setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    msg = f"🎯 <b>Take Profit Levels</b>\n\n"
    
    if current_account.take_profit_levels:
        for i, tp in enumerate(current_account.take_profit_levels, 1):
            msg += f"{i}. <b>{tp.percentage}%</b> - Close <b>{tp.close_percentage}%</b>\n"
    else:
        msg += "No levels configured\n"
    
    msg += f"\nCommands:\n"
    msg += f"• <code>tp add 2.0 50</code> - Add 2% level, close 50%\n"
    msg += f"• <code>tp edit 1 3.0 75</code> - Edit level 1 to 3%, close 75%\n"
    msg += f"• <code>tp remove 1</code> - Remove level 1\n"
    msg += f"• <code>tp clear</code> - Clear all levels"
    
    await update.message.reply_text(msg, parse_mode='HTML')

async def handle_stop_loss_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stop loss levels setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    msg = f"🛡️ <b>Stop Loss Levels</b>\n\n"
    
    if current_account.stop_loss_levels:
        for i, sl in enumerate(current_account.stop_loss_levels, 1):
            msg += f"{i}. <b>{sl.percentage}%</b> - Close <b>{sl.close_percentage}%</b>\n"
    else:
        msg += "No levels configured\n"
    
    msg += f"\nCommands:\n"
    msg += f"• <code>sl add -5.0 100</code> - Add -5% level, close 100%\n"
    msg += f"• <code>sl edit 1 -3.0 100</code> - Edit level 1 to -3%, close 100%\n"
    msg += f"• <code>sl remove 1</code> - Remove level 1\n"
    msg += f"• <code>sl clear</code> - Clear all levels"
    
    await update.message.reply_text(msg, parse_mode='HTML')

async def handle_cooldown_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cooldown setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    cooldown_enabled = getattr(current_account, 'cooldown_enabled', False)
    cooldown_hours = getattr(current_account, 'cooldown_hours', 24)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Enable", callback_data="cooldown_enable")],
        [InlineKeyboardButton("🔴 Disable", callback_data="cooldown_disable")],
        [InlineKeyboardButton("⏰ Set Hours", callback_data="cooldown_hours")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")]
    ])
    
    status = "🟢 ON" if cooldown_enabled else "🔴 OFF"
    
    await update.message.reply_text(
        f"⏰ <b>Cooldown Setting</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Duration: <b>{cooldown_hours} hours</b>\n\n"
        f"Cooldown prevents multiple trades on the same symbol within the specified time period.",
        parse_mode='HTML',
        reply_markup=keyboard
    )

async def handle_channels_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channels setting"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    msg = f"📡 <b>Monitored Channels</b>\n\n"
    msg += f"Total: <b>{len(current_account.monitored_channels)}</b>\n\n"
    
    if current_account.monitored_channels:
        msg += "Current channels:\n"
        for i, channel_id in enumerate(current_account.monitored_channels, 1):
            msg += f"{i}. <code>{channel_id}</code>\n"
    else:
        msg += "No channels configured\n"
    
    msg += f"\nUse 📡 Channels button to manage channels."
    
    await update.message.reply_text(msg, parse_mode='HTML')

async def handle_advanced_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle advanced settings"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎯 Signal Settings: {'ON' if current_account.use_signal_settings else 'OFF'}", callback_data="toggle_signal_settings")],
        [InlineKeyboardButton(f"🛡️ SL/TP Orders: {'ON' if current_account.create_sl_tp else 'OFF'}", callback_data="toggle_sl_tp")],
        [InlineKeyboardButton(f"🔗 Webhook: {'ON' if current_account.make_webhook_enabled else 'OFF'}", callback_data="toggle_webhook")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_settings")]
    ])
    
    await update.message.reply_text(
        f"🔧 <b>Advanced Settings</b>\n\n"
        f"Configure advanced trading features:",
        parse_mode='HTML',
        reply_markup=keyboard
    )

async def handle_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account deletion"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Confirm Delete", callback_data=f"delete_account_confirm_{current_account.account_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_to_settings")]
    ])
    
    await update.message.reply_text(
        f"🗑️ <b>Delete Account</b>\n\n"
        f"⚠️ <b>WARNING:</b> This will permanently delete:\n"
        f"• Account: <b>{current_account.account_name}</b>\n"
        f"• All trading history\n"
        f"• All settings\n"
        f"• All monitored channels\n\n"
        f"This action cannot be undone!",
        parse_mode='HTML',
        reply_markup=keyboard
    )

async def handle_rename_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account renaming"""
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    await update.message.reply_text(
        f"✏️ <b>Rename Account</b>\n\n"
        f"Current name: <b>{current_account.account_name}</b>\n\n"
        f"Enter new account name:",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'WAIT_ACCOUNT_RENAME'

# ================== CALLBACK QUERY HANDLERS ==================

async def handle_settings_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from settings"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    current_account = trading_bot.get_current_account(user_id)
    
    if not current_account:
        await query.edit_message_text("❌ No account selected", parse_mode='HTML')
        return
    
    data = query.data
    
    if data == "back_to_settings":
        await handle_settings_menu(update, context)
    
    elif data == "trade_amount_percentage":
        await query.edit_message_text(
            f"💰 <b>Percentage Mode</b>\n\n"
            f"Enter percentage (1-100):",
            parse_mode='HTML'
        )
        context.user_data['state'] = 'WAIT_TRADE_AMOUNT_PERCENTAGE'
    
    elif data == "trade_amount_fixed":
        await query.edit_message_text(
            f"💵 <b>Fixed USDT Mode</b>\n\n"
            f"Enter USDT amount:",
            parse_mode='HTML'
        )
        context.user_data['state'] = 'WAIT_TRADE_AMOUNT_FIXED'
    
    elif data == "cooldown_enable":
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, cooldown_enabled=True)
        await query.edit_message_text(
            f"✅ <b>Cooldown Enabled</b>\n\n"
            f"Cooldown is now active for this account.",
            parse_mode='HTML'
        )
    
    elif data == "cooldown_disable":
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, cooldown_enabled=False)
        await query.edit_message_text(
            f"✅ <b>Cooldown Disabled</b>\n\n"
            f"Cooldown is now inactive for this account.",
            parse_mode='HTML'
        )
    
    elif data == "cooldown_hours":
        await query.edit_message_text(
            f"⏰ <b>Set Cooldown Hours</b>\n\n"
            f"Enter hours (1-168):",
            parse_mode='HTML'
        )
        context.user_data['state'] = 'WAIT_COOLDOWN_HOURS'
    
    elif data == "set_trading_type_swap":
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, trading_type='swap')
        # Clear cached exchange to force recreation with new type
        if current_account.account_id in trading_bot.account_exchanges:
            del trading_bot.account_exchanges[current_account.account_id]
        await query.edit_message_text(
            f"✅ <b>Trading Type Updated</b>\n\n"
            f"Now using: <b>🔮 Futures/Swap</b>\n\n"
            f"⚠️ Make sure your BingX API key has <b>Futures Trading</b> permission enabled.",
            parse_mode='HTML'
        )
    
    elif data == "set_trading_type_spot":
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, trading_type='spot')
        # Clear cached exchange to force recreation with new type
        if current_account.account_id in trading_bot.account_exchanges:
            del trading_bot.account_exchanges[current_account.account_id]
        await query.edit_message_text(
            f"✅ <b>Trading Type Updated</b>\n\n"
            f"Now using: <b>💱 Spot</b>\n\n"
            f"⚠️ Make sure your BingX API key has <b>Spot Trading</b> permission enabled.",
            parse_mode='HTML'
        )
    
    elif data == "toggle_signal_settings":
        new_value = not current_account.use_signal_settings
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, use_signal_settings=new_value)
        await query.edit_message_text(
            f"✅ <b>Signal Settings {'Enabled' if new_value else 'Disabled'}</b>",
            parse_mode='HTML'
        )
    
    elif data == "toggle_sl_tp":
        new_value = not current_account.create_sl_tp
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, create_sl_tp=new_value)
        await query.edit_message_text(
            f"✅ <b>SL/TP Orders {'Enabled' if new_value else 'Disabled'}</b>",
            parse_mode='HTML'
        )
    
    elif data == "toggle_webhook":
        new_value = not current_account.make_webhook_enabled
        trading_bot.enhanced_db.update_account_settings(current_account.account_id, make_webhook_enabled=new_value)
        await query.edit_message_text(
            f"✅ <b>Webhook {'Enabled' if new_value else 'Disabled'}</b>",
            parse_mode='HTML'
        )
    
    elif data.startswith("delete_account_confirm_"):
        account_id = data.split("_")[-1]
        if account_id == current_account.account_id:
            # Perform actual deletion
            success = trading_bot.enhanced_db.soft_delete_account(account_id)
            if success:
                await query.edit_message_text(
                    f"✅ <b>Account Deleted</b>\n\n"
                    f"Account '{current_account.account_name}' has been deleted.",
                    parse_mode='HTML'
                )
                # Clear current account
                trading_bot.current_accounts[user_id] = None
            else:
                await query.edit_message_text(
                    f"❌ <b>Deletion Failed</b>\n\n"
                    f"Could not delete account. Please try again.",
                    parse_mode='HTML'
                )
    
    elif data == "show_history" or data == "history" or data == "account_history":
        # Handle inline history button - show trade history for current account (only closed trades)
        try:
            trade_history = trading_bot.enhanced_db.get_trade_history(current_account.account_id, limit=20, only_closed=True)
            
            if not trade_history:
                # Show "no history" message with back button to return to settings
                back_keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Settings", callback_data="back_to_settings")
                ]])
                await query.edit_message_text(
                    f"📋 <b>No Trade History</b>\n\n"
                    f"Account: {current_account.account_name}\n\n"
                    f"You haven't made any trades yet on this account.",
                    parse_mode='HTML',
                    reply_markup=back_keyboard
                )
            else:
                # Resolve channel names for all channels first
                channel_name_map = {}
                unique_channels = set(t.channel_id for t in trade_history if t.channel_id)
                for ch_id in unique_channels:
                    try:
                        channel_name_map[ch_id] = await trading_bot.get_channel_display_name(ch_id, user_id)
                    except Exception as e:
                        logger.warning(f"⚠️ Could not resolve channel name for {ch_id}: {e}")
                        channel_name_map[ch_id] = f"Channel {ch_id}"
                
                # Aggregate per-channel stats
                channel_stats = {}
                total_trades = len(trade_history)
                wins = 0
                for t in trade_history:
                    ch = t.channel_id or 'unknown'
                    cs = channel_stats.setdefault(ch, {'count': 0, 'wins': 0, 'pnl': 0.0})
                    cs['count'] += 1
                    try:
                        cs['pnl'] += float(t.pnl or 0)
                        if float(t.pnl or 0) > 0:
                            cs['wins'] += 1
                            wins += 1
                    except Exception:
                        pass

                text = f"📋 <b>Trade History - {current_account.account_name}</b>\n\n"
                text += f"Recent trades ({len(trade_history)}):\n\n"
                
                trades_shown = 0
                for trade in trade_history:
                    # Check message length to avoid exceeding Telegram's limit
                    if len(text) > 3200:  # Leave room for channel stats
                        text += f"<i>... and {len(trade_history) - trades_shown} more</i>\n\n"
                        break
                    
                    status_emoji = "🟢" if trade.status == "OPEN" else "🔴" if trade.status == "CLOSED" else "🟡"
                    ch = trade.channel_id or ''
                    ch_name = channel_name_map.get(ch, 'Unknown') if ch else ''
                    # Truncate long channel names
                    if len(ch_name) > 15:
                        ch_name = ch_name[:12] + "..."
                    ch_line = f" | {ch_name}" if ch_name else ""
                    
                    text += f"{status_emoji} <b>{trade.symbol}</b> {trade.side}{ch_line}\n"
                    text += f"Entry: {trade.entry_price} | PnL: {trade.pnl if trade.pnl else '0'}\n\n"
                    trades_shown += 1

                # Append per-channel analytics (compact)
                if channel_stats and len(text) < 3500:
                    text += "📡 <b>Per-Channel:</b>\n"
                    for ch, cs in list(channel_stats.items())[:5]:
                        if len(text) > 3800:
                            break
                        ch_name = channel_name_map.get(ch, ch) if ch != 'unknown' else 'Unknown'
                        if len(ch_name) > 15:
                            ch_name = ch_name[:12] + "..."
                        wr = (cs['wins']/cs['count']*100) if cs['count'] else 0
                        text += f"• {ch_name}: {cs['count']} trades, {wr:.0f}% WR, {cs['pnl']:.1f} PnL\n"
                    if total_trades:
                        overall_wr = wins/total_trades*100
                        text += f"\n📊 Overall: {overall_wr:.1f}% WR\n"

                # Ensure we don't exceed Telegram's limit for inline messages
                if len(text) > 4000:
                    text = text[:3900] + "\n\n<i>... (truncated)</i>"

                # Add back button to return to settings
                back_keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Settings", callback_data="back_to_settings")
                ]])
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=back_keyboard)
        except Exception as e:
            logger.error(f"❌ Error in inline history callback: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                "❌ <b>Error Loading History</b>\n\n"
                f"An error occurred while loading trade history: {str(e)}\n\n"
                "Please try again using the 📋 History button from the main menu.",
                parse_mode='HTML'
            )

# ================== TEXT INPUT HANDLERS ==================

async def handle_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text inputs for settings"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state')
    
    # If we are not in a specific input state, delegate to the main menu handler
    # so normal navigation buttons work without requiring a selected account
    if not state:
        await handle_main_menu(update, context)
        return
    
    # From here on, we are in a settings input flow which requires a current account
    current_account = trading_bot.get_current_account(user_id)
    if not current_account:
        await update.message.reply_text("❌ No account selected", parse_mode='HTML')
        return
    
    if state == 'WAIT_LEVERAGE':
        try:
            leverage = int(text)
            if 1 <= leverage <= 125:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, leverage=leverage)
                await update.message.reply_text(
                    f"✅ <b>Leverage Updated</b>\n\n"
                    f"New leverage: <b>{leverage}x</b>",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Leverage must be between 1 and 125", parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number", parse_mode='HTML')
    
    elif state == 'WAIT_RISK':
        try:
            risk = float(text)
            if 0.1 <= risk <= 100:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, risk_percentage=risk)
                await update.message.reply_text(
                    f"✅ <b>Risk Updated</b>\n\n"
                    f"New risk: <b>{risk}%</b>",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Risk must be between 0.1 and 100", parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number", parse_mode='HTML')
    
    elif state == 'WAIT_TRADE_AMOUNT_PERCENTAGE':
        try:
            percentage = float(text)
            if 1 <= percentage <= 100:
                trading_bot.enhanced_db.update_account_settings(
                    current_account.account_id, 
                    use_percentage_balance=True,
                    balance_percentage=percentage
                )
                await update.message.reply_text(
                    f"✅ <b>Trade Amount Updated</b>\n\n"
                    f"New amount: <b>{percentage}%</b> of balance",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Percentage must be between 1 and 100", parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number", parse_mode='HTML')
    
    elif state == 'WAIT_TRADE_AMOUNT_FIXED':
        try:
            amount = float(text)
            if amount > 0:
                trading_bot.enhanced_db.update_account_settings(
                    current_account.account_id, 
                    use_percentage_balance=False,
                    fixed_usdt_amount=amount
                )
                await update.message.reply_text(
                    f"✅ <b>Trade Amount Updated</b>\n\n"
                    f"New amount: <b>${amount}</b> USDT",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Amount must be greater than 0", parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number", parse_mode='HTML')
    
    elif state == 'WAIT_COOLDOWN_HOURS':
        try:
            hours = int(text)
            if 1 <= hours <= 168:
                trading_bot.enhanced_db.update_account_settings(current_account.account_id, cooldown_hours=hours)
                await update.message.reply_text(
                    f"✅ <b>Cooldown Hours Updated</b>\n\n"
                    f"New duration: <b>{hours} hours</b>",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Hours must be between 1 and 168", parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number", parse_mode='HTML')
    
    elif state == 'WAIT_ACCOUNT_RENAME':
        if len(text) > 0 and len(text) <= 50:
            success = trading_bot.enhanced_db.update_account_name(current_account.account_id, text)
            if success:
                await update.message.reply_text(
                    f"✅ <b>Account Renamed</b>\n\n"
                    f"New name: <b>{text}</b>",
                    parse_mode='HTML',
                    reply_markup=build_settings_menu()
                )
            else:
                await update.message.reply_text("❌ Failed to rename account", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Name must be 1-50 characters", parse_mode='HTML')
    
    # Clear state
    context.user_data.pop('state', None)

# ================== CONVERSATION HANDLERS ==================

async def settings_button_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for settings button press"""
    user_id = update.effective_user.id
    
    # Check if user has a current account (either in context or in bot state)
    current_account = trading_bot.get_current_account(user_id)
    if update.message and update.message.text == "⚙️ Settings":
        if current_account:
            # Ensure context.user_data has the current account ID for other parts of the code
            context.user_data['current_account_id'] = current_account.account_id
            context.user_data['current_account_name'] = current_account.account_name
            keyboard_markup = create_settings_keyboard(user_id)
            await update.message.reply_text(
                render_trading_config_text(user_id),
                reply_markup=keyboard_markup,
                parse_mode='HTML'
            )
            return WAITING_SETTINGS_SOURCE
        else:
            await update.message.reply_text(
                "❌ <b>No Account Selected</b>\n\n"
                "Please select an account first from the Accounts menu.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
    return ConversationHandler.END

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

async def channels_button_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for channels button press"""
    user_id = update.effective_user.id
    
    # Check if user has a current account (either in context or in bot state)
    current_account = trading_bot.get_current_account(user_id)
    if update.message and update.message.text == "📡 Channels":
        if current_account:
            # Ensure context.user_data has the current account ID for other parts of the code
            context.user_data['current_account_id'] = current_account.account_id
            context.user_data['current_account_name'] = current_account.account_name
            return await setup_channels(update, context)
        else:
            await update.message.reply_text(
                "❌ <b>No Account Selected</b>\n\n"
                "Please select an account first from the Accounts menu.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
    return ConversationHandler.END

channel_conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r'^📡 Channels$'), channels_button_entry)
    ],
    states={
        WAITING_CHANNEL_SELECTION: [
            CallbackQueryHandler(handle_channel_selection),
            MessageHandler(filters.FORWARDED, handle_channel_selection)
        ],
        WAITING_MANUAL_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_channel)],
        WAITING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_link)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    per_user=True,
    per_chat=True,
)

trading_conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r'^⚙️ Settings$'), settings_button_entry)
    ],
    states={
        WAITING_SETTINGS_SOURCE: [CallbackQueryHandler(handle_trading_settings)],
        WAITING_LEVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leverage)],
        WAITING_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stop_loss)],
        WAITING_TAKE_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_take_profit)],
        WAITING_BALANCE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_balance_percent)],
        WAITING_TRAILING_ACTIVATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_activation)],
        WAITING_TRAILING_CALLBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_callback)],
        WAITING_USDT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_amount)],
        WAITING_ACCOUNT_SETTINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_settings_text)],
        WAITING_TP_CONFIG: [CallbackQueryHandler(handle_tp_config)],
        WAITING_TP_LEVEL_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_level_percent)],
        WAITING_TP_LEVEL_CLOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_level_close)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    per_user=True,
    per_chat=True,
)

# Enhanced account conversation handler
account_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r'^➕ Add Account$'), add_account)],
    states={
        WAITING_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_name)],
        WAITING_ACCOUNT_BINGX_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_bingx_key)],
        WAITING_ACCOUNT_BINGX_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_bingx_secret)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# Authorization conversation handler
auth_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('authorize_account', authorize_account_start)],
    states={
        WAITING_AUTH_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code)],
        WAITING_AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_password)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    per_user=True,
    per_chat=True,
)

# ================== UTILITY FUNCTIONS ==================

def kill_existing_bot_instances():
    """Kill any existing bot instances to prevent conflicts"""
    try:
        # Find processes running testchannels.py
        result = subprocess.run(['pgrep', '-f', 'testchannels.py'], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid and pid != str(os.getpid()):  # Don't kill ourselves
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        print(f"🔄 Killed existing bot instance (PID: {pid})")
                    except ProcessLookupError:
                        pass  # Process already dead
                    except Exception as e:
                        print(f"⚠️ Could not kill process {pid}: {e}")
    except Exception as e:
        print(f"⚠️ Could not check for existing instances: {e}")

# ================== MAIN ==================

async def auto_start_monitoring(application):
    """Automatically start monitoring for all accounts with configured channels on bot startup"""
    try:
        logger.info("🔄 Auto-start monitoring: Checking for accounts with monitored channels...")
        accounts = trading_bot.enhanced_db.get_all_accounts()
        
        if not accounts:
            logger.info("ℹ️ No accounts found in database")
            return
        
        logger.info(f"✅ Retrieved {len(accounts)} accounts from database")
        
        for account in accounts:
            try:
                # Skip accounts without a user_id (not yet associated with a user)
                if not account.user_id or account.user_id == 0:
                    logger.info(f"⏭️ Skipping account {account.account_name} ({account.account_id[:8]}...) - no user associated yet")
                    continue
                
                if account.monitored_channels and len(account.monitored_channels) > 0:
                    logger.info(f"🚀 Auto-starting monitoring for user {account.user_id} with {len(account.monitored_channels)} channels")
                    logger.info(f"   Account: {account.account_name}")
                    logger.info(f"   Channels: {account.monitored_channels}")
                    
                # Set the current account for this user and bind exchange client
                trading_bot.set_current_account(account.user_id, account.account_id)
                trading_bot.enhanced_db.set_app_setting(f'current_account_{account.user_id}', account.account_id)
                
                # Use the application's bot instance
                bot_app = application.bot
                trading_bot.bot_instances[account.user_id] = bot_app
                
                # Start monitoring with timeout to prevent hanging
                try:
                    success = await asyncio.wait_for(
                        trading_bot.start_monitoring(account.user_id, bot_app),
                        timeout=30.0  # 30 second timeout
                    )
                    
                    if success:
                        trading_bot.monitoring_status[account.user_id] = True
                        trading_bot.account_monitoring_status[account.account_id] = True
                        logger.info(f"✅ Auto-started monitoring for account {account.account_id}")
                        
                        # Send notification to user
                        try:
                            await bot_app.send_message(
                                chat_id=account.user_id,
                                text=f"🤖 <b>Bot Started</b>\n\n✅ Auto-started monitoring for account <b>{account.account_name}</b>\n📡 Monitoring {len(account.monitored_channels)} channel(s)\n\n🔍 Ready to detect signals!",
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ Could not send start notification to user {account.user_id}: {e}")
                    else:
                        logger.error(f"❌ Failed to auto-start monitoring for user {account.user_id}")
                except asyncio.TimeoutError:
                    logger.error(f"⏱️ Timeout starting monitoring for account {account.account_id} - continuing anyway")
                except Exception as monitor_err:
                    logger.error(f"❌ Error starting monitoring for account {account.account_id}: {monitor_err}")
                    logger.error(traceback.format_exc())
                    
            except Exception as e:
                logger.error(f"❌ Error auto-starting monitoring for account {account.account_id}: {e}")
                logger.error(traceback.format_exc())
        
        logger.info("✅ Auto-start monitoring completed")
        
    except Exception as e:
        logger.error(f"❌ Error in auto_start_monitoring: {e}")
        logger.error(traceback.format_exc())

def main():
    """Start the enhanced bot with static button interface"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # Kill any existing bot instances to prevent conflicts
    kill_existing_bot_instances()
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        # Register /start only; rest is button-driven
        application.add_handler(CommandHandler('start', start))

        # Conversation handlers (button-driven flows only)
        application.add_handler(account_conv_handler)
        application.add_handler(auth_conv_handler)
        application.add_handler(channel_conv_handler)
        application.add_handler(trading_conv_handler)
        
        # New comprehensive settings handlers
        application.add_handler(CallbackQueryHandler(handle_settings_callbacks))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_inputs))
        
        # No extra command handlers; only buttons and /start are active

        # Enhanced static button handler (catch-all for remaining messages)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu))

        print("🤖 Enhanced Multi-Account Trading Bot v5.0 Starting...")
        print(f"🔗 Webhook: {DEFAULT_WEBHOOK_URL}")
        print("🔐 PIN Protection: ENABLED")
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
        print("✅ FIXED: Auto-start monitoring on startup")
        print("✅ FIXED: Enhanced message detection logging")
        print("📊 Ready! Use PIN code to access")
        
        # Add error handler for conflicts
        async def error_handler(update, context):
            logger.error(f"Update {update} caused error {context.error}")
            if "Conflict" in str(context.error):
                print("⚠️ Bot instance conflict detected. Please stop other instances.")
            return True
        
        application.add_error_handler(error_handler)
        
        # Auto-start monitoring after bot initialization
        async def post_init(app):
            """Called after the bot starts"""
            try:
                logger.info("🚀 Bot initialized, starting auto-monitoring...")
                await auto_start_monitoring(app)
                logger.info("✅ Auto-monitoring initialization completed")
            except Exception as e:
                logger.error(f"❌ Error in post_init: {e}")
                logger.error(traceback.format_exc())
        
        application.post_init = post_init
        
        # Run polling with proper settings to keep bot alive
        print("🚀 Starting bot polling loop...")
        logger.info("🚀 Starting bot polling loop - bot will now run indefinitely")
        sys.stdout.flush()  # Ensure output is flushed
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
        # This should never be reached unless run_polling exits
        logger.warning("⚠️ Bot polling loop exited unexpectedly")
        print("⚠️ Bot polling loop exited - this should not happen")
        
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
        logger.info("🛑 Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        logger.error(f"❌ Fatal error in main: {e}")
        logger.error(traceback.format_exc())
        if "Conflict" in str(e):
            print("⚠️ Another bot instance is running. Please stop it first.")
        else:
            print("🔄 Retrying in 5 seconds...")
            import time
            time.sleep(5)
            main()  # Retry

if __name__ == '__main__':
    main()
