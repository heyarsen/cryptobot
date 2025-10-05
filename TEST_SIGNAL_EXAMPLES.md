# Test Signal Examples

These are example messages that should be detected by the bot's signal parser:

## Format 1: Simple English Format
```
🚀 LONG BTCUSDT
Entry: 45000
TP: 46000
SL: 44000
Leverage: 10x
```

## Format 2: Multiple TP Levels
```
BUY ETHUSDT
Entry: 2500
TP1: 2550
TP2: 2600
TP3: 2650
SL: 2450
Leverage: 20x
```

## Format 3: Short Signal
```
SHORT SOLUSDT
Entry: 100
Take Profit: 95, 90
Stop Loss: 105
Leverage: 15x
```

## Format 4: Minimal Format
```
LONG BNBUSDT
TP: 350
SL: 320
```

## Format 5: With Emojis
```
📈 BUY ADAUSDT
💰 Entry: 0.50
🎯 TP: 0.55, 0.60
🛑 SL: 0.45
⚡ Leverage: 10x
```

## Format 6: Russian Format (Supported)
```
🚀 ЛОНГ BTCUSDT
Вход: 45000
ТП: 46000
СЛ: 44000
Плечо: 10x
```

## What the Parser Looks For:

### Required:
1. **Direction keyword**: LONG, SHORT, BUY, SELL (or Russian: ЛОНГ, ШОРТ, ПОКУПКА, ПРОДАЖА)
2. **Symbol**: Must end with USDT (e.g., BTCUSDT, ETHUSDT)

### Optional:
3. **Entry price**: Entry: 45000 or Вход: 45000
4. **Take Profit**: TP: 46000 or TP1: 46000, TP2: 47000
5. **Stop Loss**: SL: 44000 or СЛ: 44000
6. **Leverage**: Leverage: 10x or Плечо: 10x

## Tips:
- The symbol and direction can be on the same line or separate lines
- Numbers can have commas or decimals
- Extra text is okay - the parser extracts what it needs
- Case insensitive (LONG = long = Long)

## What WON'T Work:
❌ No direction keyword
❌ Symbol doesn't end with USDT
❌ Only price information without symbol/direction

## Testing Your Configuration:

To verify the bot is monitoring correctly, check logs for:

1. **Bot startup:**
   ```
   🚀 Auto-starting monitoring for user XXXX with N channels
   ```

2. **When you send a message:**
   ```
   🆕 New message detected in channel XXXX!
   📨 Processing new message ID XXX
   ```

3. **When parsing:**
   ```
   🔍 PARSING SIGNAL from channel XXXX
   ✅ SIGNAL PARSED SUCCESSFULLY: BTCUSDT LONG
   ```

4. **When executing:**
   ```
   🎯 SIGNAL DETECTED! BTCUSDT LONG
   🚀 EXECUTING TRADE: BTCUSDT LONG
   ```