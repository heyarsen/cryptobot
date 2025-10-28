# 🚀 Quick Fix: Accounts Not Persisting on Railway

## Problem
After redeploying on Railway.com, all your accounts disappear.

## Root Cause
Railway uses **ephemeral storage** - the filesystem is wiped on every deployment. Your SQLite database with all accounts is lost!

---

## ✅ Solution (5 minutes)

### Step 1: Add a Railway Volume
1. Open your Railway project
2. Click on your bot service
3. Go to **Settings** → **Volumes**
4. Click **"+ New Volume"**
5. Set:
   - **Mount Path**: `/data`
   - Click **"Add"**

### Step 2: Set Environment Variable
1. Still in your service settings, go to **Variables**
2. Click **"+ New Variable"**
3. Add:
   ```
   ENHANCED_DB_PATH=/data/enhanced_trading_bot.db
   ```
4. Click **"Add"**

### Step 3: Redeploy
Railway will automatically redeploy. Your accounts will now persist! ✨

---

## ⚠️ Important Note

After the first deployment with the volume:
- You'll have **0 accounts** (the old database was in ephemeral storage and is gone)
- You need to **re-add your accounts** once through the bot
- From then on, they'll persist across all future deployments

---

## Verification

Check your Railway logs after deployment:

```
✅ Database path: /data/enhanced_trading_bot.db
📊 Ready! Use PIN code XXXXXX to access
```

If you see this, you're good! The database is now on persistent storage.

---

## Need More Details?

See [RAILWAY_SETUP.md](./RAILWAY_SETUP.md) for the complete guide with troubleshooting.

---

## Alternative: Use Railway PostgreSQL (Advanced)

Instead of SQLite + Volume, you could migrate to PostgreSQL:
1. Add Railway PostgreSQL service
2. Modify bot.py to use PostgreSQL instead of SQLite
3. More robust for production

But the volume solution above is simpler and works perfectly for this use case!
