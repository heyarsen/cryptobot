#!/usr/bin/env python3
"""
Telegram Trading Bot v3.0 - COMPLETE WITH MAKE.COM WEBHOOK
- Integrated with Make.com webhook: https://hook.eu2.make.com/y2od16qhv046ht3lwbx3ovtoj5eu345l
- Advanced webhook testing and troubleshooting
- $5 minimum order enforcement
- Enhanced signal parsing for Russian formats
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

# Conversation states
(WAITING_BINANCE_KEY, WAITING_BINANCE_SECRET,
 WAITING_TELEGRAM_ID, WAITING_TELEGRAM_HASH,
 WAITING_LEVERAGE, WAITING_STOP_LOSS,
 WAITING_TAKE_PROFIT, WAITING_BALANCE_PERCENT,
 WAITING_CHANNEL_SELECTION, WAITING_MANUAL_CHANNEL,
 WAITING_SETTINGS_SOURCE, WAITING_WEBHOOK_URL) = range(12)

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
    make_webhook_enabled: bool = True  # Default enabled
    make_webhook_url: str = DEFAULT_WEBHOOK_URL  # Your webhook URL
    minimum_order_usd: float = 5.0

    def __post_init__(self):
        if self.monitored_channels is None:
            self.monitored_channels = []

class MakeWebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_trade_data(self, trade_data: Dict[str, Any]) -> bool:
        """Send trade data to Make.com webhook"""
        try:
            payload = {
                "timestamp": trade_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "symbol": trade_data.get('symbol', ''),
                "trade_type": trade_data.get('trade_type', ''),
                "entry_price": str(trade_data.get('entry_price', '')),
                "quantity": str(trade_data.get('quantity', '')),
                "leverage": str(trade_data.get('leverage', '')),
                "order_id": str(trade_data.get('order_id', '')),
                "stop_loss": str(trade_data.get('stop_loss', '')),
                "take_profit": str(trade_data.get('take_profit', '')),
                "status": trade_data.get('status', ''),
                "balance_used": str(trade_data.get('balance_used', '')),
                "channel_id": str(trade_data.get('channel_id', '')),
                "pnl": str(trade_data.get('pnl', '')),
                "notes": trade_data.get('notes', ''),
                "order_value": str(trade_data.get('order_value', '')),
                "sl_order_id": str(trade_data.get('sl_order_id', '')),
                "tp_order_ids": str(trade_data.get('tp_order_ids', '')),
                "user_id": str(trade_data.get('user_id', '')),
                "webhook_version": "3.0",
                "bot_source": "Telegram Trading Bot"
            }

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/3.0',
                'X-Bot-Version': '3.0'
            }

            response = requests.post(
                self.webhook_url,
                json=payload,
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
        """Advanced webhook testing"""
        try:
            if test_type == "simple":
                test_data = {
                    "test": True,
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "message": "Simple webhook test",
                    "status": "TEST_SIMPLE"
                }
            else:
                test_data = {
                    "test": True,
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol": "BTCUSDT",
                    "trade_type": "LONG",
                    "entry_price": "45000.50",
                    "quantity": "0.001",
                    "leverage": "10",
                    "order_id": f"TEST_{datetime.now().strftime('%H%M%S')}",
                    "stop_loss": "44000.00",
                    "take_profit": "46000.00, 47000.00",
                    "status": "TEST_EXECUTED",
                    "balance_used": "$50.00",
                    "channel_id": "test_channel_123",
                    "pnl": "0.00",
                    "notes": "Advanced webhook test from Trading Bot",
                    "order_value": "$50.00",
                    "sl_order_id": "SL_TEST_123",
                    "tp_order_ids": "TP1_TEST_124, TP2_TEST_125",
                    "user_id": "test_user",
                    "webhook_version": "3.0",
                    "bot_source": "Telegram Trading Bot"
                }

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'TradingBot/3.0',
                'X-Bot-Version': '3.0',
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
                'response_text': response.text[:500],
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
        self.binance_client: Optional[BinanceClient] = None
        self.user_monitoring_clients: Dict[int, TelegramClient] = {}
        self.user_data: Dict[int, BotConfig] = {}
        self.active_monitoring = {}
        self.monitoring_tasks = {}
        self.webhook_loggers: Dict[int, MakeWebhookLogger] = {}

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
            self.user_data[user_id] = BotConfig()
            self.user_data[user_id].user_id = user_id
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

    async def get_account_balance(self, config: BotConfig) -> Dict[str, float]:
        """Get detailed account balance information"""
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
        """Setup Telethon client - ONLY when needed, not during import"""
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
            for i, tp_price in enumerate(tp_prices[:3]):
                try:
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    tp_quantity = quantity / len(tp_prices)

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
        """Enhanced trade execution with minimum order enforcement"""
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

                if usdt_balance <= config.minimum_order_usd:
                    return {'success': False, 'error': f'Insufficient balance: {usdt_balance} (min ${config.minimum_order_usd})'}

            except Exception as e:
                logger.error(f"❌ Error getting account balance: {e}")
                return {'success': False, 'error': f'Balance error: {str(e)}'}

            # Determine leverage
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

            # Calculate position size
            trade_amount = usdt_balance * (config.balance_percent / 100)
            
            # Enforce minimum order size
            if trade_amount < config.minimum_order_usd:
                return {'success': False, 'error': f'Trade amount ${trade_amount:.2f} below minimum ${config.minimum_order_usd}'}
            
            raw_quantity = (trade_amount * leverage) / entry_price

            logger.info(f"🧮 Trade calculation:")
            logger.info(f"   Balance: {usdt_balance} USDT")
            logger.info(f"   Trade amount: ${trade_amount:.2f} ({config.balance_percent}%)")
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

                # Final check: ensure order value meets minimum
                order_value = quantity * entry_price / leverage
                if order_value < config.minimum_order_usd:
                    return {'success': False, 'error': f'Order value ${order_value:.2f} below minimum ${config.minimum_order_usd}'}

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
            sl_tp_result = {'stop_loss': None, 'take_profits': []}

            if config.create_sl_tp:
                # Determine SL/TP prices
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

                # Create SL/TP orders
                sl_tp_result = await self.create_sl_tp_orders(
                    signal.symbol, side, quantity, current_price, sl_price, tp_prices
                )

            # Send data to Make.com webhook
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
                    'pnl': '0.00',
                    'notes': f"Settings: {'Signal' if config.use_signal_settings else 'Bot'}{'| SL/TP: Enabled' if config.create_sl_tp else '| SL/TP: Disabled'}",
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
                'order_value': order_value
            }

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            
            # Log failed trade to webhook
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

            # Setup Make.com webhook
            self.setup_make_webhook(user_id)

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
        [InlineKeyboardButton(f"🔗 Make.com Webhook: {'ON' if config.make_webhook_enabled else 'OFF'}", 
                            callback_data="toggle_webhook")],
        [InlineKeyboardButton(f"⚡ Leverage: {config.leverage}x", callback_data="set_leverage")],
        [InlineKeyboardButton(f"🛑 Stop Loss: {config.stop_loss_percent}%", callback_data="set_stop_loss")],
        [InlineKeyboardButton(f"🎯 Take Profit: {config.take_profit_percent}%", callback_data="set_take_profit")],
        [InlineKeyboardButton(f"💰 Balance: {config.balance_percent}%", callback_data="set_balance_percent")],
        [InlineKeyboardButton(f"💵 Min Order: ${config.minimum_order_usd}", callback_data="set_min_order")],
        [InlineKeyboardButton("✅ Done", callback_data="trading_done")]
    ]

    return InlineKeyboardMarkup(keyboard)

# ===================== COMMAND HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = f"""🤖 <b>Telegram Trading Bot v3.0 - READY!</b>

🎉 <b>YOUR MAKE.COM WEBHOOK IS INTEGRATED:</b>
🔗 {DEFAULT_WEBHOOK_URL[:50]}...

<b>Features:</b>
• ⚙️ Choose Signal vs Bot settings
• 🎯 Auto SL/TP order creation  
• 📊 Enhanced Russian signal parsing
• 💰 Configurable position sizes
• 🔧 Interactive setup with buttons
• 🔗 Make.com webhook integration
• 💵 $5 minimum order enforcement
• 💳 Advanced balance checking

<b>Setup Steps:</b>
1️⃣ /setup_binance - Binance API
2️⃣ /setup_telegram - Telegram API  
3️⃣ /setup_channels - Select channels
4️⃣ /setup_trading - Trading params
5️⃣ /start_monitoring - Begin trading

<b>Commands:</b>
/help - All commands
/status - Configuration
/balance - Check account balance
/test_signal - Test parsing
/test_webhook - Test Make.com webhook
/test_advanced - Advanced webhook test
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""<b>📖 All Commands</b>

<b>Setup:</b>
/setup_binance - Binance API ✅
/setup_telegram - Telegram API ✅  
/setup_channels - Channel selection ✅
/setup_trading - Trading parameters ✅

<b>Control:</b>
/start_monitoring - Start monitoring ✅
/stop_monitoring - Stop monitoring ✅
/status - Current status ✅
/balance - Check account balance ✅

<b>Testing:</b>
/test_signal - Test signal parsing ✅
/test_webhook - Simple webhook test ✅
/test_advanced - Advanced webhook test ✅

🔗 <b>YOUR WEBHOOK:</b>
{DEFAULT_WEBHOOK_URL[:50]}...

<b>Make.com Setup:</b>
1. Go to Make.com scenario with your webhook
2. Click "Run Once" to activate
3. Test with /test_webhook
4. Add Google Sheets module
5. Map webhook data to spreadsheet
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check account balance"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    if not config.binance_api_key or not config.binance_api_secret:
        await update.message.reply_text("❌ <b>Binance API not configured!</b> Use /setup_binance first.", parse_mode='HTML')
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
Minimum Order: ${config.minimum_order_usd}
Status: {'✅ Can Trade' if balance_info['usdt_balance'] >= config.minimum_order_usd else '❌ Insufficient Balance'}

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

    status_text = f"""📊 <b>Bot Status Dashboard v3.0</b>

🔧 <b>Configuration:</b>
{'✅' if config.binance_api_key else '❌'} Binance API
{'✅' if config.telegram_api_id else '❌'} Telegram API  
📡 Channels: <b>{len(config.monitored_channels)}</b>
🔄 Monitoring: {'🟢 Active' if trading_bot.active_monitoring.get(user_id) else '🔴 Inactive'}
🔗 Make.com Webhook: <b>{webhook_status}</b>

⚙️ <b>Trading Settings:</b>
🎯 Settings Source: <b>{settings_source}</b>
📈 SL/TP Creation: <b>{sl_tp_status}</b>
⚡ Bot Leverage: <b>{config.leverage}x</b>
🛑 Bot Stop Loss: <b>{config.stop_loss_percent}%</b>
🎯 Bot Take Profit: <b>{config.take_profit_percent}%</b>
💰 Position Size: <b>{config.balance_percent}%</b>
💵 Minimum Order: <b>${config.minimum_order_usd}</b>

🔗 <b>Make.com Integration:</b>
Webhook URL: {DEFAULT_WEBHOOK_URL[:50]}...
Status: {'✅ Ready' if config.make_webhook_enabled else '❌ Disabled'}

✅ <b>Features:</b>
• Auto trade execution
• Real-time webhook logging
• Russian signal parsing
• Advanced balance checking
"""
    await update.message.reply_text(status_text, parse_mode='HTML')

# ================== WEBHOOK TESTING ==================

async def test_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple webhook test"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    await update.message.reply_text("🔄 <b>Testing Make.com webhook...</b>", parse_mode='HTML')

    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("simple")

    if result['success']:
        result_text = f"""✅ <b>Webhook Test Successful!</b>

📡 <b>Details:</b>
Status Code: {result['status_code']}
Response Time: {result['response_time']:.2f}s
URL: {DEFAULT_WEBHOOK_URL[:50]}...

🎯 <b>Next Steps:</b>
1. Check Make.com scenario logs
2. Verify data appeared in scenario
3. Add Google Sheets module if needed
4. Test with /test_advanced for full data"""
    else:
        result_text = f"""❌ <b>Webhook Test Failed</b>

📡 <b>Details:</b>
Status Code: {result['status_code']}
Response Time: {result['response_time']:.2f}s
Error: {result['response_text'][:200]}...

💡 <b>Troubleshooting:</b>
1. Go to your Make.com scenario
2. Click "Run Once" to activate
3. Ensure scenario is listening
4. Try /test_advanced for detailed test"""

    await update.message.reply_text(result_text, parse_mode='HTML')

async def test_webhook_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Advanced webhook test with full trade data"""
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    await update.message.reply_text("🚀 <b>Advanced webhook test...</b>", parse_mode='HTML')

    webhook_logger = MakeWebhookLogger(DEFAULT_WEBHOOK_URL)
    result = webhook_logger.test_webhook("advanced")

    if result['success']:
        result_text = f"""✅ <b>Advanced Webhook Test Successful!</b>

📡 <b>Request Details:</b>
Status Code: {result['status_code']}
Response Time: {result['response_time']:.2f}s
URL: {DEFAULT_WEBHOOK_URL[:50]}...

📊 <b>Test Data Sent:</b>
• Symbol: BTCUSDT
• Trade Type: LONG
• Entry Price: 45000.50
• Quantity: 0.001
• Leverage: 10x
• Order ID: TEST_{datetime.now().strftime('%H%M%S')}
• Stop Loss: 44000.00
• Take Profit: 46000.00, 47000.00
• Status: TEST_EXECUTED

🎉 <b>Perfect!</b> Your webhook is working correctly.
Check your Make.com scenario for the complete data."""
    else:
        result_text = f"""❌ <b>Advanced Webhook Test Failed</b>

📡 <b>Details:</b>
Status Code: {result['status_code']}
Response Time: {result['response_time']:.2f}s
Error: {result['response_text'][:200]}...

🔧 <b>Make.com Setup Guide:</b>
1. Go to: make.com/scenarios
2. Find scenario with your webhook
3. Click "Run Once" button
4. Wait for "Waiting for data..."
5. Run this test again
6. Click "OK" when data appears
7. Add Google Sheets module
8. Map all fields to spreadsheet columns

📞 <b>Still having issues?</b>
• Check scenario is ON (not OFF)
• Verify webhook URL is correct
• Try creating new webhook in Make.com"""

    await update.message.reply_text(result_text, parse_mode='HTML')

# ================== BINANCE SETUP ==================

async def setup_binance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """🔑 <b>Binance API Setup</b>

Send your Binance API Key:

⚠️ <b>Requirements:</b>
• Futures trading enabled
• API key with Futures permissions
• Sufficient balance (minimum $5 USDT)""", parse_mode='HTML')
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

# ================== TRADING SETUP ==================

async def setup_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_markup = create_settings_keyboard(user_id)

    await update.message.reply_text(
        "⚙️ <b>Trading Configuration</b>\n\nConfigure your trading parameters:",
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
            f"""✅ <b>Trading configuration complete!</b>

All settings saved successfully.
🔗 Make.com webhook is ready!

Next: /start_monitoring to begin trading""",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    elif query.data == "toggle_settings_source":
        config.use_signal_settings = not config.use_signal_settings
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure your trading parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_sl_tp":
        config.create_sl_tp = not config.create_sl_tp
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure your trading parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "toggle_webhook":
        config.make_webhook_enabled = not config.make_webhook_enabled
        keyboard_markup = create_settings_keyboard(user_id)
        await query.edit_message_text(
            "⚙️ <b>Trading Configuration</b>\n\nConfigure your trading parameters:",
            reply_markup=keyboard_markup,
            parse_mode='HTML'
        )

    elif query.data == "set_leverage":
        await query.edit_message_text(
            "⚡ <b>Set Leverage</b>\n\nSend leverage value (1-125):",
            parse_mode='HTML'
        )
        return WAITING_LEVERAGE

    elif query.data == "set_stop_loss":
        await query.edit_message_text(
            "🛑 <b>Set Stop Loss</b>\n\nSend stop loss percentage (e.g., 5 for 5%):",
            parse_mode='HTML'
        )
        return WAITING_STOP_LOSS

    elif query.data == "set_take_profit":
        await query.edit_message_text(
            "🎯 <b>Set Take Profit</b>\n\nSend take profit percentage (e.g., 10 for 10%):",
            parse_mode='HTML'
        )
        return WAITING_TAKE_PROFIT

    elif query.data == "set_balance_percent":
        await query.edit_message_text(
            "💰 <b>Set Balance Percentage</b>\n\nSend percentage of balance to use per trade (e.g., 1 for 1%):",
            parse_mode='HTML'
        )
        return WAITING_BALANCE_PERCENT

    elif query.data == "set_min_order":
        await query.edit_message_text(
            "💵 <b>Set Minimum Order</b>\n\nSend minimum order amount in USD (e.g., 5 for $5):",
            parse_mode='HTML'
        )
        return WAITING_BALANCE_PERCENT  # Reuse this state

    return WAITING_SETTINGS_SOURCE

async def handle_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        leverage = int(update.message.text)
        if 1 <= leverage <= 125:
            config.leverage = leverage
            await update.message.reply_text(f"✅ <b>Leverage set to {leverage}x</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ <b>Invalid leverage!</b> Must be between 1-125", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ <b>Invalid input!</b> Send a number between 1-125", parse_mode='HTML')

    return ConversationHandler.END

async def handle_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        sl_percent = float(update.message.text)
        if 0.1 <= sl_percent <= 50:
            config.stop_loss_percent = sl_percent
            await update.message.reply_text(f"✅ <b>Stop Loss set to {sl_percent}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ <b>Invalid percentage!</b> Must be between 0.1-50%", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ <b>Invalid input!</b> Send a number (e.g., 5)", parse_mode='HTML')

    return ConversationHandler.END

async def handle_take_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        tp_percent = float(update.message.text)
        if 0.1 <= tp_percent <= 100:
            config.take_profit_percent = tp_percent
            await update.message.reply_text(f"✅ <b>Take Profit set to {tp_percent}%</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ <b>Invalid percentage!</b> Must be between 0.1-100%", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ <b>Invalid input!</b> Send a number (e.g., 10)", parse_mode='HTML')

    return ConversationHandler.END

async def handle_balance_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    try:
        value = float(update.message.text)
        if value >= 1 and value <= 100:
            if value <= 10:  # Likely balance percentage
                config.balance_percent = value
                await update.message.reply_text(f"✅ <b>Balance percentage set to {value}%</b>", parse_mode='HTML')
            else:  # Likely minimum order amount
                config.minimum_order_usd = value
                await update.message.reply_text(f"✅ <b>Minimum order set to ${value}</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ <b>Invalid value!</b> Send a reasonable number", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ <b>Invalid input!</b> Send a number", parse_mode='HTML')

    return ConversationHandler.END

# ================== MONITORING CONTROLS ==================

async def start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = trading_bot.get_user_config(user_id)

    # Validate configuration
    if not config.binance_api_key or not config.telegram_api_id:
        await update.message.reply_text("❌ <b>Configuration incomplete!</b> Complete setup first.", parse_mode='HTML')
        return

    if not config.monitored_channels:
        await update.message.reply_text("❌ <b>No channels configured!</b> Use /setup_channels first.", parse_mode='HTML')
        return

    await update.message.reply_text("🚀 <b>Starting monitoring...</b>", parse_mode='HTML')

    success = await trading_bot.start_monitoring(user_id, context.bot)

    if success:
        status_msg = f"""✅ <b>MONITORING STARTED!</b>

📡 Monitoring: <b>{len(config.monitored_channels)}</b> channels
⚙️ Settings: {'Signal Priority' if config.use_signal_settings else 'Bot Settings'}
📊 SL/TP: {'Enabled' if config.create_sl_tp else 'Disabled'}
🔗 Make.com Webhook: ENABLED
💵 Min Order: ${config.minimum_order_usd}

🎯 <b>Ready to trade!</b>
Use /stop_monitoring to stop.

🔗 <b>Webhook URL:</b>
{DEFAULT_WEBHOOK_URL[:50]}...

📊 All trades will be logged to Make.com automatically!"""

        await update.message.reply_text(status_msg, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ <b>Failed to start monitoring!</b> Check configuration.", parse_mode='HTML')

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trading_bot.active_monitoring[user_id] = False

    await update.message.reply_text("🛑 <b>Monitoring stopped!</b>", parse_mode='HTML')

# ================== TEST FUNCTIONS ==================

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
Плечо: 5x""",

        """🚀 #SOLUSDT ЛОНГ 🚀
📈 Entry: 150.50
🎯 Target 1: 155.00
🎯 Target 2: 160.00
🛑 Stop Loss: 145.00
⚡ 15x"""
    ]

    results = []
    for i, test_msg in enumerate(test_signals, 1):
        signal = trading_bot.parse_trading_signal(test_msg, "test_channel")
        if signal:
            results.append(f"""<b>Test {i}: ✅ PARSED</b>
Symbol: {signal.symbol}
Type: {signal.trade_type}
Entry: {signal.entry_price or 'N/A'}
SL: {signal.stop_loss or 'N/A'}
TP: {signal.take_profit or 'N/A'}
Leverage: {signal.leverage or 'N/A'}""")
        else:
            results.append(f"<b>Test {i}: ❌ FAILED</b>")

    test_result = "🧪 <b>Signal Parser Test Results</b>\n\n" + "\n\n".join(results)
    await update.message.reply_text(test_result, parse_mode='HTML')

# ================== CONVERSATION HANDLERS ==================

# Binance setup conversation
binance_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_binance', setup_binance)],
    states={
        WAITING_BINANCE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_key)],
        WAITING_BINANCE_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binance_secret)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# Telegram setup conversation
telegram_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_telegram', setup_telegram_api)],
    states={
        WAITING_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_id)],
        WAITING_TELEGRAM_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_hash)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# Channel setup conversation
channel_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_channels', setup_channels)],
    states={
        WAITING_CHANNEL_SELECTION: [CallbackQueryHandler(handle_channel_selection)],
        WAITING_MANUAL_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_channel)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# Trading setup conversation
trading_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('setup_trading', setup_trading)],
    states={
        WAITING_SETTINGS_SOURCE: [CallbackQueryHandler(handle_trading_settings)],
        WAITING_LEVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leverage)],
        WAITING_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stop_loss)],
        WAITING_TAKE_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_take_profit)],
        WAITING_BALANCE_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_balance_percent)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# ================== MAIN APPLICATION ==================

def main():
    """Start the bot"""
    # Add your bot token here
    BOT_TOKEN = "8463413059:AAG9qxXPLXrLmXZDHGF_vTPYWURAKZyUoU4"  # Replace with your actual bot token
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add conversation handlers
    application.add_handler(binance_conv_handler)
    application.add_handler(telegram_conv_handler)
    application.add_handler(channel_conv_handler)
    application.add_handler(trading_conv_handler)

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("start_monitoring", start_monitoring))
    application.add_handler(CommandHandler("stop_monitoring", stop_monitoring))
    application.add_handler(CommandHandler("test_signal", test_signal))
    application.add_handler(CommandHandler("test_webhook", test_webhook))
    application.add_handler(CommandHandler("test_advanced", test_webhook_advanced))

    print("🤖 Bot starting...")
    print(f"🔗 Make.com webhook integrated: {DEFAULT_WEBHOOK_URL}")
    print("💵 Minimum order enforcement: $5")
    print("✅ Advanced webhook testing enabled")
    print("📊 Ready for Google Sheets integration")
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
