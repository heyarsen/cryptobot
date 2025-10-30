#!/usr/bin/env python3
"""
Enhanced Signal Parser v2.0 - Improved Pattern Recognition
Handles Ukrainian/Russian signals with advanced pattern matching
"""

import re
import uuid
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

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

class EnhancedSignalParser:
    """Enhanced signal parser with improved Ukrainian/Russian support"""
    
    # Updated symbol patterns with more aggressive matching
    SYMBOL_PATTERNS = [
        # Ukrainian/Russian format with emojis: "🗯DYM LONG📈"
        r'🗯([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',  # 🗯DYM LONG
        r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # DYM LONG📈
        r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # DYM SHORT📉
        
        # Handle #SYMBOL SHORT/LONG format
        r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',  # #SOL SHORT, #BTC LONG
        r'#([A-Z]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT (letters only)
        
        # Standard patterns
        r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\s*#?\s*([A-Z]{2,10})(?:/USDT|USDT)?',  # LONG BTCUSDT or SHORT BTC
        r'([A-Z]{2,10})(?:/USDT|USDT)?\s+(LONG|SHORT|ЛОНГ|ШОРТ)',  # BTC LONG, BTCUSDT SHORT
        r'([A-Z]{2,10})(?:/USDT|USDT)?',   # BTCUSDT, BTC/USDT (letters only)
        r'([A-Z]{2,10})\s*—',              # BTC —
        
        # Fallback for mixed alphanumeric (but avoid pure numbers)
        r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\s*#?\s*([A-Z0-9]{2,10})(?:/USDT|USDT)?',  # LONG BTCUSDT or SHORT BTC
        r'#([A-Z0-9]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT
        r'([A-Z0-9]{2,10})(?:/USDT|USDT)?',   # BTCUSDT, BTC/USDT
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
        r'цена входа[:\s-]*([\d.,]+)\$?',  # цена входа - 0.0983$
        r'вход[:\s-]*([\d.,]+)\$?',        # вход - 0.0983$
        r'Entry[:\s-]*([\d.,]+)\$?',
        r'@\s*([\d.,]+)\$?',
        r'Price[:\s-]*([\d.,]+)\$?',
        r'Цена[:\s-]*([\d.,]+)\$?',
        r'Вход в позицию[:\s-]*([\d.,]+)\$?',
        r'Моя точка входа[:\s-]*([\d.,]+)\$?',
        r'Точка входа[:\s-]*([\d.,]+)\$?',
        r'Открытие сделки[:\s-]*([\d.,]+)\$?',
    ]
    
    # Enhanced take profit patterns with Ukrainian terms
    TP_PATTERNS = [
        r'цели[:\s-]*([\d.,]+\$?(?:\s+[\d.,]+\$?)*)',  # цели - 0.0993$ 0.1004$ 0.1040$
        r'Target\s*\d*[:]?\s*([\d.,]+)\$?',
        r'TP\s*\d*[:]?\s*([\d.,]+)\$?',
        r'Тп[:\s-]*([\d.,]+)\$?',
        r'Take\s*Profit[:\s-]*([\d.,]+)\$?',
        r'Цель[:\s-]*([\d.,]+)\$?',
        r'Тейки[:\s-]*([\d.,]+)\$?',
        r'Тейк[:\s-]*([\d.,]+)\$?',
        r'Цели по сделке[:\s-]*([\d.,]+)\$?',
    ]
    
    # Enhanced stop loss patterns with Ukrainian terms
    SL_PATTERNS = [
        r'стоп[:\s-]*([^\n\r]+)',  # стоп - пока не ставлю
        r'Stop\s*Loss[:\s-]*([\d.,]+)\$?',
        r'SL[:\s-]*([\d.,]+)\$?',
        r'Сл[:\s-]*([\d.,]+)\$?',
        r'Стоп[:\s-]*([\d.,]+)\$?',
        r'Стоп-лос[:\s-]*([\d.,]+)\$?',
        r'Stop[:\s-]*([\d.,]+)\$?',
    ]
    
    # Enhanced leverage patterns with Ukrainian cross margin terms
    LEVERAGE_PATTERNS = [
        r'плечо[:\s-]*([\d]+)\s*кросс',     # плечо - 25 кросс
        r'плечо[:\s-]*([\d]+)',            # плечо - 25
        r'Leverage[:\s-]*([\d]+)',
        r'Плечо[:\s-]*([\d]+)[-xх]*([\d]*)',
        r'([\d]+)\s*[xх]',
        r'([\d]+)\s*X',
        r'Плечи[:\s-]*([\d]+)',
        r'([\d]+)\s*кросс',               # 25 кросс
    ]
    
    # Risk management patterns
    RISK_PATTERNS = [
        r'РМ[:\s-]*([\d.,]+)%',
        r'Риск[:\s-]*([\d.,]+)%',
        r'Риски[:\s-]*([\d.,]+)%',
        r'Risk[:\s-]*([\d.,]+)%',
        r'([\d.,]+)%\s*от депозита',
        r'([\d.,]+)%\s*от депо',
    ]
    
    @staticmethod
    def parse_signal(text: str, channel_id: str = "") -> Optional[ParsedSignal]:
        """Parse a trading signal from text with enhanced Ukrainian support"""
        try:
            logger.info(f"🔍 Enhanced parsing signal from channel {channel_id}")
            logger.info(f"📝 Text: {text[:200]}...")
            
            # Clean and normalize text
            text = text.strip()
            if not text:
                return None
            
            # Extract symbol and side together for better accuracy
            symbol, side = EnhancedSignalParser._extract_symbol_and_side(text)
            if not symbol or not side:
                logger.info(f"❌ Missing symbol ({symbol}) or side ({side})")
                return None
            
            # Extract entry price
            entry_price = EnhancedSignalParser._extract_entry_price(text)
            logger.info(f"📊 Entry price: {entry_price}")
            
            # Extract take profits with enhanced multi-target parsing
            take_profits = EnhancedSignalParser._extract_take_profits(text)
            logger.info(f"🎯 Take profits: {take_profits}")
            
            # Extract stop loss with special handling for "not setting" messages
            stop_loss = EnhancedSignalParser._extract_stop_loss(text)
            logger.info(f"🛑 Stop loss: {stop_loss}")
            
            # Extract leverage with cross margin support
            leverage = EnhancedSignalParser._extract_leverage(text)
            logger.info(f"⚡ Leverage: {leverage}")
            
            # Extract risk percentage
            risk_percentage = EnhancedSignalParser._extract_risk_percentage(text)
            logger.info(f"💰 Risk: {risk_percentage}")
            
            # Calculate confidence score
            confidence = EnhancedSignalParser._calculate_confidence(
                symbol, side, entry_price, take_profits, stop_loss, leverage
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
            
            logger.info(f"✅ Enhanced parsed signal: {symbol} {side} (confidence: {confidence:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            return None
    
    @staticmethod
    def _extract_symbol_and_side(text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract both symbol and side together for better accuracy"""
        # Try patterns that capture both symbol and side
        combined_patterns = [
            r'🗯([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # 🗯DYM LONG📈
            r'🗯([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # 🗯DYM SHORT📉
            r'🗯([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # 🗯DYM LONG
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',   # DYM LONG📈
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',   # DYM SHORT📉
            r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',    # #SOL SHORT
            r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\s+([A-Z]{2,10})(?:/USDT|USDT)?',  # LONG BTC
            r'([A-Z]{2,10})(?:/USDT|USDT)?\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # BTC LONG
        ]
        
        for pattern in combined_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                
                # Determine which group is symbol and which is side
                symbol_group = None
                side_group = None
                
                for group in groups:
                    if re.match(r'^(LONG|SHORT|ЛОНГ|ШОРТ)$', group, re.IGNORECASE):
                        side_group = group.upper()
                        if side_group in ['ЛОНГ']:
                            side_group = 'LONG'
                        elif side_group in ['ШОРТ']:
                            side_group = 'SHORT'
                    elif re.match(r'^[A-Z]{2,10}$', group, re.IGNORECASE):
                        symbol_group = group.upper()
                
                if symbol_group and side_group:
                    # Skip if symbol is just numbers
                    if symbol_group.isdigit():
                        continue
                    
                    # Normalize symbol
                    if not symbol_group.endswith('USDT'):
                        symbol_group = symbol_group + 'USDT'
                    
                    # Fix double USDT
                    if symbol_group.endswith('USDUSDT'):
                        symbol_group = symbol_group.replace('USDUSDT', 'USDT')
                    
                    logger.info(f"✅ Combined pattern matched: {symbol_group} {side_group}")
                    return symbol_group, side_group
        
        # Fallback to separate extraction
        symbol = EnhancedSignalParser._extract_symbol(text)
        side = EnhancedSignalParser._extract_side(text)
        
        return symbol, side
    
    @staticmethod
    def _extract_symbol(text: str) -> Optional[str]:
        """Extract trading symbol from text"""
        for pattern in EnhancedSignalParser.SYMBOL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle different pattern formats
                if len(match.groups()) >= 2:
                    # Check if first group is LONG/SHORT
                    if re.match(r"LONG|SHORT|ЛОНГ|ШОРТ", match.group(1), re.IGNORECASE):
                        symbol = match.group(2).upper()
                    # Check if second group is LONG/SHORT (for #SYMBOL SHORT format)
                    elif re.match(r"LONG|SHORT|ЛОНГ|ШОРТ", match.group(2), re.IGNORECASE):
                        symbol = match.group(1).upper()
                    else:
                        symbol = match.group(1).upper()
                else:
                    symbol = match.group(1).upper()
                
                # Skip if symbol is just numbers (like "25x" -> "25")
                if symbol.isdigit():
                    continue
                    
                # Skip if symbol is too short or looks like leverage
                if len(symbol) < 2 or symbol in ['X', 'XX', 'XXX']:
                    continue
                
                # Normalize symbol
                if not symbol.endswith('USDT'): 
                    symbol = symbol + 'USDT'
                
                # Fix double USDT
                if symbol.endswith('USDUSDT'):
                    symbol = symbol.replace('USDUSDT', 'USDT')
                
                return symbol
        
        return None
    
    @staticmethod
    def _extract_side(text: str) -> Optional[str]:
        """Extract trade side (LONG/SHORT) from text"""
        # First, check for explicit SHORT/LONG words anywhere in text (highest priority)
        if re.search(r'\bSHORT\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bLONG\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Check for Russian equivalents
        if re.search(r'\bШОРТ\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bЛОНГ\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Check for BUY/SELL
        if re.search(r'\bSELL\b', text, re.IGNORECASE):
            return 'SHORT'
        if re.search(r'\bBUY\b', text, re.IGNORECASE):
            return 'LONG'
        
        # Only check emojis if no explicit words found
        # Check for SHORT patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'SHORT'
        
        # Check for LONG patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 'LONG'
        
        return None
    
    @staticmethod
    def _extract_entry_price(text: str) -> Optional[float]:
        """Extract entry price from text with Ukrainian support"""
        for pattern in EnhancedSignalParser.ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
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
        """Extract take profit levels with enhanced multi-target parsing"""
        take_profits = []
        
        # Look for the Ukrainian "цели" pattern with multiple prices
        # цели - 0.0993$ 0.1004$ 0.1040$
        celi_match = re.search(r'цели[:\s-]*([\d.,\$\s]+)', text, re.IGNORECASE)
        if celi_match:
            # Extract all price numbers from the matched group
            price_text = celi_match.group(1)
            # Find all numbers with optional $ suffix
            numbers = re.findall(r'([\d.,]+)\$?', price_text)
            for num_str in numbers:
                try:
                    price = float(num_str.replace(',', ''))
                    if price > 0:
                        take_profits.append(price)
                except ValueError:
                    continue
            
            if take_profits:
                logger.info(f"✅ Found TP targets from 'цели': {take_profits}")
                return sorted(take_profits)
        
        # Look for multiple TP patterns if no "цели" found
        for pattern in EnhancedSignalParser.TP_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
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
        
        # Look for comma-separated TP values in a single line
        # Handle formats like "TP: 0.55, 0.60" or "Take Profit: 95, 90"
        multi_tp_patterns = [
            r'(?:TP|Take\s*Profit|Тп|Цель)[:\s]*([\d.,\s$]+)',
            r'(?:Target|Targets)[:\s]*([\d.,\s$]+)',
        ]
        
        for pattern in multi_tp_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                tp_text = match.group(1)
                # Split by comma and extract numbers
                parts = re.split(r'[,\s]+', tp_text)
                for part in parts:
                    clean_part = part.replace('$', '').strip()
                    if clean_part and re.match(r'^\d+\.?\d*$', clean_part):
                        try:
                            tp_val = float(clean_part)
                            if tp_val > 0:
                                take_profits.append(tp_val)
                        except ValueError:
                            continue
        
        # Remove duplicates and sort
        take_profits = sorted(list(set(take_profits)))
        
        # Limit to reasonable number of TPs
        return take_profits[:5]
    
    @staticmethod
    def _extract_stop_loss(text: str) -> Optional[float]:
        """Extract stop loss with special handling for 'not setting' messages"""
        for pattern in EnhancedSignalParser.SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                sl_text = match.group(1).strip()
                
                # Check for "not setting" messages in Ukrainian/Russian
                not_setting_phrases = [
                    'пока не ставлю',
                    'не ставлю',
                    'не устанавливаю',
                    'не ставим',
                    'без стопа',
                    'not setting',
                    'no stop',
                    'manually'
                ]
                
                for phrase in not_setting_phrases:
                    if phrase.lower() in sl_text.lower():
                        logger.info(f"🛑 Stop loss not being set: {sl_text}")
                        return None
                
                # Try to extract a numeric value
                numbers = re.findall(r'([\d.,]+)', sl_text)
                for num_str in numbers:
                    try:
                        sl = float(num_str.replace(',', ''))
                        if sl > 0:
                            return sl
                    except ValueError:
                        continue
        
        return None
    
    @staticmethod
    def _extract_leverage(text: str) -> Optional[int]:
        """Extract leverage with Ukrainian cross margin support"""
        for pattern in EnhancedSignalParser.LEVERAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 125:
                        return leverage
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_risk_percentage(text: str) -> Optional[float]:
        """Extract risk percentage from text"""
        for pattern in EnhancedSignalParser.RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    risk = float(match.group(1).replace(',', ''))
                    if 0 < risk <= 100:
                        return risk
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _calculate_confidence(symbol: str, side: str, entry_price: Optional[float], 
                            take_profits: List[float], stop_loss: Optional[float], 
                            leverage: Optional[int]) -> float:
        """Calculate confidence score for the parsed signal"""
        confidence = 0.0
        
        # Base confidence for having symbol and side
        if symbol and side:
            confidence += 0.4  # Increased base confidence
        
        # Entry price adds confidence
        if entry_price:
            confidence += 0.2
        
        # Take profits add confidence
        if take_profits:
            confidence += 0.2
            # Bonus for multiple TPs
            if len(take_profits) > 1:
                confidence += 0.1
        
        # Stop loss adds confidence (but not required)
        if stop_loss:
            confidence += 0.1
        
        # Leverage adds confidence
        if leverage:
            confidence += 0.1
        
        return min(confidence, 1.0)


def test_enhanced_parser():
    """Test the enhanced parser with your signal format"""
    test_signal = """❗️СИГНАЛ

🗯DYM LONG📈

плечо - 25 кросс
цена входа - 0.0983$
цели - 0.0993$ 0.1004$ 0.1040$
стоп - пока не ставлю

🎁400$ на спот за регистрацию и торговлю на бирже Bybit📈"""
    
    print("🧪 Testing Enhanced Parser with your signal format...")
    print(f"📝 Input: {test_signal}")
    print("-" * 50)
    
    signal = EnhancedSignalParser.parse_signal(test_signal, "test_channel")
    
    if signal:
        print(f"✅ SIGNAL PARSED SUCCESSFULLY!")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Side: {signal.side}")
        print(f"   Entry Price: {signal.entry_price}")
        print(f"   Take Profits: {signal.take_profit}")
        print(f"   Stop Loss: {signal.stop_loss}")
        print(f"   Leverage: {signal.leverage}")
        print(f"   Confidence: {signal.confidence:.2f}")
        print(f"   Risk %: {signal.risk_percentage}")
    else:
        print("❌ FAILED TO PARSE SIGNAL")
    
    print("-" * 50)
    
    # Test additional formats
    additional_tests = [
        "🗯SOL SHORT📉\nплечо - 10\nцена входа - 245.50$\nцели - 240.00$ 235.00$",
        "BTC LONG\nEntry: 45000\nTP: 46000, 47000\nSL: 44000\nLeverage: 20x",
        "🚀 ETHUSDT SHORT\nВход: 2500\nТП1: 2450\nТП2: 2400\nСЛ: 2550"
    ]
    
    for i, test in enumerate(additional_tests, 1):
        print(f"\n🧪 Additional Test {i}:")
        signal = EnhancedSignalParser.parse_signal(test, f"test_{i}")
        if signal:
            print(f"✅ {signal.symbol} {signal.side} (confidence: {signal.confidence:.2f})")
        else:
            print("❌ Failed to parse")


if __name__ == "__main__":
    # Run test if called directly
    test_enhanced_parser()