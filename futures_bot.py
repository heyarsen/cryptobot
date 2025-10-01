#!/usr/bin/env python3
"""
Telegram Trading Bot v4.0 - MULTI-CHANNEL API KEYS
- NEW: Different BingX API keys per channel
- NEW: Subaccount support per channel
- Feature: Per-channel trading configuration
- Feature: Auto-cancel SL when TP fills (OCO simulation)
- Fixed: Decimal precision for all price levels
"""

import asyncio
import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import os
import sys
import traceback
import requests

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

from bingx import BingX

# Import Telethon
from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Auto-configured Telegram API Credentials
DEFAULT_TELEGRAM_API_ID = '23312577'
DEFAULT_TELEGRAM_API_HASH = 'e879a3e9fd3d45cee98ef55214092805'

# Conversation states
(WAITING_BINGX_KEY, WAITING_BINGX_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE, WAITING_WEBHOOK_URL,
 WAITING_MIN_ORDER, WAITING_TP1_PERCENT, WAITING_TP1_CLOSE,
 WAITING_TP2_PERCENT, WAITING_TP2_CLOSE,
 WAITING_TP3_PERCENT, WAITING_TP3_CLOSE,
 WAITING_TRAILING_CALLBACK, WAITING_TRAILING_ACTIVATION,
 WAITING_CHANNEL_API_KEY, WAITING_CHANNEL_API_SECRET,
 WAITING_CHANNEL_SUBACCOUNT) = range(24)

# Your Make.com Webhook URL
DEFAULT_WEBHOOK_URL = "https://hook.eu2.make.com/whf9it0leksyn2hffklu1rho7wywsava"

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
class ChannelAPIConfig:
    """Store API credentials for each channel"""
    channel_id: str
    api_key: str = ""
    api_secret: str = ""
    subaccount: str = ""  # Optional subaccount identifier

    def is_configured(self) -> bool:
        """Check if channel has API credentials configured"""
        return bool(self.api_key and self.api_secret)

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
    # NEW: Store API configs per channel
    channel_api_configs: Dict[str, ChannelAPIConfig] = field(default_factory=dict)

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

    def get_channel_api_config(self, channel_id: str) -> Optional[ChannelAPIConfig]:
        """Get API config for specific channel"""
        return self.channel_api_configs.get(channel_id)

    def set_channel_api_config(self, channel_id: str, api_key: str, api_secret: str, subaccount: str = ""):
        """Set API credentials for a channel"""
        self.channel_api_configs[channel_id] = ChannelAPIConfig(
            channel_id=channel_id,
            api_key=api_key,
            api_secret=api_secret,
            subaccount=subaccount
        )

@dataclass
class ActivePosition:
    """Track active positions with their SL/TP orders"""
    symbol: str
    user_id: int
    side: str
    quantity: float
    entry_price: float
    channel_id: str = ""
    stop_loss_order_id: Optional[int] = None
    take_profit_order_ids: List[int] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.take_profit_order_ids is None:
            self.take_profit_order_ids = []
        if self.timestamp is None:
            self.timestamp = datetime.now()

class MakeWebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_trade_data(self, trade_data: Dict[str, Any]) -> bool:
        """Send trade data to Make.com webhook"""
        try:
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
                "subaccount": str(trade_data.get('subaccount', '')),
                "webhook_version": "4.0",
                "bot_source": "Telegram Trading Bot",
                "time": datetime.now().strftime('%H:%M:%S'),
                "date": datetime.now().strftime('%Y-%m-%d')
            }

            clean_payload = {k: v for k, v in payload.items() if v and str(v).strip()}

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/4.0',
                'X-Bot-Version': '4.0'
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
                logger.error(f"❌ Make.com webhook error. Status: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"❌ Make.com webhook error: {e}")
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

class TradingBot:
    def __init__(self):
        self.config = BotConfig()
        # NEW: Store BingX clients per channel
        self.bingx_clients: Dict[str, BingX] = {}
        self.user_monitoring_clients: Dict[int, TelegramClient] = {}
        self.user_data: Dict[int, BotConfig] = {}
        self.active_monitoring = {}
        self.monitoring_tasks = {}
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.active_positions: Dict[str, ActivePosition] = {}
        self.order_monitor_running = False

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

            logger.info(f"✅ Make.com webhook setup for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Make.com webhook setup error: {e}")
            return False

    async def get_bingx_client_for_channel(self, channel_id: str, config: BotConfig) -> Optional[BingX]:
        """Get or create BingX client for specific channel"""
        try:
            # Check if we already have a client for this channel
            if channel_id in self.bingx_clients:
                return self.bingx_clients[channel_id]

            # Get API config for this channel
            channel_api = config.get_channel_api_config(channel_id)
            if not channel_api or not channel_api.is_configured():
                logger.error(f"❌ No API configuration for channel {channel_id}")
                return None

            # Create new BingX client for this channel
            client = BingX(
                api_key=channel_api.api_key,
                api_secret=channel_api.api_secret,
                testnet=False,
                requests_params={'timeout': 60}
            )

            # Test connection
            account_info = client.swap_user()
            logger.info(f"✅ BingX client created for channel {channel_id}")
            if channel_api.subaccount:
                logger.info(f"   Subaccount: {channel_api.subaccount}")
            logger.info(f"   Balance: {account_info.get('totalWalletBalance', 'N/A')} USDT")

            # Cache the client
            self.bingx_clients[channel_id] = client
            return client

        except Exception as e:
            logger.error(f"❌ Error creating BingX client for channel {channel_id}: {e}")
            return None

    def get_symbol_precision(self, symbol: str, client: BingX) -> Dict[str, Any]:
        """Get and cache symbol precision information"""
        try:
            cache_key = f"{symbol}_{id(client)}"
            if cache_key in self.symbol_info_cache:
                return self.symbol_info_cache[cache_key]

            exchange_info = client.swap_exchangeInfo()
            symbol_info = None

            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    symbol_info = s
                    break

            if not symbol_info:
                return {'error': f'Symbol {symbol} not found'}

            # Get LOT_SIZE filter
            step_size = None
            min_qty = None
            for f in symbol_info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    min_qty = float(f['minQty'])
                    break

            # Get PRICE_FILTER
            tick_size = None
            min_price = None
            max_price = None
            for f in symbol_info['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    tick_size = float(f['tickSize'])
                    min_price = float(f['minPrice'])
                    max_price = float(f['maxPrice'])
                    break

            # Calculate precision decimals
            qty_precision = 0
            price_precision = 0

            if step_size and step_size > 0:
                step_str = f"{step_size:.10f}".rstrip('0')
                if '.' in step_str:
                    qty_precision = len(step_str.split('.')[-1])
            else:
                step_size = 1.0

            if tick_size and tick_size > 0:
                tick_str = f"{tick_size:.10f}".rstrip('0')
                if '.' in tick_str:
                    price_precision = len(tick_str.split('.')[-1])
            else:
                tick_size = 0.00001
                price_precision = 5

            precision_info = {
                'step_size': step_size,
                'min_qty': min_qty if min_qty else 1.0,
                'tick_size': tick_size,
                'min_price': min_price if min_price else 0.00001,
                'max_price': max_price if max_price else 1000000.0,
                'qty_precision': max(qty_precision, 0),
                'price_precision': max(price_precision, 5)
            }

            self.symbol_info_cache[cache_key] = precision_info
            logger.info(f"📏 Symbol precision for {symbol}: qty={precision_info['qty_precision']}, price={precision_info['price_precision']}")
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
        """Round price to match tick size and precision"""
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

    async def cancel_related_orders(self, symbol: str, user_id: int, filled_order_type: str, bot_instance, client: BingX):
        """Cancel SL when TP fills, or cancel all TPs when SL fills"""
        try:
            position = self.active_positions.get(symbol)
            if not position:
                logger.info(f"⚠️ No active position found for {symbol}")
                return

            logger.info(f"🔄 Canceling related orders for {symbol} after {filled_order_type} filled")

            cancelled_orders = []

            if filled_order_type == "TAKE_PROFIT" and position.stop_loss_order_id:
                try:
                    client.swap_cancelOrder(
                        symbol=symbol,
                        orderId=position.stop_loss_order_id
                    )
                    cancelled_orders.append(f"SL-{position.stop_loss_order_id}")
                    logger.info(f"✅ Cancelled Stop Loss order: {position.stop_loss_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to cancel SL: {e}")

            elif filled_order_type == "STOP_LOSS" and position.take_profit_order_ids:
                for tp_id in position.take_profit_order_ids:
                    try:
                        client.swap_cancelOrder(
                            symbol=symbol,
                            orderId=tp_id
                        )
                        cancelled_orders.append(f"TP-{tp_id}")
                        logger.info(f"✅ Cancelled Take Profit order: {tp_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to cancel TP {tp_id}: {e}")

            if symbol in self.active_positions:
                del self.active_positions[symbol]
                logger.info(f"🗑️ Removed {symbol} from active positions")

            if cancelled_orders:
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=f"🔄 <b>Auto-Cancelled Orders</b>\n\n💰 {symbol}\n📋 Cancelled: {', '.join(cancelled_orders)}\n⚠️ Reason: {filled_order_type} was filled",
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
                            # Get the right client for this position's channel
                            config = self.get_user_config(position.user_id)
                            client = await self.get_bingx_client_for_channel(position.channel_id, config)
                            if not client:
                                continue

                            open_orders = client.swap_openOrders(symbol=symbol)
                            open_order_ids = [int(order['orderId']) for order in open_orders]

                            if position.stop_loss_order_id and position.stop_loss_order_id not in open_order_ids:
                                logger.info(f"🛑 Stop Loss filled for {symbol}")
                                await self.cancel_related_orders(symbol, position.user_id, "STOP_LOSS", bot_instance, client)

                            for tp_id in position.take_profit_order_ids:
                                if tp_id not in open_order_ids:
                                    logger.info(f"🎯 Take Profit filled for {symbol}")
                                    await self.cancel_related_orders(symbol, position.user_id, "TAKE_PROFIT", bot_instance, client)
                                    break

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

    async def create_sl_tp_orders(self, symbol: str, side: str, quantity: float, entry_price: float, 
                                sl_price: Optional[float], tp_prices: List[float], user_id: int, 
                                channel_id: str, client: BingX) -> Dict[str, Any]:
        """Create stop loss and take profit orders with PROPER PRECISION and OCO tracking"""
        try:
            results = {'stop_loss': None, 'take_profits': []}

            precision_info = self.get_symbol_precision(symbol, client)
            if 'error' in precision_info:
                logger.error(f"❌ Cannot create SL/TP: {precision_info['error']}")
                return results

            tick_size = precision_info['tick_size']
            price_precision = precision_info['price_precision']
            step_size = precision_info['step_size']
            qty_precision = precision_info['qty_precision']

            logger.info(f"📐 Using precision: price={price_precision} decimals, qty={qty_precision} decimals")

            if sl_price:
                try:
                    sl_side = 'SELL' if side == 'BUY' else 'BUY'
                    sl_price_rounded = self.round_price(sl_price, tick_size, price_precision)

                    logger.info(f"🛑 Creating Stop Loss: {sl_price_rounded}")

                    if sl_price_rounded <= 0:
                        logger.error(f"❌ Invalid SL price after rounding: {sl_price_rounded}")
                        return results

                    sl_order = client.swap_order(
                        symbol=symbol,
                        side=sl_side,
                        type='STOP_MARKET',
                        quantity=quantity,
                        stopPrice=sl_price_rounded,
                        closePosition=True
                    )
                    results['stop_loss'] = sl_order['orderId']
                    logger.info(f"✅ Stop Loss created: {sl_order['orderId']} @ {sl_price_rounded}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Stop Loss: {e}")

            for i, tp_price in enumerate(tp_prices[:3]):
                try:
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    tp_quantity = quantity / len(tp_prices)

                    tp_price_rounded = self.round_price(tp_price, tick_size, price_precision)
                    tp_quantity_rounded = self.round_quantity(tp_quantity, step_size, qty_precision)

                    logger.info(f"🎯 Creating Take Profit {i+1}: {tp_price_rounded} qty={tp_quantity_rounded}")

                    if tp_price_rounded <= 0:
                        logger.error(f"❌ Invalid TP price after rounding: {tp_price_rounded}")
                        continue

                    tp_order = client.swap_order(
                        symbol=symbol,
                        side=tp_side,
                        type='TAKE_PROFIT_MARKET',
                        quantity=tp_quantity_rounded,
                        stopPrice=tp_price_rounded,
                        closePosition=False
                    )
                    results['take_profits'].append({
                        'order_id': tp_order['orderId'],
                        'price': tp_price_rounded,
                        'quantity': tp_quantity_rounded
                    })
                    logger.info(f"✅ Take Profit {i+1} created: {tp_order['orderId']} @ {tp_price_rounded}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Take Profit {i+1}: {e}")

            if results['stop_loss'] or results['take_profits']:
                position = ActivePosition(
                    symbol=symbol,
                    user_id=user_id,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    channel_id=channel_id,
                    stop_loss_order_id=results['stop_loss'],
                    take_profit_order_ids=[tp['order_id'] for tp in results['take_profits']]
                )
                self.active_positions[symbol] = position
                logger.info(f"📍 Tracking position for {symbol} with OCO monitoring")

            return results

        except Exception as e:
            logger.error(f"❌ Error creating SL/TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

# (Continue with remaining code...)

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """Enhanced trade execution with per-channel API credentials"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type} for channel {signal.channel_id}")

            # Get BingX client for this specific channel
            client = await self.get_bingx_client_for_channel(signal.channel_id, config)
            if not client:
                return {'success': False, 'error': f'No API configuration for channel {signal.channel_id}'}

            channel_api = config.get_channel_api_config(signal.channel_id)

            try:
                logger.info(f"💰 Getting account balance for channel {signal.channel_id}...")
                balance_info = client.swap_balance()
                usdt_balance = 0

                for asset in balance_info:
                    if asset['asset'] == 'USDT':
                        usdt_balance = float(asset['balance'])
                        logger.info(f"✅ Found USDT balance: {usdt_balance}")
                        break

                if usdt_balance == 0:
                    logger.info(f"🔄 Using fallback method...")
                    account = client.swap_user()
                    for asset in account['assets']:
                        if asset['asset'] == 'USDT':
                            usdt_balance = float(asset['walletBalance'])
                            logger.info(f"✅ Found USDT balance (fallback): {usdt_balance}")
                            break

            except Exception as e:
                logger.error(f"❌ Error getting account balance: {e}")
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            if config.use_signal_settings and signal.leverage:
                leverage = signal.leverage
            else:
                leverage = config.leverage

            logger.info(f"⚙️ Using settings: {'Signal' if config.use_signal_settings else 'Bot'}")
            logger.info(f"⚡ Leverage: {leverage}x")
            if channel_api.subaccount:
                logger.info(f"🔑 Subaccount: {channel_api.subaccount}")

            try:
                client.swap_changeLeverage(symbol=signal.symbol, leverage=leverage)
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage setting warning: {e}")

            ticker = client.swap_ticker(symbol=signal.symbol)
            current_price = float(ticker['price'])
            logger.info(f"💲 Current {signal.symbol} price: {current_price}")

            entry_price = signal.entry_price or current_price
            trade_amount = usdt_balance * (config.balance_percent / 100)
            position_value = trade_amount * leverage
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Balance: {usdt_balance} USDT")
            logger.info(f"   Trade amount: ${trade_amount:.2f} ({config.balance_percent}%)")
            logger.info(f"   Entry price: {entry_price}")
            logger.info(f"   Raw quantity: {raw_quantity}")

            precision_info = self.get_symbol_precision(signal.symbol, client)
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
            side = 'BUY' if signal.trade_type == 'LONG' else 'SELL'

            order = client.swap_order(
                symbol=signal.symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )

            logger.info(f"✅ Main order executed: {order['orderId']}")

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
                        tp_prices = signal.take_profit
                    else:
                        if signal.trade_type == 'LONG':
                            tp_prices = [current_price * (1 + config.take_profit_percent / 100)]
                        else:
                            tp_prices = [current_price * (1 - config.take_profit_percent / 100)]
                else:
                    if signal.trade_type == 'LONG':
                        sl_price = current_price * (1 - config.stop_loss_percent / 100)
                        tp_prices = [current_price * (1 + config.take_profit_percent / 100)]
                    else:
                        sl_price = current_price * (1 + config.stop_loss_percent / 100)
                        tp_prices = [current_price * (1 - config.take_profit_percent / 100)]

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

                sl_tp_result = await self.create_sl_tp_orders(
                    signal.symbol, side, quantity, current_price, sl_price, tp_prices, 
                    config.user_id, signal.channel_id, client
                )

            if config.make_webhook_enabled and config.user_id in self.webhook_loggers:
                trade_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': signal.symbol,
                    'trade_type': signal.trade_type,
                    'entry_price': current_price,
                    'quantity': quantity,
                    'leverage': leverage,
                    'order_id': order['orderId'],
                    'stop_loss': sl_price if sl_price else '',
                    'take_profit': ', '.join([str(tp) for tp in tp_prices]) if tp_prices else '',
                    'status': 'EXECUTED',
                    'balance_used': f"${trade_amount:.2f}",
                    'channel_id': signal.channel_id,
                    'subaccount': channel_api.subaccount if channel_api else '',
                    'pnl': '0.00',
                    'notes': f"Channel API | Settings: {'Signal' if config.use_signal_settings else 'Bot'} | SL/TP: {'Enabled' if config.create_sl_tp else 'Disabled'} | OCO: Active",
                    'order_value': f"${order_value:.2f}",
                    'sl_order_id': sl_tp_result['stop_loss'] if sl_tp_result['stop_loss'] else '',
                    'tp_order_ids': ', '.join([str(tp['order_id']) for tp in sl_tp_result['take_profits']]) if sl_tp_result['take_profits'] else '',
                    'user_id': config.user_id
                }
                self.webhook_loggers[config.user_id].send_trade_data(trade_data)

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
                'tp_prices': tp_prices,
                'order_value': order_value,
                'channel_id': signal.channel_id,
                'subaccount': channel_api.subaccount if channel_api else ''
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
                    'sl_order_id': '', 'tp_order_ids': '', 'subaccount': ''
                }
                self.webhook_loggers[config.user_id].send_trade_data(trade_data)

            return {'success': False, 'error': str(e)}

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

                    channel_id = list(matching_channels)[0]
                    channel_api = user_config.get_channel_api_config(channel_id)

                    api_status = "✅ Configured" if channel_api and channel_api.is_configured() else "❌ No API"
                    subaccount_text = f"\n🔑 Subaccount: {channel_api.subaccount}" if channel_api and channel_api.subaccount else ""

                    await bot_instance.send_message(
                        chat_id=user_id,
                        text=f"📨 <b>Message Received</b>\n\n<b>Channel:</b> {channel_id}\n<b>API Status:</b> {api_status}{subaccount_text}\n\n<pre>{message_text[:300]}</pre>\n\n🔍 Processing...",
                        parse_mode='HTML'
                    )

                    signal = self.parse_trading_signal(message_text, channel_id)

                    if signal:
                        if not channel_api or not channel_api.is_configured():
                            await bot_instance.send_message(
                                chat_id=user_id,
                                text=f"❌ <b>No API Credentials!</b>\n\nChannel: {channel_id}\n\nUse /manage_channel_apis to configure API keys for this channel.",
                                parse_mode='HTML'
                            )
                            return

                        settings_source = "Signal" if user_config.use_signal_settings else "Bot"
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text=f"🎯 <b>SIGNAL DETECTED!</b>\n\n💰 {signal.symbol} {signal.trade_type}\n📡 Channel: {channel_id}\n⚙️ Using: {settings_source} settings{subaccount_text}\n🚀 Executing...",
                            parse_mode='HTML'
                        )

                        result = await self.execute_trade(signal, user_config)

                        if result['success']:
                            notification = f"""✅ <b>TRADE EXECUTED!</b>

💰 Symbol: {result['symbol']}
📈 Direction: {signal.trade_type}
📡 Channel: {result['channel_id']}"""

                            if result.get('subaccount'):
                                notification += f"\n🔑 Subaccount: {result['subaccount']}"

                            notification += f"""
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
📡 Channel: {signal.channel_id}
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
        channel_api = config.get_channel_api_config(channel['id'])
        has_api = channel_api and channel_api.is_configured()

        emoji = "✅" if is_selected else "⭕"
        api_emoji = " 🔑" if has_api else ""
        title = channel['title'][:20] + "..." if len(channel['title']) > 20 else channel['title']

        keyboard.append([InlineKeyboardButton(
            f"{emoji} {title}{api_emoji}", 
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
        [InlineKeyboardButton(f"🔗 Make.com Webhook: {'ON' if config.make_webhook_enabled else 'OFF'}", 
                            callback_data="toggle_webhook")],
        [InlineKeyboardButton(f"⚡ Leverage: {config.leverage}x", callback_data="set_leverage")],
        [InlineKeyboardButton(f"🛑 Stop Loss: {config.stop_loss_percent}%", callback_data="set_stop_loss")],
        [InlineKeyboardButton(f"🎯 Take Profit: {config.take_profit_percent}%", callback_data="set_take_profit")],
        [InlineKeyboardButton(f"💰 Balance: {config.balance_percent}%", callback_data="set_balance_percent")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)


# ===================== COMMAND HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = f"""🤖 <b>Telegram Trading Bot v4.0 - MULTI-CHANNEL API!</b>

🎉 <b>NEW IN v4.0:</b>
✅ Different BingX API keys per channel
✅ Subaccount support for each channel
✅ Independent trading per channel
✅ OCO order simulation
✅ Decimal precision fixed

🔗 {DEFAULT_WEBHOOK_URL[:50]}...

<b>Features:</b>
• 🔑 Per-channel API credentials
• ⚙️ Signal vs Bot settings
• 🎯 Auto SL/TP creation  
• 🔄 OCO: Auto-cancel orders
• 📊 Russian signal parsing
• 💰 Configurable sizes
• 🔗 Make.com webhook

<b>Setup Steps:</b>
1️⃣ /setup_telegram
2️⃣ /setup_channels
3️⃣ /manage_channel_apis ⭐ NEW
4️⃣ /setup_trading
5️⃣ /start_monitoring

<b>Test Commands:</b>
/test_simple
/test_basic
/test_advanced
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""<b>📖 All Commands</b>

<b>Setup:</b>
/setup_telegram - Telegram API  
/setup_channels - Select channels
/manage_channel_apis - ⭐ Configure API per channel
/setup_trading - Trading parameters

<b>Control:</b>
/start_monitoring - Start ✅
/stop_monitoring - Stop ❌
/status - Bot status
/channel_status - ⭐ Channel API status

<b>Testing:</b>
/test_simple - Simple test
/test_basic - Basic test
/test_advanced - Full test
/test_signal - Parser test

🔗 {DEFAULT_WEBHOOK_URL[:50]}...

<b>Multi-Channel API:</b>
Each channel can have its own:
• BingX API Key
• BingX API Secret
• Subaccount identifier
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    settings_source = "📊 Signal" if config.use_signal_settings else "🤖 Bot"
    sl_tp_status = "🟢 ON" if config.create_sl_tp else "🔴 OFF"
    webhook_status = "🟢 ON" if config.make_webhook_enabled else "🔴 OFF"
    oco_status = "🟢 Active" if trading_bot.order_monitor_running else "🔴 Inactive"

    # Count configured channels
    configured_channels = sum(1 for ch_id in config.monitored_channels 
                              if config.get_channel_api_config(ch_id) and 
                              config.get_channel_api_config(ch_id).is_configured())

    status_text = f"""📊 <b>Bot Status Dashboard v4.0</b>

🔧 <b>Configuration:</b>
{'✅' if config.telegram_api_id else '❌'} Telegram API  
📡 Channels: <b>{len(config.monitored_channels)}</b>
🔑 Configured APIs: <b>{configured_channels}/{len(config.monitored_channels)}</b>
🔄 Monitoring: {'🟢 Active' if trading_bot.active_monitoring.get(user_id) else '🔴 Inactive'}
🔗 Webhook: <b>{webhook_status}</b>
🔄 OCO Monitor: <b>{oco_status}</b>

⚙️ <b>Trading Settings:</b>
🎯 Settings: <b>{settings_source}</b>
📈 SL/TP: <b>{sl_tp_status}</b>
⚡ Leverage: <b>{config.leverage}x</b>
🛑 Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Take Profit: <b>{config.take_profit_percent}%</b>
💰 Balance: <b>{config.balance_percent}%</b>

📍 <b>Active Positions:</b> {len(trading_bot.active_positions)}

✅ <b>Features v4.0:</b>
• Per-channel API keys
• Subaccount support
• Multi-exchange trading
• OCO order management
"""
    await update.message.reply_text(status_text, parse_mode='HTML')

async def channel_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed status of all monitored channels"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.monitored_channels:
        await update.message.reply_text("❌ No channels configured! Use /setup_channels", parse_mode='HTML')
        return

    status_text = "📡 <b>Channel API Status</b>\n\n"

    for channel_id in config.monitored_channels:
        channel_api = config.get_channel_api_config(channel_id)

        if channel_api and channel_api.is_configured():
            api_status = "✅ Configured"
            key_preview = channel_api.api_key[:10] + "..." if len(channel_api.api_key) > 10 else channel_api.api_key
            subaccount = f"\n   🔑 Subaccount: {channel_api.subaccount}" if channel_api.subaccount else ""

            status_text += f"<b>{channel_id}</b>\n   {api_status}\n   API: {key_preview}{subaccount}\n\n"
        else:
            status_text += f"<b>{channel_id}</b>\n   ❌ Not configured\n\n"

    status_text += "\nUse /manage_channel_apis to configure"

    await update.message.reply_text(status_text, parse_mode='HTML')

# ================== CHANNEL API MANAGEMENT ==================

async def manage_channel_apis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu for managing channel API credentials"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.monitored_channels:
        await update.message.reply_text(
            "❌ No channels configured! Use /setup_channels first",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    keyboard = []
    for channel_id in config.monitored_channels:
        channel_api = config.get_channel_api_config(channel_id)
        has_api = channel_api and channel_api.is_configured()

        emoji = "🔑" if has_api else "❌"
        button_text = f"{emoji} {channel_id[:15]}..."

        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"config_channel_{channel_id}"
        )])

    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="api_config_done")])

    await update.message.reply_text(
        "🔑 <b>Channel API Management</b>\n\nSelect a channel to configure:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

    return WAITING_CHANNEL_SELECTION

async def handle_channel_api_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel selection for API configuration"""
    query = update.callback_query
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        await query.answer()
    except:
        pass

    if query.data == "api_config_done":
        await query.edit_message_text(
            "✅ <b>Channel API configuration complete!</b>\n\nUse /channel_status to view all configurations.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data.startswith("config_channel_"):
        channel_id = query.data.replace("config_channel_", "")
        context.user_data['configuring_channel'] = channel_id

        channel_api = config.get_channel_api_config(channel_id)
        current_config = ""

        if channel_api and channel_api.is_configured():
            key_preview = channel_api.api_key[:10] + "..."
            current_config = f"\n\n<b>Current:</b>\nAPI Key: {key_preview}"
            if channel_api.subaccount:
                current_config += f"\nSubaccount: {channel_api.subaccount}"

        await query.edit_message_text(
            f"🔑 <b>Configure API for Channel</b>\n\nChannel ID: <code>{channel_id}</code>{current_config}\n\nSend your BingX API Key:",
            parse_mode='HTML'
        )
        return WAITING_CHANNEL_API_KEY

    return WAITING_CHANNEL_SELECTION

async def handle_channel_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle API key input"""
    user_id = update.effective_user.id
    channel_id = context.user_data.get('configuring_channel')

    if not channel_id:
        await update.message.reply_text("❌ Error: No channel selected", parse_mode='HTML')
        return ConversationHandler.END

    api_key = update.message.text.strip()
    context.user_data['temp_api_key'] = api_key

    await update.message.reply_text(
        f"✅ <b>API Key saved!</b>\n\nNow send your API Secret:",
        parse_mode='HTML'
    )
    return WAITING_CHANNEL_API_SECRET

async def handle_channel_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle API secret input"""
    user_id = update.effective_user.id
    channel_id = context.user_data.get('configuring_channel')
    api_key = context.user_data.get('temp_api_key')

    if not channel_id or not api_key:
        await update.message.reply_text("❌ Error: Missing data", parse_mode='HTML')
        return ConversationHandler.END

    api_secret = update.message.text.strip()
    context.user_data['temp_api_secret'] = api_secret

    await update.message.reply_text(
        f"✅ <b>API Secret saved!</b>\n\nOptional: Send subaccount identifier or /skip",
        parse_mode='HTML'
    )
    return WAITING_CHANNEL_SUBACCOUNT

async def handle_channel_subaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle subaccount input"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    channel_id = context.user_data.get('configuring_channel')
    api_key = context.user_data.get('temp_api_key')
    api_secret = context.user_data.get('temp_api_secret')

    if not channel_id or not api_key or not api_secret:
        await update.message.reply_text("❌ Error: Missing data", parse_mode='HTML')
        return ConversationHandler.END

    subaccount = ""
    if update.message.text and update.message.text != "/skip":
        subaccount = update.message.text.strip()

    # Save configuration
    config.set_channel_api_config(channel_id, api_key, api_secret, subaccount)

    # Test the connection
    await update.message.reply_text("🔄 <b>Testing API connection...</b>", parse_mode='HTML')

    try:
        test_client = BingX(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            requests_params={'timeout': 30}
        )
        account_info = test_client.swap_user()
        balance = account_info.get('totalWalletBalance', 'N/A')

        success_msg = f"""✅ <b>Channel API Configured!</b>

📡 Channel: <code>{channel_id}</code>
🔑 API Key: {api_key[:10]}...
💰 Balance: {balance} USDT"""

        if subaccount:
            success_msg += f"\n🔐 Subaccount: {subaccount}"

        success_msg += "\n\n🎉 Ready to trade from this channel!"

        await update.message.reply_text(success_msg, parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(
            f"⚠️ <b>API saved but connection test failed</b>\n\nError: {str(e)[:100]}\n\nYou can try again with /manage_channel_apis",
            parse_mode='HTML'
        )

    # Cleanup
    context.user_data.pop('configuring_channel', None)
    context.user_data.pop('temp_api_key', None)
    context.user_data.pop('temp_api_secret', None)

    return ConversationHandler.END

async def skip_subaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip subaccount configuration"""
    return await handle_channel_subaccount(update, context)

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

⭐ Next: /manage_channel_apis to configure API keys
Then: /setup_trading""",
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

⭐ Next: /manage_channel_apis to configure API
Then: /setup_trading""",
        parse_mode='HTML'
    )

    return ConversationHandler.END

