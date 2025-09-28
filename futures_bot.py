#!/usr/bin/env python3
"""
Telegram Trading Bot v4.4 - BINGX INTEGRATION (API PARAMETERS FIXED)
- BingX API integration (150x leverage, no subaccount restrictions!)
- Uses bot settings (leverage, SL, TP, position size)
- Creates SL/TP orders automatically  
- Option to use signal settings vs bot settings
- Enhanced signal parsing for Russian formats
- Interactive setup with buttons
- FIXED: BingX API response handling
- FIXED: Telethon "EOF when reading a line" error
- FIXED: BingX balance parsing (single object vs array)
- FIXED: BingX API v2 parameters (positionSide required)
"""

import asyncio
import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
import os
import sys
import traceback
import hashlib
import hmac
import time
import aiohttp

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

from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Conversation states
(WAITING_BINGX_KEY, WAITING_BINGX_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE) = range(11)

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
class BotConfig:
    bingx_api_key: str = ""
    bingx_api_secret: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    leverage: int = 10
    stop_loss_percent: float = 5.0
    take_profit_percent: float = 10.0
    balance_percent: float = 1.0
    monitored_channels: List[str] = None
    user_id: int = 0
    use_signal_settings: bool = True  # Choose signal vs bot settings
    create_sl_tp: bool = True  # Auto create SL/TP orders

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

class BingXClient:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://open-api.bingx.com"

    def _generate_signature(self, params: str, timestamp: str) -> str:
        """Generate signature for BingX API"""
        query_string = f"{params}&timestamp={timestamp}"
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _make_request(self, method: str, endpoint: str, params: dict = None) -> dict:
        """Make HTTP request to BingX API"""
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))

        # Convert params to query string
        query_params = []
        for key, value in params.items():
            if value is not None:
                query_params.append(f"{key}={value}")
        query_string = "&".join(query_params)

        # Generate signature
        signature = self._generate_signature(query_string, timestamp)

        # Add authentication
        query_string += f"&timestamp={timestamp}&signature={signature}"

        headers = {
            "X-BX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        }

        url = f"{self.base_url}{endpoint}?{query_string}"

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers) as response:
                text = await response.text()
                logger.info(f"BingX API Response: {text}")

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON response: {text}")
                    raise Exception(f"BingX API returned invalid JSON: {text}")

                if response.status != 200:
                    raise Exception(f"BingX API Error: {data}")

                return data

    async def get_account_balance(self) -> dict:
        """Get futures account balance"""
        return await self._make_request("GET", "/openApi/swap/v2/user/balance")

    async def get_symbol_info(self, symbol: str) -> dict:
        """Get symbol trading info"""
        return await self._make_request("GET", "/openApi/swap/v2/quote/contracts", {"symbol": symbol})

    async def set_leverage(self, symbol: str, leverage: int, side: str = "BOTH") -> dict:
        """Set leverage for symbol"""
        params = {
            "symbol": symbol,
            "leverage": leverage,
            "side": side
        }
        return await self._make_request("POST", "/openApi/swap/v2/trade/leverage", params)

    async def create_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                          price: float = None, stop_price: float = None, 
                          reduce_only: bool = False, close_position: bool = False,
                          position_side: str = None) -> dict:
        """FIXED: Create trading order with proper BingX v2 parameters"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity
        }

        # FIXED: Add required positionSide parameter for BingX v2
        if position_side:
            params["positionSide"] = position_side
        else:
            # Default position side based on trade direction
            if side.upper() in ['BUY', 'Buy']:
                params["positionSide"] = "LONG"
            else:
                params["positionSide"] = "SHORT"

        # Optional parameters
        if price:
            params["price"] = price
        if stop_price:
            params["stopPrice"] = stop_price
        if reduce_only:
            params["reduceOnly"] = reduce_only
        if close_position:
            params["closePosition"] = close_position

        return await self._make_request("POST", "/openApi/swap/v2/trade/order", params)

    async def get_current_price(self, symbol: str) -> float:
        """Get current market price for symbol"""
        data = await self._make_request("GET", "/openApi/swap/v2/quote/price", {"symbol": symbol})

        # FIXED: Handle different response formats
        if isinstance(data, dict):
            if 'price' in data:
                return float(data['price'])
            elif 'data' in data and isinstance(data['data'], dict) and 'price' in data['data']:
                return float(data['data']['price'])
            elif 'data' in data and isinstance(data['data'], list) and len(data['data']) > 0:
                return float(data['data'][0]['price'])

        raise Exception(f"Could not parse price from response: {data}")

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

            # Extract symbol - enhanced patterns - BingX uses different format
            sym_match = re.match(r'([A-Z0-9]{1,10})(?:/USDT|USDT|-USDT)?', symbol_line, re.I)
            if not sym_match:
                continue

            sym = sym_match.group(1).upper()
            # BingX format: BTC-USDT (not BTCUSDT)
            if sym.endswith('USDT'):
                symbol = sym.replace('USDT', '-USDT')
            else:
                symbol = sym + '-USDT'

            # Fix double USDT
            if symbol.endswith('USDT-USDT'):
                symbol = symbol.replace('USDT-USDT','-USDT')

            # Find trade side - enhanced detection
            trade_side = None
            for l in lines[1:8]:  # Check more lines
                if re.search(r'\b(LONG|BUY|ЛОНГ|📈|🟢|⬆️|🚀)\b', l, re.I):
                    trade_side = 'LONG'
                    break
                elif re.search(r'\b(SHORT|SELL|ШОРТ|📉|🔴|⬇️|🔻)\b', l, re.I):
                    trade_side = 'SHORT'
                    break

            # Fallback search in entire block
            if not trade_side:
                if re.search(r'\b(LONG|ЛОНГ)\b', block, re.I):
                    trade_side = 'LONG'
                elif re.search(r'\b(SHORT|ШОРТ)\b', block, re.I):
                    trade_side = 'SHORT'

            if not trade_side:
                continue

            # Entry price - enhanced patterns
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

            # Take profits - enhanced patterns
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

            # Remove duplicates and sort
            tps = sorted(list(set(tps)))[:3]  # Max 3 TPs

            # Stop loss - enhanced patterns
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

            # Leverage - enhanced patterns - BingX supports up to 150x
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
                            if 1 <= lev <= 150:  # BingX max leverage
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

# [Continue with the rest of the original classes and functions...]

# Continuing from where the code was cut off...

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """<b>📖 All Commands</b>

<b>Setup:</b>
/setup_bingx - BingX API ✅
/setup_telegram - Telegram API ✅  
/setup_channels - Channel selection ✅
/setup_trading - Trading parameters + SL/TP ✅

<b>Control:</b>
/start_monitoring - Begin monitoring 🚀
/stop_monitoring - Stop monitoring ⏹️
/status - Configuration status 📊
/balance - Account balance 💰

<b>Testing:</b>
/test_signal - Test signal parsing 🧪
/test_trade - Test trade execution 🔬

<b>Utilities:</b>
/restart - Restart bot 🔄
/logs - View recent logs 📝
/help - This help message ❓

<b>⚠️ Risk Warning:</b>
Crypto trading with high leverage involves significant risk. 
Never risk more than you can afford to lose!
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

# ===================== SETUP HANDLERS =====================

async def setup_bingx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔑 <b>BingX API Setup</b>\n\nPlease send your BingX API Key:",
        parse_mode='HTML'
    )
    return WAITING_BINGX_KEY

async def setup_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📱 <b>Telegram API Setup</b>\n\nPlease send your Telegram API ID:",
        parse_mode='HTML'
    )
    return WAITING_TELEGRAM_ID

async def setup_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    await update.message.reply_text("🔍 Loading available channels...")

    channels = await trading_bot.get_available_channels(user_id)

    if not channels:
        await update.message.reply_text(
            "❌ <b>No channels found</b>\n\nMake sure you have:\n"
            "1. Set up Telegram API\n"
            "2. Joined some Telegram channels\n"
            "3. Authorized the bot",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    text = create_channel_selection_text(user_id)
    keyboard = create_channel_keyboard(user_id, channels)

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
    return WAITING_CHANNEL_SELECTION

async def setup_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    settings_text = f"""⚙️ <b>Trading Configuration</b>

<b>Current Settings:</b>
• Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}
• SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}
• Leverage: {config.leverage}x
• Stop Loss: {config.stop_loss_percent}%
• Take Profit: {config.take_profit_percent}%
• Balance Usage: {config.balance_percent}%

<b>Settings Source Explanation:</b>
• <b>Signal</b>: Use leverage/SL/TP from trading signals (fallback to bot settings)
• <b>Bot</b>: Always use bot default settings

Configure your trading parameters:"""

    keyboard = create_settings_keyboard(user_id)
    await update.message.reply_text(settings_text, reply_markup=keyboard, parse_mode='HTML')

# ===================== INPUT HANDLERS =====================

async def handle_bingx_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_key = update.message.text.strip()
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.bingx_api_key = api_key

    await update.message.reply_text(
        "🔑 API Key saved! Now send your BingX API Secret:",
        parse_mode='HTML'
    )
    return WAITING_BINGX_SECRET

async def handle_bingx_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_secret = update.message.text.strip()
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.bingx_api_secret = api_secret

    await update.message.reply_text("🔍 Testing BingX connection...")

    success = await trading_bot.setup_bingx_client(config)

    if success:
        await update.message.reply_text(
            "✅ <b>BingX API Connected Successfully!</b>\n\n"
            "Next: /setup_telegram for Telegram API",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ <b>BingX Connection Failed</b>\n\n"
            "Please check your API credentials and try again with /setup_bingx",
            parse_mode='HTML'
        )

    return ConversationHandler.END

async def handle_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_id = update.message.text.strip()
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        config.telegram_api_id = str(int(api_id))
        await update.message.reply_text(
            "📱 API ID saved! Now send your Telegram API Hash:",
            parse_mode='HTML'
        )
        return WAITING_TELEGRAM_HASH
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid API ID. Please send a valid numeric API ID:",
            parse_mode='HTML'
        )
        return WAITING_TELEGRAM_ID

async def handle_telegram_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_hash = update.message.text.strip()
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.telegram_api_hash = api_hash

    await update.message.reply_text("🔍 Testing Telegram connection...")

    success = await trading_bot.setup_telethon_client(config)

    if success:
        await update.message.reply_text(
            "✅ <b>Telegram API Connected!</b>\n\n"
            "Next: /setup_channels to select channels",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ <b>Telegram Connection Failed</b>\n\n"
            "Make sure you have authorized the session locally first.\n"
            "Then try again with /setup_telegram",
            parse_mode='HTML'
        )

    return ConversationHandler.END

# ===================== CALLBACK HANDLERS =====================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    config = trading_bot.get_user_config(user_id)
    data = query.data

    if data.startswith("toggle_channel_"):
        channel_id = data.replace("toggle_channel_", "")

        if channel_id in config.monitored_channels:
            config.monitored_channels.remove(channel_id)
        else:
            config.monitored_channels.append(channel_id)

        # Refresh channel list
        channels = await trading_bot.get_available_channels(user_id)
        text = create_channel_selection_text(user_id)
        keyboard = create_channel_keyboard(user_id, channels)

        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

    elif data == "clear_all_channels":
        config.monitored_channels.clear()

        channels = await trading_bot.get_available_channels(user_id)
        text = create_channel_selection_text(user_id)
        keyboard = create_channel_keyboard(user_id, channels)

        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

    elif data == "channels_done":
        await query.edit_message_text(
            f"✅ <b>Channels Configured!</b>\n\n"
            f"Monitoring: {len(config.monitored_channels)} channels\n\n"
            f"Next: /setup_trading for trading parameters",
            parse_mode='HTML'
        )

    elif data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings

        settings_text = f"""⚙️ <b>Trading Configuration</b>

<b>Current Settings:</b>
• Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}
• SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}
• Leverage: {config.leverage}x
• Stop Loss: {config.stop_loss_percent}%
• Take Profit: {config.take_profit_percent}%
• Balance Usage: {config.balance_percent}%

<b>Settings Source Explanation:</b>
• <b>Signal</b>: Use leverage/SL/TP from trading signals (fallback to bot settings)
• <b>Bot</b>: Always use bot default settings

Configure your trading parameters:"""

        keyboard = create_settings_keyboard(user_id)
        await query.edit_message_text(settings_text, reply_markup=keyboard, parse_mode='HTML')

    elif data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp

        settings_text = f"""⚙️ <b>Trading Configuration</b>

<b>Current Settings:</b>
• Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}
• SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}
• Leverage: {config.leverage}x
• Stop Loss: {config.stop_loss_percent}%
• Take Profit: {config.take_profit_percent}%
• Balance Usage: {config.balance_percent}%

Configure your trading parameters:"""

        keyboard = create_settings_keyboard(user_id)
        await query.edit_message_text(settings_text, reply_markup=keyboard, parse_mode='HTML')

    elif data == "trading_done":
        await query.edit_message_text(
            "✅ <b>Trading Configuration Complete!</b>\n\n"
            "Ready to start: /start_monitoring",
            parse_mode='HTML'
        )

# ===================== MONITORING HANDLERS =====================

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    # Validate configuration
    if not all([config.bingx_api_key, config.bingx_api_secret]):
        await update.message.reply_text(
            "❌ <b>BingX API not configured</b>\n\nRun /setup_bingx first",
            parse_mode='HTML'
        )
        return

    if not all([config.telegram_api_id, config.telegram_api_hash]):
        await update.message.reply_text(
            "❌ <b>Telegram API not configured</b>\n\nRun /setup_telegram first",
            parse_mode='HTML'
        )
        return

    if not config.monitored_channels:
        await update.message.reply_text(
            "❌ <b>No channels selected</b>\n\nRun /setup_channels first",
            parse_mode='HTML'
        )
        return

    if user_id in trading_bot.active_monitoring:
        await update.message.reply_text(
            "⚠️ <b>Already monitoring!</b>\n\nUse /stop_monitoring to stop first",
            parse_mode='HTML'
        )
        return

    await update.message.reply_text("🚀 Starting monitoring...")

    success = await trading_bot.start_monitoring(user_id, context.bot)

    if success:
        await update.message.reply_text(
            f"""✅ <b>MONITORING STARTED!</b>

📡 Channels: {len(config.monitored_channels)}
⚙️ Settings: {'Signal' if config.use_signal_settings else 'Bot'}
🎯 SL/TP: {'ON' if config.create_sl_tp else 'OFF'}
⚡ Leverage: {config.leverage}x
💰 Balance: {config.balance_percent}%

🎉 <b>Bot is now live on BingX!</b>
Ready to execute trades automatically.

Use /stop_monitoring when you want to stop.""",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ <b>Failed to Start Monitoring</b>\n\n"
            "Check your API configurations and try again.",
            parse_mode='HTML'
        )

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in trading_bot.active_monitoring:
        await update.message.reply_text(
            "⚠️ <b>Not currently monitoring</b>\n\nUse /start_monitoring to start",
            parse_mode='HTML'
        )
        return

    # Stop monitoring
    trading_bot.active_monitoring.pop(user_id, None)

    # Close Telethon client if exists
    if user_id in trading_bot.user_monitoring_clients:
        client = trading_bot.user_monitoring_clients[user_id]
        if client.is_connected():
            await client.disconnect()
        trading_bot.user_monitoring_clients.pop(user_id, None)

    await update.message.reply_text(
        "⏹️ <b>Monitoring Stopped</b>\n\nBot is no longer processing signals.",
        parse_mode='HTML'
    )

# ===================== STATUS & UTILITY HANDLERS =====================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    # Check configurations
    bingx_status = "✅" if all([config.bingx_api_key, config.bingx_api_secret]) else "❌"
    telegram_status = "✅" if all([config.telegram_api_id, config.telegram_api_hash]) else "❌"
    channels_status = "✅" if config.monitored_channels else "❌"
    monitoring_status = "🟢 ACTIVE" if user_id in trading_bot.active_monitoring else "🔴 STOPPED"

    status_text = f"""📊 <b>Bot Status</b>

<b>API Configuration:</b>
• BingX API: {bingx_status}
• Telegram API: {telegram_status}
• Channels: {channels_status} ({len(config.monitored_channels)} selected)

<b>Trading Settings:</b>
• Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}
• SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}
• Leverage: {config.leverage}x
• Stop Loss: {config.stop_loss_percent}%
• Take Profit: {config.take_profit_percent}%
• Balance Usage: {config.balance_percent}%

<b>Monitoring:</b>
• Status: {monitoring_status}

<b>Setup Progress:</b>
1. BingX API: {bingx_status}
2. Telegram API: {telegram_status}
3. Channels: {channels_status}
4. Ready to trade: {'✅' if all([bingx_status=='✅', telegram_status=='✅', channels_status=='✅']) else '❌'}"""

    await update.message.reply_text(status_text, parse_mode='HTML')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not all([config.bingx_api_key, config.bingx_api_secret]):
        await update.message.reply_text(
            "❌ <b>BingX API not configured</b>\n\nRun /setup_bingx first",
            parse_mode='HTML'
        )
        return

    try:
        await update.message.reply_text("💰 Fetching account balance...")

        if not trading_bot.bingx_client:
            await trading_bot.setup_bingx_client(config)

        balance_info = await trading_bot.bingx_client.get_account_balance()

        # Parse balance using the fixed method
        usdt_balance = 0
        if isinstance(balance_info, dict) and balance_info.get('code') == 0:
            data = balance_info.get('data', {})
            balance_obj = data.get('balance', {})

            if isinstance(balance_obj, dict) and balance_obj.get('asset') == 'USDT':
                usdt_balance = float(balance_obj.get('balance', 0))

        trade_amount = usdt_balance * (config.balance_percent / 100)

        balance_text = f"""💰 <b>BingX Account Balance</b>

<b>Futures Account:</b>
• Total USDT: {usdt_balance:.2f}
• Available: {usdt_balance:.2f}

<b>Trading Settings:</b>
• Balance Usage: {config.balance_percent}%
• Trade Amount: {trade_amount:.2f} USDT

<b>With {config.leverage}x Leverage:</b>
• Position Size: {trade_amount * config.leverage:.2f} USDT"""

        await update.message.reply_text(balance_text, parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Error fetching balance:</b>\n\n{str(e)}",
            parse_mode='HTML'
        )

async def test_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_signals = [
        """#BCHUSDT
📈 LONG
Entry: 245.50
Target 1: 250.00
Target 2: 255.00
Stop Loss: 240.00
Leverage: 10x""",

        """#ETH
ШОРТ 📉
Вход: 1850.00
Тп1: 1820.00
Тп2: 1800.00
Сл: 1880.00
Плечо: 20х"""
    ]

    test_text = "🧪 <b>Testing Signal Parsing</b>\n\n"

    for i, signal_text in enumerate(test_signals, 1):
        test_text += f"<b>Test Signal {i}:</b>\n<pre>{signal_text}</pre>\n\n"

        signal = trading_bot.parse_trading_signal(signal_text, "test_channel")

        if signal:
            test_text += f"""✅ <b>Parsed Successfully:</b>
• Symbol: {signal.symbol}
• Direction: {signal.trade_type}
• Entry: {signal.entry_price}
• Take Profits: {signal.take_profit}
• Stop Loss: {signal.stop_loss}
• Leverage: {signal.leverage}

"""
        else:
            test_text += "❌ <b>Parsing Failed</b>\n\n"

    await update.message.reply_text(test_text, parse_mode='HTML')

# ===================== CONVERSATION HANDLERS =====================

def create_conversation_handlers():
    # BingX Setup Conversation
    bingx_conv = ConversationHandler(
        entry_points=[CommandHandler('setup_bingx', setup_bingx)],
        states={
            WAITING_BINGX_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bingx_key)],
            WAITING_BINGX_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bingx_secret)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )

    # Telegram Setup Conversation
    telegram_conv = ConversationHandler(
        entry_points=[CommandHandler('setup_telegram', setup_telegram)],
        states={
            WAITING_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_id)],
            WAITING_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_hash)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )

    return [bingx_conv, telegram_conv]

# ===================== MAIN APPLICATION =====================

def main():
    # Replace with your bot token
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

    application = Application.builder().token(BOT_TOKEN).build()

    # Add conversation handlers
    for conv_handler in create_conversation_handlers():
        application.add_handler(conv_handler)

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setup_channels", setup_channels))
    application.add_handler(CommandHandler("setup_trading", setup_trading))
    application.add_handler(CommandHandler("start_monitoring", start_monitoring))
    application.add_handler(CommandHandler("stop_monitoring", stop_monitoring))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("test_signal", test_signal))

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    print("🚀 BingX Trading Bot v4.4 Starting...")
    print("✅ All API fixes implemented!")
    print("🎯 Ready for BCH-USDT and all BingX pairs!")

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
