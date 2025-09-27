#!/usr/bin/env python3
"""
Telegram Trading Bot v4.4 - BINGX INTEGRATION (COMPLETE FIX)
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

class TradingBot:
    def __init__(self):
        self.config = BotConfig()
        self.bingx_client: Optional[BingXClient] = None
        self.user_monitoring_clients: Dict[int, TelegramClient] = {}
        self.user_data: Dict[int, BotConfig] = {}
        self.active_monitoring = {}
        self.monitoring_tasks = {}

    def parse_trading_signal(self, message: str, channel_id: str) -> Optional[TradingSignal]:
        """Enhanced signal parsing with Russian support"""
        try:
            logger.info(f"🔍 PARSING SIGNAL from channel {channel_id}")
            signals = SignalDetector.parse_signals(message)

            if not signals:
                logger.info("❌ No signals found")
                return None

            s = signals[0]
            if not all([s['symbol'], s['trade_side']]):
                logger.info("❌ Incomplete signal data")
                return None

            logger.info(f"✅ Parsed signal: {s['symbol']} {s['trade_side']}")
            if s['entry']:
                logger.info(f"   Entry: {s['entry']}")
            if s['take_profit']:
                logger.info(f"   TPs: {s['take_profit']}")
            if s['stop_loss']:
                logger.info(f"   SL: {s['stop_loss']}")
            if s['leverage']:
                logger.info(f"   Leverage: {s['leverage']}")

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
            self.user_data[user_id] = BotConfig()
            self.user_data[user_id].user_id = user_id
        return self.user_data[user_id]

    async def setup_bingx_client(self, config: BotConfig) -> bool:
        try:
            self.bingx_client = BingXClient(
                api_key=config.bingx_api_key,
                secret_key=config.bingx_api_secret
            )

            # Test connection by getting balance
            balance_info = await self.bingx_client.get_account_balance()
            logger.info(f"Balance API response: {balance_info}")

            # FIXED: BingX specific balance parsing for single object
            total_balance = 0

            if isinstance(balance_info, dict) and balance_info.get('code') == 0:
                # BingX successful response format
                data = balance_info.get('data', {})
                balance_obj = data.get('balance', {})

                if isinstance(balance_obj, dict):
                    # Single balance object (your case)
                    if balance_obj.get('asset') == 'USDT':
                        total_balance = float(balance_obj.get('balance', 0))
                        logger.info(f"🔍 Parsed single balance object: {total_balance}")

                elif isinstance(balance_obj, list):
                    # Multiple balance objects (fallback)
                    for asset in balance_obj:
                        if isinstance(asset, dict) and asset.get('asset') == 'USDT':
                            total_balance = float(asset.get('balance', 0))
                            logger.info(f"🔍 Found USDT in balance list: {total_balance}")
                            break

            logger.info(f"✅ BingX connected. Futures Balance: {total_balance} USDT")
            return True

        except Exception as e:
            logger.error(f"❌ BingX setup error: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False

    async def setup_telethon_client(self, config: BotConfig) -> bool:
        """FIXED: Setup Telethon client with proper session handling"""
        try:
            session_name = f'session_{config.user_id}'

            # FIXED: Create Telethon client with proper startup parameters
            telethon_client = TelegramClient(
                session_name,
                api_id=int(config.telegram_api_id),
                api_hash=config.telegram_api_hash,
                system_version="4.16.30-vxCUSTOM"
            )

            # FIXED: Start client without interactive login
            # This prevents the "EOF when reading a line" error
            try:
                await telethon_client.start()

                # Test if client is properly authenticated
                me = await telethon_client.get_me()
                logger.info(f"✅ Telethon authenticated as: {me.first_name}")

                self.user_monitoring_clients[config.user_id] = telethon_client
                logger.info(f"✅ Telethon setup successful for user {config.user_id}")
                return True

            except Exception as auth_error:
                logger.error(f"❌ Telethon authentication failed: {auth_error}")

                # If not authenticated, we need session files from local run
                logger.error("❌ Telethon requires pre-authentication")
                logger.error("❌ Please run the bot locally first to create session files")
                logger.error("❌ Then upload session files to server")

                return False

        except Exception as e:
            logger.error(f"❌ Telethon setup error: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
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
                                sl_price: Optional[float], tp_prices: List[float]) -> Dict[str, Any]:
        """FIXED: Create stop loss and take profit orders with proper parameters"""
        try:
            results = {'stop_loss': None, 'take_profits': []}

            # Create Stop Loss Order
            if sl_price:
                try:
                    sl_side = 'Sell' if side == 'Buy' else 'Buy'  # BingX format
                    sl_position_side = "LONG" if side == 'Buy' else "SHORT"  # FIXED: Add positionSide

                    sl_order = await self.bingx_client.create_order(
                        symbol=symbol,
                        side=sl_side,
                        order_type='STOP_MARKET',
                        quantity=quantity,
                        stop_price=sl_price,
                        reduce_only=True,
                        position_side=sl_position_side  # FIXED: Add this parameter
                    )

                    # Better response handling
                    order_id = None
                    if isinstance(sl_order, dict):
                        if 'data' in sl_order and isinstance(sl_order['data'], dict):
                            order_id = sl_order['data'].get('orderId')
                        elif 'orderId' in sl_order:
                            order_id = sl_order['orderId']

                    results['stop_loss'] = order_id
                    logger.info(f"✅ Stop Loss created: {order_id} @ {sl_price}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Stop Loss: {e}")

            # Create Take Profit Orders
            for i, tp_price in enumerate(tp_prices[:3]):  # Max 3 TPs
                try:
                    tp_side = 'Sell' if side == 'Buy' else 'Buy'  # BingX format
                    tp_position_side = "LONG" if side == 'Buy' else "SHORT"  # FIXED: Add positionSide
                    tp_quantity = quantity / len(tp_prices)  # Split quantity across TPs

                    tp_order = await self.bingx_client.create_order(
                        symbol=symbol,
                        side=tp_side,
                        order_type='TAKE_PROFIT_MARKET',
                        quantity=round(tp_quantity, 6),
                        stop_price=tp_price,
                        reduce_only=True,
                        position_side=tp_position_side  # FIXED: Add this parameter
                    )

                    # Better response handling
                    order_id = None
                    if isinstance(tp_order, dict):
                        if 'data' in tp_order and isinstance(tp_order['data'], dict):
                            order_id = tp_order['data'].get('orderId')
                        elif 'orderId' in tp_order:
                            order_id = tp_order['orderId']

                    results['take_profits'].append({
                        'order_id': order_id,
                        'price': tp_price,
                        'quantity': tp_quantity
                    })
                    logger.info(f"✅ Take Profit {i+1} created: {order_id} @ {tp_price}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Take Profit {i+1}: {e}")

            return results

        except Exception as e:
            logger.error(f"❌ Error creating SL/TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """FIXED: Enhanced trade execution with all fixes applied"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")

            if not self.bingx_client:
                success = await self.setup_bingx_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to BingX API'}

            # Get account balance with FIXED parsing
            try:
                logger.info(f"💰 Getting account balance...")
                balance_info = await self.bingx_client.get_account_balance()
                logger.info(f"Raw balance response: {balance_info}")

                usdt_balance = 0

                # FIXED: BingX specific balance parsing for single object
                if isinstance(balance_info, dict) and balance_info.get('code') == 0:
                    data = balance_info.get('data', {})
                    balance_obj = data.get('balance', {})

                    if isinstance(balance_obj, dict):
                        # Single balance object (your case)
                        if balance_obj.get('asset') == 'USDT':
                            usdt_balance = float(balance_obj.get('balance', 0))
                            logger.info(f"✅ Parsed single balance object: {usdt_balance} USDT")

                    elif isinstance(balance_obj, list):
                        # Multiple balance objects (fallback)
                        for asset in balance_obj:
                            if isinstance(asset, dict) and asset.get('asset') == 'USDT':
                                usdt_balance = float(asset.get('balance', 0))
                                logger.info(f"✅ Found USDT in list: {usdt_balance} USDT")
                                break

                if usdt_balance <= 0.1:  # BingX minimum check
                    return {'success': False, 'error': f'Insufficient USDT balance: {usdt_balance}'}

                logger.info(f"✅ Proceeding with balance: {usdt_balance} USDT")

            except Exception as e:
                logger.error(f"❌ Error getting account balance: {e}")
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            # Determine settings to use
            if config.use_signal_settings and signal.leverage:
                leverage = min(signal.leverage, 150)  # BingX max 150x
            else:
                leverage = min(config.leverage, 150)

            logger.info(f"⚙️ Using settings: {'Signal' if config.use_signal_settings else 'Bot'}")
            logger.info(f"⚡ Leverage: {leverage}x")

            # Set leverage
            try:
                await self.bingx_client.set_leverage(symbol=signal.symbol, leverage=leverage)
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage setting warning: {e}")

            # Get current price
            current_price = await self.bingx_client.get_current_price(signal.symbol)
            logger.info(f"💲 Current {signal.symbol} price: {current_price}")

            # Use entry price from signal or current price
            entry_price = signal.entry_price or current_price

            # Calculate position size using BOT settings (always use bot balance %)
            trade_amount = usdt_balance * (config.balance_percent / 100)
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Balance: {usdt_balance} USDT")
            logger.info(f"   Trade amount: {trade_amount} USDT ({config.balance_percent}%)")
            logger.info(f"   Entry price: {entry_price}")
            logger.info(f"   Raw quantity: {raw_quantity}")

            # BingX quantity precision (usually 6 decimal places)
            quantity = round(raw_quantity, 6)

            if quantity <= 0:
                return {'success': False, 'error': 'Calculated quantity is zero or negative'}

            logger.info(f"📦 Final quantity: {quantity}")

            # Execute market order with FIXED parameters
            side = 'Buy' if signal.trade_type == 'LONG' else 'Sell'  # BingX format
            position_side = "LONG" if signal.trade_type == 'LONG' else "SHORT"  # FIXED: Add positionSide

            order = await self.bingx_client.create_order(
                symbol=signal.symbol,
                side=side,
                order_type='MARKET',
                quantity=quantity,
                position_side=position_side  # FIXED: Add this parameter
            )

            # FIXED: Better order response handling
            order_id = "Unknown"
            if isinstance(order, dict):
                if 'data' in order and isinstance(order['data'], dict):
                    order_id = order['data'].get('orderId', 'Unknown')
                elif 'orderId' in order:
                    order_id = order['orderId']

            logger.info(f"✅ Main order executed: {order_id}")

            # Calculate SL/TP prices
            sl_price = None
            tp_prices = []

            if config.create_sl_tp:
                # Determine SL/TP prices
                if config.use_signal_settings:
                    # Use signal SL/TP if available, fallback to bot settings
                    if signal.stop_loss:
                        sl_price = signal.stop_loss
                    else:
                        # Calculate SL from bot percentage
                        if signal.trade_type == 'LONG':
                            sl_price = current_price * (1 - config.stop_loss_percent / 100)
                        else:
                            sl_price = current_price * (1 + config.stop_loss_percent / 100)

                    if signal.take_profit:
                        tp_prices = signal.take_profit
                    else:
                        # Calculate TP from bot percentage
                        if signal.trade_type == 'LONG':
                            tp_prices = [current_price * (1 + config.take_profit_percent / 100)]
                        else:
                            tp_prices = [current_price * (1 - config.take_profit_percent / 100)]
                else:
                    # Always use bot settings
                    if signal.trade_type == 'LONG':
                        sl_price = current_price * (1 - config.stop_loss_percent / 100)
                        tp_prices = [current_price * (1 + config.take_profit_percent / 100)]
                    else:
                        sl_price = current_price * (1 + config.stop_loss_percent / 100)
                        tp_prices = [current_price * (1 - config.take_profit_percent / 100)]

                # Create SL/TP orders
                sl_tp_result = await self.create_sl_tp_orders(
                    signal.symbol, side, quantity, current_price, sl_price, tp_prices
                )

                return {
                    'success': True,
                    'order_id': order_id,
                    'symbol': signal.symbol,
                    'quantity': quantity,
                    'price': current_price,
                    'leverage': leverage,
                    'stop_loss_id': sl_tp_result['stop_loss'],
                    'take_profit_ids': sl_tp_result['take_profits'],
                    'sl_price': sl_price,
                    'tp_prices': tp_prices
                }
            else:
                return {
                    'success': True,
                    'order_id': order_id,
                    'symbol': signal.symbol,
                    'quantity': quantity,
                    'price': current_price,
                    'leverage': leverage
                }

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
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
                            notification = f"""✅ <b>TRADE EXECUTED ON BINGX!</b>

💰 Symbol: {result['symbol']}
📈 Direction: {signal.trade_type}
🆔 Order ID: {result['order_id']}
📦 Quantity: {result['quantity']}
💲 Entry: {result['price']}
⚡ Leverage: {result['leverage']}x"""

                            if 'sl_price' in result and result['sl_price']:
                                notification += f"\n🛑 Stop Loss: {result['sl_price']:.6f}"
                                if result['stop_loss_id']:
                                    notification += f" (ID: {result['stop_loss_id']})"

                            if 'tp_prices' in result and result['tp_prices']:
                                notification += f"\n🎯 Take Profits:"
                                for i, tp in enumerate(result['take_profit_ids']):
                                    notification += f"\n  TP{i+1}: {tp['price']:.6f} (ID: {tp['order_id']})"

                            notification += f"\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
                            notification += f"\n\n🎉 BingX Position is LIVE!"

                        else:
                            notification = f"""❌ <b>BINGX TRADE EXECUTION FAILED</b>

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
        InlineKeyboardButton("➕ Manual", callback_data="add_manual_channel"),
        InlineKeyboardButton("🧹 Clear", callback_data="clear_all_channels")
    ])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="channels_done")])

    return InlineKeyboardMarkup(keyboard)

def create_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)

    keyboard = [
        [InlineKeyboardButton(f"⚙️ Settings Source: {'Signal' if config.use_signal_settings else 'Bot'}", 
                            callback_data="toggle_settings_source")],
        [InlineKeyboardButton(f"📊 SL/TP Orders: {'ON' if config.create_sl_tp else 'OFF'}", 
                            callback_data="toggle_sl_tp")],
        [InlineKeyboardButton(f"⚡ Leverage: {config.leverage}x", callback_data="set_leverage")],
        [InlineKeyboardButton(f"🛑 Stop Loss: {config.stop_loss_percent}%", callback_data="set_stop_loss")],
        [InlineKeyboardButton(f"🎯 Take Profit: {config.take_profit_percent}%", callback_data="set_take_profit")],
        [InlineKeyboardButton(f"💰 Balance: {config.balance_percent}%", callback_data="set_balance_percent")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)
