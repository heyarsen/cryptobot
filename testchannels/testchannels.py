#!/usr/bin/env python3
"""
Enhanced Multi-Account Trading Bot v6.0 - IMPROVED SETTINGS & CHANNEL MANAGEMENT
- Easy-to-understand settings display
- Flexible TP/SL configuration with multiple levels
- Multiple channel addition methods (list, ID, forward, link)
- Account renaming and deletion
- Real-time settings persistence
- Improved user experience
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
BOT_PIN_CODE = "496745"
DEFAULT_TELEGRAM_API_ID = '28270452'
DEFAULT_TELEGRAM_API_HASH = '8bb0aa3065dd515fb6e105f1fc60fdb6'
DEFAULT_BINANCE_API_KEY = 'ojMy5XVmKUFxfoAG1SwR2jCiYqYGuHfFb3CmM1tPv01rvtLcIQL68wTUwtU8mMijfaWc2aOPsiGZSSqg'
DEFAULT_BINANCE_API_SECRET = 'R26Tvlq8rRjK4HCqhG5EstMXGAqHr1B22DH3IuTRjHOiEanmIlCRPowDcOGH8oKDjnVypPM5fXUg3lbYhQ'
DEFAULT_WEBHOOK_URL = "https://hook.eu2.make.com/pnfx5xy1q8caxq4qc2yhmnrkmio1ixqj"

# Conversation states
(WAITING_PIN, WAITING_ACCOUNT_SELECT, WAITING_ACCOUNT_NAME, WAITING_ACCOUNT_RENAME,
 WAITING_BINGX_KEY, WAITING_BINGX_SECRET, WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_PHONE, WAITING_LEVERAGE, WAITING_RISK_PERCENT, WAITING_TP_PERCENT, 
 WAITING_TP_CLOSE_PERCENT, WAITING_SL_PERCENT, WAITING_CHANNEL_METHOD,
 WAITING_CHANNEL_ID, WAITING_CHANNEL_LINK, WAITING_CHANNEL_FORWARD,
 WAITING_BALANCE_MODE, WAITING_BALANCE_VALUE, WAITING_SETTING_CHOICE) = range(21)

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
class TakeProfitLevel:
    """Individual take profit level"""
    percentage: float  # Price percentage (e.g., 2.0 for 2%)
    close_percentage: float  # Position close percentage (e.g., 50.0 for 50%)
    
@dataclass
class StopLossLevel:
    """Individual stop loss level"""
    percentage: float
    close_percentage: float

@dataclass
class AccountConfig:
    """Enhanced account configuration"""
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
    use_percentage_balance: bool = True
    balance_percentage: float = 2.0
    fixed_usdt_amount: float = 100.0
    
    # TP/SL management
    take_profit_levels: List[TakeProfitLevel] = None
    stop_loss_levels: List[StopLossLevel] = None
    
    # Channels
    monitored_channels: List[Dict[str, str]] = None  # [{'id': '...', 'name': '...'}]
    
    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []
        if self.take_profit_levels is None:
            self.take_profit_levels = [
                TakeProfitLevel(2.0, 50.0),
                TakeProfitLevel(3.5, 50.0),
                TakeProfitLevel(5.0, 100.0)
            ]
        if self.stop_loss_levels is None:
            self.stop_loss_levels = [StopLossLevel(2.0, 100.0)]
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_used:
            self.last_used = datetime.now().isoformat()

class EnhancedDatabase:
    def __init__(self, db_path: str = "enhanced_trading_bot_v6.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
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
                    monitored_channels TEXT DEFAULT '[]'
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Database initialized")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def create_account(self, account: AccountConfig) -> bool:
        """Create or update account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO accounts (
                    account_id, account_name, bingx_api_key, bingx_secret_key,
                    telegram_api_id, telegram_api_hash, phone, is_active,
                    created_at, last_used, leverage, risk_percentage,
                    default_symbol, auto_trade_enabled, use_percentage_balance,
                    balance_percentage, fixed_usdt_amount,
                    take_profit_levels, stop_loss_levels, monitored_channels
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account.account_id, account.account_name, account.bingx_api_key,
                account.bingx_secret_key, account.telegram_api_id, account.telegram_api_hash,
                account.phone, account.is_active, account.created_at, account.last_used,
                account.leverage, account.risk_percentage, account.default_symbol,
                account.auto_trade_enabled, account.use_percentage_balance,
                account.balance_percentage, account.fixed_usdt_amount,
                json.dumps([{'percentage': tp.percentage, 'close_percentage': tp.close_percentage} 
                           for tp in account.take_profit_levels]),
                json.dumps([{'percentage': sl.percentage, 'close_percentage': sl.close_percentage} 
                           for sl in account.stop_loss_levels]),
                json.dumps(account.monitored_channels)
            ))

            conn.commit()
            conn.close()
            logger.info(f"✅ Account {account.account_name} saved")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save account: {e}")
            return False

    def get_account(self, account_id: str) -> Optional[AccountConfig]:
        """Get single account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts WHERE account_id = ?', (account_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            tp_levels = []
            if row[17]:
                tp_data = json.loads(row[17])
                tp_levels = [TakeProfitLevel(tp['percentage'], tp['close_percentage']) 
                            for tp in tp_data]

            sl_levels = []
            if row[18]:
                sl_data = json.loads(row[18])
                sl_levels = [StopLossLevel(sl['percentage'], sl['close_percentage']) 
                            for sl in sl_data]

            return AccountConfig(
                account_id=row[0], account_name=row[1], bingx_api_key=row[2],
                bingx_secret_key=row[3], telegram_api_id=row[4], telegram_api_hash=row[5],
                phone=row[6], is_active=bool(row[7]), created_at=row[8], last_used=row[9],
                leverage=row[10], risk_percentage=row[11], default_symbol=row[12],
                auto_trade_enabled=bool(row[13]), use_percentage_balance=bool(row[14]),
                balance_percentage=row[15], fixed_usdt_amount=row[16],
                take_profit_levels=tp_levels, stop_loss_levels=sl_levels,
                monitored_channels=json.loads(row[19]) if row[19] else []
            )
        except Exception as e:
            logger.error(f"❌ Failed to get account: {e}")
            return None

    def get_all_accounts(self) -> List[AccountConfig]:
        """Get all accounts"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts WHERE is_active = TRUE')
            rows = cursor.fetchall()
            conn.close()

            accounts = []
            for row in rows:
                try:
                    tp_levels = []
                    if row[17]:
                        tp_data = json.loads(row[17])
                        tp_levels = [TakeProfitLevel(tp['percentage'], tp['close_percentage']) 
                                    for tp in tp_data]

                    sl_levels = []
                    if row[18]:
                        sl_data = json.loads(row[18])
                        sl_levels = [StopLossLevel(sl['percentage'], sl['close_percentage']) 
                                    for sl in sl_data]

                    account = AccountConfig(
                        account_id=row[0], account_name=row[1], bingx_api_key=row[2],
                        bingx_secret_key=row[3], telegram_api_id=row[4], telegram_api_hash=row[5],
                        phone=row[6], is_active=bool(row[7]), created_at=row[8], last_used=row[9],
                        leverage=row[10], risk_percentage=row[11], default_symbol=row[12],
                        auto_trade_enabled=bool(row[13]), use_percentage_balance=bool(row[14]),
                        balance_percentage=row[15], fixed_usdt_amount=row[16],
                        take_profit_levels=tp_levels, stop_loss_levels=sl_levels,
                        monitored_channels=json.loads(row[19]) if row[19] else []
                    )
                    accounts.append(account)
                except Exception as e:
                    logger.error(f"❌ Error parsing account: {e}")
                    continue

            return accounts
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return []

    def delete_account(self, account_id: str) -> bool:
        """Delete account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET is_active = FALSE WHERE account_id = ?', (account_id,))
            conn.commit()
            conn.close()
            logger.info(f"✅ Account {account_id} deleted")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete account: {e}")
            return False

class TradingBot:
    def __init__(self):
        self.db = EnhancedDatabase()
        self.current_accounts: Dict[int, str] = {}  # user_id -> account_id
        self.authenticated_users: Dict[int, bool] = {}
        
    def is_authenticated(self, user_id: int) -> bool:
        return self.authenticated_users.get(user_id, False)
    
    def get_current_account(self, user_id: int) -> Optional[AccountConfig]:
        account_id = self.current_accounts.get(user_id)
        if not account_id:
            return None
        return self.db.get_account(account_id)

# Initialize bot
trading_bot = TradingBot()

# ==================== UI BUILDERS ====================

def build_main_menu():
    return ReplyKeyboardMarkup([
        ["📋 Accounts", "⚙️ Settings"],
        ["📊 Status", "🚀 Start Trading"],
        ["🛑 Stop Trading"]
    ], resize_keyboard=True)

def build_account_settings_keyboard(account_id: str) -> InlineKeyboardMarkup:
    """Build settings keyboard for an account"""
    keyboard = [
        [InlineKeyboardButton("⚡ Leverage", callback_data=f"set_leverage_{account_id}"),
         InlineKeyboardButton("💰 Balance Mode", callback_data=f"set_balance_{account_id}")],
        [InlineKeyboardButton("🎯 Take Profits", callback_data=f"set_tp_{account_id}"),
         InlineKeyboardButton("🛡️ Stop Loss", callback_data=f"set_sl_{account_id}")],
        [InlineKeyboardButton("📡 Channels", callback_data=f"manage_channels_{account_id}")],
        [InlineKeyboardButton("✏️ Rename Account", callback_data=f"rename_{account_id}"),
         InlineKeyboardButton("🗑️ Delete Account", callback_data=f"delete_{account_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_accounts")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_channel_method_keyboard(account_id: str) -> InlineKeyboardMarkup:
    """Build channel addition method selector"""
    keyboard = [
        [InlineKeyboardButton("📋 Select from List", callback_data=f"channel_list_{account_id}")],
        [InlineKeyboardButton("🆔 Enter Channel ID", callback_data=f"channel_id_{account_id}")],
        [InlineKeyboardButton("🔗 Enter Channel Link", callback_data=f"channel_link_{account_id}")],
        [InlineKeyboardButton("📤 Forward Message", callback_data=f"channel_forward_{account_id}")],
        [InlineKeyboardButton("🗑️ Clear All Channels", callback_data=f"clear_channels_{account_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_account_{account_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_tp_management_keyboard(account_id: str) -> InlineKeyboardMarkup:
    """Build TP level management keyboard"""
    keyboard = [
        [InlineKeyboardButton("➕ Add TP Level", callback_data=f"add_tp_{account_id}")],
        [InlineKeyboardButton("🗑️ Clear All", callback_data=f"clear_tp_{account_id}"),
         InlineKeyboardButton("🔄 Reset Default", callback_data=f"reset_tp_{account_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_account_{account_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== COMMAND HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - authenticate user"""
    user_id = update.effective_user.id
    
    if not trading_bot.is_authenticated(user_id):
        await update.message.reply_text(
            "🔐 <b>Enhanced Multi-Account Trading Bot v6.0</b>\n\n"
            "Please enter PIN code to access:",
            parse_mode='HTML'
        )
        return WAITING_PIN
    
    await update.message.reply_text(
        "🏠 <b>Main Menu</b>\n\n"
        "Choose an action:",
        parse_mode='HTML',
        reply_markup=build_main_menu()
    )
    return ConversationHandler.END

async def handle_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PIN authentication"""
    user_id = update.effective_user.id
    pin = update.message.text.strip()
    
    if pin == BOT_PIN_CODE:
        trading_bot.authenticated_users[user_id] = True
        await update.message.reply_text(
            "✅ <b>Authenticated!</b>\n\n"
            "Welcome to Enhanced Multi-Account Trading Bot v6.0\n\n"
            "<b>NEW in v6.0:</b>\n"
            "• Easy settings management\n"
            "• Flexible TP/SL configuration\n"
            "• Multiple channel addition methods\n"
            "• Account renaming & deletion\n"
            "• Real-time settings updates\n\n"
            "Choose an action:",
            parse_mode='HTML',
            reply_markup=build_main_menu()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ <b>Invalid PIN!</b>\n\n"
            "Please try again:",
            parse_mode='HTML'
        )
        return WAITING_PIN

async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all accounts"""
    user_id = update.effective_user.id
    
    if not trading_bot.is_authenticated(user_id):
        await update.message.reply_text("🔐 Please use /start to authenticate")
        return
    
    accounts = trading_bot.db.get_all_accounts()
    
    if not accounts:
        keyboard = [[InlineKeyboardButton("➕ Add Account", callback_data="add_account")]]
        await update.message.reply_text(
            "📋 <b>No Accounts Found</b>\n\n"
            "Add your first trading account to get started.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📋 <b>Your Trading Accounts</b>\n\n"
    keyboard = []
    
    for account in accounts:
        status = "🟢" if account.auto_trade_enabled else "⚪"
        text += f"{status} <b>{account.account_name}</b>\n"
        text += f"   Leverage: {account.leverage}x | Channels: {len(account.monitored_channels)}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"⚙️ {account.account_name}",
            callback_data=f"select_account_{account.account_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("➕ Add Account", callback_data="add_account")])
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_account_settings(query, account_id: str):
    """Show detailed account settings"""
    account = trading_bot.db.get_account(account_id)
    if not account:
        await query.edit_message_text("❌ Account not found")
        return
    
    # Build comprehensive settings display
    text = f"⚙️ <b>{account.account_name} - Settings</b>\n\n"
    
    # Trading parameters
    text += "<b>📊 Trading Parameters:</b>\n"
    text += f"   ⚡ Leverage: <b>{account.leverage}x</b>\n"
    text += f"   📈 Risk: <b>{account.risk_percentage}%</b> per trade\n\n"
    
    # Balance mode
    text += "<b>💰 Balance Configuration:</b>\n"
    if account.use_percentage_balance:
        text += f"   Mode: <b>Percentage</b>\n"
        text += f"   Value: <b>{account.balance_percentage}%</b> of balance\n"
    else:
        text += f"   Mode: <b>Fixed USDT</b>\n"
        text += f"   Value: <b>${account.fixed_usdt_amount:.0f}</b> USDT\n"
    text += "\n"
    
    # Take Profit Levels
    text += "<b>🎯 Take Profit Levels:</b>\n"
    for i, tp in enumerate(account.take_profit_levels, 1):
        text += f"   TP{i}: <b>{tp.percentage}%</b> → Close <b>{tp.close_percentage}%</b>\n"
    text += "\n"
    
    # Stop Loss Levels
    text += "<b>🛡️ Stop Loss Levels:</b>\n"
    for i, sl in enumerate(account.stop_loss_levels, 1):
        text += f"   SL{i}: <b>{sl.percentage}%</b> → Close <b>{sl.close_percentage}%</b>\n"
    text += "\n"
    
    # Channels
    text += f"<b>📡 Monitored Channels:</b> <b>{len(account.monitored_channels)}</b>\n"
    if account.monitored_channels:
        for ch in account.monitored_channels[:3]:
            text += f"   • {ch.get('name', 'Channel')}\n"
        if len(account.monitored_channels) > 3:
            text += f"   ... and {len(account.monitored_channels) - 3} more\n"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=build_account_settings_keyboard(account_id)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    # Account selection
    if data.startswith("select_account_"):
        account_id = data.replace("select_account_", "")
        trading_bot.current_accounts[user_id] = account_id
        await show_account_settings(query, account_id)
        return
    
    # Add account
    if data == "add_account":
        await query.edit_message_text(
            "➕ <b>Add New Account</b>\n\n"
            "Enter account name:",
            parse_mode='HTML'
        )
        return WAITING_ACCOUNT_NAME
    
    # Back to accounts
    if data == "back_to_accounts":
        accounts = trading_bot.db.get_all_accounts()
        text = "📋 <b>Your Trading Accounts</b>\n\n"
        keyboard = []
        
        for account in accounts:
            status = "🟢" if account.auto_trade_enabled else "⚪"
            text += f"{status} <b>{account.account_name}</b>\n"
            keyboard.append([InlineKeyboardButton(
                f"⚙️ {account.account_name}",
                callback_data=f"select_account_{account.account_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("➕ Add Account", callback_data="add_account")])
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Back to specific account
    if data.startswith("back_to_account_"):
        account_id = data.replace("back_to_account_", "")
        await show_account_settings(query, account_id)
        return
    
    # Leverage setting
    if data.startswith("set_leverage_"):
        account_id = data.replace("set_leverage_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'leverage'
        await query.edit_message_text(
            "⚡ <b>Set Leverage</b>\n\n"
            "Enter leverage value (1-125):",
            parse_mode='HTML'
        )
        return WAITING_SETTING_CHOICE
    
    # Balance mode setting
    if data.startswith("set_balance_"):
        account_id = data.replace("set_balance_", "")
        context.user_data['setting_account_id'] = account_id
        
        keyboard = [
            [InlineKeyboardButton("📊 Percentage of Balance", callback_data=f"balance_percent_{account_id}")],
            [InlineKeyboardButton("💵 Fixed USDT Amount", callback_data=f"balance_fixed_{account_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_account_{account_id}")]
        ]
        
        await query.edit_message_text(
            "💰 <b>Balance Configuration</b>\n\n"
            "Choose balance mode:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Balance percentage mode
    if data.startswith("balance_percent_"):
        account_id = data.replace("balance_percent_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'balance_percent'
        await query.edit_message_text(
            "📊 <b>Percentage Mode</b>\n\n"
            "Enter percentage of balance to use (1-100):",
            parse_mode='HTML'
        )
        return WAITING_SETTING_CHOICE
    
    # Balance fixed mode
    if data.startswith("balance_fixed_"):
        account_id = data.replace("balance_fixed_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'balance_fixed'
        await query.edit_message_text(
            "💵 <b>Fixed USDT Mode</b>\n\n"
            "Enter fixed USDT amount:",
            parse_mode='HTML'
        )
        return WAITING_SETTING_CHOICE
    
    # TP management
    if data.startswith("set_tp_"):
        account_id = data.replace("set_tp_", "")
        account = trading_bot.db.get_account(account_id)
        
        text = "🎯 <b>Take Profit Levels</b>\n\n"
        text += "<b>Current Levels:</b>\n"
        for i, tp in enumerate(account.take_profit_levels, 1):
            text += f"TP{i}: <b>{tp.percentage}%</b> → Close <b>{tp.close_percentage}%</b>\n"
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=build_tp_management_keyboard(account_id)
        )
        return
    
    # Add TP level
    if data.startswith("add_tp_"):
        account_id = data.replace("add_tp_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'tp_add'
        await query.edit_message_text(
            "🎯 <b>Add Take Profit Level</b>\n\n"
            "Enter price percentage (e.g., 2.5 for 2.5%):",
            parse_mode='HTML'
        )
        return WAITING_TP_PERCENT
    
    # Clear all TP
    if data.startswith("clear_tp_"):
        account_id = data.replace("clear_tp_", "")
        account = trading_bot.db.get_account(account_id)
        account.take_profit_levels = []
        trading_bot.db.create_account(account)
        
        await query.edit_message_text(
            "✅ All TP levels cleared",
            parse_mode='HTML'
        )
        await asyncio.sleep(1)
        await show_account_settings(query, account_id)
        return
    
    # Reset TP to default
    if data.startswith("reset_tp_"):
        account_id = data.replace("reset_tp_", "")
        account = trading_bot.db.get_account(account_id)
        account.take_profit_levels = [
            TakeProfitLevel(2.0, 50.0),
            TakeProfitLevel(3.5, 50.0),
            TakeProfitLevel(5.0, 100.0)
        ]
        trading_bot.db.create_account(account)
        
        await query.edit_message_text(
            "✅ TP levels reset to default",
            parse_mode='HTML'
        )
        await asyncio.sleep(1)
        await show_account_settings(query, account_id)
        return
    
    # SL management
    if data.startswith("set_sl_"):
        account_id = data.replace("set_sl_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'sl_percent'
        await query.edit_message_text(
            "🛡️ <b>Stop Loss Configuration</b>\n\n"
            "Enter stop loss percentage (e.g., 2 for 2%):",
            parse_mode='HTML'
        )
        return WAITING_SETTING_CHOICE
    
    # Channel management
    if data.startswith("manage_channels_"):
        account_id = data.replace("manage_channels_", "")
        account = trading_bot.db.get_account(account_id)
        
        text = "📡 <b>Channel Management</b>\n\n"
        text += f"<b>Monitored Channels: {len(account.monitored_channels)}</b>\n\n"
        
        if account.monitored_channels:
            for ch in account.monitored_channels:
                text += f"• {ch.get('name', 'Unknown')} (<code>{ch.get('id', 'N/A')}</code>)\n"
        else:
            text += "No channels configured yet.\n"
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=build_channel_method_keyboard(account_id)
        )
        return
    
    # Channel list method
    if data.startswith("channel_list_"):
        account_id = data.replace("channel_list_", "")
        await query.edit_message_text(
            "📋 <b>Loading your channels...</b>\n\n"
            "This feature requires Telethon setup. For now, use other methods.",
            parse_mode='HTML'
        )
        return
    
    # Channel ID method
    if data.startswith("channel_id_"):
        account_id = data.replace("channel_id_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'channel_id'
        await query.edit_message_text(
            "🆔 <b>Add Channel by ID</b>\n\n"
            "Enter channel ID (e.g., -1001234567890):",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_ID
    
    # Channel link method
    if data.startswith("channel_link_"):
        account_id = data.replace("channel_link_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'channel_link'
        await query.edit_message_text(
            "🔗 <b>Add Channel by Link</b>\n\n"
            "Enter channel link:\n"
            "• https://t.me/channel_name\n"
            "• t.me/channel_name\n"
            "• @channel_name",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_LINK
    
    # Channel forward method
    if data.startswith("channel_forward_"):
        account_id = data.replace("channel_forward_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'channel_forward'
        await query.edit_message_text(
            "📤 <b>Add Channel by Forward</b>\n\n"
            "Forward any message from the channel you want to monitor.\n\n"
            "The bot will automatically detect the channel.",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_FORWARD
    
    # Clear all channels
    if data.startswith("clear_channels_"):
        account_id = data.replace("clear_channels_", "")
        account = trading_bot.db.get_account(account_id)
        account.monitored_channels = []
        trading_bot.db.create_account(account)
        
        await query.edit_message_text(
            "✅ All channels cleared",
            parse_mode='HTML'
        )
        await asyncio.sleep(1)
        await show_account_settings(query, account_id)
        return
    
    # Rename account
    if data.startswith("rename_"):
        account_id = data.replace("rename_", "")
        context.user_data['setting_account_id'] = account_id
        context.user_data['setting_type'] = 'rename'
        await query.edit_message_text(
            "✏️ <b>Rename Account</b>\n\n"
            "Enter new account name:",
            parse_mode='HTML'
        )
        return WAITING_ACCOUNT_RENAME
    
    # Delete account
    if data.startswith("delete_"):
        account_id = data.replace("delete_", "")
        
        keyboard = [
            [InlineKeyboardButton("⚠️ Yes, Delete", callback_data=f"confirm_delete_{account_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"back_to_account_{account_id}")]
        ]
        
        await query.edit_message_text(
            "🗑️ <b>Delete Account</b>\n\n"
            "⚠️ Are you sure you want to delete this account?\n"
            "This action cannot be undone.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Confirm delete
    if data.startswith("confirm_delete_"):
        account_id = data.replace("confirm_delete_", "")
        trading_bot.db.delete_account(account_id)
        
        await query.edit_message_text(
            "✅ Account deleted successfully",
            parse_mode='HTML'
        )
        await asyncio.sleep(1)
        
        # Show accounts list
        accounts = trading_bot.db.get_all_accounts()
        text = "📋 <b>Your Trading Accounts</b>\n\n"
        keyboard = []
        
        for account in accounts:
            status = "🟢" if account.auto_trade_enabled else "⚪"
            text += f"{status} <b>{account.account_name}</b>\n"
            keyboard.append([InlineKeyboardButton(
                f"⚙️ {account.account_name}",
                callback_data=f"select_account_{account.account_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("➕ Add Account", callback_data="add_account")])
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

# ==================== TEXT INPUT HANDLERS ====================

async def handle_account_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new account name"""
    account_name = update.message.text.strip()
    context.user_data['new_account_name'] = account_name
    
    await update.message.reply_text(
        f"✅ Account name: <b>{account_name}</b>\n\n"
        "Enter BingX API Key:",
        parse_mode='HTML'
    )
    return WAITING_BINGX_KEY

async def handle_bingx_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle BingX API key"""
    api_key = update.message.text.strip()
    context.user_data['bingx_api_key'] = api_key
    
    await update.message.reply_text(
        "✅ API Key saved\n\n"
        "Enter BingX Secret Key:",
        parse_mode='HTML'
    )
    return WAITING_BINGX_SECRET

async def handle_bingx_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle BingX secret and create account"""
    secret_key = update.message.text.strip()
    
    # Create account with default values
    account = AccountConfig(
        account_id=str(uuid.uuid4()),
        account_name=context.user_data['new_account_name'],
        bingx_api_key=context.user_data['bingx_api_key'],
        bingx_secret_key=secret_key,
        telegram_api_id=DEFAULT_TELEGRAM_API_ID,
        telegram_api_hash=DEFAULT_TELEGRAM_API_HASH,
        phone=""
    )
    
    if trading_bot.db.create_account(account):
        await update.message.reply_text(
            f"🎉 <b>Account Created!</b>\n\n"
            f"Name: <b>{account.account_name}</b>\n\n"
            f"Default settings applied:\n"
            f"• Leverage: 10x\n"
            f"• Risk: 2% per trade\n"
            f"• Balance: 2% of balance\n"
            f"• TP: 2%/3.5%/5%\n"
            f"• SL: 2%\n\n"
            f"Use /accounts to configure settings.",
            parse_mode='HTML',
            reply_markup=build_main_menu()
        )
    else:
        await update.message.reply_text(
            "❌ Failed to create account. Please try again.",
            parse_mode='HTML'
        )
    
    return ConversationHandler.END

async def handle_account_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account rename"""
    new_name = update.message.text.strip()
    account_id = context.user_data.get('setting_account_id')
    
    account = trading_bot.db.get_account(account_id)
    if account:
        account.account_name = new_name
        trading_bot.db.create_account(account)
        
        await update.message.reply_text(
            f"✅ Account renamed to: <b>{new_name}</b>",
            parse_mode='HTML',
            reply_markup=build_main_menu()
        )
    
    return ConversationHandler.END

async def handle_setting_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle various setting inputs"""
    value_text = update.message.text.strip()
    setting_type = context.user_data.get('setting_type')
    account_id = context.user_data.get('setting_account_id')
    
    account = trading_bot.db.get_account(account_id)
    if not account:
        await update.message.reply_text("❌ Account not found")
        return ConversationHandler.END
    
    try:
        if setting_type == 'leverage':
            value = int(value_text)
            if 1 <= value <= 125:
                account.leverage = value
                trading_bot.db.create_account(account)
                await update.message.reply_text(
                    f"✅ Leverage set to <b>{value}x</b>",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
            else:
                await update.message.reply_text("❌ Leverage must be between 1 and 125")
        
        elif setting_type == 'balance_percent':
            value = float(value_text)
            if 1 <= value <= 100:
                account.use_percentage_balance = True
                account.balance_percentage = value
                trading_bot.db.create_account(account)
                await update.message.reply_text(
                    f"✅ Balance mode set to <b>{value}%</b> of balance",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
            else:
                await update.message.reply_text("❌ Percentage must be between 1 and 100")
        
        elif setting_type == 'balance_fixed':
            value = float(value_text)
            if value > 0:
                account.use_percentage_balance = False
                account.fixed_usdt_amount = value
                trading_bot.db.create_account(account)
                await update.message.reply_text(
                    f"✅ Balance mode set to <b>${value:.0f} USDT</b> fixed",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
            else:
                await update.message.reply_text("❌ Amount must be positive")
        
        elif setting_type == 'sl_percent':
            value = float(value_text)
            if 0.1 <= value <= 50:
                account.stop_loss_levels = [StopLossLevel(value, 100.0)]
                trading_bot.db.create_account(account)
                await update.message.reply_text(
                    f"✅ Stop Loss set to <b>{value}%</b>",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
            else:
                await update.message.reply_text("❌ Stop loss must be between 0.1 and 50")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
    
    return ConversationHandler.END

async def handle_tp_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TP percentage input"""
    try:
        percentage = float(update.message.text.strip())
        if 0.1 <= percentage <= 100:
            context.user_data['tp_percentage'] = percentage
            await update.message.reply_text(
                f"✅ TP at <b>{percentage}%</b>\n\n"
                f"Now enter what percentage of position to close (1-100):",
                parse_mode='HTML'
            )
            return WAITING_TP_CLOSE_PERCENT
        else:
            await update.message.reply_text("❌ Percentage must be between 0.1 and 100")
            return WAITING_TP_PERCENT
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return WAITING_TP_PERCENT

async def handle_tp_close_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TP close percentage"""
    try:
        close_percent = float(update.message.text.strip())
        if 1 <= close_percent <= 100:
            account_id = context.user_data.get('setting_account_id')
            tp_percentage = context.user_data.get('tp_percentage')
            
            account = trading_bot.db.get_account(account_id)
            if account:
                # Add new TP level
                new_tp = TakeProfitLevel(tp_percentage, close_percent)
                account.take_profit_levels.append(new_tp)
                # Sort by percentage
                account.take_profit_levels.sort(key=lambda x: x.percentage)
                trading_bot.db.create_account(account)
                
                await update.message.reply_text(
                    f"✅ <b>TP Level Added!</b>\n\n"
                    f"At <b>{tp_percentage}%</b> profit → Close <b>{close_percent}%</b> of position\n\n"
                    f"Total TP levels: {len(account.take_profit_levels)}",
                    parse_mode='HTML',
                    reply_markup=build_main_menu()
                )
        else:
            await update.message.reply_text("❌ Close percentage must be between 1 and 100")
            return WAITING_TP_CLOSE_PERCENT
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return WAITING_TP_CLOSE_PERCENT
    
    return ConversationHandler.END

async def handle_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel ID input"""
    channel_id = update.message.text.strip()
    account_id = context.user_data.get('setting_account_id')
    
    # Validate channel ID format
    if not channel_id.lstrip('-').isdigit():
        await update.message.reply_text(
            "❌ Invalid format. Channel ID should be like: -1001234567890",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_ID
    
    if not channel_id.startswith('-'):
        channel_id = '-' + channel_id
    
    account = trading_bot.db.get_account(account_id)
    if account:
        # Add channel
        channel_info = {
            'id': channel_id,
            'name': f'Channel {channel_id[-4:]}'
        }
        
        # Check if already exists
        if not any(ch['id'] == channel_id for ch in account.monitored_channels):
            account.monitored_channels.append(channel_info)
            trading_bot.db.create_account(account)
            
            await update.message.reply_text(
                f"✅ <b>Channel Added!</b>\n\n"
                f"ID: <code>{channel_id}</code>\n"
                f"Total channels: {len(account.monitored_channels)}",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
        else:
            await update.message.reply_text(
                "⚠️ Channel already exists",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
    
    return ConversationHandler.END

async def handle_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel link input"""
    link = update.message.text.strip()
    account_id = context.user_data.get('setting_account_id')
    
    # Extract channel username from link
    import re
    match = re.search(r't\.me/([^/?]+)', link) or re.search(r'@(\w+)', link)
    
    if not match:
        await update.message.reply_text(
            "❌ Invalid link format",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_LINK
    
    username = match.group(1)
    
    account = trading_bot.db.get_account(account_id)
    if account:
        # Add channel (note: actual ID resolution would require Telethon)
        channel_info = {
            'id': f'@{username}',
            'name': username
        }
        
        if not any(ch['id'] == channel_info['id'] for ch in account.monitored_channels):
            account.monitored_channels.append(channel_info)
            trading_bot.db.create_account(account)
            
            await update.message.reply_text(
                f"✅ <b>Channel Added!</b>\n\n"
                f"Username: @{username}\n"
                f"Total channels: {len(account.monitored_channels)}\n\n"
                f"Note: Full ID resolution requires Telethon setup",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
        else:
            await update.message.reply_text(
                "⚠️ Channel already exists",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
    
    return ConversationHandler.END

async def handle_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded message for channel detection"""
    if not update.message.forward_from_chat:
        await update.message.reply_text(
            "❌ Please forward a message from the channel",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_FORWARD
    
    account_id = context.user_data.get('setting_account_id')
    forward_from = update.message.forward_from_chat
    
    channel_id = str(-abs(forward_from.id))
    channel_name = getattr(forward_from, 'title', 'Unknown Channel')
    
    account = trading_bot.db.get_account(account_id)
    if account:
        channel_info = {
            'id': channel_id,
            'name': channel_name
        }
        
        if not any(ch['id'] == channel_id for ch in account.monitored_channels):
            account.monitored_channels.append(channel_info)
            trading_bot.db.create_account(account)
            
            await update.message.reply_text(
                f"✅ <b>Channel Added!</b>\n\n"
                f"Name: <b>{channel_name}</b>\n"
                f"ID: <code>{channel_id}</code>\n"
                f"Total channels: {len(account.monitored_channels)}",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
        else:
            await update.message.reply_text(
                "⚠️ Channel already exists",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
    
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu text buttons"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if not trading_bot.is_authenticated(user_id):
        await update.message.reply_text("🔐 Please use /start to authenticate")
        return
    
    if text == "📋 Accounts":
        await show_accounts(update, context)
    
    elif text == "⚙️ Settings":
        account = trading_bot.get_current_account(user_id)
        if account:
            keyboard = [[InlineKeyboardButton(
                "⚙️ Configure Account",
                callback_data=f"select_account_{account.account_id}"
            )]]
            await update.message.reply_text(
                f"⚙️ Current account: <b>{account.account_name}</b>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "❌ No account selected. Use '📋 Accounts' to select one.",
                parse_mode='HTML'
            )
    
    elif text == "📊 Status":
        account = trading_bot.get_current_account(user_id)
        if account:
            status_text = f"📊 <b>Bot Status</b>\n\n"
            status_text += f"Account: <b>{account.account_name}</b>\n"
            status_text += f"Leverage: <b>{account.leverage}x</b>\n"
            status_text += f"Channels: <b>{len(account.monitored_channels)}</b>\n"
            status_text += f"TP Levels: <b>{len(account.take_profit_levels)}</b>\n"
            status_text += f"Trading: <b>{'🟢 Active' if account.auto_trade_enabled else '⚪ Inactive'}</b>"
            
            await update.message.reply_text(status_text, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ No account selected")

# ==================== CONVERSATION HANDLER ====================

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start_command)],
    states={
        WAITING_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pin)],
        WAITING_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_name)],
        WAITING_BINGX_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bingx_key)],
        WAITING_BINGX_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bingx_secret)],
        WAITING_ACCOUNT_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_rename)],
        WAITING_SETTING_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_choice)],
        WAITING_TP_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_percent)],
        WAITING_TP_CLOSE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_close_percent)],
        WAITING_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_id)],
        WAITING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_link)],
        WAITING_CHANNEL_FORWARD: [MessageHandler(filters.ALL, handle_channel_forward)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    allow_reentry=True
)

# ==================== MAIN ====================

def main():
    """Start the bot"""
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('accounts', show_accounts))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 Enhanced Multi-Account Trading Bot v6.0")
    print("✅ Easy settings management")
    print("✅ Flexible TP/SL configuration")
    print("✅ Multiple channel addition methods")
    print("✅ Account renaming & deletion")
    print("✅ Real-time updates")
    print("🔐 PIN: 496745")
    print("🚀 Starting...")
    
    application.run_polling()

if __name__ == '__main__':
    main()
