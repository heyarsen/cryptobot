#!/usr/bin/env python3
"""
Telegram Trading Bot v3.3 - ADVANCED MULTI-TP WITH CONFIGURABLE TRAILING STOP
- Configurable Take Profits: TP1 (2.5%, 50%), TP2 (5%, 50%), TP3 (7.5%, 100%)
- Adjustable Trailing Stop with bot commands
- Enhanced balance checking
- Full settings management via bot interface
"""

import asyncio
import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
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

from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceOrderException

# Import Telethon
from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Auto-configured API Credentials
DEFAULT_TELEGRAM_API_ID = '23312577'
DEFAULT_TELEGRAM_API_HASH = 'e879a3e9fd3d45cee98ef55214092805'
DEFAULT_BINANCE_API_KEY = 'JCZ8WdmkVDoTm8sfphNGzEA1iUL8nSrAtUk2zVBqaSqcpycxJFX79XZGt82ZmfVr'
DEFAULT_BINANCE_API_SECRET = 'rDnnNSURkb466pIFGG1IKzIYKImYPAJnNbQVwmwCWBnR45WUDxwob2PTw4sWKfiB'

# Conversation states
(WAITING_BINANCE_KEY, WAITING_BINANCE_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE, WAITING_WEBHOOK_URL,
 WAITING_MIN_ORDER, WAITING_TP1_PERCENT, WAITING_TP1_CLOSE,
 WAITING_TP2_PERCENT, WAITING_TP2_CLOSE,
 WAITING_TP3_PERCENT, WAITING_TRAILING_PERCENT) = range(20)

# Your NEW Make.com Webhook URL
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
    use_signal_settings: bool = True
    create_sl_tp: bool = True
    make_webhook_enabled: bool = True
    make_webhook_url: str = DEFAULT_WEBHOOK_URL
    minimum_order_usd: float = 5.0
    # Multi-TP settings
    tp1_percent: float = 2.5
    tp2_percent: float = 5.0
    tp3_percent: float = 7.5
    tp1_close_percent: float = 50.0
    tp2_close_percent: float = 50.0
    tp3_close_percent: float = 100.0
    # Trailing stop settings
    trailing_stop_enabled: bool = True
    trailing_stop_percent: float = 2.0
    trailing_activation: str = "TP1"  # When to activate: "TP1", "TP2", "IMMEDIATE"

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

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
    timestamp: datetime = None
    tp1_filled: bool = False
    tp2_filled: bool = False
    tp3_filled: bool = False
    remaining_quantity: float = 0.0
    trailing_stop_active: bool = False
    highest_price: float = 0.0  # For LONG trailing
    lowest_price: float = 999999.0  # For SHORT trailing
    last_sl_price: float = 0.0  # Track last SL price to avoid redundant updates

    def __post_init__(self):
        if self.take_profit_order_ids is None:
            self.take_profit_order_ids = []
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.remaining_quantity == 0.0:
            self.remaining_quantity = self.quantity

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
                "webhook_version": "3.3",
                "bot_source": "Telegram Trading Bot",
                "time": datetime.now().strftime('%H:%M:%S'),
                "date": datetime.now().strftime('%Y-%m-%d')
            }

            clean_payload = {k: v for k, v in payload.items() if v and str(v).strip()}

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/3.3',
                'X-Bot-Version': '3.3'
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

    def test_webhook(self, test_type="simple") -> Dict[str, Any]:
        """Flexible webhook testing"""
        try:
            if test_type == "simple":
                test_data = {
                    "text": "Simple webhook test from Trading Bot",
                    "status": "TEST",
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "webhook_version": "3.3"
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
                    "text": f"FULL TEST: BTCUSDT LONG at 45000.50",
                    "timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol": "BTCUSDT",
                    "trade_type": "LONG",
                    "entry_price": "45000.50",
                    "quantity": "0.001",
                    "leverage": "10",
                    "order_id": f"TEST_{current_time.strftime('%H%M%S')}",
                    "stop_loss": "44000.00",
                    "take_profit": "TP1:2.5%(50%), TP2:5%(50%), TP3:7.5%(100%)",
                    "status": "TEST_EXECUTED",
                    "balance_used": "$50.00",
                    "notes": "Multi-TP with trailing stop",
                    "webhook_version": "3.3",
                    "time": current_time.strftime('%H:%M:%S'),
                    "date": current_time.strftime('%Y-%m-%d')
                }

            response = requests.post(self.webhook_url, json=test_data, timeout=30)
            
            return {
                'success': response.status_code == 200,
                'status_code': response.status_code,
                'response_time': 0.5,
                'response_text': response.text[:500] if response.text else "No response"
            }

        except Exception as e:
            return {
                'success': False,
                'status_code': 0,
                'response_text': str(e)
            }

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
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.active_positions: Dict[str, ActivePosition] = {}
        self.order_monitor_running = False

    def parse_trading_signal(self, message: str, channel_id: str) -> Optional[TradingSignal]:
        """Enhanced signal parsing"""
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
            
            logger.info(f"✅ Make.com webhook setup for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Make.com webhook setup error: {e}")
            return False

    def get_symbol_precision(self, symbol: str) -> Dict[str, Any]:
        """Get and cache symbol precision information"""
        try:
            if symbol in self.symbol_info_cache:
                return self.symbol_info_cache[symbol]

            exchange_info = self.binance_client.futures_exchange_info()
            symbol_info = None
            
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    symbol_info = s
                    break

            if not symbol_info:
                return {'error': f'Symbol {symbol} not found'}

            step_size = None
            min_qty = None
            for f in symbol_info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    min_qty = float(f['minQty'])
                    break

            tick_size = None
            min_price = None
            max_price = None
            for f in symbol_info['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    tick_size = float(f['tickSize'])
                    min_price = float(f['minPrice'])
                    max_price = float(f['maxPrice'])
                    break

            qty_precision = 0
            price_precision = 0

            if step_size and step_size > 0:
                step_str = f"{step_size:.10f}".rstrip('0')
                if '.' in step_str:
                    qty_precision = len(step_str.split('.')[-1])
            else:
                step_size = 1.0
                qty_precision = 0

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

            self.symbol_info_cache[symbol] = precision_info
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
        """Round price properly"""
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
        """Round quantity properly"""
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

    async def update_trailing_stop(self, symbol: str, position: ActivePosition, current_price: float, bot_instance):
        """Update trailing stop loss"""
        try:
            config = self.get_user_config(position.user_id)
            
            if not config.trailing_stop_enabled or not position.trailing_stop_active:
                return

            precision_info = self.get_symbol_precision(symbol)
            tick_size = precision_info['tick_size']
            price_precision = precision_info['price_precision']

            new_sl_price = None
            should_update = False

            if position.side == 'BUY':  # LONG position
                if current_price > position.highest_price:
                    position.highest_price = current_price
                    new_sl_price = current_price * (1 - config.trailing_stop_percent / 100)
                    should_update = True
            else:  # SHORT position
                if current_price < position.lowest_price:
                    position.lowest_price = current_price
                    new_sl_price = current_price * (1 + config.trailing_stop_percent / 100)
                    should_update = True

            if should_update and new_sl_price:
                new_sl_price_rounded = self.round_price(new_sl_price, tick_size, price_precision)
                
                # Check if new SL is significantly different
                if abs(new_sl_price_rounded - position.last_sl_price) / position.last_sl_price < 0.001:
                    return  # Less than 0.1% change, skip update
                
                # Cancel old SL
                if position.stop_loss_order_id:
                    try:
                        self.binance_client.futures_cancel_order(
                            symbol=symbol,
                            orderId=position.stop_loss_order_id
                        )
                        logger.info(f"🔄 Cancelled old trailing SL: {position.stop_loss_order_id}")
                    except:
                        pass

                # Create new trailing SL
                sl_side = 'SELL' if position.side == 'BUY' else 'BUY'
                
                sl_order = self.binance_client.futures_create_order(
                    symbol=symbol,
                    side=sl_side,
                    type='STOP_MARKET',
                    quantity=position.remaining_quantity,
                    stopPrice=new_sl_price_rounded,
                    closePosition=False
                )
                
                position.stop_loss_order_id = sl_order['orderId']
                position.last_sl_price = new_sl_price_rounded
                logger.info(f"✅ Updated trailing SL to {new_sl_price_rounded} (Order: {sl_order['orderId']})")
                
                await bot_instance.send_message(
                    chat_id=position.user_id,
                    text=f"🔄 <b>Trailing Stop Updated</b>\n\n💰 {symbol}\n🛑 New SL: {new_sl_price_rounded:.8f}\n📈 Current: {current_price:.8f}\n📊 Best: {position.highest_price if position.side == 'BUY' else position.lowest_price:.8f}",
                    parse_mode='HTML'
                )

        except Exception as e:
            logger.error(f"❌ Error updating trailing stop: {e}")

    async def cancel_related_orders(self, symbol: str, user_id: int, filled_order_type: str, bot_instance):
        """Cancel related orders when TP or SL fills"""
        try:
            position = self.active_positions.get(symbol)
            if not position:
                return

            logger.info(f"🔄 Canceling related orders for {symbol} after {filled_order_type} filled")

            cancelled_orders = []

            if filled_order_type in ["TAKE_PROFIT", "TAKE_PROFIT_3"] and position.stop_loss_order_id:
                try:
                    self.binance_client.futures_cancel_order(
                        symbol=symbol,
                        orderId=position.stop_loss_order_id
                    )
                    cancelled_orders.append(f"SL-{position.stop_loss_order_id}")
                    logger.info(f"✅ Cancelled SL: {position.stop_loss_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to cancel SL: {e}")

            elif filled_order_type == "STOP_LOSS" and position.take_profit_order_ids:
                for tp_id in position.take_profit_order_ids:
                    try:
                        self.binance_client.futures_cancel_order(
                            symbol=symbol,
                            orderId=tp_id
                        )
                        cancelled_orders.append(f"TP-{tp_id}")
                        logger.info(f"✅ Cancelled TP: {tp_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to cancel TP {tp_id}: {e}")

            if symbol in self.active_positions:
                del self.active_positions[symbol]
                logger.info(f"🗑️ Removed {symbol} from active positions")

            if cancelled_orders:
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=f"🔄 <b>Auto-Cancelled Orders</b>\n\n💰 {symbol}\n📋 Cancelled: {', '.join(cancelled_orders)}",
                    parse_mode='HTML'
                )

        except Exception as e:
            logger.error(f"❌ Error canceling related orders: {e}")

    async def monitor_orders(self, bot_instance):
        """Monitor orders with trailing stop and TP management"""
        try:
            if self.order_monitor_running:
                return

            self.order_monitor_running = True
            logger.info("👁️ Order monitor started with trailing stop")

            while self.order_monitor_running:
                try:
                    for symbol, position in list(self.active_positions.items()):
                        try:
                            # Get current price
                            ticker = self.binance_client.futures_symbol_ticker(symbol=symbol)
                            current_price = float(ticker['price'])

                            # Update trailing stop if active
                            await self.update_trailing_stop(symbol, position, current_price, bot_instance)

                            # Check open orders
                            open_orders = self.binance_client.futures_get_open_orders(symbol=symbol)
                            open_order_ids = [int(order['orderId']) for order in open_orders]

                            # Check if SL filled
                            if position.stop_loss_order_id and position.stop_loss_order_id not in open_order_ids:
                                logger.info(f"🛑 Stop Loss filled for {symbol}")
                                await self.cancel_related_orders(symbol, position.user_id, "STOP_LOSS", bot_instance)

                            # Check TPs
                            for i, tp_id in enumerate(position.take_profit_order_ids):
                                if tp_id not in open_order_ids:
                                    logger.info(f"🎯 Take Profit {i+1} filled for {symbol}")
                                    
                                    config = self.get_user_config(position.user_id)
                                    
                                    if i == 0:  # TP1 filled
                                        position.tp1_filled = True
                                        
                                        # Activate trailing if configured for TP1
                                        if config.trailing_activation == "TP1":
                                            position.trailing_stop_active = True
                                            position.highest_price = current_price if position.side == 'BUY' else 0
                                            position.lowest_price = current_price if position.side == 'SELL' else 999999
                                            position.last_sl_price = 0
                                            logger.info(f"✅ Trailing stop ACTIVATED for {symbol} after TP1")
                                        
                                        await bot_instance.send_message(
                                            chat_id=position.user_id,
                                            text=f"🎯 <b>TP1 Hit ({config.tp1_percent}%)!</b>\n\n💰 {symbol}\n📈 Price: {current_price:.8f}\n📊 Closed: {config.tp1_close_percent}%\n{f'🔄 Trailing stop ACTIVE!' if position.trailing_stop_active else ''}",
                                            parse_mode='HTML'
                                        )
                                    
                                    elif i == 1:  # TP2 filled
                                        position.tp2_filled = True
                                        
                                        # Activate trailing if configured for TP2
                                        if config.trailing_activation == "TP2" and not position.trailing_stop_active:
                                            position.trailing_stop_active = True
                                            position.highest_price = current_price if position.side == 'BUY' else 0
                                            position.lowest_price = current_price if position.side == 'SELL' else 999999
                                            position.last_sl_price = 0
                                            logger.info(f"✅ Trailing stop ACTIVATED for {symbol} after TP2")
                                        
                                        await bot_instance.send_message(
                                            chat_id=position.user_id,
                                            text=f"🎯 <b>TP2 Hit ({config.tp2_percent}%)!</b>\n\n💰 {symbol}\n📈 Price: {current_price:.8f}\n📊 Closed: {config.tp2_close_percent}%\n{f'🔄 Trailing stop ACTIVE!' if position.trailing_stop_active else '🔄 Trailing continues'}",
                                            parse_mode='HTML'
                                        )
                                    
                                    elif i == 2:  # TP3 filled - full exit
                                        position.tp3_filled = True
                                        logger.info(f"🎉 TP3 filled for {symbol} - Position fully closed")
                                        await self.cancel_related_orders(symbol, position.user_id, "TAKE_PROFIT_3", bot_instance)
                                        
                                        await bot_instance.send_message(
                                            chat_id=position.user_id,
                                            text=f"🎉 <b>TP3 Hit ({config.tp3_percent}%) - Full Exit!</b>\n\n💰 {symbol}\n📈 Price: {current_price:.8f}\n✅ Position fully closed with profit!",
                                            parse_mode='HTML'
                                        )

                        except Exception as e:
                            logger.error(f"❌ Error checking orders for {symbol}: {e}")

                    await asyncio.sleep(3)  # Check every 3 seconds for trailing

                except Exception as e:
                    logger.error(f"❌ Order monitor loop error: {e}")
                    await asyncio.sleep(3)

        except Exception as e:
            logger.error(f"❌ Order monitor error: {e}")
        finally:
            self.order_monitor_running = False
            logger.info("👁️ Order monitor stopped")

    async def get_account_balance(self, config: BotConfig) -> Dict[str, float]:
        """Get account balance"""
        try:
            if not self.binance_client:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to Binance API'}

            balance_info = self.binance_client.futures_account_balance()
            account_info = self.binance_client.futures_account()

            usdt_info = {'balance': 0, 'available': 0, 'wallet_balance': 0}

            for asset in balance_info:
                if asset['asset'] == 'USDT':
                    usdt_info['balance'] = float(asset['balance'])
                    usdt_info['available'] = float(asset['withdrawAvailable'])
                    break

            for asset in account_info['assets']:
                if asset['asset'] == 'USDT':
                    usdt_info['wallet_balance'] = float(asset['walletBalance'])
                    break

            total_wallet_balance = float(account_info.get('totalWalletBalance', 0))
            
            return {
                'success': True,
                'usdt_balance': usdt_info['balance'],
                'usdt_available': usdt_info['available'],
                'usdt_wallet_balance': usdt_info['wallet_balance'],
                'total_wallet_balance': total_wallet_balance,
                'total_unrealized_pnl': float(account_info.get('totalUnrealizedProfit', 0)),
                'total_margin_balance': float(account_info.get('totalMarginBalance', 0))
            }

        except Exception as e:
            logger.error(f"❌ Error getting account balance: {e}")
            return {'success': False, 'error': str(e)}

    async def setup_binance_client(self, config: BotConfig) -> bool:
        try:
            self.binance_client = BinanceClient(
                api_key=config.binance_api_key,
                api_secret=config.binance_api_secret,
                testnet=False,
                requests_params={'timeout': 60}
            )

            account_info = self.binance_client.futures_account()
            logger.info(f"✅ Binance connected. Balance: {account_info.get('totalWalletBalance', 'N/A')} USDT")
            return True

        except Exception as e:
            logger.error(f"❌ Binance setup error: {e}")
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

    async def create_multi_tp_orders(self, symbol: str, side: str, quantity: float, entry_price: float, 
                                    sl_price: Optional[float], current_price: float, config: BotConfig, user_id: int) -> Dict[str, Any]:
        """Create multiple TP orders with configurable percentages"""
        try:
            results = {'stop_loss': None, 'take_profits': []}

            precision_info = self.get_symbol_precision(symbol)
            if 'error' in precision_info:
                logger.error(f"❌ Cannot create orders: {precision_info['error']}")
                return results

            tick_size = precision_info['tick_size']
            price_precision = precision_info['price_precision']
            step_size = precision_info['step_size']
            qty_precision = precision_info['qty_precision']

            logger.info(f"📐 Precision: price={price_precision}, qty={qty_precision}")

            # Create Stop Loss
            if sl_price:
                try:
                    sl_side = 'SELL' if side == 'BUY' else 'BUY'
                    sl_price_rounded = self.round_price(sl_price, tick_size, price_precision)
                    
                    logger.info(f"🛑 Creating initial SL: {sl_price_rounded}")
                    
                    if sl_price_rounded > 0:
                        sl_order = self.binance_client.futures_create_order(
                            symbol=symbol,
                            side=sl_side,
                            type='STOP_MARKET',
                            quantity=quantity,
                            stopPrice=sl_price_rounded,
                            closePosition=False
                        )
                        results['stop_loss'] = sl_order['orderId']
                        logger.info(f"✅ Stop Loss created: {sl_order['orderId']} @ {sl_price_rounded}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Stop Loss: {e}")

            # Calculate TP prices and quantities
            tp_configs = [
                {'percent': config.tp1_percent, 'close_percent': config.tp1_close_percent, 'name': 'TP1'},
                {'percent': config.tp2_percent, 'close_percent': config.tp2_close_percent, 'name': 'TP2'},
                {'percent': config.tp3_percent, 'close_percent': config.tp3_close_percent, 'name': 'TP3'}
            ]

            remaining_qty = quantity

            for i, tp_config in enumerate(tp_configs):
                try:
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    
                    # Calculate TP price
                    if side == 'BUY':
                        tp_price = current_price * (1 + tp_config['percent'] / 100)
                    else:
                        tp_price = current_price * (1 - tp_config['percent'] / 100)
                    
                    # Calculate quantity to close
                    if i == 2:  # TP3 closes remaining
                        tp_quantity = remaining_qty
                    else:
                        tp_quantity = quantity * (tp_config['close_percent'] / 100)
                        remaining_qty -= tp_quantity
                    
                    tp_price_rounded = self.round_price(tp_price, tick_size, price_precision)
                    tp_quantity_rounded = self.round_quantity(tp_quantity, step_size, qty_precision)
                    
                    logger.info(f"🎯 Creating {tp_config['name']}: {tp_price_rounded} qty={tp_quantity_rounded} ({tp_config['close_percent']}%)")
                    
                    if tp_price_rounded > 0 and tp_quantity_rounded > 0:
                        tp_order = self.binance_client.futures_create_order(
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
                            'quantity': tp_quantity_rounded,
                            'name': tp_config['name']
                        })
                        logger.info(f"✅ {tp_config['name']} created: {tp_order['orderId']} @ {tp_price_rounded}")
                except Exception as e:
                    logger.error(f"❌ Failed to create {tp_config['name']}: {e}")

            # Track position
            if results['stop_loss'] or results['take_profits']:
                position = ActivePosition(
                    symbol=symbol,
                    user_id=user_id,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss_order_id=results['stop_loss'],
                    take_profit_order_ids=[tp['order_id'] for tp in results['take_profits']],
                    remaining_quantity=quantity,
                    highest_price=current_price if side == 'BUY' else 0,
                    lowest_price=current_price if side == 'SELL' else 999999,
                    trailing_stop_active=(config.trailing_activation == "IMMEDIATE"),
                    last_sl_price=sl_price if sl_price else 0
                )
                self.active_positions[symbol] = position
                logger.info(f"📍 Tracking position for {symbol} with multi-TP and trailing stop")

            return results

        except Exception as e:
            logger.error(f"❌ Error creating TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """Execute trade with multi-TP and trailing stop"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")

            if not self.binance_client:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to Binance API'}

            # Get balance
            try:
                balance_info = self.binance_client.futures_account_balance()
                usdt_balance = 0

                for asset in balance_info:
                    if asset['asset'] == 'USDT':
                        usdt_balance = float(asset['balance'])
                        break

                if usdt_balance == 0:
                    account = self.binance_client.futures_account()
                    for asset in account['assets']:
                        if asset['asset'] == 'USDT':
                            usdt_balance = float(asset['walletBalance'])
                            break

            except Exception as e:
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            # Set leverage
            if config.use_signal_settings and signal.leverage:
                leverage = signal.leverage
            else:
                leverage = config.leverage

            try:
                self.binance_client.futures_change_leverage(symbol=signal.symbol, leverage=leverage)
                logger.info(f"✅ Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ Leverage warning: {e}")

            # Get current price
            ticker = self.binance_client.futures_symbol_ticker(symbol=signal.symbol)
            current_price = float(ticker['price'])

            entry_price = signal.entry_price or current_price
            trade_amount = usdt_balance * (config.balance_percent / 100)
            raw_quantity = (trade_amount * leverage) / entry_price

            precision_info = self.get_symbol_precision(signal.symbol)
            if 'error' in precision_info:
                return {'success': False, 'error': precision_info['error']}

            quantity = self.round_quantity(raw_quantity, precision_info['step_size'], precision_info['qty_precision'])

            if quantity < precision_info['min_qty'] or quantity <= 0:
                return {'success': False, 'error': f'Invalid quantity: {quantity}'}

            order_value = quantity * entry_price
            side = 'BUY' if signal.trade_type == 'LONG' else 'SELL'

            # Execute market order
            order = self.binance_client.futures_create_order(
                symbol=signal.symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )

            logger.info(f"✅ Main order executed: {order['orderId']}")

            # Calculate SL
            sl_price = None
            if config.create_sl_tp:
                if signal.trade_type == 'LONG':
                    sl_price = current_price * (1 - config.stop_loss_percent / 100)
                else:
                    sl_price = current_price * (1 + config.stop_loss_percent / 100)

            # Create multi-TP orders
            sl_tp_result = await self.create_multi_tp_orders(
                signal.symbol, side, quantity, current_price, sl_price, current_price, config, config.user_id
            )

            # Send to webhook
            if config.make_webhook_enabled and config.user_id in self.webhook_loggers:
                tp_info = f"TP1:{config.tp1_percent}%({config.tp1_close_percent}%), TP2:{config.tp2_percent}%({config.tp2_close_percent}%), TP3:{config.tp3_percent}%({config.tp3_close_percent}%)"
                
                trade_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': signal.symbol,
                    'trade_type': signal.trade_type,
                    'entry_price': current_price,
                    'quantity': quantity,
                    'leverage': leverage,
                    'order_id': order['orderId'],
                    'stop_loss': sl_price if sl_price else '',
                    'take_profit': tp_info,
                    'status': 'EXECUTED',
                    'balance_used': f"${trade_amount:.2f}",
                    'channel_id': signal.channel_id,
                    'notes': f"Multi-TP with Trailing Stop ({config.trailing_stop_percent}%) | Activation: {config.trailing_activation} | {tp_info}",
                    'order_value': f"${order_value:.2f}",
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
                'order_value': order_value
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
                        await bot_instance.send_message(
                            chat_id=user_id,
                            text=f"🎯 <b>SIGNAL DETECTED!</b>\n\n💰 {signal.symbol} {signal.trade_type}\n🚀 Executing with multi-TP...",
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
💵 Order Value: ${result['order_value']:.2f}

🎯 <b>Take Profits:</b>
TP1: {user_config.tp1_percent}% (closes {user_config.tp1_close_percent}%)
TP2: {user_config.tp2_percent}% (closes {user_config.tp2_close_percent}%)
TP3: {user_config.tp3_percent}% (closes {user_config.tp3_close_percent}%)

🔄 <b>Trailing Stop:</b> {user_config.trailing_stop_percent}%
🎬 <b>Activation:</b> {user_config.trailing_activation}
🛑 <b>Initial SL:</b> {user_config.stop_loss_percent}%

⏰ Time: {datetime.now().strftime('%H:%M:%S')}
🎉 Position is LIVE!"""

                        else:
                            notification = f"""❌ <b>TRADE FAILED</b>

💰 Symbol: {signal.symbol}
🚨 Error: {result['error']}"""

                        await bot_instance.send_message(chat_id=user_id, text=notification, parse_mode='HTML')

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

Currently monitoring: <b>{len(config.monitored_channels)}</b> channels"""

def create_channel_keyboard(user_id: int, channels: list) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)
    keyboard = []

    for channel in channels[:15]:
        is_selected = channel['id'] in config.monitored_channels
        emoji = "✅" if is_selected else "⭕"
        title = channel['title'][:25]

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
        [InlineKeyboardButton(f"⚙️ Settings: {'Signal' if config.use_signal_settings else 'Bot'}", 
                            callback_data="toggle_settings_source")],
        [InlineKeyboardButton(f"📊 SL/TP: {'ON' if config.create_sl_tp else 'OFF'}", 
                            callback_data="toggle_sl_tp")],
        [InlineKeyboardButton(f"🔗 Webhook: {'ON' if config.make_webhook_enabled else 'OFF'}", 
                            callback_data="toggle_webhook")],
        [InlineKeyboardButton(f"⚡ Leverage: {config.leverage}x", callback_data="set_leverage")],
        [InlineKeyboardButton(f"🛑 Stop Loss: {config.stop_loss_percent}%", callback_data="set_stop_loss")],
        [InlineKeyboardButton(f"💰 Balance: {config.balance_percent}%", callback_data="set_balance_percent")],
        [InlineKeyboardButton("🎯 Configure TPs", callback_data="configure_tps")],
        [InlineKeyboardButton("🔄 Trailing Stop", callback_data="configure_trailing")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)

def create_tp_config_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)

    keyboard = [
        [InlineKeyboardButton(f"TP1: {config.tp1_percent}% ({config.tp1_close_percent}%)", callback_data="set_tp1")],
        [InlineKeyboardButton(f"TP2: {config.tp2_percent}% ({config.tp2_close_percent}%)", callback_data="set_tp2")],
        [InlineKeyboardButton(f"TP3: {config.tp3_percent}% ({config.tp3_close_percent}%)", callback_data="set_tp3")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_settings")]
    ]

    return InlineKeyboardMarkup(keyboard)

def create_trailing_config_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = trading_bot.get_user_config(user_id)

    keyboard = [
        [InlineKeyboardButton(f"Trailing: {config.trailing_stop_percent}%", callback_data="set_trailing_percent")],
        [InlineKeyboardButton(f"Enable: {'ON' if config.trailing_stop_enabled else 'OFF'}", callback_data="toggle_trailing")],
        [InlineKeyboardButton(f"Activation: {config.trailing_activation}", callback_data="set_trailing_activation")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_settings")]
    ]

    return InlineKeyboardMarkup(keyboard)

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = f"""🤖 <b>Trading Bot v3.3 - Advanced Multi-TP!</b>

🎯 <b>Configurable Take Profits:</b>
• TP1: Adjustable % (closes X%)
• TP2: Adjustable % (closes X%)  
• TP3: Adjustable % (closes remaining)

🔄 <b>Smart Trailing Stop:</b>
• Adjustable trailing %
• Choose activation: IMMEDIATE, TP1, or TP2
• Protects profits automatically

💰 <b>Enhanced Balance Check:</b>
• Real-time USDT balance
• Available margin
• Unrealized PNL

<b>Setup:</b>
1️⃣ /setup_binance
2️⃣ /setup_telegram
3️⃣ /setup_channels
4️⃣ /setup_trading
5️⃣ /start_monitoring

<b>Quick Commands:</b>
/balance - Check balance
/configure_tp - Configure TPs
/configure_trailing - Configure trailing"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """<b>📖 Commands</b>

<b>Setup:</b>
/setup_binance - API
/setup_telegram - API  
/setup_channels - Channels
/setup_trading - Settings

<b>Configuration:</b>
/configure_tp - Set TP levels
/configure_trailing - Trailing stop

<b>Control:</b>
/start_monitoring - Start
/stop_monitoring - Stop
/status - Status
/balance - Balance

<b>Features:</b>
• Multi-TP: Configurable
• Trailing stop: Adjustable
• Real-time balance check
• OCO order management"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.binance_api_key:
        await update.message.reply_text("❌ Setup Binance first: /setup_binance", parse_mode='HTML')
        return

    await update.message.reply_text("💰 <b>Checking balance...</b>", parse_mode='HTML')

    balance_info = await trading_bot.get_account_balance(config)

    if balance_info['success']:
        balance_text = f"""💳 <b>Binance Futures Balance</b>

💰 <b>USDT Balance:</b> {balance_info['usdt_balance']:.2f} USDT
🔓 <b>Available:</b> {balance_info['usdt_available']:.2f} USDT
💼 <b>Wallet:</b> {balance_info['usdt_wallet_balance']:.2f} USDT
📊 <b>Total Margin:</b> {balance_info['total_margin_balance']:.2f} USDT
📈 <b>Unrealized PNL:</b> {balance_info['total_unrealized_pnl']:.2f} USDT

💵 <b>Trade Calculations:</b>
Position Size ({config.balance_percent}%): ${balance_info['usdt_balance'] * config.balance_percent / 100:.2f}
Leverage: {config.leverage}x
Max Position: ${balance_info['usdt_balance'] * config.balance_percent / 100 * config.leverage:.2f}

⏰ Updated: {datetime.now().strftime('%H:%M:%S')}"""
    else:
        balance_text = f"❌ <b>Balance Check Failed</b>\n\n🚨 Error: {balance_info['error']}"

    await update.message.reply_text(balance_text, parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    status_text = f"""📊 <b>Bot Status v3.3</b>

🔧 <b>Config:</b>
{'✅' if config.binance_api_key else '❌'} Binance
{'✅' if config.telegram_api_id else '❌'} Telegram
📡 Channels: {len(config.monitored_channels)}
🔄 Monitoring: {'🟢' if trading_bot.active_monitoring.get(user_id) else '🔴'}

⚙️ <b>Trading:</b>
⚡ Leverage: {config.leverage}x
🛑 SL: {config.stop_loss_percent}%
💰 Balance: {config.balance_percent}%

🎯 <b>Take Profits:</b>
TP1: {config.tp1_percent}% (closes {config.tp1_close_percent}%)
TP2: {config.tp2_percent}% (closes {config.tp2_close_percent}%)
TP3: {config.tp3_percent}% (closes {config.tp3_close_percent}%)

🔄 <b>Trailing Stop:</b>
{'🟢 Enabled' if config.trailing_stop_enabled else '🔴 Disabled'} ({config.trailing_stop_percent}%)
Activation: {config.trailing_activation}

📍 Active Positions: {len(trading_bot.active_positions)}"""
    await update.message.reply_text(status_text, parse_mode='HTML')

# Webhook tests
async def test_webhook_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("simple")
    
    if result['success']:
        await update.message.reply_text("✅ Webhook test successful!", parse_mode='HTML')
    else:
        await update.message.reply_text(f"❌ Test failed: {result['response_text'][:200]}", parse_mode='HTML')

async def test_webhook_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("advanced")
    
    if result['success']:
        await update.message.reply_text("✅ Advanced test successful!", parse_mode='HTML')
    else:
        await update.message.reply_text(f"❌ Test failed", parse_mode='HTML')

# TP Configuration
async def configure_tp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_tp_config_keyboard(user_id)
    
    await update.message.reply_text(
        "🎯 <b>Take Profit Configuration</b>\n\nConfigure each TP level:",
        reply_markup=keyboard_markup,
        parse_mode='HTML'
    )

# Trailing Configuration  
async def configure_trailing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_trailing_config_keyboard(user_id)
    
    await update.message.reply_text(
        "🔄 <b>Trailing Stop Configuration</b>\n\nConfigure trailing stop:",
        reply_markup=keyboard_markup,
        parse_mode='HTML'
    )

# Setup handlers (simplified - same as before but added new conversation states)
async def setup_binance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your Binance API Key:", parse_mode='HTML')
    return WAITING_BINANCE_KEY

async def handle_binance_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.binance_api_key = update.message.text.strip()
    await update.message.reply_text("Now send your API Secret:", parse_mode='HTML')
    return WAITING_BINANCE_SECRET

async def handle_binance_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.binance_api_secret = update.message.text.strip()
    success = await trading_bot.setup_binance_client(config)
    if success:
        await update.message.reply_text("✅ Binance configured!", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Failed!", parse_mode='HTML')
    return ConversationHandler.END

async def setup_telegram_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your Telegram API ID:", parse_mode='HTML')
    return WAITING_TELEGRAM_ID

async def handle_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.telegram_api_id = update.message.text.strip()
    await update.message.reply_text("Now send your API Hash:", parse_mode='HTML')
    return WAITING_TELEGRAM_HASH

async def handle_telegram_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    config.telegram_api_hash = update.message.text.strip()
    success = await trading_bot.setup_telethon_client(config)
    if success:
        await update.message.reply_text("✅ Telegram configured!", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Failed!", parse_mode='HTML')
    return ConversationHandler.END

async def setup_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = await trading_bot.get_available_channels(user_id)
    if not channels:
        await update.message.reply_text("❌ No channels!", parse_mode='HTML')
        return ConversationHandler.END
    context.user_data['available_channels'] = channels
    keyboard_markup = create_channel_keyboard(user_id, channels)
    await update.message.reply_text(create_channel_selection_text(user_id), reply_markup=keyboard_markup, parse_mode='HTML')
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
        await query.edit_message_text(f"✅ Monitoring: {len(config.monitored_channels)} channels", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data.startswith("toggle_channel_"):
        channel_id = query.data.replace("toggle_channel_", "")
        if channel_id in config.monitored_channels:
            config.monitored_channels.remove(channel_id)
        else:
            config.monitored_channels.append(channel_id)
        channels = context.user_data.get('available_channels', [])
        keyboard_markup = create_channel_keyboard(user_id, channels)
        await query.edit_message_text(create_channel_selection_text(user_id), reply_markup=keyboard_markup, parse_mode='HTML')
    return WAITING_CHANNEL_SELECTION

async def setup_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_settings_keyboard(user_id)
    await update.message.reply_text("⚙️ Trading Configuration", reply_markup=keyboard_markup, parse_mode='HTML')
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
        await query.edit_message_text("✅ Configuration complete!", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text("⚙️ Trading Configuration", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text("⚙️ Trading Configuration", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "toggle_webhook":
        config.make_webhook_enabled = not config.make_webhook_enabled
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text("⚙️ Trading Configuration", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "configure_tps":
        keyboard_markup = create_tp_config_keyboard(user_id)
        await query.edit_message_text("🎯 <b>Take Profit Configuration</b>", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "configure_trailing":
        keyboard_markup = create_trailing_config_keyboard(user_id)
        await query.edit_message_text("🔄 <b>Trailing Stop Configuration</b>", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "back_to_settings":
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text("⚙️ Trading Configuration", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "set_tp1":
        await query.edit_message_text("🎯 Send TP1 settings as: <code>2.5 50</code> (2.5% profit, closes 50%)", parse_mode='HTML')
        return WAITING_TP1_PERCENT
    elif query.data == "set_tp2":
        await query.edit_message_text("🎯 Send TP2 settings as: <code>5 50</code> (5% profit, closes 50%)", parse_mode='HTML')
        return WAITING_TP2_PERCENT
    elif query.data == "set_tp3":
        await query.edit_message_text("🎯 Send TP3 settings as: <code>7.5 100</code> (7.5% profit, closes 100%)", parse_mode='HTML')
        return WAITING_TP3_PERCENT
    elif query.data == "set_trailing_percent":
        await query.edit_message_text("🔄 Send trailing stop % (e.g., 2 for 2%):", parse_mode='HTML')
        return WAITING_TRAILING_PERCENT
    elif query.data == "toggle_trailing":
        config.trailing_stop_enabled = not config.trailing_stop_enabled
        keyboard_markup = create_trailing_config_keyboard(user_id)
        await query.edit_message_text("🔄 <b>Trailing Stop Configuration</b>", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "set_trailing_activation":
        # Cycle through activation options
        if config.trailing_activation == "IMMEDIATE":
            config.trailing_activation = "TP1"
        elif config.trailing_activation == "TP1":
            config.trailing_activation = "TP2"
        else:
            config.trailing_activation = "IMMEDIATE"
        keyboard_markup = create_trailing_config_keyboard(user_id)
        await query.edit_message_text("🔄 <b>Trailing Stop Configuration</b>", reply_markup=keyboard_markup, parse_mode='HTML')
    elif query.data == "set_leverage":
        await query.edit_message_text("⚡ Send leverage (1-125):", parse_mode='HTML')
        return WAITING_LEVERAGE
    elif query.data == "set_stop_loss":
        await query.edit_message_text("🛑 Send stop loss %:", parse_mode='HTML')
        return WAITING_STOP_LOSS
    elif query.data == "set_balance_percent":
        await query.edit_message_text("💰 Send balance % (1-100):", parse_mode='HTML')
        return WAITING_BALANCE_PERCENT
    return WAITING_SETTINGS_SOURCE

# TP handlers
async def handle_tp1_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        parts = update.message.text.split()
        if len(parts) == 2:
            config.tp1_percent = float(parts[0])
            config.tp1_close_percent = float(parts[1])
            await update.message.reply_text(f"✅ TP1: {config.tp1_percent}% (closes {config.tp1_close_percent}%)", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid format! Use: <code>2.5 50</code>", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_tp2_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        parts = update.message.text.split()
        if len(parts) == 2:
            config.tp2_percent = float(parts[0])
            config.tp2_close_percent = float(parts[1])
            await update.message.reply_text(f"✅ TP2: {config.tp2_percent}% (closes {config.tp2_close_percent}%)", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid format!", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_tp3_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        parts = update.message.text.split()
        if len(parts) == 2:
            config.tp3_percent = float(parts[0])
            config.tp3_close_percent = float(parts[1])
            await update.message.reply_text(f"✅ TP3: {config.tp3_percent}% (closes {config.tp3_close_percent}%)", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Invalid format!", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_trailing_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        value = float(update.message.text)
        if 0.1 <= value <= 10:
            config.trailing_stop_percent = value
            await update.message.reply_text(f"✅ Trailing: {value}%", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 0.1-10%", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid input!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        leverage = int(update.message.text)
        if 1 <= leverage <= 125:
            config.leverage = leverage
            await update.message.reply_text(f"✅ Leverage: {leverage}x", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-125", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        sl = float(update.message.text)
        if 0.1 <= sl <= 50:
            config.stop_loss_percent = sl
            await update.message.reply_text(f"✅ SL: {sl}%", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 0.1-50%", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid!", parse_mode='HTML')
    return ConversationHandler.END

async def handle_balance_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    try:
        value = float(update.message.text)
        if 1 <= value <= 100:
            config.balance_percent = value
            await update.message.reply_text(f"✅ Balance: {value}%", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Must be 1-100", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Invalid!", parse_mode='HTML')
    return ConversationHandler.END

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)
    if not config.binance_api_key or not config.telegram_api_id:
        await update.message.reply_text("❌ Complete setup first!", parse_mode='HTML')
        return
    if not config.monitored_channels:
        await update.message.reply_text("❌ No channels!", parse_mode='HTML')
        return
    success = await trading_bot.start_monitoring(user_id, context.bot)
    if success:
        await update.message.reply_text(f"""✅ <b>MONITORING STARTED!</b>

📡 Channels: {len(config.monitored_channels)}
🎯 Multi-TP: {config.tp1_percent}%, {config.tp2_percent}%, {config.tp3_percent}%
🔄 Trailing: {config.trailing_stop_percent}% (activates on {config.trailing_activation})
🚀 Ready to trade!""", parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Failed!", parse_mode='HTML')

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trading_bot.active_monitoring[user_id] = False
    trading_bot.order_monitor_running = False
    await update.message.reply_text("🛑 Monitoring stopped!", parse_mode='HTML')

# Conversation handlers
binance_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_binance', setup_binance)],
    states={
        WAITING_BINANCE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_key)],
        WAITING_BINANCE_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_secret)],
    },
    fallbacks=[]
)

telegram_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_telegram', setup_telegram_api)],
    states={
        WAITING_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_id)],
        WAITING_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_hash)],
    },
    fallbacks=[]
)

channel_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_channels', setup_channels)],
    states={
        WAITING_CHANNEL_SELECTION: [CallbackQueryHandler(handle_channel_selection)],
    },
    fallbacks=[]
)

trading_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_trading', setup_trading)],
    states={
        WAITING_SETTINGS_SOURCE: [CallbackQueryHandler(handle_trading_settings)],
        WAITING_LEVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leverage)],
        WAITING_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stop_loss)],
        WAITING_BALANCE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_balance_percent)],
        WAITING_TP1_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp1_settings)],
        WAITING_TP2_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp2_settings)],
        WAITING_TP3_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp3_settings)],
        WAITING_TRAILING_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_percent)],
    },
    fallbacks=[]
)

def main():
    """Start the bot"""
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"
    
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(binance_conv_handler)
    application.add_handler(telegram_conv_handler)
    application.add_handler(channel_conv_handler)
    application.add_handler(trading_conv_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("configure_tp", configure_tp))
    application.add_handler(CommandHandler("configure_trailing", configure_trailing))
    application.add_handler(CommandHandler("start_monitoring", start_monitoring))
    application.add_handler(CommandHandler("stop_monitoring", stop_monitoring))
    application.add_handler(CommandHandler("test_simple", test_webhook_simple))
    application.add_handler(CommandHandler("test_advanced", test_webhook_advanced))

    print("🤖 Trading Bot v3.3 Starting...")
    print("✅ Configurable Multi-TP: TP1, TP2, TP3")
    print("✅ Adjustable Trailing Stop")
    print("✅ Enhanced Balance Checking")
    print("✅ Full Bot Configuration")
    print("📊 Ready!")
    
    application.run_polling()

if __name__ == '__main__':
    main()
