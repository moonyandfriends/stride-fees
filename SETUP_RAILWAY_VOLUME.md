# Railway Volume Setup for Persistent Snapshots

Railway containers are ephemeral and reset on every deployment. To persist the snapshot data, you need to use Railway Volumes.

## Step-by-Step Setup

### 1. Create a Volume in Railway Dashboard

1. Go to your Railway project: https://railway.app/project/[your-project-id]
2. Click on your service (`stride-fees-api` or similar)
3. Go to the **"Volumes"** tab
4. Click **"+ New Volume"**
5. Set these values:
   - **Mount Path**: `/data`
   - **Name**: `stride-snapshots` (or any name you prefer)
6. Click **"Add"**

### 2. Set Environment Variable

In Railway dashboard, add this environment variable:
- **Key**: `SNAPSHOT_DATA_DIR`
- **Value**: `/data`

This tells the app where to store snapshots.

### 3. Deploy

Railway will automatically redeploy with the volume mounted. Your snapshots will now persist across deployments!

## How It Works

The code automatically checks for `SNAPSHOT_DATA_DIR` environment variable:
- If set: Uses `/data/redemption_rate_snapshots.json` (persistent)
- If not set: Uses `./redemption_rate_snapshots.json` (ephemeral, for local dev)

## Verify It's Working

1. Check Railway logs after deployment:
   ```
   Snapshot file will be stored at: /data/redemption_rate_snapshots.json
   ```

2. After the first snapshot runs, check it persists:
   - Deploy a new version
   - Check logs - should say "Loading existing snapshots" instead of "No existing snapshot file"

## Volume Path Reference

```
/data/
  └── redemption_rate_snapshots.json  ← Persists across deploys
```

## Troubleshooting

**Problem**: Volume not mounting
- Solution: Check Railway logs for mount errors
- Solution: Verify mount path is exactly `/data`

**Problem**: Snapshots still lost on deploy
- Solution: Verify `SNAPSHOT_DATA_DIR=/data` is set in Railway environment variables
- Solution: Check file is actually being written to `/data/` in logs

**Problem**: Permission errors
- Solution: Railway handles permissions automatically, but check container logs for write errors

## Cost

Railway Volumes:
- **Free tier**: 1GB included
- **Pro tier**: $0.25/GB/month

Snapshot file size: ~100KB per snapshot, ~40MB for 400 days of history
