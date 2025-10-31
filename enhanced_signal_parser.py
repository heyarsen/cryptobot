#!/usr/bin/env python3
"""
Enhanced Signal Parser v2.7 - FIXED: Confidence Scoring for Signal Indicators
CRITICAL FIXES:
- Signals with explicit indicators like ❗️СИГНАЛ now get massive confidence boost (0.5 base)
- Fixed confidence calculation to properly detect signals with signal markers
- Enhanced emoji-marked pattern detection (🗯DYM LONG gets highest priority)
- Improved multi-line signal handling with proper confidence scoring
- Signal deduplication within 10 minutes
- Improved symbol detection when not first word
"""

import re
import uuid
import logging
import sqlite3
import os
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

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

class SignalDeduplicator:
    """Handle signal deduplication to prevent trading the same signal multiple times"""
    
    def __init__(self, db_path: str = "signal_dedup.db"):
        # Use persistent path similar to main database
        try:
            # Try to use same directory as main database
            volume_envs = [
                os.getenv('RAILWAY_VOLUME_MOUNT_PATH'),
                os.getenv('RAILWAY_VOLUME_DIR'),
                os.getenv('RAILWAY_VOLUME_PATH')
            ]
            for v in volume_envs:
                if v and v.strip():
                    db_path = os.path.join(v.strip(), 'signal_dedup.db')
                    break
            elif os.path.isdir('/data'):
                db_path = "/data/signal_dedup.db"
                
            parent_dir = os.path.dirname(db_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
        except Exception:
            pass
            
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the deduplication database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL,
                    signal_hash TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Create index for faster lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_signal_lookup 
                ON signal_history(channel_id, signal_hash, timestamp)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Signal deduplication database initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize deduplication database: {e}")
            raise
    
    def generate_signal_hash(self, channel_id: str, symbol: str, side: str, entry_price: Optional[float] = None) -> str:
        """Generate a hash for signal deduplication"""
        # Create a simple hash based on key components
        components = [channel_id, symbol, side]
        if entry_price:
            components.append(f"{entry_price:.6f}")
        
        hash_input = "|".join(str(c) for c in components)
        # Simple hash using built-in hash function
        return str(abs(hash(hash_input)))
    
    def is_duplicate_signal(self, channel_id: str, symbol: str, side: str, 
                           entry_price: Optional[float] = None, 
                           cooldown_minutes: int = 10) -> bool:
        """Check if this signal was already processed within the cooldown period"""
        try:
            signal_hash = self.generate_signal_hash(channel_id, symbol, side, entry_price)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check for similar signal within cooldown period
            cutoff_time = datetime.now() - timedelta(minutes=cooldown_minutes)
            
            cursor.execute('''
                SELECT COUNT(*) FROM signal_history 
                WHERE channel_id = ? AND signal_hash = ? AND timestamp > ?
            ''', (channel_id, signal_hash, cutoff_time))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            is_duplicate = count > 0
            if is_duplicate:
                logger.info(f"🔄 Duplicate signal detected: {symbol} {side} from {channel_id} (within {cooldown_minutes} min)")
            
            return is_duplicate
            
        except Exception as e:
            logger.error(f"❌ Error checking for duplicate signal: {e}")
            return False  # On error, allow the signal to proceed
    
    def record_signal(self, channel_id: str, symbol: str, side: str, entry_price: Optional[float] = None) -> bool:
        """Record a signal to prevent future duplicates"""
        try:
            signal_hash = self.generate_signal_hash(channel_id, symbol, side, entry_price)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO signal_history (channel_id, symbol, side, entry_price, signal_hash, processed)
                VALUES (?, ?, ?, ?, ?, TRUE)
            ''', (channel_id, symbol, side, entry_price, signal_hash))
            
            conn.commit()
            conn.close()
            
            logger.info(f"📝 Recorded signal: {symbol} {side} from {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error recording signal: {e}")
            return False
    
    def cleanup_old_signals(self, max_age_hours: int = 24):
        """Clean up old signal records to keep database size manageable"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            cursor.execute('''
                DELETE FROM signal_history WHERE timestamp < ?
            ''', (cutoff_time,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} old signal records (older than {max_age_hours}h)")
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up old signals: {e}")

class EnhancedSignalParser:
    """Enhanced signal parser with deduplication and improved symbol detection"""
    
    # Initialize deduplicator
    _deduplicator = None
    
    @classmethod
    def get_deduplicator(cls):
        if cls._deduplicator is None:
            cls._deduplicator = SignalDeduplicator()
        return cls._deduplicator
    
    # CRITICAL FIX: Enhanced signal block indicators - words that indicate a trading signal
    SIGNAL_INDICATORS = [
        r'❗️\s*сигнал\b',        # ❗️СИГНАЛ or ❗️сигнал
        r'❗️\s*signal\b',        # ❗️SIGNAL or ❗️signal
        r'🚨\s*сигнал\b',         # 🚨сигнал
        r'🚨\s*signal\b',         # 🚨signal
        r'новый\s*сигнал\b',      # новый сигнал
        r'new\s*signal\b',        # new signal
        r'торговый\s*сигнал\b',   # торговый сигнал
        r'trading\s*signal\b',    # trading signal
        r'\bсигнал\b',           # сигнал (standalone)
        r'\bsignal\b',           # signal (standalone)
    ]
    
    # FIXED: Enhanced symbol patterns with HIGHEST PRIORITY for emoji-marked symbols
    SYMBOL_PATTERNS = [
        # HIGHEST PRIORITY: Emoji-marked patterns anywhere in text (🗯DYM LONG)
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # 🗯DYM LONG📈
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # 🗯DYM SHORT📉
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # 🗯DYM LONG
        
        # Standard format anywhere in text (not just at beginning)
        r'(?:^|\s|\n)([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',   # DYM LONG📈
        r'(?:^|\s|\n)([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',   # DYM SHORT📉
        r'(?:^|\s|\n)([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',     # DYM LONG
        
        # NEW: Find symbol and side on SAME LINE anywhere in message
        r'([A-Z]{2,10})(?:/USDT|USDT)?.*\b(LONG|SHORT|ЛОНГ|ШОРТ)\b',
        r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\b.*?([A-Z]{2,10})(?:/USDT|USDT)?',
        
        # Hash format anywhere
        r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',    # #SOL SHORT
        r'#([A-Z]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT
        
        # NEW: Look for patterns like "BTC USDT" or "BTC/USDT" with trade words nearby
        r'([A-Z]{2,10})\s*[/\-]?\s*USDT.*\b(LONG|SHORT|ЛОНГ|ШОРТ)\b',
        r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\b.*?([A-Z]{2,10})\s*[/\-]?\s*USDT',
        
        # Standard symbol patterns - now search entire message
        r'(?:^|\s|\n)([A-Z]{2,10})(?:/USDT|USDT)?(?=\s|$|\n)',   # Any crypto symbol
        r'([A-Z]{2,10})\s*—',              # BTC —
    ]
    
    # Enhanced side patterns with more variations
    LONG_PATTERNS = [
        r'\b(LONG|ЛОНГ|Long|long)\b',
        r'\b(BUY|ПОКУПКА|Buy|buy)\b',
        r'📈',  # Green arrow up
        r'🟢',  # Green circle
        r'⬆️',  # Up arrow
        r'🚀',  # Rocket
        r'🎯',  # Direct target
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
    
    # Enhanced entry price patterns with Ukrainian terms
    ENTRY_PATTERNS = [
        r'цена входа[:\s-]*([\.,\d,]+)\$?',  # цена входа - 0.0983$
        r'вход[:\s-]*([\.,\d,]+)\$?',        # вход - 0.0983$
        r'Entry[:\s-]*([\.,\d,]+)\$?',
        r'@\s*([\.,\d,]+)\$?',
        r'Price[:\s-]*([\.,\d,]+)\$?',
        r'Цена[:\s-]*([\.,\d,]+)\$?',
        r'Вход в позицию[:\s-]*([\.,\d,]+)\$?',
        r'Моя точка входа[:\s-]*([\.,\d,]+)\$?',
        r'Точка входа[:\s-]*([\.,\d,]+)\$?',
        r'Открытие сделки[:\s-]*([\.,\d,]+)\$?',
    ]
    
    # Enhanced take profit patterns supporting multiple values on same line
    TP_PATTERNS = [
        # NEW: Handle "цели - 0.0993$ 0.1004$ 0.1040$" format
        r'цели[:\s-]*((?:[\.,\d,]+\$?\s*)+)',  # цели - 0.0993$ 0.1004$ 0.1040$
        r'Target\s*\d*[:.]?\s*([\.,\d,]+)\$?',
        r'TP\s*\d*[:.]?\s*([\.,\d,]+)\$?',
        r'Тп[:\s-]*([\.,\d,]+)\$?',
        r'Take\s*Profit[:\s-]*([\.,\d,]+)\$?',
        r'Цель[:\s-]*([\.,\d,]+)\$?',
        r'Тейки[:\s-]*([\.,\d,]+)\$?',
        r'Тейк[:\s-]*([\.,\d,]+)\$?',
        r'Цели по сделке[:\s-]*([\.,\d,]+)\$?',
        # NEW: Multiple TPs on same line
        r'(?:TP|Target|цели)[:\s-]*((?:[\.,\d,]+\$?[\s/|]*)+)',
    ]
    
    # Enhanced stop loss patterns supporting non-numeric values
    SL_PATTERNS = [
        r'стоп[:\s-]*([^\n\r]+)',  # стоп - пока не ставлю
        r'Stop\s*Loss[:\s-]*([\.,\d,]+)\$?',
        r'SL[:\s-]*([\.,\d,]+)\$?',
        r'Сл[:\s-]*([\.,\d,]+)\$?',
        r'Стоп[:\s-]*([\.,\d,]+)\$?',
        r'Стоп-лос[:\s-]*([\.,\d,]+)\$?',
        r'Stop[:\s-]*([\.,\d,]+)\$?',
    ]
    
    # Enhanced leverage patterns with Ukrainian cross margin terms
    LEVERAGE_PATTERNS = [
        r'плечо[:\s-]*(\d+)\s*кросс',     # плечо - 25 кросс
        r'плечо[:\s-]*(\d+)',            # плечо - 25
        r'Leverage[:\s-]*(\d+)',
        r'Плечо[:\s-]*(\d+)[-xх]*(\d*)',
        r'(\d+)\s*[xх]',
        r'(\d+)\s*X',
        r'Плечи[:\s-]*(\d+)',
        r'(\d+)\s*кросс',               # 25 кросс
    ]
    
    # Risk management patterns
    RISK_PATTERNS = [
        r'РМ[:\s-]*([\.,\d,]+)%',
        r'Риск[:\s-]*([\.,\d,]+)%',
        r'Риски[:\s-]*([\.,\d,]+)%',
        r'Risk[:\s-]*([\.,\d,]+)%',
        r'([\.,\d,]+)%\s*от депозита',
        r'([\.,\d,]+)%\s*от депо',
    ]
    
    @staticmethod
    def parse_signal(text: str, channel_id: str = "", account_id: str = "", 
                    check_duplicates: bool = True) -> Optional[ParsedSignal]:
        """Parse a trading signal from text with deduplication"""
        try:
            logger.info(f"🔍 Enhanced parsing signal from channel {channel_id}")
            
            # Clean and normalize text
            text = text.strip()
            if not text:
                return None
            
            # CRITICAL: Check if this message contains signal indicators FIRST
            has_signal_indicator = False
            for indicator in EnhancedSignalParser.SIGNAL_INDICATORS:
                if re.search(indicator, text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
                    has_signal_indicator = True
                    logger.info(f"✅ Found CRITICAL signal indicator: {indicator}")
                    break
            
            # NEW APPROACH: Search for symbols and sides ANYWHERE in the entire message
            logger.info(f"📝 Full message text: {text[:300]}...")
            
            # Extract symbol and side together for better accuracy
            symbol, side = EnhancedSignalParser._extract_symbol_and_side_anywhere(text)
            if not symbol or not side:
                logger.info(f"❌ Missing symbol ({symbol}) or side ({side}) when searching entire message")
                return None
            
            logger.info(f"✅ Found symbol and side anywhere in message: {symbol} {side}")
            
            # Extract other components from the ENTIRE text
            entry_price = EnhancedSignalParser._extract_entry_price(text)
            take_profits = EnhancedSignalParser._extract_take_profits(text)
            stop_loss = EnhancedSignalParser._extract_stop_loss(text)
            leverage = EnhancedSignalParser._extract_leverage(text)
            risk_percentage = EnhancedSignalParser._extract_risk_percentage(text)
            
            logger.info(f"📊 Parsed components - Entry: {entry_price}, TP: {take_profits}, SL: {stop_loss}, Lev: {leverage}")
            
            # Check for duplicate signals if enabled
            if check_duplicates:
                deduplicator = EnhancedSignalParser.get_deduplicator()
                if deduplicator.is_duplicate_signal(channel_id, symbol, side, entry_price, cooldown_minutes=10):
                    logger.info(f"🔄 Signal rejected as duplicate: {symbol} {side} (10 min cooldown)")
                    return None
            
            # CRITICAL FIX: Calculate confidence score with massive indicator bonus
            confidence = EnhancedSignalParser._calculate_confidence(
                symbol, side, entry_price, take_profits, stop_loss, leverage, has_signal_indicator
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
                account_id=account_id,
                confidence=confidence
            )
            
            # Record this signal to prevent duplicates
            if check_duplicates:
                deduplicator = EnhancedSignalParser.get_deduplicator()
                deduplicator.record_signal(channel_id, symbol, side, entry_price)
                
                # Periodic cleanup (every 10th signal)
                if hash(signal_id) % 10 == 0:
                    deduplicator.cleanup_old_signals()
            
            logger.info(f"✅ Enhanced parsed signal: {symbol} {side} (confidence: {confidence:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            return None
    
    @staticmethod
    def _extract_symbol_and_side_anywhere(text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract both symbol and side from ANYWHERE in the message - ENHANCED VERSION"""
        
        # STRATEGY 1: Look for combined patterns (symbol + side together) ANYWHERE
        combined_patterns = [
            # HIGHEST PRIORITY: Handle the specific format "🗯DYM LONG📈" anywhere in message
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # 🗯DYM LONG📈
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # 🗯DYM SHORT📉
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # 🗯DYM LONG
            
            # Standard patterns with emojis anywhere in message
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',   # DYM LONG📈
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',   # DYM SHORT📉
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',     # DYM LONG
            
            # Hash format
            r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',    # #SOL SHORT
            
            # Reverse order patterns anywhere in text
            r'(LONG|SHORT|ЛОНГ|ШОРТ)\s+([A-Z]{2,10})(?:/USDT|USDT)?',  # LONG BTC
            r'([A-Z]{2,10})(?:/USDT|USDT)?\s+(LONG|SHORT|ЛОНГ|ШОРТ)',  # BTC LONG
            
            # NEW: Find on same line but may have other text in between
            r'([A-Z]{2,10})(?:/USDT|USDT)?.*?\b(LONG|SHORT|ЛОНГ|ШОРТ)\b',
            r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\b.*?([A-Z]{2,10})(?:/USDT|USDT)?',
            
            # NEW: Handle cases with punctuation or dashes
            r'([A-Z]{2,10})(?:/USDT|USDT)?\s*[-–—].*?\b(LONG|SHORT|ЛОНГ|ШОРТ)\b',
            r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\b.*?[-–—]\s*([A-Z]{2,10})(?:/USDT|USDT)?',
        ]
        
        # Search with ALL flags to find patterns ANYWHERE in the entire message
        for pattern in combined_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                groups = match.groups()
                logger.info(f"🎯 Combined pattern matched ANYWHERE: {pattern} -> groups: {groups}")
                
                # Determine which group is symbol and which is side
                symbol_group = None
                side_group = None
                
                for group in groups:
                    if group and re.match(r'^(LONG|SHORT|ЛОНГ|ШОРТ)$', group, re.IGNORECASE):
                        side_group = group.upper()
                        # Normalize Cyrillic to English
                        if side_group in ['ЛОНГ']:
                            side_group = 'LONG'
                        elif side_group in ['ШОРТ']:
                            side_group = 'SHORT'
                    elif (group and re.match(r'^[A-Z]{2,10}$', group, re.IGNORECASE) and 
                          not group.isdigit() and 
                          not re.match(r'^(LONG|SHORT|ЛОНГ|ШОРТ)$', group, re.IGNORECASE)):
                        symbol_group = group.upper()
                
                if symbol_group and side_group:
                    # Clean up symbol
                    symbol = symbol_group
                    if not symbol.endswith('USDT'):
                        symbol = symbol + 'USDT'
                    
                    # Fix double USDT
                    if symbol.endswith('USDUSDT'):
                        symbol = symbol.replace('USDUSDT', 'USDT')
                    
                    logger.info(f"✅ Combined pattern SUCCESS anywhere: {symbol} {side_group}")
                    return symbol, side_group
        
        # STRATEGY 2: Search for symbol and side separately ANYWHERE in the message
        logger.info("🔄 No combined pattern found anywhere, searching separately...")
        symbol = EnhancedSignalParser._extract_symbol_anywhere(text)
        side = EnhancedSignalParser._extract_side_anywhere(text)
        
        logger.info(f"🔄 Separate extraction anywhere results: symbol={symbol}, side={side}")
        return symbol, side
    
    @staticmethod
    def _extract_symbol_anywhere(text: str) -> Optional[str]:
        """Extract trading symbol from ANYWHERE in the message - ENHANCED VERSION"""
        
        # NEW: Look for ANY crypto-like symbol ANYWHERE in the message, not just in trading blocks
        # Use multiple strategies to find symbols in various message formats
        
        # STRATEGY 1: Look for symbols near trade keywords
        trade_keywords = r'\b(LONG|SHORT|ЛОНГ|ШОРТ|BUY|SELL|long|short)\b'
        
        # Find all lines containing trade keywords
        lines = text.split('\n')
        for line in lines:
            if re.search(trade_keywords, line, re.IGNORECASE):
                logger.info(f"📍 Found trade keyword line: {line.strip()}")
                # Look for symbol in this line
                symbol_matches = re.findall(r'\b([A-Z]{2,10})(?:/USDT|USDT)?\b', line, re.IGNORECASE)
                for match in symbol_matches:
                    symbol = match.upper()
                    # Skip common false positives
                    if (symbol.isdigit() or len(symbol) < 2 or 
                        symbol in ['X', 'XX', 'XXX', 'LONG', 'SHORT', 'BUY', 'SELL']):
                        continue
                    
                    # Normalize symbol
                    if not symbol.endswith('USDT'):
                        symbol = symbol + 'USDT'
                    
                    if symbol.endswith('USDUSDT'):
                        symbol = symbol.replace('USDUSDT', 'USDT')
                    
                    logger.info(f"✅ Symbol found near trade keyword: {symbol}")
                    return symbol
        
        # STRATEGY 2: Look for emoji-marked symbols anywhere
        emoji_patterns = [
            r'🗯\s*([A-Z]{2,10})\b',    # 🗯DYM
            r'([A-Z]{2,10})\s*📈',      # DYM📈
            r'([A-Z]{2,10})\s*📉',      # DYM📉
            r'#([A-Z]{2,10})\b',        # #BTC
        ]
        
        for pattern in emoji_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                symbol = match.group(1).upper()
                if not symbol.isdigit() and len(symbol) >= 2:
                    if not symbol.endswith('USDT'):
                        symbol = symbol + 'USDT'
                    if symbol.endswith('USDUSDT'):
                        symbol = symbol.replace('USDUSDT', 'USDT')
                    logger.info(f"✅ Symbol found with emoji marker anywhere: {symbol}")
                    return symbol
        
        # STRATEGY 3: Look for any potential crypto symbols in the message
        # Focus on common crypto patterns but be more selective to reduce false positives
        potential_symbols = re.findall(r'\b([A-Z]{2,8})(?:/USDT|USDT|/USD|USD)?\b', text, re.IGNORECASE)
        
        crypto_keywords = [
            'BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOT', 'LINK', 'SOL', 'AVAX', 'MATIC',
            'UNI', 'ATOM', 'XLM', 'VET', 'FIL', 'TRX', 'EOS', 'XTZ', 'ALGO', 'HBAR',
            'NEAR', 'FLOW', 'ICP', 'FTM', 'ONE', 'ZIL', 'ENJ', 'BAT', 'ZRX', 'COMP',
            'SUSHI', 'CRV', 'YFI', 'SNX', 'MKR', 'AAVE', '1INCH', 'DOGE', 'SHIB',
            'DYM', 'COAI', 'ARB', 'OP', 'APT', 'SUI', 'INJ', 'SEI', 'TIA', 'ORDI'
        ]
        
        for symbol_match in potential_symbols:
            symbol = symbol_match.upper()
            
            # Prioritize known crypto symbols
            if symbol in crypto_keywords or symbol.replace('USDT', '') in crypto_keywords:
                if not symbol.endswith('USDT'):
                    symbol = symbol + 'USDT'
                logger.info(f"✅ Known crypto symbol found anywhere: {symbol}")
                return symbol
            
            # For unknown symbols, be more selective
            if (len(symbol) >= 3 and not symbol.isdigit() and 
                symbol not in ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF']):
                if not symbol.endswith('USDT'):
                    symbol = symbol + 'USDT'
                logger.info(f"✅ Potential crypto symbol found anywhere: {symbol}")
                return symbol
        
        logger.info("❌ No symbol found anywhere in message")
        return None
    
    @staticmethod
    def _extract_side_anywhere(text: str) -> Optional[str]:
        """Extract trade side (LONG/SHORT) from ANYWHERE in the message"""
        
        # Search with ALL flags to find patterns ANYWHERE
        
        # First, check for explicit SHORT/LONG words anywhere (highest priority)
        if re.search(r'\bSHORT\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found SHORT keyword anywhere in message")
            return 'SHORT'
        if re.search(r'\bLONG\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found LONG keyword anywhere in message")
            return 'LONG'
        
        # Check for Russian equivalents anywhere
        if re.search(r'\bШОРТ\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found ШОРТ keyword anywhere in message")
            return 'SHORT'
        if re.search(r'\bЛОНГ\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found ЛОНГ keyword anywhere in message")
            return 'LONG'
        
        # Check for BUY/SELL anywhere
        if re.search(r'\bSELL\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found SELL keyword anywhere in message")
            return 'SHORT'
        if re.search(r'\bBUY\b', text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            logger.info("✅ Found BUY keyword anywhere in message")
            return 'LONG'
        
        # Only check emojis if no explicit words found - search EVERYWHERE
        # Check for SHORT patterns
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
                logger.info(f"✅ Found SHORT pattern anywhere: {pattern}")
                return 'SHORT'
        
        # Check for LONG patterns
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
                logger.info(f"✅ Found LONG pattern anywhere: {pattern}")
                return 'LONG'
        
        logger.info("❌ No side pattern found anywhere in message")
        return None
    
    @staticmethod
    def _extract_entry_price(text: str) -> Optional[float]:
        """Extract entry price from ANYWHERE in the message"""
        for pattern in EnhancedSignalParser.ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                try:
                    # Handle different decimal separators and currency symbols
                    price_str = match.group(1).replace('$', '').replace(',', '.')
                    price = float(price_str)
                    if price > 0:
                        logger.info(f"💲 Found entry price ANYWHERE: {price}")
                        return price
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_take_profits(text: str) -> List[float]:
        """Extract take profit levels from ANYWHERE in the message with support for multiple values"""
        take_profits = []
        
        # Look for TP patterns ANYWHERE in message
        for pattern in EnhancedSignalParser.TP_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                
                # For patterns like "цели - 0.0993$ 0.1004$ 0.1040$", extract all numbers
                if 'цели' in pattern.lower() or 'TP|Target|цели' in pattern:
                    # Extract all price-like numbers from the matched group
                    numbers = re.findall(r'([\d.,]+)', match)
                    logger.info(f"🎯 Found multiple TP values ANYWHERE: {numbers}")
                    for num_str in numbers:
                        try:
                            clean_str = num_str.replace(',', '.')
                            tp_val = float(clean_str)
                            if tp_val > 0:
                                take_profits.append(tp_val)
                                logger.info(f"  ✅ Added TP: {tp_val}")
                        except ValueError:
                            continue
                else:
                    # Single TP value
                    clean_match = match.replace('$', '').replace(',', '.').strip()
                    if clean_match and re.match(r'^[\d.]+$', clean_match):
                        try:
                            tp_val = float(clean_match)
                            if tp_val > 0:
                                take_profits.append(tp_val)
                                logger.info(f"  ✅ Added single TP ANYWHERE: {tp_val}")
                        except ValueError:
                            continue
        
        # Remove duplicates and sort
        take_profits = sorted(list(set(take_profits)))
        logger.info(f"🎯 Final take profits found ANYWHERE: {take_profits}")
        
        # Limit to reasonable number of TPs
        return take_profits[:5]
    
    @staticmethod
    def _extract_stop_loss(text: str) -> Optional[float]:
        """Extract stop loss from ANYWHERE in the message with support for non-numeric values"""
        for pattern in EnhancedSignalParser.SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                sl_value = match.group(1).strip()
                logger.info(f"🛑 Found stop loss text ANYWHERE: '{sl_value}'")
                
                # Check if it's a numeric value
                try:
                    # Remove currency symbols and normalize decimal separator
                    clean_value = sl_value.replace('$', '').replace(',', '.')
                    if re.match(r'^[\d.]+$', clean_value):
                        sl = float(clean_value)
                        if sl > 0:
                            logger.info(f"🛑 Parsed numeric stop loss ANYWHERE: {sl}")
                            return sl
                except ValueError:
                    pass
                
                # If it's a non-numeric value like "пока не ставлю", log but return None
                logger.info(f"🛑 Non-numeric stop loss found ANYWHERE: {sl_value} (will use default SL)")
                return None  # Let the bot use its default SL settings
        
        return None
    
    @staticmethod
    def _extract_leverage(text: str) -> Optional[int]:
        """Extract leverage from ANYWHERE in the message with cross margin support"""
        for pattern in EnhancedSignalParser.LEVERAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 125:
                        logger.info(f"⚡ Found leverage ANYWHERE: {leverage}x")
                        return leverage
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_risk_percentage(text: str) -> Optional[float]:
        """Extract risk percentage from ANYWHERE in the message"""
        for pattern in EnhancedSignalParser.RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                try:
                    risk = float(match.group(1).replace(',', '.'))
                    if 0 < risk <= 100:
                        logger.info(f"💰 Found risk percentage ANYWHERE: {risk}%")
                        return risk
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _calculate_confidence(symbol: str, side: str, entry_price: Optional[float], 
                            take_profits: List[float], stop_loss: Optional[float], 
                            leverage: Optional[int], has_signal_indicator: bool = False) -> float:
        """Calculate confidence score for the parsed signal with FIXED indicator bonus"""
        confidence = 0.0
        
        # CRITICAL FIX: MASSIVE bonus for having explicit signal indicators (like ❗️СИГНАЛ)
        if has_signal_indicator:
            confidence += 0.6  # HUGE boost for messages that explicitly say "SIGNAL" - this alone exceeds threshold!
            logger.info("✅ CRITICAL SIGNAL INDICATOR MEGA BONUS: +0.6")
        
        # Base confidence for having symbol and side (most important)
        if symbol and side:
            confidence += 0.25  # Solid bonus for valid symbol + side
            logger.info(f"✅ Symbol + side bonus: +0.25 (total: {confidence})")
        
        # Entry price adds significant confidence
        if entry_price:
            confidence += 0.15  # Good bonus for entry price
            logger.info(f"✅ Entry price bonus: +0.15 (total: {confidence})")
        
        # Take profits add confidence
        if take_profits:
            confidence += 0.1
            logger.info(f"✅ Take profits bonus: +0.1 (total: {confidence})")
        
        # Stop loss adds some confidence (even if None due to "not setting")
        confidence += 0.05
        logger.info(f"✅ Stop loss considered bonus: +0.05 (total: {confidence})")
        
        # Leverage adds confidence
        if leverage:
            confidence += 0.05
            logger.info(f"✅ Leverage bonus: +0.05 (total: {confidence})")
        
        # Bonus for having multiple TPs
        if len(take_profits) > 1:
            confidence += 0.05
            logger.info(f"✅ Multiple TPs bonus: +0.05 (total: {confidence})")
        
        # Bonus if this looks like a properly formatted signal
        if symbol and side and (entry_price or take_profits):
            confidence += 0.05
            logger.info(f"✅ Well-formatted signal bonus: +0.05 (total: {confidence})")
        
        final_confidence = min(confidence, 1.0)
        logger.info(f"📊 FINAL CONFIDENCE SCORE: {final_confidence:.2f} {'✅ ABOVE THRESHOLD (0.5)' if final_confidence >= 0.5 else '❌ BELOW THRESHOLD (0.5)'}")
        return final_confidence

# Test function for development
def test_parser():
    """Test the enhanced parser with example signals including duplicates"""
    test_signals = [
        # Test 1: Standard format with intro text (YOUR EXACT CASE)
        """❗️СИГНАЛ

🗯DYM LONG📈

плечо - 25 кросс
цена входа - 0.0983$
цели - 0.0993$ 0.1004$ 0.1040$
стоп - пока не ставлю

🎁400$ на спот за регистрацию""",
        
        # Test 2: Same signal repeated (should be rejected as duplicate)
        """❗️СИГНАЛ

🗯DYM LONG📈

плечо - 25 кросс
цена входа - 0.0983$
цели - 0.0993$ 0.1004$ 0.1040$
стоп - пока не ставлю

🎁400$ на спот за регистрацию""",
        
        # Test 3: Symbol not first word
        """Новости рынка:
Сегодня хороший день для SOL LONG📈

Entry: 245.50
TP: 250 255 260
SL: 240
Leverage: 10x

Удачи!""",
        
        # Test 4: Mixed text with symbol buried deep
        """Ежедневный анализ крипто рынка
Рекомендации на сегодня:
- Биткоин показывает рост
- Эфириум стабилен
- Альткоины перспективны

Обратите внимание на BTC LONG
Вход по рынку около 67500
Цели: 68000 68500 69000
Стоп: 67000
Плечо: 5x

Остальные сигналы в канале""",
        
        # Test 5: Different symbol to test deduplication doesn't block legitimate signals
        """🗯ETH SHORT📉

плечо - 15 кросс
цена входа - 2500$
цели - 2450$ 2400$ 2350$
стоп - 2550$"""
    ]
    
    print("🧪 Testing Enhanced Signal Parser v2.7 - FIXED CONFIDENCE SCORING")
    print("=" * 80)
    
    for i, signal_text in enumerate(test_signals, 1):
        print(f"\n📊 Testing Signal {i}:")
        print(f"Input preview: {signal_text[:150].replace(chr(10), ' ')}...")
        
        signal = EnhancedSignalParser.parse_signal(signal_text, f"test_channel_1", f"test_account_1")
        
        if signal:
            print(f"✅ SUCCESS")
            print(f"   Symbol: {signal.symbol}")
            print(f"   Side: {signal.side}")
            print(f"   Entry: {signal.entry_price}")
            print(f"   TP: {signal.take_profit}")
            print(f"   SL: {signal.stop_loss}")
            print(f"   Leverage: {signal.leverage}")
            print(f"   Confidence: {signal.confidence:.2f}")
        else:
            print(f"❌ FAILED/DUPLICATE - No signal detected or duplicate rejected")
    
    print("\n" + "=" * 80)
    print("🧪 Testing deduplication with time gap...")
    
    # Test deduplication with forced time gap
    import time
    time.sleep(1)  # Small delay
    
    # This should work (different channel)
    signal = EnhancedSignalParser.parse_signal(test_signals[0], f"test_channel_2", f"test_account_1")
    print(f"\n📊 Same signal, different channel: {'✅ SUCCESS' if signal else '❌ FAILED'}")
    
    # Test without deduplication (should work)
    signal = EnhancedSignalParser.parse_signal(test_signals[1], f"test_channel_1", f"test_account_1", check_duplicates=False)
    print(f"📊 Duplicate with check_duplicates=False: {'✅ SUCCESS' if signal else '❌ FAILED'}")

if __name__ == "__main__":
    # Enable logging for testing
    logging.basicConfig(level=logging.INFO)
    test_parser()