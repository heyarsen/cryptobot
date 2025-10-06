# Trading Bot - Quick Reference Guide

## 🎯 What's New?

All requested features have been implemented successfully!

---

## 📱 Main Menu Features

### 🔑 Accounts
- View all your trading accounts
- Add new accounts (only needs BingX credentials now!)
- Click on any account to manage it

### 📊 Stats
- See statistics for ALL accounts
- View per-account breakdown:
  - Monitoring status
  - Active/total trades
  - PnL for each account
  - Channel counts

### 🚀 Start All
- Starts monitoring for ALL accounts with configured channels
- Shows success/failure count
- Lists any failed accounts

### 🛑 Stop All
- Stops monitoring for ALL accounts
- Clean shutdown of all monitoring tasks
- Confirmation message

### 📋 All History
- View trade history from ALL accounts
- Shows which account each trade belongs to
- Sorted by most recent first
- Displays up to 20 recent trades

### 📈 All Trades
- View active positions across ALL accounts
- Groups by account name
- Shows complete trade details

### ⚙️ Default Settings
- Configure default settings for NEW accounts
- Settings include: leverage, risk %, TP/SL levels
- Easy-to-use commands:
  - `default leverage 10`
  - `default risk 2.0`
  - `default sl -10`
  - `default tp 2.0,3.5,5.0`

---

## 📋 Account Page Features (When You Click on an Account)

### Account Info Display
Shows comprehensive information:
- 🔄 Monitoring status
- 📊 Statistics (active trades, total trades, PnL)
- ⚙️ Trading settings (leverage, risk, trade amount)
- 🎯 TP/SL configuration (with details)
- 📉 Trailing stop settings (activation %, callback %)
- ✅ Feature status (signals, SL/TP creation, webhooks)

### 🚀 Start
- Starts monitoring ONLY this account
- Requires channels to be configured first
- Shows success confirmation

### 🛑 Stop
- Stops monitoring ONLY this account
- Clean shutdown of monitoring tasks
- Disconnects Telegram clients properly

### 📋 History
- Shows trade history for THIS account only
- Up to 20 recent trades
- Displays: symbol, side, entry, PnL, time

### 📈 Trades
- Shows active positions for THIS account only
- Complete trade details
- Current status

### 📊 Account Stats (NEW!)
- Detailed performance metrics:
  - **Trading Performance**: Total/winning/losing trades, win rate, total PnL
  - **Active Positions**: Open trades count, active PnL
  - **Configuration**: All settings at a glance
  - **Monitoring Status**: Current state, channel count

### ⚙️ Settings
Opens settings menu with:
- Settings source (Signal/Bot)
- SL/TP orders (ON/OFF)
- Make.com webhook (ON/OFF)
- Leverage setting
- Stop loss setting
- Take profit configuration
- **Trade Amount** - Now with inline button selection! ⭐
  - Click to choose: Percentage OR Fixed USDT
  - Easy switching between modes
- Trailing stop settings
- Channel management
- Account rename/delete

### 📡 Channels
- Add/remove monitored channels
- Select from available channels
- Manual channel entry option

---

## 🆕 Creating a New Account (Simplified!)

### Old Process (5 steps):
1. Account name
2. BingX API Key
3. BingX Secret Key
4. ~~Telegram API ID~~ ❌
5. ~~Telegram API Hash~~ ❌
6. ~~Phone number~~ ❌

### New Process (3 steps):
1. **Account name** ✅
2. **BingX API Key** ✅
3. **BingX Secret Key** ✅
4. **Done!** 🎉

The bot now automatically uses default Telegram credentials!

---

## 💡 Trade Amount Configuration (Enhanced!)

When you click on "Trade Amount" in settings:

### Step 1: Choose Mode
You'll see inline buttons:
- 💰 **Percentage** - Use a percentage of your balance
- 💵 **Fixed USDT** - Use a fixed USDT amount
- 🔙 **Back** - Return to settings

### Step 2: Enter Value
- If Percentage: Enter 1-100
- If Fixed USDT: Enter amount

### Step 3: Automatic Save
- Setting saved to database immediately
- Applied to current account
- Visible in account display

---

## 📊 Understanding Stats

### Global Stats (Main Menu → 📊 Stats)
Shows overview of ALL accounts:
- Total accounts count
- How many are actively monitoring
- Per-account breakdown with all key metrics

### Account Stats (Account Page → 📊 Account Stats)
Detailed statistics for ONE account:
- **Win Rate**: Percentage of profitable trades
- **Total PnL**: Sum of all profits/losses
- **Active PnL**: Current unrealized PnL
- **Trade Counts**: Total, winning, losing
- **Configuration Summary**: All settings
- **Monitoring Status**: Current state

---

## 🎛️ Monitoring Controls

### Individual Control (Account Page)
- 🚀 **Start**: Starts THIS account only
- 🛑 **Stop**: Stops THIS account only
- Best when you want to manage accounts separately

### Global Control (Main Menu)
- 🚀 **Start All**: Starts ALL accounts with channels
- 🛑 **Stop All**: Stops ALL accounts
- Best when you want to start/stop everything at once

### Which Should I Use?
- **Individual**: When testing, debugging, or managing specific accounts
- **Global**: When you want all accounts running or stopped together

---

## 🔍 Viewing Trades

### Account-Specific Views (Account Page)
- **📋 History**: See past trades for THIS account
- **📈 Trades**: See active positions for THIS account
- Useful for tracking individual account performance

### Multi-Account Views (Main Menu)
- **📋 All History**: See past trades from ALL accounts
- **📈 All Trades**: See active positions from ALL accounts
- Useful for overall portfolio view

---

## ⚙️ Settings You'll See

### Account Display Shows:
- Leverage (e.g., 10x)
- Risk % (e.g., 2%)
- Balance Mode (Percentage or Fixed USDT)
- Trade Amount (e.g., 5% or $100)
- TP Levels with percentages
- SL Levels with percentages
- Trailing Stop: ON/OFF
  - If ON: Shows activation % and callback %
- Signal Settings: ON/OFF
- Create SL/TP: ON/OFF
- Make Webhook: ON/OFF

### All Settings Are:
- ✅ Persisted to database
- ✅ Account-specific
- ✅ Visible at a glance
- ✅ Easy to modify

---

## 🚀 Quick Start Guide

1. **Create an Account**
   - Main Menu → 🔑 Accounts → ➕ Add Account
   - Enter: Name, BingX Key, BingX Secret
   - Done in 3 steps!

2. **Configure Settings**
   - Click on your account
   - Click ⚙️ Settings
   - Set leverage, trade amount, TP/SL levels
   - Configure trailing stop if desired

3. **Add Channels**
   - From account page, click 📡 Channels
   - Select channels to monitor
   - Or add manually with channel link

4. **Start Monitoring**
   - Click 🚀 Start on account page (for one account)
   - OR click 🚀 Start All on main menu (for all accounts)

5. **Monitor Performance**
   - Check 📊 Account Stats for detailed metrics
   - Check 📋 History for trade history
   - Check 📈 Trades for active positions

---

## 💡 Pro Tips

### Tip 1: Use Default Settings
Set your preferred defaults in Main Menu → ⚙️ Default Settings
- New accounts will inherit these settings
- Saves time on configuration

### Tip 2: Monitor Specific Accounts
Use individual Start/Stop when:
- Testing new settings
- Monitoring specific channels
- Debugging issues

### Tip 3: Check Stats Regularly
- Global stats for portfolio overview
- Account stats for individual performance
- Win rate helps identify best strategies

### Tip 4: Trade Amount Flexibility
- Use Percentage for proportional trading
- Use Fixed USDT for consistent position sizes
- Switch easily with inline buttons

---

## 🎯 Summary

Everything now works as requested:
- ✅ Inline button selection for percentage/USDT
- ✅ Simplified account creation (no Telegram credentials needed)
- ✅ Individual account monitoring control
- ✅ Global monitoring control (Start All / Stop All)
- ✅ Account-specific trade views
- ✅ Multi-account trade views
- ✅ Enhanced default settings page
- ✅ Comprehensive stats tab
- ✅ Complete account information display
- ✅ Detailed account statistics page

Enjoy your enhanced trading bot! 🚀
