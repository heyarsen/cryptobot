# Railway.com Persistent Storage Setup

## The Problem

Railway deployments use **ephemeral storage** by default, meaning the filesystem gets wiped on every deployment. This causes:
- ❌ All accounts lost after redeployment
- ❌ Session files (.session) lost
- ❌ Database wiped clean

## The Solution: Railway Volumes

Railway Volumes provide **persistent storage** that survives deployments.

---

## Step-by-Step Setup

### 1. Create a Railway Volume

1. Go to your Railway project dashboard
2. Click on your service (the bot)
3. Go to the **"Variables"** tab
4. Scroll down and click **"+ New Volume"**
5. Configure the volume:
   - **Mount Path**: `/data`
   - **Size**: 1 GB (minimum, adjust as needed)
6. Click **"Add"**

### 2. Set Environment Variables

In your Railway project, add these environment variables:

```bash
ENHANCED_DB_PATH=/data/enhanced_trading_bot.db
```

**Optional but recommended:**
```bash
# Your other environment variables
BINGX_API_KEY=your_api_key
BINGX_API_SECRET=your_api_secret
# ... any other vars you need
```

### 3. Redeploy

After adding the volume and environment variable:
1. Railway will automatically redeploy
2. The bot will now store data in `/data/` which persists across deployments

---

## Verification

After redeployment, check your Railway logs for:

```
✅ Database path: /data/enhanced_trading_bot.db
📊 Ready! Use PIN code XXXXXX to access
✅ Retrieved N accounts from database
```

If you see "Retrieved 0 accounts", it's normal for the **first** deployment after setting up the volume (your old accounts were in the ephemeral storage and are lost).

---

## Migration: Recovering Existing Accounts

If you have accounts configured but they're being lost, you have two options:

### Option A: Re-add Accounts (Recommended)

1. After setting up the volume and redeploying, use the bot to add your accounts again
2. They will now persist across deployments

### Option B: Manual Database Migration (Advanced)

If you can access your old database before it gets wiped:

1. **Before redeployment**, download the current database:
   ```bash
   # Using Railway CLI
   railway connect
   cat enhanced_trading_bot.db > /tmp/backup.db
   exit
   ```

2. **After** setting up the volume and redeploying:
   ```bash
   # Upload the database to the volume
   railway connect
   cat /tmp/backup.db > /data/enhanced_trading_bot.db
   exit
   
   # Restart the service
   railway restart
   ```

---

## Session Files Persistence

The bot also creates `.session` files for Telegram connections. These should also be stored in the persistent volume.

If session files are stored separately, you may also want to:

```bash
# Move session files to persistent storage
TELEGRAM_SESSION_PATH=/data/
```

Check `bot.py` for session file handling and ensure they're stored in `/data/` as well.

---

## Troubleshooting

### "Retrieved 0 accounts after setup"

**This is normal** if:
- First time setting up the volume
- The old database was in ephemeral storage

**Fix**: Re-add your accounts through the bot interface. They will now persist.

### "Database locked" error

Railway might not be properly mounting the volume.

**Fix**: 
1. Verify the volume is created and mounted at `/data`
2. Check Railway dashboard for volume status
3. Try restarting the service

### Volume not showing up

**Check**:
1. Make sure you're on a Railway plan that supports volumes (not all do)
2. Verify the volume is attached to the correct service
3. Check Railway status page for any issues

---

## Important Notes

⚠️ **Backup Your Database Regularly**

Even with persistent volumes, you should backup your database:

```bash
# Using Railway CLI
railway connect
cp /data/enhanced_trading_bot.db /data/backup_$(date +%Y%m%d).db
# Or download it
railway volume get /data/enhanced_trading_bot.db
```

⚠️ **Volume Size**

- Start with 1 GB
- Monitor usage in Railway dashboard
- Increase if needed (though SQLite databases are typically small)

⚠️ **Cost**

- Railway volumes have associated costs
- Check Railway pricing for current rates
- Usually very affordable for small databases (<1 GB)

---

## Quick Reference

| Item | Value |
|------|-------|
| Volume Mount Path | `/data` |
| Environment Variable | `ENHANCED_DB_PATH=/data/enhanced_trading_bot.db` |
| Database File | `enhanced_trading_bot.db` |
| Full Path | `/data/enhanced_trading_bot.db` |

---

## Next Steps

After setting up persistent storage:

1. ✅ Add your trading accounts back to the bot
2. ✅ Configure your monitored channels
3. ✅ Test with a sample signal
4. ✅ Verify accounts persist after redeployment

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for testing procedures.
