#!/usr/bin/env python3
"""
Telegram Trading Bot v4.0 - ADVANCED TP & TRAILING STOP
- Feature: Multiple take profit levels (2.5%, 5.0%, 7.5%) with partial closing (50%, 50%, 100%)
- Feature: Trailing stop loss with activation threshold
- Feature: Configurable TP/SL settings in bot menu
- Enhanced: Real-time position tracking with trailing stop
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
 WAITING_MIN_ORDER, WAITING_TP1_PERCENT, WAITING_TP2_PERCENT,
 WAITING_TP3_PERCENT, WAITING_TP1_CLOSE, WAITING_TP2_CLOSE,
 WAITING_TP3_CLOSE, WAITING_TRAILING_ENABLED, 
 WAITING_TRAILING_PERCENT, WAITING_TRAILING_ACTIVATION) = range(22)

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
    
    # Multiple TP configuration
    tp1_percent: float = 2.5
    tp2_percent: float = 5.0
    tp3_percent: float = 7.5
    tp1_close_percent: float = 50.0
    tp2_close_percent: float = 50.0
    tp3_close_percent: float = 100.0
    
    # Trailing stop configuration
    trailing_stop_enabled: bool = True
    trailing_stop_percent: float = 2.0
    trailing_activation_percent: float = 1.0
    
    balance_percent: float = 1.0
    monitored_channels: List[str] = None
    user_id: int = 0
    use_signal_settings: bool = True
    create_sl_tp: bool = True
    make_webhook_enabled: bool = True
    make_webhook_url: str = DEFAULT_WEBHOOK_URL
    minimum_order_usd: float = 5.0
    
    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

@dataclass
class ActivePosition:
    """Track active positions with their SL/TP orders and trailing stop"""
    symbol: str
    user_id: int
    side: str
    quantity: float
    entry_price: float
    remaining_quantity: float = 0
    stop_loss_order_id: Optional[int] = None
    take_profit_order_ids: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = None
    
    # Trailing stop fields
    trailing_enabled: bool = False
    trailing_activation_price: Optional[float] = None
    trailing_activated: bool = False
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    trailing_stop_distance: float = 0.02
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity

class MakeWebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_trade_data(self, trade_ Dict[str, Any]) -> bool:
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

    def test_webhook(self, test_type="simple") -> Dict[str, Any]:
        """Test webhook connection"""
        try:
            test_data = {
                "text": "Test from Trading Bot v4.0",
                "status": "TEST",
                "time": datetime.now().strftime('%H:%M:%S'),
                "date": datetime.now().strftime('%Y-%m-%d'),
                "webhook_version": "4.0"
            }
            
            response = requests.post(self.webhook_url, json=test_data, timeout=15)
            return {
                'success': response.status_code == 200,
                'status_code': response.status_code,
                'response_text': response.text[:500]
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

class SignalDetector:
    @staticmethod
    def parse_signals(text):
        """Enhanced signal parsing"""
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
            symbol = sym + 'USDT' if not sym.endswith('USDT') else sym
            
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
                continue
                
            # Entry price
            entry = None
            for l in lines:
                patterns = [
                    r'Entry[:\s]*([\d.,]+)',
                    r'Вход[:\s]*([\d.,]+)',
                    r'@\s*([\d.,]+)',
                    r'Price[:\s]*([\d.,]+)'
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
                    r'Take\s*Profit[:\s]*([\d.,]+)'
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, l, re.I)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
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
                    r'SL[:\s]*([\d.,]+)'
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
                    r'Leverage[:\s]*([\\d]+)',
                    r'([\\d]+)\s*[xх]'
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
        self.user_ Dict[int, BotConfig] = {}
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
        if user_id not in self.user_
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
            
            self.symbol_info_cache[symbol] = precision_info
            logger.info(f"📏 Symbol precision for {symbol}: qty={qty_precision}, price={price_precision}")
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

    async def cancel_related_orders(self, symbol: str, user_id: int, filled_order_type: str, bot_instance):
        """Cancel SL when TP fills, or cancel remaining TPs when SL fills"""
        try:
            position = self.active_positions.get(symbol)
            if not position:
                logger.info(f"⚠️ No active position found for {symbol}")
                return
                
            logger.info(f"🔄 Canceling related orders for {symbol} after {filled_order_type} filled")
            cancelled_orders = []
            
            if filled_order_type == "TAKE_PROFIT" and position.stop_loss_order_id:
                try:
                    self.binance_client.futures_cancel_order(
                        symbol=symbol,
                        orderId=position.stop_loss_order_id
                    )
                    cancelled_orders.append(f"SL-{position.stop_loss_order_id}")
                    logger.info(f"✅ Cancelled Stop Loss order: {position.stop_loss_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to cancel SL: {e}")
                    
            elif filled_order_type == "STOP_LOSS":
                for tp_info in position.take_profit_order_ids:
                    try:
                        self.binance_client.futures_cancel_order(
                            symbol=symbol,
                            orderId=tp_info['order_id']
                        )
                        cancelled_orders.append(f"TP-{tp_info['order_id']}")
                        logger.info(f"✅ Cancelled Take Profit order: {tp_info['order_id']}")
                    except Exception as e:
                        logger.error(f"❌ Failed to cancel TP: {e}")
                        
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

    async def update_trailing_stop(self, symbol: str, current_price: float, position: ActivePosition, bot_instance):
        """Update trailing stop logic"""
        try:
            if not position.trailing_enabled:
                return
                
            # Check if trailing stop should be activated
            if not position.trailing_activated:
                if position.side == 'BUY':  # LONG position
                    if current_price >= position.trailing_activation_price:
                        position.trailing_activated = True
                        position.highest_price = current_price
                        logger.info(f"🎯 Trailing stop ACTIVATED for {symbol} at {current_price}")
                        
                        await bot_instance.send_message(
                            chat_id=position.user_id,
                            text=f"🎯 <b>Trailing Stop Activated</b>\n\n💰 {symbol}\n📈 Price: {current_price}\n✅ Trailing will now follow price movements",
                            parse_mode='HTML'
                        )
                else:  # SHORT position
                    if current_price <= position.trailing_activation_price:
                        position.trailing_activated = True
                        position.lowest_price = current_price
                        logger.info(f"🎯 Trailing stop ACTIVATED for {symbol} at {current_price}")
                        
            # Update trailing stop if activated
            if position.trailing_activated:
                if position.side == 'BUY':  # LONG position
                    if current_price > position.highest_price:
                        position.highest_price = current_price
                        new_stop_price = current_price * (1 - position.trailing_stop_distance)
                        
                        # Cancel old SL and create new one
                        if position.stop_loss_order_id:
                            try:
                                self.binance_client.futures_cancel_order(
                                    symbol=symbol,
                                    orderId=position.stop_loss_order_id
                                )
                            except:
                                pass
                                
                            # Create new trailing SL
                            precision_info = self.get_symbol_precision(symbol)
                            new_stop_rounded = self.round_price(
                                new_stop_price, 
                                precision_info['tick_size'], 
                                precision_info['price_precision']
                            )
                            
                            sl_order = self.binance_client.futures_create_order(
                                symbol=symbol,
                                side='SELL',
                                type='STOP_MARKET',
                                quantity=position.remaining_quantity,
                                stopPrice=new_stop_rounded,
                                closePosition=True
                            )
                            
                            position.stop_loss_order_id = sl_order['orderId']
                            logger.info(f"📈 Trailing SL updated for {symbol}: {new_stop_rounded} (highest: {current_price})")
                            
                else:  # SHORT position
                    if current_price < position.lowest_price:
                        position.lowest_price = current_price
                        new_stop_price = current_price * (1 + position.trailing_stop_distance)
                        
                        # Cancel old SL and create new one
                        if position.stop_loss_order_id:
                            try:
                                self.binance_client.futures_cancel_order(
                                    symbol=symbol,
                                    orderId=position.stop_loss_order_id
                                )
                            except:
                                pass
                                
                            # Create new trailing SL
                            precision_info = self.get_symbol_precision(symbol)
                            new_stop_rounded = self.round_price(
                                new_stop_price, 
                                precision_info['tick_size'], 
                                precision_info['price_precision']
                            )
                            
                            sl_order = self.binance_client.futures_create_order(
                                symbol=symbol,
                                side='BUY',
                                type='STOP_MARKET',
                                quantity=position.remaining_quantity,
                                stopPrice=new_stop_rounded,
                                closePosition=True
                            )
                            
                            position.stop_loss_order_id = sl_order['orderId']
                            logger.info(f"📉 Trailing SL updated for {symbol}: {new_stop_rounded} (lowest: {current_price})")
                            
        except Exception as e:
            logger.error(f"❌ Error updating trailing stop: {e}")

    async def monitor_orders(self, bot_instance):
        """Monitor open orders and manage trailing stops"""
        try:
            if self.order_monitor_running:
                return
                
            self.order_monitor_running = True
            logger.info("👁️ Order monitor started with trailing stop support")
            
            while self.order_monitor_running:
                try:
                    for symbol, position in list(self.active_positions.items()):
                        try:
                            # Get current price
                            ticker = self.binance_client.futures_symbol_ticker(symbol=symbol)
                            current_price = float(ticker['price'])
                            
                            # Update trailing stop
                            await self.update_trailing_stop(symbol, current_price, position, bot_instance)
                            
                            # Check open orders
                            open_orders = self.binance_client.futures_get_open_orders(symbol=symbol)
                            open_order_ids = [int(order['orderId']) for order in open_orders]
                            
                            # Check if SL filled
                            if position.stop_loss_order_id and position.stop_loss_order_id not in open_order_ids:
                                logger.info(f"🛑 Stop Loss filled for {symbol}")
                                await self.cancel_related_orders(symbol, position.user_id, "STOP_LOSS", bot_instance)
                                
                            # Check if any TP filled
                            for tp_info in position.take_profit_order_ids:
                                if tp_info['order_id'] not in open_order_ids and not tp_info.get('filled', False):
                                    logger.info(f"🎯 Take Profit {tp_info['level']} filled for {symbol}")
                                    tp_info['filled'] = True
                                    
                                    # Update remaining quantity
                                    position.remaining_quantity -= tp_info['quantity']
                                    
                                    # If last TP filled, clean up
                                    if position.remaining_quantity <= 0.001:  # Small threshold for float precision
                                        logger.info(f"✅ All TPs filled for {symbol}")
                                        await self.cancel_related_orders(symbol, position.user_id, "TAKE_PROFIT", bot_instance)
                                        break
                                        
                                    await bot_instance.send_message(
                                        chat_id=position.user_id,
                                        text=f"🎯 <b>TP{tp_info['level']} Hit!</b>\n\n💰 {symbol}\n📊 Closed: {tp_info['close_percent']}%\n💵 Price: {tp_info['price']}\n📦 Remaining: {position.remaining_quantity:.4f}",
                                        parse_mode='HTML'
                                    )
                                    
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
                                   sl_price: Optional[float], config: BotConfig, user_id: int) -> Dict[str, Any]:
        """Create stop loss and multiple take profit orders with partial closing"""
        try:
            results = {'stop_loss': None, 'take_profits': []}
            
            precision_info = self.get_symbol_precision(symbol)
            if 'error' in precision_info:
                logger.error(f"❌ Cannot create SL/TP: {precision_info['error']}")
                return results
                
            tick_size = precision_info['tick_size']
            price_precision = precision_info['price_precision']
            step_size = precision_info['step_size']
            qty_precision = precision_info['qty_precision']
            
            logger.info(f"📐 Using precision: price={price_precision}, qty={qty_precision}")
            
            # Create Stop Loss
            if sl_price:
                try:
                    sl_side = 'SELL' if side == 'BUY' else 'BUY'
                    sl_price_rounded = self.round_price(sl_price, tick_size, price_precision)
                    
                    logger.info(f"🛑 Creating Stop Loss: {sl_price_rounded}")
                    
                    sl_order = self.binance_client.futures_create_order(
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
            
            # Create Multiple Take Profits with partial closing
            tp_configs = [
                {'percent': config.tp1_percent, 'close_percent': config.tp1_close_percent, 'level': 1},
                {'percent': config.tp2_percent, 'close_percent': config.tp2_close_percent, 'level': 2},
                {'percent': config.tp3_percent, 'close_percent': config.tp3_close_percent, 'level': 3}
            ]
            
            cumulative_close = 0
            remaining_qty = quantity
            
            for i, tp_config in enumerate(tp_configs):
                try:
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    
                    # Calculate TP price
                    if side == 'BUY':
                        tp_price = entry_price * (1 + tp_config['percent'] / 100)
                    else:
                        tp_price = entry_price * (1 - tp_config['percent'] / 100)
                    
                    # Calculate quantity to close
                    if i < 2:  # First two TPs close percentage of total
                        close_qty = quantity * (tp_config['close_percent'] / 100)
                    else:  # Last TP closes everything remaining
                        close_qty = remaining_qty
                    
                    tp_price_rounded = self.round_price(tp_price, tick_size, price_precision)
                    tp_quantity_rounded = self.round_quantity(close_qty, step_size, qty_precision)
                    
                    logger.info(f"🎯 Creating TP{tp_config['level']}: {tp_price_rounded} qty={tp_quantity_rounded} ({tp_config['close_percent']}%)")
                    
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
                        'level': tp_config['level'],
                        'close_percent': tp_config['close_percent'],
                        'filled': False
                    })
                    
                    remaining_qty -= tp_quantity_rounded
                    
                    logger.info(f"✅ TP{tp_config['level']} created: {tp_order['orderId']} @ {tp_price_rounded}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to create TP{tp_config['level']}: {e}")
            
            # Setup trailing stop
            if config.trailing_stop_enabled and (results['stop_loss'] or results['take_profits']):
                trailing_activation_price = None
                
                if side == 'BUY':  # LONG
                    trailing_activation_price = entry_price * (1 + config.trailing_activation_percent / 100)
                else:  # SHORT
                    trailing_activation_price = entry_price * (1 - config.trailing_activation_percent / 100)
                
                position = ActivePosition(
                    symbol=symbol,
                    user_id=user_id,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    remaining_quantity=quantity,
                    stop_loss_order_id=results['stop_loss'],
                    take_profit_order_ids=results['take_profits'],
                    trailing_enabled=config.trailing_stop_enabled,
                    trailing_activation_price=trailing_activation_price,
                    trailing_stop_distance=config.trailing_stop_percent / 100,
                    highest_price=entry_price if side == 'BUY' else None,
                    lowest_price=entry_price if side == 'SELL' else None
                )
                
                self.active_positions[symbol] = position
                logger.info(f"📍 Tracking position for {symbol} with trailing stop @ {trailing_activation_price}")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Error creating SL/TP orders: {e}")
            return {'stop_loss': None, 'take_profits': []}

    async def execute_trade(self, signal: TradingSignal, config: BotConfig) -> Dict[str, Any]:
        """Enhanced trade execution with multiple TPs and trailing stop"""
        try:
            logger.info(f"🚀 EXECUTING TRADE: {signal.symbol} {signal.trade_type}")
            
            if not self.binance_client:
                success = await self.setup_binance_client(config)
                if not success:
                    return {'success': False, 'error': 'Failed to connect to Binance API'}
            
            # Get account balance
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
                logger.error(f"❌ Error getting account balance: {e}")
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
                logger.warning(f"⚠️ Leverage setting warning: {e}")
            
            # Get current price
            ticker = self.binance_client.futures_symbol_ticker(symbol=signal.symbol)
            current_price = float(ticker['price'])
            entry_price = signal.entry_price or current_price
            
            # Calculate position size
            trade_amount = usdt_balance * (config.balance_percent / 100)
            raw_quantity = (trade_amount * leverage) / entry_price
            
            logger.info(f"🧮 Trade calculation:")
            logger.info(f"  Balance: {usdt_balance} USDT")
            logger.info(f"  Trade amount: ${trade_amount:.2f} ({config.balance_percent}%)")
            logger.info(f"  Entry price: {entry_price}")
            logger.info(f"  Raw quantity: {raw_quantity}")
            
            # Round quantity
            precision_info = self.get_symbol_precision(signal.symbol)
            if 'error' in precision_info:
                return {'success': False, 'error': precision_info['error']}
            
            step_size = precision_info['step_size']
            min_qty = precision_info['min_qty']
            qty_precision = precision_info['qty_precision']
            
            quantity = self.round_quantity(raw_quantity, step_size, qty_precision)
            
            if quantity < min_qty or quantity <= 0:
                return {'success': False, 'error': f'Quantity {quantity} below minimum {min_qty}'}
            
            order_value = quantity * entry_price
            side = 'BUY' if signal.trade_type == 'LONG' else 'SELL'
            
            # Execute main order
            order = self.binance_client.futures_create_order(
                symbol=signal.symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"✅ Main order executed: {order['orderId']}")
            
            # Create SL/TP
            sl_price = None
            sl_tp_result = {'stop_loss': None, 'take_profits': []}
            
            if config.create_sl_tp:
                if config.use_signal_settings and signal.stop_loss:
                    sl_price = signal.stop_loss
                else:
                    if signal.trade_type == 'LONG':
                        sl_price = current_price * (1 - config.stop_loss_percent / 100)
                    else:
                        sl_price = current_price * (1 + config.stop_loss_percent / 100)
                
                # Validate SL price
                if sl_price:
                    if signal.trade_type == 'LONG' and sl_price >= current_price:
                        sl_price = current_price * 0.95
                    elif signal.trade_type == 'SHORT' and sl_price <= current_price:
                        sl_price = current_price * 1.05
                
                sl_tp_result = await self.create_sl_tp_orders(
                    signal.symbol, side, quantity, current_price, sl_price, config, config.user_id
                )
            
            # Send webhook data
            if config.make_webhook_enabled and config.user_id in self.webhook_loggers:
                tp_text = f"TP1: {config.tp1_percent}%/{config.tp1_close_percent}%, TP2: {config.tp2_percent}%/{config.tp2_close_percent}%, TP3: {config.tp3_percent}%/{config.tp3_close_percent}%"
                trailing_text = f"Trailing: {'ON' if config.trailing_stop_enabled else 'OFF'} ({config.trailing_stop_percent}%)"
                
                trade_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': signal.symbol,
                    'trade_type': signal.trade_type,
                    'entry_price': current_price,
                    'quantity': quantity,
                    'leverage': leverage,
                    'order_id': order['orderId'],
                    'stop_loss': sl_price if sl_price else '',
                    'take_profit': tp_text,
                    'status': 'EXECUTED',
                    'balance_used': f"${trade_amount:.2f}",
                    'channel_id': signal.channel_id,
                    'pnl': '0.00',
                    'notes': f"Multi-TP + {trailing_text}",
                    'order_value': f"${order_value:.2f}",
                    'sl_order_id': sl_tp_result['stop_loss'] if sl_tp_result['stop_loss'] else '',
                    'tp_order_ids': ', '.join([str(tp['order_id']) for tp in sl_tp_result['take_profits']]),
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
                'order_value': order_value,
                'trailing_enabled': config.trailing_stop_enabled
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
                    'user_id': config.user_id
                }
                self.webhook_loggers[config.user_id].send_trade_data(trade_data)
            
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
                        text=f"📨 <b>Message Received</b>\n\n{message_text[:300]}\n\n🔍 Processing...",
                        parse_mode='HTML'
                    )
                    
                    signal = self.parse_trading_signal(message_text, list(matching_channels)[0])
                    
                    if signal:
                        result = await self.execute_trade(signal, user_config)
                        
                        if result['success']:
                            tp_info = "\n".join([
                                f"🎯 TP{tp['level']}: {tp['price']} ({tp['close_percent']}%)"
                                for tp in result.get('take_profit_ids', [])
                            ])
                            
                            trailing_text = "🔄 Trailing: ON" if result.get('trailing_enabled') else "🔄 Trailing: OFF"
                            
                            await bot_instance.send_message(
                                chat_id=user_id,
                                text=f"""✅ <b>Trade Executed!</b>

💰 {signal.symbol} {signal.trade_type}
📊 Quantity: {result['quantity']}
💵 Entry: {result['price']}
⚡ Leverage: {result['leverage']}x
📝 Order ID: {result['order_id']}

{tp_info}
🛑 Stop Loss: {result.get('sl_price', 'N/A')}

{trailing_text}
💼 Value: ${result.get('order_value', 0):.2f}""",
                                parse_mode='HTML'
                            )
                        else:
                            await bot_instance.send_message(
                                chat_id=user_id,
                                text=f"❌ <b>Trade Failed</b>\n\n{result.get('error', 'Unknown error')}",
                                parse_mode='HTML'
                            )
                
                except Exception as e:
                    logger.error(f"❌ Error handling message: {e}")
            
            self.active_monitoring[user_id] = True
            logger.info(f"✅ Monitoring started for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error starting monitoring: {e}")
            return False

    async def stop_monitoring(self, user_id: int) -> bool:
        try:
            self.active_monitoring[user_id] = False
            
            if user_id in self.user_monitoring_clients:
                await self.user_monitoring_clients[user_id].disconnect()
                del self.user_monitoring_clients[user_id]
            
            logger.info(f"✅ Monitoring stopped for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error stopping monitoring: {e}")
            return False


# Initialize bot
trading_bot = TradingBot()


# Telegram Bot Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
         InlineKeyboardButton("📊 Status", callback_data="status")],
        [InlineKeyboardButton("📡 Channels", callback_data="channels"),
         InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🎯 TP Settings", callback_data="tp_settings"),
         InlineKeyboardButton("🔄 Trailing Stop", callback_data="trailing_settings")],
        [InlineKeyboardButton("▶️ Start Monitoring", callback_data="start_monitoring"),
         InlineKeyboardButton("⏹️ Stop Monitoring", callback_data="stop_monitoring")],
        [InlineKeyboardButton("🌐 Webhook Test", callback_data="test_webhook")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""🤖 <b>Trading Bot v4.0</b>

Welcome! This bot features:
✅ Multi-level Take Profits (3 levels)
✅ Partial Position Closing
✅ Trailing Stop Loss
✅ Signal Auto-Trading
✅ Make.com Integration

User ID: <code>{user_id}</code>

Choose an option below:""",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    config = trading_bot.get_user_config(user_id)
    
    if query.data == "tp_settings":
        keyboard = [
            [InlineKeyboardButton(f"TP1: {config.tp1_percent}% / {config.tp1_close_percent}% close", callback_data="edit_tp1")],
            [InlineKeyboardButton(f"TP2: {config.tp2_percent}% / {config.tp2_close_percent}% close", callback_data="edit_tp2")],
            [InlineKeyboardButton(f"TP3: {config.tp3_percent}% / {config.tp3_close_percent}% close", callback_data="edit_tp3")],
            [InlineKeyboardButton("« Back", callback_data="settings")]
        ]
        
        await query.edit_message_text(
            f"""🎯 <b>Take Profit Settings</b>

Current Configuration:
━━━━━━━━━━━━━━━━━━
📊 TP1: +{config.tp1_percent}% → Close {config.tp1_close_percent}%
📊 TP2: +{config.tp2_percent}% → Close {config.tp2_close_percent}%
📊 TP3: +{config.tp3_percent}% → Close {config.tp3_close_percent}%

This means:
• At TP1: Close {config.tp1_close_percent}% of position
• At TP2: Close {config.tp2_close_percent}% of remaining
• At TP3: Close {config.tp3_close_percent}% (everything left)

Click to edit each level:""",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        
    elif query.data == "trailing_settings":
        status = "✅ ENABLED" if config.trailing_stop_enabled else "❌ DISABLED"
        keyboard = [
            [InlineKeyboardButton(f"Toggle: {status}", callback_data="toggle_trailing")],
            [InlineKeyboardButton(f"Distance: {config.trailing_stop_percent}%", callback_data="edit_trailing_distance")],
            [InlineKeyboardButton(f"Activation: {config.trailing_activation_percent}%", callback_data="edit_trailing_activation")],
            [InlineKeyboardButton("« Back", callback_data="settings")]
        ]
        
        await query.edit_message_text(
            f"""🔄 <b>Trailing Stop Settings</b>

Status: {status}
━━━━━━━━━━━━━━━━━━
📏 Trailing Distance: {config.trailing_stop_percent}%
🎯 Activation Threshold: {config.trailing_activation_percent}%

How it works:
• Activates when profit reaches {config.trailing_activation_percent}%
• Follows price {config.trailing_stop_percent}% behind
• Protects profits automatically

Click to modify:""",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == "toggle_trailing":
        config.trailing_stop_enabled = not config.trailing_stop_enabled
        status = "✅ ENABLED" if config.trailing_stop_enabled else "❌ DISABLED"
        
        keyboard = [
            [InlineKeyboardButton(f"Toggle: {status}", callback_data="toggle_trailing")],
            [InlineKeyboardButton(f"Distance: {config.trailing_stop_percent}%", callback_data="edit_trailing_distance")],
            [InlineKeyboardButton(f"Activation: {config.trailing_activation_percent}%", callback_data="edit_trailing_activation")],
            [InlineKeyboardButton("« Back", callback_data="settings")]
        ]
        
        await query.edit_message_text(
            f"""🔄 <b>Trailing Stop Settings</b>

Status: {status}
━━━━━━━━━━━━━━━━━━
📏 Trailing Distance: {config.trailing_stop_percent}%
🎯 Activation Threshold: {config.trailing_activation_percent}%

Updated successfully!""",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == "status":
        monitoring_status = "🟢 ACTIVE" if config.user_id in trading_bot.active_monitoring and trading_bot.active_monitoring[config.user_id] else "🔴 INACTIVE"
        active_positions = len([p for p in trading_bot.active_positions.values() if p.user_id == user_id])
        
        await query.edit_message_text(
            f"""📊 <b>Bot Status</b>

Monitoring: {monitoring_status}
Active Positions: {active_positions}
Channels: {len(config.monitored_channels)}

⚙️ Configuration:
━━━━━━━━━━━━━━━━━━
💰 Balance Use: {config.balance_percent}%
⚡ Leverage: {config.leverage}x
🛑 Stop Loss: {config.stop_loss_percent}%

🎯 Take Profits:
• TP1: {config.tp1_percent}% ({config.tp1_close_percent}%)
• TP2: {config.tp2_percent}% ({config.tp2_close_percent}%)
• TP3: {config.tp3_percent}% ({config.tp3_close_percent}%)

🔄 Trailing Stop: {'ON' if config.trailing_stop_enabled else 'OFF'}
   Distance: {config.trailing_stop_percent}%
   Activation: {config.trailing_activation_percent}%""",
            parse_mode='HTML'
        )
    
    elif query.data == "balance":
        balance_info = await trading_bot.get_account_balance(config)
        
        if balance_info.get('success'):
            await query.edit_message_text(
                f"""💰 <b>Account Balance</b>

💵 USDT Balance: ${balance_info['usdt_balance']:.2f}
✅ Available: ${balance_info['usdt_available']:.2f}
📊 Wallet Balance: ${balance_info['usdt_wallet_balance']:.2f}
💼 Total Balance: ${balance_info['total_wallet_balance']:.2f}
📈 Unrealized PNL: ${balance_info['total_unrealized_pnl']:.2f}

Per Trade: ${balance_info['usdt_balance'] * config.balance_percent / 100:.2f} ({config.balance_percent}%)""",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                f"❌ <b>Error</b>\n\n{balance_info.get('error', 'Unknown error')}",
                parse_mode='HTML'
            )
    
    elif query.data == "start_monitoring":
        success = await trading_bot.start_monitoring(user_id, context.bot)
        
        if success:
            await query.edit_message_text(
                "✅ <b>Monitoring Started</b>\n\nBot is now listening for signals in your configured channels.",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                "❌ <b>Failed to Start</b>\n\nPlease configure channels first.",
                parse_mode='HTML'
            )
    
    elif query.data == "stop_monitoring":
        success = await trading_bot.stop_monitoring(user_id)
        
        if success:
            await query.edit_message_text(
                "⏹️ <b>Monitoring Stopped</b>",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                "❌ <b>Error Stopping Monitoring</b>",
                parse_mode='HTML'
            )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    await update.message.reply_text(
        """📖 <b>Bot Help - v4.0</b>

<b>Commands:</b>
/start - Main menu
/help - This help message
/status - View bot status
/balance - Check account balance

<b>Features:</b>

🎯 <b>Multi-Level Take Profits:</b>
• TP1: Close 50% at 2.5% profit
• TP2: Close 50% of remaining at 5.0%
• TP3: Close everything at 7.5%

🔄 <b>Trailing Stop:</b>
• Activates after 1% profit
• Follows price 2% behind
• Protects your profits automatically

⚙️ <b>All values are configurable!</b>
Use the settings menu to customize TP levels, percentages, and trailing stop parameters.

📊 <b>How It Works:</b>
1. Bot monitors your channels
2. Detects trading signals
3. Executes trades automatically
4. Places 3 TPs + Trailing SL
5. Manages position automatically

Questions? Check the /settings menu!""",
        parse_mode='HTML'
    )


def main():
    """Main function"""
    # Use your bot token here
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"  # Replace with your actual bot token
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    logger.info("🚀 Bot started - v4.0 with Multi-TP and Trailing Stop")
    application.run_polling()


if __name__ == '__main__':
    main()
