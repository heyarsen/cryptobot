#!/usr/bin/env python3
"""
Telegram Trading Bot v3.0 - ENHANCED VERSION
- Uses bot settings (leverage, SL, TP, position size)
- Creates SL/TP orders automatically  
- Option to use signal settings vs bot settings
- Enhanced signal parsing for Russian formats
- Interactive setup with buttons
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

from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceOrderException

from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Conversation states
(WAITING_BINANCE_KEY, WAITING_BINANCE_SECRET,
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
    use_signal_settings: bool = True  # NEW: Choose signal vs bot settings
    create_sl_tp: bool = True  # NEW: Auto create SL/TP orders

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

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

            # Extract symbol - enhanced patterns
            sym_match = re.match(r'([A-Z0-9]{1,10})(?:/USDT|USDT)?', symbol_line, re.I)
            if not sym_match:
                continue

            sym = sym_match.group(1).upper()
            if sym.endswith('USDT'):
                symbol = sym
            else:
                symbol = sym + 'USDT'

            # Fix double USDT
            if symbol.endswith('USDUSDT'):
                symbol = symbol.replace('USDUSDT','USDT')

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

            # Leverage - enhanced patterns
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

class TradingBot:
    def __init__(self):
        self.config = BotConfig()
        self.binance_client: Optional[BinanceClient] = None
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

    async def setup_binance_client(self, config: BotConfig) -> bool:
        try:
            self.binance_client = BinanceClient(
                api_key=config.binance_api_key,
                api_secret=config.binance_api_secret,
                testnet=False,
                requests_params={'timeout': 60}
            )

            account_info = self.binance_client.futures_account()
            logger.info(f"✅ Binance connected. Futures Balance: {account_info.get('totalWalletBalance', 'N/A')} USDT")
            return True

        except Exception as e:
            logger.error(f"❌ Binance setup error: {e}")
            return False

    async def setup_telethon_client(self, config: BotConfig) -> bool:
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
                                sl_price: Optional[float], tp_prices: List[float]) -> Dict[str, Any]:
        """Create stop loss and take profit orders"""
        try:
            results = {'stop_loss': None, 'take_profits': []}

            # Create Stop Loss Order
            if sl_price:
                try:
                    sl_side = 'SELL' if side == 'BUY' else 'BUY'
                    sl_order = self.binance_client.futures_create_order(
                        symbol=symbol,
                        side=sl_side,
                        type='STOP_MARKET',
                        quantity=quantity,
                        stopPrice=sl_price,
                        closePosition=True
                    )
                    results['stop_loss'] = sl_order['orderId']
                    logger.info(f"✅ Stop Loss created: {sl_order['orderId']} @ {sl_price}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Stop Loss: {e}")

            # Create Take Profit Orders
            for i, tp_price in enumerate(tp_prices[:3]):  # Max 3 TPs
                try:
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    tp_quantity = quantity / len(tp_prices)  # Split quantity across TPs

                    tp_order = self.binance_client.futures_create_order(
                        symbol=symbol,
                        side=tp_side,
                        type='TAKE_PROFIT_MARKET',
                        quantity=round(tp_quantity, 6),
                        stopPrice=tp_price,
                        closePosition=False
                    )
                    results['take_profits'].append({
                        'order_id': tp_order['orderId'],
                        'price': tp_price,
                        'quantity': tp_quantity
                    })
                    logger.info(f"✅ Take Profit {i+1} created: {tp_order['orderId']} @ {tp_price}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Take Profit {i+1}: {e}")

            return results

        except Exception as e:
            logger.error(f"❌ Error creating SL/TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """Enhanced trade execution with SL/TP orders and configurable settings"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")

            if not self.binance_client:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to Binance API'}

            # Get account balance
            try:
                logger.info(f"💰 Getting account balance...")
                balance_info = self.binance_client.futures_account_balance()
                usdt_balance = 0

                for asset in balance_info:
                    if asset['asset'] == 'USDT':
                        usdt_balance = float(asset['balance'])
                        logger.info(f"✅ Found USDT balance: {usdt_balance}")
                        break

                if usdt_balance == 0:
                    logger.info(f"🔄 Using fallback method...")
                    account = self.binance_client.futures_account()
                    for asset in account['assets']:
                        if asset['asset'] == 'USDT':
                            usdt_balance = float(asset['walletBalance'])
                            logger.info(f"✅ Found USDT balance (fallback): {usdt_balance}")
                            break

                if usdt_balance <= 5:
                    return {'success': False, 'error': f'Insufficient USDT balance: {usdt_balance}'}

            except Exception as e:
                logger.error(f"❌ Error getting account balance: {e}")
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            # Determine settings to use
            if config.use_signal_settings and signal.leverage:
                leverage = signal.leverage
            else:
                leverage = config.leverage

            logger.info(f"⚙️ Using settings: {'Signal' if config.use_signal_settings else 'Bot'}")
            logger.info(f"⚡ Leverage: {leverage}x")

            # Set leverage
            try:
                self.binance_client.futures_change_leverage(symbol=signal.symbol, leverage=leverage)
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage setting warning: {e}")

            # Get current price
            ticker = self.binance_client.futures_symbol_ticker(symbol=signal.symbol)
            current_price = float(ticker['price'])
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

            # Get symbol precision
            try:
                exchange_info = self.binance_client.futures_exchange_info()
                symbol_info = None
                for s in exchange_info['symbols']:
                    if s['symbol'] == signal.symbol:
                        symbol_info = s
                        break

                if not symbol_info:
                    return {'success': False, 'error': f'Symbol {signal.symbol} not found'}

                step_size = None
                min_qty = None
                for f in symbol_info['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = float(f['stepSize'])
                        min_qty = float(f['minQty'])
                        break

                if step_size:
                    if '.' in str(step_size):
                        precision = len(str(step_size).rstrip('0').split('.')[-1])
                    else:
                        precision = 0

                    quantity = round(raw_quantity / step_size) * step_size
                    quantity = round(quantity, precision)

                    logger.info(f"📏 Step size: {step_size}, Min qty: {min_qty}")
                    logger.info(f"📦 Final quantity: {quantity}")

                    if quantity < min_qty:
                        return {'success': False, 'error': f'Quantity {quantity} below minimum {min_qty}'}
                else:
                    quantity = round(raw_quantity, 6)

                if quantity <= 0:
                    return {'success': False, 'error': 'Calculated quantity is zero or negative'}

            except Exception as e:
                logger.error(f"❌ Error getting symbol info: {e}")
                return {'success': False, 'error': f'Symbol info error: {str(e)}'}

            # Execute market order
            side = 'BUY' if signal.trade_type == 'LONG' else 'SELL'

            order = self.binance_client.futures_create_order(
                symbol=signal.symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )

            logger.info(f"✅ Main order executed: {order['orderId']}")

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
                    'order_id': order['orderId'],
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
                    'order_id': order['orderId'],
                    'symbol': signal.symbol,
                    'quantity': quantity,
                    'price': current_price,
                    'leverage': leverage
                }

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
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
                            notification = f"""✅ <b>TRADE EXECUTED!</b>

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

# ===================== ALL COMMAND HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """🤖 <b>Telegram Trading Bot v3.0</b>

🎉 <b>ENHANCED VERSION FEATURES:</b>
• ⚙️ Choose Signal vs Bot settings
• 🎯 Auto SL/TP order creation  
• 📊 Enhanced Russian signal parsing
• 💰 Uses your configured position sizes
• 🔧 Interactive setup with buttons

<b>Setup Steps:</b>
1️⃣ /setup_binance - Binance API
2️⃣ /setup_telegram - Telegram API  
3️⃣ /setup_channels - Select channels
4️⃣ /setup_trading - Trading params + SL/TP
5️⃣ /start_monitoring - Begin trading

<b>Commands:</b>
/help - All commands
/status - Configuration
/test_signal - Test parsing
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """<b>📖 All Commands</b>

<b>Setup:</b>
/setup_binance - Binance API ✅
/setup_telegram - Telegram API ✅  
/setup_channels - Channel selection ✅
/setup_trading - Trading parameters + SL/TP ✅

<b>Control:</b>
/start_monitoring - Start monitoring ✅
/stop_monitoring - Stop monitoring ✅
/status - Current status ✅
/test_signal - Test signal parsing ✅

🎉 <b>NEW FEATURES:</b>
• Choose Signal vs Bot settings
• Auto SL/TP order creation
• Enhanced parsing for Russian signals
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    settings_source = "📊 Signal" if config.use_signal_settings else "🤖 Bot"
    sl_tp_status = "🟢 ON" if config.create_sl_tp else "🔴 OFF"

    status_text = f"""📊 <b>Bot Status Dashboard v3.0</b>

🔧 <b>Configuration:</b>
{'✅' if config.binance_api_key else '❌'} Binance API
{'✅' if config.telegram_api_id else '❌'} Telegram API  
📡 Channels: <b>{len(config.monitored_channels)}</b>
🔄 Monitoring: {'🟢 Active' if trading_bot.active_monitoring.get(user_id) else '🔴 Inactive'}

⚙️ <b>Trading Settings:</b>
🎯 Settings Source: <b>{settings_source}</b>
📈 SL/TP Creation: <b>{sl_tp_status}</b>
⚡ Bot Leverage: <b>{config.leverage}x</b>
🛑 Bot Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Bot Take Profit: <b>{config.take_profit_percent}%</b>
💰 Position Size: <b>{config.balance_percent}%</b>

✅ <b>Enhanced Features:</b>
• Auto SL/TP orders
• Russian signal parsing
• Configurable settings priority
"""
    await update.message.reply_text(status_text, parse_mode='HTML')

# ================== BINANCE SETUP ==================

async def setup_binance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """🔑 <b>Binance API Setup</b>

Send your Binance API Key:

⚠️ <b>Requirements:</b>
• Futures trading enabled
• API key with Futures permissions
• Sufficient balance (minimum 5 USDT)""", parse_mode='HTML')
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

    await update.message.reply_text("🔄 Testing Binance connection...")
    success = await trading_bot.setup_binance_client(config)

    if success:
        await update.message.reply_text(
            """✅ <b>Binance configured successfully!</b>

Next step: /setup_telegram

⚠️ <b>Important:</b>
Your API key has Futures permissions enabled!""", 
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            """❌ <b>Binance configuration failed!</b>

<b>Common fixes:</b>
• Check API key and secret are correct
• Enable Futures trading on your account
• Enable Futures permissions on API key
• Check IP whitelist settings""", 
            parse_mode='HTML'
        )

    return ConversationHandler.END

# ================== TELEGRAM SETUP ==================

async def setup_telegram_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """📱 <b>Telegram API Setup</b>

Send your Telegram API ID:

ℹ️ <b>Get from:</b> https://my.telegram.org/apps
• Login with your phone number
• Create new application
• Copy API ID and Hash""", parse_mode='HTML')
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

    await update.message.reply_text("🔄 Testing Telegram API connection...")
    success = await trading_bot.setup_telethon_client(config)

    if success:
        await update.message.reply_text("✅ <b>Telegram API configured!</b> Next: /setup_channels", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ <b>Configuration failed!</b> Check API credentials", parse_mode='HTML')

    return ConversationHandler.END

# ================== CHANNEL SETUP ==================

async def setup_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    await update.message.reply_text("🔍 <b>Loading your channels...</b>", parse_mode='HTML')

    channels = await trading_bot.get_available_channels(user_id)

    if not channels:
        await update.message.reply_text("❌ <b>No channels found!</b> Configure Telegram API first with /setup_telegram", parse_mode='HTML')
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
    query = update.callback_query
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        await query.answer()
    except:
        pass

    if query.data == "channels_done":
        await query.edit_message_text(
            f"""✅ <b>Channel selection complete!</b>

Monitoring: <b>{len(config.monitored_channels)}</b> channels

Next step: /setup_trading to configure parameters""",
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
            """📝 <b>Manual Channel ID Input</b>

Send the channel ID (numbers only):

<b>Format:</b> <code>-1001234567890</code>

<b>How to get Channel ID:</b>
• Forward message to @userinfobot
• Use @RawDataBot""",
            parse_mode='HTML'
        )
        return WAITING_MANUAL_CHANNEL

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
        await update.message.reply_text("❌ <b>Invalid format!</b> Send numeric ID like: <code>-1001234567890</code>", parse_mode='HTML')
        return WAITING_MANUAL_CHANNEL

    if not channel_id.startswith('-'):
        channel_id = '-' + channel_id

    if channel_id not in config.monitored_channels:
        config.monitored_channels.append(channel_id)

    await update.message.reply_text(
        f"""✅ <b>Channel added successfully!</b>

Channel ID: <code>{channel_id}</code>
Total monitoring: <b>{len(config.monitored_channels)}</b> channels

Use /setup_trading to configure parameters""",
        parse_mode='HTML'
    )

    return ConversationHandler.END

# ================== ENHANCED TRADING SETUP ==================

async def setup_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_settings_keyboard(user_id)

    await update.message.reply_text(
        """⚙️ <b>Enhanced Trading Setup v3.0</b>

🎯 <b>Settings Source:</b>
• <b>Signal</b>: Use leverage/SL/TP from signals (fallback to bot)
• <b>Bot</b>: Always use your configured settings

📊 <b>SL/TP Orders:</b>
• <b>ON</b>: Auto-create stop loss & take profit orders
• <b>OFF</b>: Only create main position

Click any parameter to change it:""",
        reply_markup=keyboard_markup,
        parse_mode='HTML'
    )
    return WAITING_LEVERAGE

async def handle_trading_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    await query.answer()

    if query.data == "trading_done":
        settings_source = "Signal" if config.use_signal_settings else "Bot"
        sl_tp_status = "ON" if config.create_sl_tp else "OFF"

        await query.edit_message_text(
            f"""✅ <b>Trading setup complete!</b>

⚙️ <b>Configuration:</b>
🎯 Settings Source: <b>{settings_source}</b>
📊 SL/TP Creation: <b>{sl_tp_status}</b>
⚡ Leverage: <b>{config.leverage}x</b>
🛑 Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Take Profit: <b>{config.take_profit_percent}%</b>
💰 Position Size: <b>{config.balance_percent}%</b>

Ready to start: /start_monitoring""", 
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_reply_markup(reply_markup=keyboard_markup)
        return WAITING_LEVERAGE

    elif query.data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_reply_markup(reply_markup=keyboard_markup)
        return WAITING_LEVERAGE

    elif query.data == "set_leverage":
        await query.edit_message_text("⚡ <b>Set Bot Leverage</b>\n\nSend leverage (1-125):", parse_mode='HTML')
        return WAITING_LEVERAGE

    elif query.data == "set_stop_loss":
        await query.edit_message_text("🛑 <b>Set Bot Stop Loss %</b>\n\nSend percentage (0.5-20):", parse_mode='HTML')
        return WAITING_STOP_LOSS

    elif query.data == "set_take_profit":
        await query.edit_message_text("🎯 <b>Set Bot Take Profit %</b>\n\nSend percentage (1-100):", parse_mode='HTML')
        return WAITING_TAKE_PROFIT

    elif query.data == "set_balance_percent":
        await query.edit_message_text("💰 <b>Set Position Size %</b>\n\nSend percentage per trade (0.1-10):", parse_mode='HTML')
        return WAITING_BALANCE_PERCENT

async def handle_leverage_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        leverage = int(update.message.text.strip())
        if 1 <= leverage <= 125:
            config.leverage = leverage
            await update.message.reply_text(f"✅ <b>Bot leverage set to {leverage}x</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid! Enter 1-125", parse_mode='HTML')
            return WAITING_LEVERAGE
    except ValueError:
        await update.message.reply_text("❌ Invalid! Enter a number", parse_mode='HTML')
        return WAITING_LEVERAGE

    return ConversationHandler.END

async def handle_stop_loss_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        stop_loss = float(update.message.text.strip())
        if 0.1 <= stop_loss <= 50:
            config.stop_loss_percent = stop_loss
            await update.message.reply_text(f"✅ <b>Bot stop loss set to {stop_loss}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid! Enter 0.1-50", parse_mode='HTML')
            return WAITING_STOP_LOSS
    except ValueError:
        await update.message.reply_text("❌ Invalid! Enter a number", parse_mode='HTML')
        return WAITING_STOP_LOSS

    return ConversationHandler.END

async def handle_take_profit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id  
    config = trading_bot.get_user_config(user_id)

    try:
        take_profit = float(update.message.text.strip())
        if 1 <= take_profit <= 100:
            config.take_profit_percent = take_profit
            await update.message.reply_text(f"✅ <b>Bot take profit set to {take_profit}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid! Enter 1-100", parse_mode='HTML')
            return WAITING_TAKE_PROFIT
    except ValueError:
        await update.message.reply_text("❌ Invalid! Enter a number", parse_mode='HTML')
        return WAITING_TAKE_PROFIT

    return ConversationHandler.END

async def handle_balance_percent_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        balance_percent = float(update.message.text.strip())
        if 0.1 <= balance_percent <= 20:
            config.balance_percent = balance_percent
            await update.message.reply_text(f"✅ <b>Position size set to {balance_percent}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid! Enter 0.1-20", parse_mode='HTML')
            return WAITING_BALANCE_PERCENT
    except ValueError:
        await update.message.reply_text("❌ Invalid! Enter a number", parse_mode='HTML')
        return WAITING_BALANCE_PERCENT

    return ConversationHandler.END

# ================== MONITORING COMMANDS ==================

async def start_monitoring_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    missing = []
    if not config.binance_api_key:
        missing.append("/setup_binance")
    if not config.telegram_api_id:
        missing.append("/setup_telegram")
    if not config.monitored_channels:
        missing.append("/setup_channels")

    if missing:
        await update.message.reply_text(f"❌ <b>Setup incomplete!</b>\n\nMissing: {' '.join(missing)}", parse_mode='HTML')
        return

    if trading_bot.active_monitoring.get(user_id):
        await update.message.reply_text("⚠️ <b>Already monitoring!</b> Use /stop_monitoring first", parse_mode='HTML')
        return

    await update.message.reply_text("🚀 <b>Starting enhanced monitoring...</b>", parse_mode='HTML')

    success = await trading_bot.start_monitoring(user_id, context.bot)

    if success:
        settings_source = "📊 Signal" if config.use_signal_settings else "🤖 Bot"
        sl_tp_status = "🟢 ON" if config.create_sl_tp else "🔴 OFF"

        await update.message.reply_text(
            f"""🟢 <b>ENHANCED MONITORING STARTED!</b>

📡 Watching <b>{len(config.monitored_channels)}</b> channels
⚙️ Settings Source: <b>{settings_source}</b>
📊 SL/TP Creation: <b>{sl_tp_status}</b>
⚡ Bot Leverage: <b>{config.leverage}x</b>
🛑 Bot Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Bot Take Profit: <b>{config.take_profit_percent}%</b>
💰 Position Size: <b>{config.balance_percent}%</b>

✅ <b>Enhanced Features Active:</b>
• Auto SL/TP order creation
• Russian signal parsing (Плечо, Сл, Тп)
• Configurable settings priority
• Improved error handling

🎯 <b>Ready for advanced trading!</b>
Send signals like:
#BAKE/USDT
LONG
Плечо: 5x-50x
Сл:На ваше усмотрение 
Тп: 60%+""",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ <b>Failed to start monitoring</b>", parse_mode='HTML')

async def stop_monitoring_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not trading_bot.active_monitoring.get(user_id):
        await update.message.reply_text("ℹ️ <b>Not currently monitoring</b>", parse_mode='HTML')
        return

    trading_bot.active_monitoring[user_id] = False
    await update.message.reply_text("🔴 <b>Enhanced monitoring stopped</b>", parse_mode='HTML')

# ================== TEST SIGNAL ==================

async def test_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    samples = [
        """🚀 SIGNAL ALERT 🚀
#BTCUSDT LONG
Entry: 109642
Target 1: 109890
Target 2: 110350
Stop Loss: 109000
Leverage: 10x""",

        """#BAKE/USDT
LONG
Плечо: 5x-50x
Сл:На ваше усмотрение 
Тп: 60%+
Осторожно 🛑""",

        """#SOL/USDT
LONG
Entry: 135.5
Плечо: 20х
Сл: 130.0
Тп: 145.0"""
    ]

    results = []
    for i, msg in enumerate(samples, 1):
        signal = trading_bot.parse_trading_signal(msg, "test")
        if signal:
            result_text = f"✅ Sample {i}: {signal.symbol} {signal.trade_type}"
            if signal.entry_price:
                result_text += f" @ {signal.entry_price}"
            if signal.leverage:
                result_text += f" ({signal.leverage}x)"
            results.append(result_text)
        else:
            results.append(f"❌ Sample {i}: Failed to parse")

    await update.message.reply_text(
        f"""🧪 <b>Enhanced Signal Parser Test v3.0</b>

{chr(10).join(results)}

✅ <b>Enhanced Features:</b>
• Russian parsing (Плечо, Сл, Тп)
• Multiple entry patterns
• Flexible TP detection
• Leverage range support
• Settings priority system

🚀 <b>Ready for advanced trading!</b>""",
        parse_mode='HTML'
    )

# ================== ERROR HANDLER ==================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ================== MAIN FUNCTION ==================

def main():
    BOT_TOKEN = '8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4'

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_error_handler(error_handler)

    # Basic commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("start_monitoring", start_monitoring_command))
    application.add_handler(CommandHandler("stop_monitoring", stop_monitoring_command))
    application.add_handler(CommandHandler("test_signal", test_signal))

    # ALL CONVERSATION HANDLERS
    binance_handler = ConversationHandler(
        entry_points=[CommandHandler("setup_binance", setup_binance)],
        states={
            WAITING_BINANCE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_key)],
            WAITING_BINANCE_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_secret)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )

    telegram_handler = ConversationHandler(
        entry_points=[CommandHandler("setup_telegram", setup_telegram_api)],
        states={
            WAITING_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_id)],
            WAITING_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_hash)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )

    channels_handler = ConversationHandler(
        entry_points=[CommandHandler("setup_channels", setup_channels)],
        states={
            WAITING_CHANNEL_SELECTION: [
                CallbackQueryHandler(handle_channel_selection,
                    pattern=r"^(toggle_channel_.*|channels_done|clear_all_channels|add_manual_channel)$")
            ],
            WAITING_MANUAL_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_channel)
            ],
        },
        fallbacks=[CommandHandler("cancel", start)],
        allow_reentry=True
    )

    trading_handler = ConversationHandler(
        entry_points=[CommandHandler("setup_trading", setup_trading)],
        states={
            WAITING_LEVERAGE: [
                CallbackQueryHandler(handle_trading_setup,
                    pattern=r"^(set_leverage|set_stop_loss|set_take_profit|set_balance_percent|trading_done|toggle_settings_source|toggle_sl_tp)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leverage_input)
            ],
            WAITING_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stop_loss_input)],
            WAITING_TAKE_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_take_profit_input)],
            WAITING_BALANCE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_balance_percent_input)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )

    # Add ALL handlers
    application.add_handler(binance_handler)
    application.add_handler(telegram_handler)
    application.add_handler(channels_handler)
    application.add_handler(trading_handler)

    logger.info("🚀 Enhanced Trading Bot v3.0 - READY!")
    logger.info("✅ ENHANCED FEATURES:")
    logger.info("   • Signal vs Bot settings choice")
    logger.info("   • Auto SL/TP order creation")
    logger.info("   • Russian signal parsing")
    logger.info("   • Interactive setup with buttons")
    logger.info("   • Improved error handling")

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
