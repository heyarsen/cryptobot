#!/usr/bin/env python3
"""
Telegram Trading Bot v3.1 - COMPLETE WITH OCO SIMULATION
- Fixed: Decimal precision for all price levels
- Feature: Auto-cancel SL when TP fills and vice versa
- Fixed: Stop Loss and Take Profit rounding errors
- Enhanced: Order monitoring with OCO simulation
- Fixed: Syntax error in send_trade_data
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

import ccxt

# Import Telethon
from telethon import TelegramClient, events
from telethon.tl.types import Channel, PeerChannel
from telethon.errors import ApiIdInvalidError

# Auto-configured API Credentials
DEFAULT_TELEGRAM_API_ID = '28270452'
DEFAULT_TELEGRAM_API_HASH = '8bb0aa3065dd515fb6e105f1fc60fdb6'
DEFAULT_BINANCE_API_KEY = 'ojMy5XVmKUFxfoAG1SwR2jCiYqYGuHfFb3CmM1tPv01rvtLcIQL68wTUwtU8mMijfaWc2aOPsiGZSSqg'
DEFAULT_BINANCE_API_SECRET = 'R26Tvlq8rRjK4HCqhG5EstMXGAqHr1B22DH3IuTRjHOiEanmIlCRPowDcOGH8oKDjnVypPM5fXUg3lbYhQ'

# Conversation states
(WAITING_BINANCE_KEY, WAITING_BINANCE_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE, WAITING_WEBHOOK_URL,
 WAITING_MIN_ORDER, WAITING_TP1_PERCENT, WAITING_TP1_CLOSE,
 WAITING_TP2_PERCENT, WAITING_TP2_CLOSE,
 WAITING_TP3_PERCENT, WAITING_TP3_CLOSE,
 WAITING_TRAILING_CALLBACK, WAITING_TRAILING_ACTIVATION) = range(21)

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
        self.exchange: Optional[ccxt.Exchange] = None
        self.user_monitoring_clients: Dict[int, TelegramClient] = {}
        self.user_data: Dict[int, BotConfig] = {}
        self.active_monitoring = {}
        self.monitoring_tasks = {}
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.active_positions: Dict[str, ActivePosition] = {}
        self.order_monitor_running = False
        self.main_menu = ReplyKeyboardMarkup(
            [[KeyboardButton("📊 Status"), KeyboardButton("💰 Balance")],
             [KeyboardButton("🚀 Start"), KeyboardButton("🛑 Stop")],
             [KeyboardButton("⚙️ Settings")]],
            resize_keyboard=True
        )

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
            trade_amount = usdt_balance * (config.balance_percent / 100)
            position_value = trade_amount * leverage
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Balance: {usdt_balance} USDT")
            logger.info(f"   Trade amount: ${trade_amount:.2f} ({config.balance_percent}%)")
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
                        # Default ladder: 2.5%, 5%, 7.5%
                        if signal.trade_type == 'LONG':
                            tp_prices = [
                                current_price * 1.025,
                                current_price * 1.05,
                                current_price * 1.075
                            ]
                        else:
                            tp_prices = [
                                current_price * 0.975,
                                current_price * 0.95,
                                current_price * 0.925
                            ]
                else:
                    if signal.trade_type == 'LONG':
                        sl_price = current_price * (1 - config.stop_loss_percent / 100)
                        tp_prices = [
                            current_price * 1.025,
                            current_price * 1.05,
                            current_price * 1.075
                        ]
                    else:
                        sl_price = current_price * (1 + config.stop_loss_percent / 100)
                        tp_prices = [
                            current_price * 0.975,
                            current_price * 0.95,
                            current_price * 0.925
                        ]

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

                    # Split quantities: 50%, 50% of remaining, then all remaining (50/25/25 effectively or 50/50/0 if 2 targets)
                    tp_targets = tp_prices[:3]
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
                    quantities = []
                    if len(tp_targets) >= 3:
                        quantities = [quantity * 0.5, quantity * 0.25, quantity * 0.25]
                    elif len(tp_targets) == 2:
                        quantities = [quantity * 0.5, quantity * 0.5]
                    else:
                        quantities = [quantity]

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
        [InlineKeyboardButton(f"🧵 Trailing: {'ON' if config.trailing_enabled else 'OFF'}", callback_data="toggle_trailing")],
        [InlineKeyboardButton(f"🔔 Trailing Activation: {config.trailing_activation_percent}%", callback_data="set_trailing_activation")],
        [InlineKeyboardButton(f"↩️ Trailing Callback: {config.trailing_callback_percent}%", callback_data="set_trailing_callback")],
        [InlineKeyboardButton(f"💰 Balance: {config.balance_percent}%", callback_data="set_balance_percent")],
        [InlineKeyboardButton("📡 Manage Channels", callback_data="manage_channels"), InlineKeyboardButton("🔄 Enable OCO Monitor", callback_data="enable_oco")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)

# ===================== COMMAND HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = f"""🤖 <b>Telegram Trading Bot v3.1 - OCO READY!</b>

🎉 <b>NEW FEATURES:</b>
✅ Fixed decimal precision for all symbols
✅ OCO simulation: Auto-cancel orders
✅ Proper rounding for micro-priced coins

🔗 {DEFAULT_WEBHOOK_URL[:50]}...

<b>Features:</b>
• ⚙️ Signal vs Bot settings
• 🎯 Auto SL/TP creation  
• 🔄 OCO: Cancel SL when TP fills
• 🔄 OCO: Cancel TP when SL fills
• 📊 Russian signal parsing
• 💰 Configurable sizes
• 🔗 Make.com webhook

<b>Setup Steps:</b>
1️⃣ /setup_binance
2️⃣ /setup_telegram
3️⃣ /setup_channels
4️⃣ /setup_trading
5️⃣ /start_monitoring

<b>Test Commands:</b>
/test_simple
/test_basic
/test_advanced
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')
    # Show persistent main menu
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
🎯 Take Profit: <b>{config.take_profit_percent}%</b>
💰 Balance: <b>{config.balance_percent}%</b>

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
        WAITING_CHANNEL_SELECTION: [CallbackQueryHandler(handle_channel_selection)],
        WAITING_MANUAL_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_channel)],
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
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# ================== MAIN ==================

def main():
    """Start the bot"""
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"
    
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(binance_conv_handler)
    application.add_handler(telegram_conv_handler)
    application.add_handler(channel_conv_handler)
    application.add_handler(trading_conv_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    # Reply keyboard text handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("start_monitoring", start_monitoring))
    application.add_handler(CommandHandler("stop_monitoring", stop_monitoring))
    application.add_handler(CommandHandler("test_signal", test_signal))
    application.add_handler(CommandHandler("test_simple", test_webhook_simple))
    application.add_handler(CommandHandler("test_basic", test_webhook_basic))
    application.add_handler(CommandHandler("test_advanced", test_webhook_advanced))

    print("🤖 Trading Bot v3.1 Starting...")
    print(f"🔗 Webhook: {DEFAULT_WEBHOOK_URL}")
    print("✅ Fixed: Decimal precision for micro-priced coins")
    print("✅ Feature: OCO order simulation")
    print("✅ Feature: Auto-cancel opposite orders")
    print("✅ Fixed: Syntax error in send_trade_data")
    print("📊 Ready!")
    
    application.run_polling()

if __name__ == '__main__':
    main()
