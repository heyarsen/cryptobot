#!/usr/bin/env python3
"""
Enhanced Signal Parser v2.2 - Improved Pattern Recognition for Multi-Line Signals
Handles signals where trading information is not at the beginning of the message
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
    """Enhanced signal parser with improved multi-line and intro text support"""
    
    # Signal block indicators - words that might appear before the actual signal
    SIGNAL_INDICATORS = [
        r'❗️?\s*сигнал\b',      # ❗️СИГНАЛ or сигнал
        r'❗️?\s*signal\b',      # ❗️SIGNAL or signal
        r'🚨\s*сигнал\b',       # 🚨сигнал
        r'🚨\s*signal\b',       # 🚨signal
        r'новый\s*сигнал\b',    # новый сигнал
        r'new\s*signal\b',      # new signal
        r'торговый\s*сигнал\b', # торговый сигнал
        r'trading\s*signal\b',  # trading signal
    ]
    
    # Enhanced symbol patterns - now searches across entire text, not just beginning
    SYMBOL_PATTERNS = [
        # NEW: Handle "🗯DYM LONG📈" format anywhere in text
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # 🗯DYM LONG📈
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # 🗯DYM SHORT📉
        r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # 🗯DYM LONG
        
        # Ukrainian/Russian format with emojis anywhere in text
        r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',   # DYM LONG📈
        r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',   # DYM SHORT📉
        r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',     # DYM LONG
        
        # Handle #SYMBOL SHORT/LONG format
        r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',  # #SOL SHORT, #BTC LONG
        r'#([A-Z]{2,10})(?:/USDT|USDT)?',  # #BTCUSDT, #BTC/USDT
        
        # Standard patterns
        r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\s*#?\s*([A-Z]{2,10})(?:/USDT|USDT)?',
        r'([A-Z]{2,10})(?:/USDT|USDT)?\s+(LONG|SHORT|ЛОНГ|ШОРТ)',
        
        # Look for symbols in any line that might be trading pairs
        r'\b([A-Z]{2,10})(?:/USDT|USDT)?\b',   # Any potential crypto symbol
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
    
    # Enhanced take profit patterns supporting multiple values on same line
    TP_PATTERNS = [
        # NEW: Handle "цели - 0.0993$ 0.1004$ 0.1040$" format
        r'цели[:\s-]*((?:[\d.,]+\$?\s*)+)',  # цели - 0.0993$ 0.1004$ 0.1040$
        r'Target\s*\d*[:]?\s*([\d.,]+)\$?',
        r'TP\s*\d*[:]?\s*([\d.,]+)\$?',
        r'Тп[:\s-]*([\d.,]+)\$?',
        r'Take\s*Profit[:\s-]*([\d.,]+)\$?',
        r'Цель[:\s-]*([\d.,]+)\$?',
        r'Тейки[:\s-]*([\d.,]+)\$?',
        r'Тейк[:\s-]*([\d.,]+)\$?',
        r'Цели по сделке[:\s-]*([\d.,]+)\$?',
    ]
    
    # Enhanced stop loss patterns supporting non-numeric values
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
        """Parse a trading signal from text with enhanced multi-line support"""
        try:
            logger.info(f"🔍 Enhanced parsing signal from channel {channel_id}")
            
            # Clean and normalize text
            text = text.strip()
            if not text:
                return None
            
            # NEW: Look for signal indicators and extract the trading block
            trading_block = EnhancedSignalParser._extract_trading_block(text)
            if trading_block:
                logger.info(f"📦 Extracted trading block: {trading_block[:100]}...")
                # Use the extracted block for parsing
                parse_text = trading_block
            else:
                # No specific block found, use entire text
                parse_text = text
            
            # Extract symbol and side together for better accuracy
            symbol, side = EnhancedSignalParser._extract_symbol_and_side(parse_text)
            if not symbol or not side:
                logger.info(f"❌ Missing symbol ({symbol}) or side ({side}) in trading block")
                # Fallback: try parsing the entire original text
                if parse_text != text:
                    logger.info("🔄 Fallback: trying entire message")
                    symbol, side = EnhancedSignalParser._extract_symbol_and_side(text)
                    parse_text = text  # Use full text for other extractions
                
                if not symbol or not side:
                    logger.info(f"❌ Still missing symbol ({symbol}) or side ({side})")
                    return None
            
            # Extract other components from the parse_text
            entry_price = EnhancedSignalParser._extract_entry_price(parse_text)
            take_profits = EnhancedSignalParser._extract_take_profits(parse_text)
            stop_loss = EnhancedSignalParser._extract_stop_loss(parse_text)
            leverage = EnhancedSignalParser._extract_leverage(parse_text)
            risk_percentage = EnhancedSignalParser._extract_risk_percentage(parse_text)
            
            logger.info(f"📊 Parsed components - Entry: {entry_price}, TP: {take_profits}, SL: {stop_loss}, Lev: {leverage}")
            
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
    def _extract_trading_block(text: str) -> Optional[str]:
        """Extract the actual trading block from a message that may have intro text"""
        try:
            lines = text.split('\n')
            
            # Look for signal indicators in the message
            signal_start_idx = None
            for i, line in enumerate(lines):
                line_lower = line.lower().strip()
                for indicator_pattern in EnhancedSignalParser.SIGNAL_INDICATORS:
                    if re.search(indicator_pattern, line_lower, re.IGNORECASE):
                        logger.info(f"📍 Found signal indicator at line {i}: {line.strip()}")
                        signal_start_idx = i
                        break
                if signal_start_idx is not None:
                    break
            
            # If we found a signal indicator, extract from the next meaningful line
            if signal_start_idx is not None:
                # Look for the actual trading content starting from the next line
                for i in range(signal_start_idx + 1, len(lines)):
                    line = lines[i].strip()
                    if not line:  # Skip empty lines
                        continue
                    
                    # Check if this line contains trading symbols/info
                    if (re.search(r'🗯|[A-Z]{2,10}.*(?:LONG|SHORT|ЛОНГ|ШОРТ)', line, re.IGNORECASE) or
                        re.search(r'плечо|leverage|цена|entry|цели|target', line, re.IGNORECASE)):
                        # Found the start of trading block, extract from here
                        trading_lines = lines[i:]
                        
                        # Find where trading block ends (look for promotional text or non-trading content)
                        end_idx = len(trading_lines)
                        for j, trade_line in enumerate(trading_lines):
                            trade_line_lower = trade_line.lower().strip()
                            # Stop at promotional content
                            if (re.search(r'🎁|bonus|бонус|регистрация|registration|deposit|депозит', trade_line_lower) or
                                re.search(r'http|www\.|\.com|t\.me', trade_line_lower) or
                                len(trade_line_lower) > 100):  # Very long lines are usually promotional
                                end_idx = j
                                break
                        
                        trading_block = '\n'.join(trading_lines[:end_idx]).strip()
                        logger.info(f"📦 Extracted trading block from lines {signal_start_idx + 1 + i} to {signal_start_idx + 1 + i + end_idx - 1}")
                        return trading_block
            
            # If no signal indicator found, look for trading symbols anywhere in the message
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                
                # Check if this line contains trading symbols
                if re.search(r'🗯.*[A-Z]{2,10}.*(?:LONG|SHORT|ЛОНГ|ШОРТ)', line_stripped, re.IGNORECASE):
                    # Found potential start, extract from here
                    trading_lines = lines[i:]
                    
                    # Find where trading block ends
                    end_idx = len(trading_lines)
                    for j, trade_line in enumerate(trading_lines):
                        if (re.search(r'🎁|bonus|бонус|регистрация', trade_line, re.IGNORECASE) or
                            re.search(r'http|www\.|\.com', trade_line, re.IGNORECASE)):
                            end_idx = j
                            break
                    
                    trading_block = '\n'.join(trading_lines[:end_idx]).strip()
                    logger.info(f"📦 Extracted trading block without signal indicator from line {i}")
                    return trading_block
            
            # If still no trading block found, return None to use full text
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extracting trading block: {e}")
            return None
    
    @staticmethod
    def _extract_symbol_and_side(text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract both symbol and side together for better accuracy"""
        # Try patterns that capture both symbol and side
        combined_patterns = [
            # NEW: Handle the specific format "🗯DYM LONG📈" - prioritize this pattern
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',  # 🗯DYM LONG📈
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',  # 🗯DYM SHORT📉
            r'🗯\s*([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # 🗯DYM LONG
            
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📈',   # DYM LONG📈
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)📉',   # DYM SHORT📉
            r'([A-Z]{2,10})\s+(LONG|SHORT|ЛОНГ|ШОРТ)',     # DYM LONG
            r'#([A-Z]{2,10})\s+(SHORT|LONG|ЛОНГ|ШОРТ)',    # #SOL SHORT
            r'\b(LONG|SHORT|ЛОНГ|ШОРТ)\s+([A-Z]{2,10})(?:/USDT|USDT)?',  # LONG BTC
            r'([A-Z]{2,10})(?:/USDT|USDT)?\s+(LONG|SHORT|ЛОНГ|ШОРТ)',    # BTC LONG
        ]
        
        for pattern in combined_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                groups = match.groups()
                logger.info(f"🎯 Pattern matched: {pattern} -> groups: {groups}")
                
                # Determine which group is symbol and which is side
                symbol_group = None
                side_group = None
                
                for group in groups:
                    if re.match(r'^(LONG|SHORT|ЛОНГ|ШОРТ)$', group, re.IGNORECASE):
                        side_group = group.upper()
                        # Normalize Cyrillic to English
                        if side_group in ['ЛОНГ']:
                            side_group = 'LONG'
                        elif side_group in ['ШОРТ']:
                            side_group = 'SHORT'
                    elif re.match(r'^[A-Z]{2,10}$', group, re.IGNORECASE) and not group.isdigit():
                        symbol_group = group.upper()
                
                if symbol_group and side_group:
                    # Clean up symbol
                    symbol = symbol_group
                    if not symbol.endswith('USDT'):
                        symbol = symbol + 'USDT'
                    
                    # Fix double USDT
                    if symbol.endswith('USDUSDT'):
                        symbol = symbol.replace('USDUSDT', 'USDT')
                    
                    logger.info(f"✅ Combined pattern matched: {symbol} {side_group}")
                    return symbol, side_group
        
        # Fallback: extract symbol and side separately
        symbol = EnhancedSignalParser._extract_symbol(text)
        side = EnhancedSignalParser._extract_side(text)
        
        logger.info(f"🔄 Fallback extraction: symbol={symbol}, side={side}")
        return symbol, side
    
    @staticmethod
    def _extract_symbol(text: str) -> Optional[str]:
        """Extract trading symbol from text - improved to search entire message"""
        # Look through all patterns, prioritizing those with emoji indicators
        priority_patterns = []
        regular_patterns = []
        
        for pattern in EnhancedSignalParser.SYMBOL_PATTERNS:
            if '🗯' in pattern or '📈' in pattern or '📉' in pattern:
                priority_patterns.append(pattern)
            else:
                regular_patterns.append(pattern)
        
        # Try priority patterns first
        all_patterns = priority_patterns + regular_patterns
        
        for pattern in all_patterns:
            # Use MULTILINE flag to match across lines
            matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
            
            for match in matches:
                if len(match.groups()) >= 2:
                    # Handle patterns with multiple groups
                    for group in match.groups():
                        if (re.match(r'^[A-Z]{2,10}$', group, re.IGNORECASE) and 
                            not group.isdigit() and 
                            not re.match(r'^(LONG|SHORT|ЛОНГ|ШОРТ)$', group, re.IGNORECASE)):
                            symbol = group.upper()
                            break
                    else:
                        continue
                else:
                    symbol = match.group(1).upper()
                
                # Skip if symbol is just numbers or too short
                if symbol.isdigit() or len(symbol) < 2 or symbol in ['X', 'XX', 'XXX']:
                    continue
                
                # Normalize symbol
                if not symbol.endswith('USDT'): 
                    symbol = symbol + 'USDT'
                
                # Fix double USDT
                if symbol.endswith('USDUSDT'):
                    symbol = symbol.replace('USDUSDT', 'USDT')
                
                logger.info(f"✅ Symbol found with pattern {pattern}: {symbol}")
                return symbol
        
        return None
    
    @staticmethod
    def _extract_side(text: str) -> Optional[str]:
        """Extract trade side (LONG/SHORT) from text"""
        # First, check for explicit SHORT/LONG words anywhere in text (highest priority)
        # Use MULTILINE flag to search across all lines
        if re.search(r'\bSHORT\b', text, re.IGNORECASE | re.MULTILINE):
            return 'SHORT'
        if re.search(r'\bLONG\b', text, re.IGNORECASE | re.MULTILINE):
            return 'LONG'
        
        # Check for Russian equivalents
        if re.search(r'\bШОРТ\b', text, re.IGNORECASE | re.MULTILINE):
            return 'SHORT'
        if re.search(r'\bЛОНГ\b', text, re.IGNORECASE | re.MULTILINE):
            return 'LONG'
        
        # Check for BUY/SELL
        if re.search(r'\bSELL\b', text, re.IGNORECASE | re.MULTILINE):
            return 'SHORT'
        if re.search(r'\bBUY\b', text, re.IGNORECASE | re.MULTILINE):
            return 'LONG'
        
        # Only check emojis if no explicit words found
        # Check for SHORT patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.SHORT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                return 'SHORT'
        
        # Check for LONG patterns (emojis and other indicators)
        for pattern in EnhancedSignalParser.LONG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                return 'LONG'
        
        return None
    
    @staticmethod
    def _extract_entry_price(text: str) -> Optional[float]:
        """Extract entry price from text"""
        for pattern in EnhancedSignalParser.ENTRY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                try:
                    price_str = match.group(1).replace('$', '').replace(',', '.')
                    price = float(price_str)
                    if price > 0:
                        logger.info(f"💲 Found entry price: {price}")
                        return price
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_take_profits(text: str) -> List[float]:
        """Extract take profit levels from text with support for multiple values on same line"""
        take_profits = []
        
        # Look for multiple TP patterns
        for pattern in EnhancedSignalParser.TP_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                
                # For patterns like "цели - 0.0993$ 0.1004$ 0.1040$", extract all numbers
                if 'цели' in pattern.lower():
                    # Extract all price-like numbers from the matched group
                    numbers = re.findall(r'([\d.,]+)', match)
                    logger.info(f"🎯 Found multiple TP values in match '{match}': {numbers}")
                    for num_str in numbers:
                        try:
                            tp_val = float(num_str.replace(',', '.'))
                            if tp_val > 0:
                                take_profits.append(tp_val)
                                logger.info(f"  ✅ Added TP: {tp_val}")
                        except ValueError:
                            continue
                else:
                    # Single TP value
                    if match and re.match(r'[\d.,]+', match.replace('$', '').strip()):
                        try:
                            tp_val = float(match.replace('$', '').replace(',', '.').strip())
                            if tp_val > 0:
                                take_profits.append(tp_val)
                                logger.info(f"  ✅ Added single TP: {tp_val}")
                        except ValueError:
                            continue
        
        # Remove duplicates and sort
        take_profits = sorted(list(set(take_profits)))
        logger.info(f"🎯 Final take profits: {take_profits}")
        
        # Limit to reasonable number of TPs
        return take_profits[:5]
    
    @staticmethod
    def _extract_stop_loss(text: str) -> Optional[float]:
        """Extract stop loss from text with support for non-numeric values"""
        for pattern in EnhancedSignalParser.SL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                sl_value = match.group(1).strip()
                logger.info(f"🛑 Found stop loss text: '{sl_value}'")
                
                # Check if it's a numeric value
                try:
                    # Remove currency symbols and normalize decimal separator
                    clean_value = sl_value.replace('$', '').replace(',', '.')
                    if re.match(r'^[\d.]+$', clean_value):
                        sl = float(clean_value)
                        if sl > 0:
                            logger.info(f"🛑 Parsed numeric stop loss: {sl}")
                            return sl
                except ValueError:
                    pass
                
                # If it's a non-numeric value like "пока не ставлю", log but return None
                logger.info(f"🛑 Non-numeric stop loss found: {sl_value} (will use default SL)")
                return None  # Let the bot use its default SL settings
        
        return None
    
    @staticmethod
    def _extract_leverage(text: str) -> Optional[int]:
        """Extract leverage from text with cross margin support"""
        for pattern in EnhancedSignalParser.LEVERAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 125:
                        logger.info(f"⚡ Found leverage: {leverage}x")
                        return leverage
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def _extract_risk_percentage(text: str) -> Optional[float]:
        """Extract risk percentage from text"""
        for pattern in EnhancedSignalParser.RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                try:
                    risk = float(match.group(1).replace(',', '.'))
                    if 0 < risk <= 100:
                        logger.info(f"💰 Found risk percentage: {risk}%")
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
        
        # Base confidence for having symbol and side (most important)
        if symbol and side:
            confidence += 0.4  # Increased from 0.3
        
        # Entry price adds significant confidence
        if entry_price:
            confidence += 0.25  # Increased from 0.2
        
        # Take profits add confidence
        if take_profits:
            confidence += 0.2
        
        # Stop loss adds some confidence (even if None due to "not setting")
        # We still found and parsed the SL field
        confidence += 0.1
        
        # Leverage adds confidence
        if leverage:
            confidence += 0.1
        
        # Bonus for having multiple TPs
        if len(take_profits) > 1:
            confidence += 0.05
        
        # Bonus if this looks like a properly formatted signal with key components
        if symbol and side and (entry_price or take_profits):
            confidence += 0.1  # Extra bonus for complete signals
        
        return min(confidence, 1.0)

# Test function for development
def test_parser():
    """Test the enhanced parser with example signals"""
    test_signals = [
        """❗️СИГНАЛ

🗯DYM LONG📈

плечо - 25 кросс
цена входа - 0.0983$
цели - 0.0993$ 0.1004$ 0.1040$
стоп - пока не ставлю

🎁400$ на спот за регистрацию и торговлю на бирже Bybit📈""",

        """Новости и аналитика

🗯SOL SHORT📉

плечо - 10 кросс
цена входа - 245.50$
цели - 240$ 235$ 230$
стоп - 250$

Торговля с умом!""",

        """Ежедневный обзор рынка
Сегодня интересные движения

🗯BTC LONG📈

плечо - 5 кросс
цена входа - 67500$
цели - 68000$ 68500$ 69000$
стоп - 67000$"""
    ]
    
    print("🧪 Testing Enhanced Signal Parser v2.2")
    print("=" * 50)
    
    for i, signal_text in enumerate(test_signals, 1):
        print(f"\n📊 Testing Signal {i}:")
        print(f"Input: {signal_text[:100]}...")
        
        signal = EnhancedSignalParser.parse_signal(signal_text, f"test_channel_{i}")
        
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
            print(f"❌ FAILED - No signal detected")

if __name__ == "__main__":
    # Enable logging for testing
    logging.basicConfig(level=logging.INFO)
    test_parser()