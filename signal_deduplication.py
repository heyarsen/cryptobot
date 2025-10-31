"""
Signal Deduplication and Enhanced Symbol Detection Module
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ProcessedSignal:
    """Track processed signals to prevent duplicates"""
    symbol: str
    side: str
    channel_id: str
    timestamp: datetime
    signal_hash: str

class SignalDuplicationTracker:
    """Prevents duplicate signals within a specified timeframe"""
    def __init__(self, db_path: str = "enhanced_trading_bot.db", cooldown_minutes: int = 10):
        self.cooldown_minutes = cooldown_minutes
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize signal tracking database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signal_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    signal_hash TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create index for efficient lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_signal_lookup 
                ON signal_tracking(symbol, side, channel_id, timestamp)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Signal tracking database initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize signal tracking database: {e}")
    
    def generate_signal_hash(self, symbol: str, side: str, channel_id: str, raw_message: str = "") -> str:
        """Generate a hash for the signal to identify duplicates"""
        try:
            # Use symbol, side, channel, and key parts of message for hash
            # Include entry price and TP levels to differentiate updated signals
            import re
            
            # Extract key price info from message
            entry_match = re.search(r'(?:вход|entry|цена входа)[:\s-]*([0-9.,]+)', raw_message, re.IGNORECASE)
            entry_price = entry_match.group(1) if entry_match else ""
            
            tp_matches = re.findall(r'(?:цел|target|tp)[:\s-]*([0-9.,]+)', raw_message, re.IGNORECASE)
            tp_prices = "_".join(tp_matches[:3])  # First 3 TP levels
            
            # Create unique identifier
            content = f"{symbol}_{side}_{channel_id}_{entry_price}_{tp_prices}"
            return hashlib.md5(content.encode()).hexdigest()[:12]
        except Exception as e:
            logger.error(f"❌ Error generating signal hash: {e}")
            # Fallback to simple hash
            content = f"{symbol}_{side}_{channel_id}"
            return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def is_duplicate(self, symbol: str, side: str, channel_id: str, raw_message: str = "") -> bool:
        """Check if this signal was already processed recently"""
        try:
            # Clean up old signals first
            self.cleanup_old_signals()
            
            # Check for recent similar signals
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Look for signals with same symbol, side, channel within cooldown period
            cutoff_time = datetime.now() - timedelta(minutes=self.cooldown_minutes)
            
            cursor.execute('''
                SELECT COUNT(*) FROM signal_tracking 
                WHERE symbol = ? AND side = ? AND channel_id = ? 
                AND timestamp > ?
            ''', (symbol, side, channel_id, cutoff_time))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            if count > 0:
                logger.info(f"🔄 Duplicate signal blocked: {symbol} {side} from {channel_id} (within {self.cooldown_minutes} min cooldown)")
                return True
            
            # Not a duplicate, record this signal
            self.record_signal(symbol, side, channel_id, raw_message)
            return False
            
        except Exception as e:
            logger.error(f"❌ Error checking signal duplicate: {e}")
            return False  # On error, allow the signal
    
    def record_signal(self, symbol: str, side: str, channel_id: str, raw_message: str = ""):
        """Record a processed signal"""
        try:
            signal_hash = self.generate_signal_hash(symbol, side, channel_id, raw_message)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO signal_tracking 
                (symbol, side, channel_id, signal_hash, timestamp, processed_at) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (symbol, side, channel_id, signal_hash, datetime.now(), datetime.now()))
            
            conn.commit()
            conn.close()
            
            logger.info(f"📝 Recorded signal: {symbol} {side} from {channel_id}")
            
        except Exception as e:
            logger.error(f"❌ Error recording signal: {e}")
    
    def cleanup_old_signals(self):
        """Remove signals older than cooldown period + buffer"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=self.cooldown_minutes + 30)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM signal_tracking WHERE timestamp < ?', (cutoff_time,))
            deleted_count = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                logger.debug(f"🧹 Cleaned up {deleted_count} old signal records")
                
        except Exception as e:
            logger.error(f"❌ Error cleaning up old signals: {e}")
    
    def get_recent_signals(self, minutes: int = 60) -> List[dict]:
        """Get recent signals for debugging"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT symbol, side, channel_id, timestamp 
                FROM signal_tracking 
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            ''', (cutoff_time,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [{'symbol': row[0], 'side': row[1], 'channel_id': row[2], 'timestamp': row[3]} for row in rows]
            
        except Exception as e:
            logger.error(f"❌ Error getting recent signals: {e}")
            return []