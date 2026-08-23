# Critical Timezone Bug Fix

## Problem Identified

The bot was using UTC time to check `active_hours` instead of the local timezone configured via the `TZ` environment variable. This caused the bot to:
- Run during incorrect hours (UTC hours instead of local hours)
- Execute fewer actions than expected if the current UTC hour was outside the configured hours
- Incorrectly determine weekends (for reduced activity)

## Example

If you set:
- `active_hours: [8, 23]` (8 AM to 11 PM)
- `TZ=Europe/Paris` (UTC+1 or UTC+2 depending on DST)

The bot would check:
- **WRONG (Before fix)**: Is current UTC hour between 8-23?
- **CORRECT (After fix)**: Is current Paris time hour between 8-23?

## Files Changed

1. **safety/rate_limiter.py**
   - `is_active_hours()`: Now uses `datetime.now()` instead of `datetime.utcnow()`
   - `is_weekend()`: Now uses `datetime.now()` instead of `datetime.utcnow()`

2. **core/subreddit_hub.py**
   - `_get_scheduled_content()`: Now uses `datetime.now().weekday()` instead of `datetime.utcnow().weekday()`

## How to Verify the Fix

### On Raspberry Pi via Tailscale SSH

1. **Check the timezone setting:**
   ```bash
   docker-compose config | grep TZ
   ```
   If not set, add to your `.env` file or docker-compose override:
   ```bash
   export TZ=Europe/Paris
   # or your actual timezone
   ```

2. **Verify local time in container:**
   ```bash
   docker-compose exec miloagent date
   ```
   This should show your local timezone, not UTC.

3. **Check logs for timezone-related messages:**
   ```bash
   docker-compose logs miloagent --tail 50 | grep -E "active|hour"
   ```

4. **Run the diagnostic script:**
   ```bash
   docker-compose exec miloagent python3 diagnostics/action_count_debug.py
   ```
   This will show:
   - Current local time vs UTC time
   - Whether bot is currently within active hours
   - Recent actions and scans
   - Pending opportunities

### Expected Behavior After Fix

Once the container restarts with the fix:
- Bot will correctly interpret `active_hours` in your local timezone
- You should see increased action counts if scans are finding opportunities
- The diagnostic script should show "Currently within active hours: true" during your configured hours

## Important: Restart Required

The timezone fix will take effect after:
1. Pushing the changes to your Raspberry Pi:
   ```bash
   git pull origin claude/new-session-akqio7
   ```

2. Restarting the container:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

3. (Optional) Watching the logs to confirm the fix is working:
   ```bash
   docker-compose logs -f miloagent
   ```
