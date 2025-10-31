"""
Enhanced Signal Parser with Russian Support and Improved Symbol Detection
"""

import re
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class ParsedSignal:
    """Enhanced signal structure"""
    signal_id: str
    channel_id: str
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

class EnhancedSignalParser:
    """Enhanced signal parser with support for multiple formats and Russian text"""
    
    # Enhanced symbol patterns - can detect symbols anywhere in the text
    SYMBOL_PATTERNS = [
        # Format: #SYMBOL SIDE (highest priority)
        r'#([A-Z]{2,10})\s+(SHORT|LONG|шорт|лонг)',  # #SOL SHORT, #BTC LONG, #DYM LONG
        r'#([A-Z]{2,10})(?:/USDT|USDT|-USDT)?',  # #BTCUSDT, #BTC/USDT, #BTC-USDT
        
        # Format: SIDE #SYMBOL or SIDE SYMBOL (works with Russian too)
        r'\b(LONG|SHORT|BUY|SELL|ЛОНГ|ШОРТ|лонг|шорт|покупка|продажа)\s*#?\s*([A-Z]{2,10})(?:/USDT|USDT|-USDT)?',  # LONG BTCUSDT, ЛОНГ DYM
        
        # Russian-specific patterns
        r'🗩\s*([A-Z]{2,10})\s+(LONG|SHORT|лонг|шорт)',  # 🗩DYM LONG
        r'([A-Z]{2,10})\s+(ЛОНГ|ШОРТ|лонг|шорт)',  # DYM ЛОНГ
        
        # Symbols with various separators (anywhere in text)
        r'\b([A-Z]{2,10})(?:/USDT|USDT|-USDT)\b',   # BTCUSDT, BTC/USDT, BTC-USDT
        r'\b([A-Z]{2,10})\s*[/\-]\s*USDT\b',       # BTC / USDT, BTC - USDT
        r'\b([A-Z]{2,10})\s+USDT\b',                # BTC USDT
        
        # Symbols followed by common indicators
        r'\b([A-Z]{2,10})\s*(?:—|:|\s)\s*(?:LONG|SHORT|BUY|SELL|лонг|шорт)',  # BTC — LONG, SOL: SHORT
        r'\b([A-Z]{2,10})\s+(?:Long|Short|лонг|шорт)\b',  # BTC Long, ETH Short
        
        # Known crypto symbols (higher priority to avoid false positives)
        r'\b(BTC|ETH|SOL|ADA|MATIC|AVAX|LINK|UNI|AAVE|SUSHI|COMP|MKR|YFI|SNX|1INCH|CRV|BAL|ALPHA|BETA|RUNE|FTM|BNB|DOT|ATOM|LUNA|UST|NEAR|ROSE|MANA|SAND|ENJ|CHZ|BAT|ZRX|LRC|GRT|STORJ|SKL|NKN|REN|KNC|MLN|REP|ZEC|ETC|LTC|BCH|XRP|TRX|EOS|IOST|ONT|NEO|VET|IOTA|XTZ|ALGO|FIL|DOGE|SHIB|SAFEMOON|GME|AMC|DYM|PYTH|JTO|WIF|BONK|PEPE)(?:USDT|/USDT|-USDT)?\b',
        
        # Fallback: any 2-10 letter combo that looks like crypto (lowest priority)
        r'\b([A-Z]{2,10})(?:/USDT|USDT|-USDT)?\b'
    ]
    
    # Side patterns (LONG/SHORT) - Enhanced for Russian
    LONG_PATTERNS = [
        r'\b(LONG|ЛОНГ|лонг|Long|long)\b',
        r'\b(BUY|ПОКУПКА|покупка|Buy|buy)\b',
        r'📈',  # Green arrow up
        r'🜢',  # Green circle
        r'⬆️',  # Up arrow
        r'🚀',  # Rocket
        r'набираю позицию в Long',
        r'открываю Long',
        r'открываю в Long',
    ]
    
    SHORT_PATTERNS = [
        r'\b(SHORT|ШОРТ|шорт|Short|short)\b',
        r'\b(SELL|ПРОДАЖА|продажа|Sell|sell)\b',
        r'📉',  # Red arrow down
        r'🔴',  # Red circle
        r'⬇️',  # Down arrow
        r'🔻',  # Down triangle
        r'набираю позицию в Short',
        r'открываю Short',
        r'открываю в Short',
        r'открываем шорт-позицию',
    ]
    
    # Enhanced price patterns for Russian
    ENTRY_PATTERNS = [
        r'Entry[:\s]*([큃4.,]+)',
        r'Вход[:\s]*([큃4.,]+)',
        r'цена входа[:\s-]*([큃4.,]+)',
        r'@\s*([큃4.,]+)',
        r'Price[:\s]*([큃4.,]+)',
        r'Цена[:\s]*([큃4.,]+)',
        r'вход в позицию[:\s-]*([큃4.,]+)',
        r'Моя точка входа[:\s-]*([큃4.,]+)',
        r'Точка входа[:\s-]*([큃4.,]+)',
        r'Открытие сделки[:\s-]*([큃4.,]+)',
    ]
    
    # Enhanced take profit patterns for Russian
    TP_PATTERNS = [
        r'Target\s*\d*[:]?\s*([큃4.,]+)',
        r'TP\s*\d*[:]?\s*([큃4.,]+)',
        r'Тп[:\s]*([큃4.,]+)',
        r'цели?[:\s-]*([큃4.,]+)',
        r'Take\s*Profit[:\s]*([큃4.,]+)',
        r'Цель[:\s]*([큃4.,]+)',
        r'Тейки[:\s]*([큃4.,]+)',
        r'Тейк[:\s]*([큃4.,]+)',
        r'Цели по сделке[:\s-]*([큃4.,]+)',
    ]
    
    # Enhanced stop loss patterns for Russian
    SL_PATTERNS = [
        r'Stop\s*Loss[:\s]*([큃4.,]+)',
        r'SL[:\s]*([큃4.,]+)',
        r'Сл[:\s]*([큃4.,]+)',
        r'Стоп[:\s-]*([큃4.,]+)',
        r'Стоп-лос[:\s-]*([큃4.,]+)',
        r'Stop[:\s]*([큃4.,]+)',
        r'стоп \- пока не ставлю',  # Special case for "no stop loss yet"
    ]
    
    # Enhanced leverage patterns for Russian
    LEVERAGE_PATTERNS = [
        r'Leverage[:\s]*(\d+)',
        r'Плечо[:\s-]*(\d+)[-xх]*(\d)*',
        r'(\d+)\s*[xх]',
        r'(\d+)\s*X',
        r'Плечи[:\s]*(\d+)',
        r'плечо[:\s-]*(\d+)',
        r'(\d+)\s*кросс',  # Russian "cross" margin
    ]
    
    # Risk management patterns for Russian
    RISK_PATTERNS = [
        r'РМ[:\s]*([큃4.,]+)%',
        r'Риск[:\s]*([큃4.,]+)%',
        r'Риски[:\s]*([큃4.,]+)%',
        r'Risk[:\s]*([큃4.,]+)%',
        r'([큃4.,]+)%\s*от депозита',
        r'([큃4.,]+)%\s*от депо',
    ]
    
    @staticmethod
    def parse_signal(text: str, channel_id: str = "") -> Optional[ParsedSignal]:
        """Parse a trading signal from text with enhanced Russian support"""
        try:
            logger.info(f"🔍 Parsing signal from channel {channel_id}")
            logger.debug(f"Raw text: {repr(text)}")
            
            # Clean and normalize text
            text = text.strip()
            if not text:
                return None
            
            # Extract symbol
            symbol = EnhancedSignalParser._extract_symbol(text)
            if not symbol:
                logger.info("❌ No symbol found")
                return None
            
            # Extract side (LONG/SHORT)
            side = EnhancedSignalParser._extract_side(text)
            if not side:
                logger.info("❌ No trade side found")
                return None
            
            # Extract entry price
            entry_price = EnhancedSignalParser._extract_entry_price(text)
            
            # Extract take profits
            take_profits = EnhancedSignalParser._extract_take_profits(text)
            
            # Extract stop loss
            stop_loss = EnhancedSignalParser._extract_stop_loss(text)
            
            # Extract leverage
            leverage = EnhancedSignalParser._extract_leverage(text)
            
            # Extract risk percentage
            risk_percentage = EnhancedSignalParser._extract_risk_percentage(text)
            
            # Calculate confidence score (lowered threshold for Russian signals)
            confidence = EnhancedSignalParser._calculate_confidence(
                symbol, side, entry_price, take_profits, stop_loss, leverage, text
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
                confidence=confidence
            )
            
            logger.info(f"✅ Parsed signal: {symbol} {side} (confidence: {confidence:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            return None
    
    @staticmethod
    def _extract_symbol(text: str) -> Optional[str]:
        """Extract trading symbol from text with enhanced detection"""
        for pattern in EnhancedSignalParser.SYMBOL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                # Handle different pattern formats
                groups = match.groups()
                symbol = None
                
                if len(groups) >= 2:
                    # Check patterns with side indicators
                    for i, group in enumerate(groups):
                        if group and re.match(r'^[A-Z]{2,10}$', group, re.IGNORECASE):
                            symbol = group.upper()
                            break
                elif len(groups) >= 1:
                    symbol = groups[0].upper()
                
                if not symbol:
                    continue
                    
                # Skip if symbol is just numbers
                if symbol.isdigit():
                    continue
                    
                # Skip very short symbols or common false positives
                if len(symbol) < 2 or symbol in ['X', 'XX', 'XXX', 'THE', 'AND', 'FOR']:
                    continue
                
                # Normalize symbol to USDT pair
                if not symbol.endswith('USDT'): 
                    symbol = symbol + 'USDT'
                
                # Fix double USDT
                if symbol.endswith('USDUSDT'):
                    symbol = symbol.replace('USDUSDT', 'USDT')
                
                logger.debug(f"Found symbol: {symbol} using pattern: {pattern}")
                return symbol
        
        return None
    
    @staticmethod
    def _extract_side(text: str) -> Optional[str]:
        """Extract trade side (LONG/SHORT) from text with Russian support"""
        # First check for explicit LONG/SHORT words (highest priority)
        if re.search(r'\b(SHORT|ШОРТ|шорт)\b', text, re.IGNORECASE | re.UNICODE):
            return 'SHORT'
        if re.search(r'\b(LONG|ЛОНГ|лонг)\b', text, re.IGNORECASE | re.UNICODE):
            return 'LONG'
        
        # Check for BUY/SELL and Russian equivalents
        if re.search(r'\b(SELL|ПРОДАЖА|продажа)\b', text, re.IGNORECASE | re.UNICODE):
            return 'SHORT'
        if re.search(r'\b(BUY|ПОКУПКА|покупка)\b', text, re.IGNORECASE | re.UNICODE):
            return 'LONG'
        
        # Check for SHORT patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
                return 'SHORT'
        
        # Check for LONG patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
                return 'LONG'
        
        return None
    
    @staticmethod
    def _extract_entry_price(text: str) -> Optional[float]:
        """Extract entry price from text with Russian support"""
        for pattern in EnhancedSignalParser.ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                try:
                    price_str = match.group(1).replace(',', '').replace('$', '')
                    price = float(price_str)
                    if price > 0:
                        return price
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_take_profits(text: str) -> List[float]:
        """Extract take profit levels from text with Russian support"""
        take_profits = []
        
        # Look for multiple TP patterns
        for pattern in EnhancedSignalParser.TP_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE | re.UNICODE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                if match and match.replace('.', '').replace(',', '').replace('$', '').isdigit():
                    try:
                        tp_val = float(match.replace(',', '').replace('$', ''))
                        if tp_val > 0:
                            take_profits.append(tp_val)
                    except ValueError:
                        continue
        
        # Special handling for Russian "цели" with multiple prices in one line
        tp_line_match = re.search(r'цели[\s-]*((?:[큃4.,]+\$?\s*)+)', text, re.IGNORECASE | re.UNICODE)
        if tp_line_match:
            tp_line = tp_line_match.group(1)
            # Find all price-like patterns in the line
            price_matches = re.findall(r'([\d.,]+)\$?', tp_line)
            for price_match in price_matches:
                try:
                    tp_val = float(price_match.replace(',', ''))
                    if tp_val > 0 and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except ValueError:
                    continue
        
        # Remove duplicates and sort
        take_profits = sorted(list(set(take_profits)))
        
        # Limit to reasonable number of TPs
        return take_profits[:5]
    
    @staticmethod
    def _extract_stop_loss(text: str) -> Optional[float]:
        """Extract stop loss from text with Russian support"""
        # Check for "no stop loss" indicators first
        if re.search(r'стоп[\s-]*пока не ставлю', text, re.IGNORECASE | re.UNICODE):
            logger.debug("Found 'no stop loss yet' indicator")
            return None
        
        for pattern in EnhancedSignalParser.SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                try:
                    sl_str = match.group(1).replace(',', '').replace('$', '')
                    sl = float(sl_str)
                    if sl > 0:
                        return sl
                except (ValueError, IndexError):
                    continue
        
        return None
    
    @staticmethod
    def _extract_leverage(text: str) -> Optional[int]:
        """Extract leverage from text with Russian support"""
        for pattern in EnhancedSignalParser.LEVERAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 125:
                        return leverage
                except (ValueError, IndexError):
                    continue
        
        return None
    
    @staticmethod
    def _extract_risk_percentage(text: str) -> Optional[float]:
        """Extract risk percentage from text with Russian support"""
        for pattern in EnhancedSignalParser.RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                try:
                    risk = float(match.group(1).replace(',', ''))
                    if 0 < risk <= 100:
                        return risk
                except (ValueError, IndexError):
                    continue
        
        return None
    
    @staticmethod
    def _calculate_confidence(symbol: str, side: str, entry_price: Optional[float], 
                            take_profits: List[float], stop_loss: Optional[float], 
                            leverage: Optional[int], text: str = "") -> float:
        """Calculate confidence score for the parsed signal (adjusted for Russian signals)"""
        confidence = 0.0
        
        # Base confidence for having symbol and side (higher for clear signals)
        if symbol and side:
            confidence += 0.4  # Increased base confidence
        
        # Russian signal bonus (more tolerance for Russian signals)
        if re.search(r'[Ѐ-ӿ]', text):  # Contains Cyrillic characters
            confidence += 0.1
            logger.debug("Russian signal detected, confidence bonus applied")
        
        # Entry price adds confidence
        if entry_price:
            confidence += 0.2
        
        # Take profits add confidence
        if take_profits:
            confidence += 0.15
            # Bonus for multiple TPs
            if len(take_profits) > 1:
                confidence += 0.05
        
        # Stop loss adds confidence (but not penalize if explicitly stated as "not set yet")
        if stop_loss:
            confidence += 0.1
        elif re.search(r'пока не ставлю', text, re.IGNORECASE):
            # Explicit "not setting stop loss yet" - don't penalize
            confidence += 0.05
        
        # Leverage adds confidence
        if leverage:
            confidence += 0.1
        
        # Signal quality indicators
        if re.search(r'(СИГНАЛ|❗️)', text, re.IGNORECASE | re.UNICODE):
            confidence += 0.05
        
        return min(confidence, 1.0)