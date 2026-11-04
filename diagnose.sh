#!/usr/bin/env bash
# Health check for the assistant bot, for when it doesn't answer in Telegram.
# Run in the Droplet Console:  bash /opt/assistant-bot/diagnose.sh
cd /opt/assistant-bot 2>/dev/null || { echo "❌ /opt/assistant-bot not found (was the setup finished?)"; exit 1; }

echo "== 1. Is the bot running? =="
if systemctl is-active --quiet assistant; then
  echo "✅ running since $(systemctl show -p ActiveEnterTimestamp --value assistant)"
else
  echo "❌ NOT running. Try:  systemctl restart assistant   (then run this check again)"
fi
restarts=$(systemctl show -p NRestarts --value assistant 2>/dev/null || echo 0)
if [ "${restarts:-0}" -gt 3 ]; then
  echo "⚠️  it has restarted $restarts times: it keeps crashing, see the errors below"
fi

echo; echo "== 2. Settings =="
if [ -f .env ]; then echo "✅ .env file present"; else echo "❌ .env file missing"; fi
for k in TELEGRAM_BOT_TOKEN ANTHROPIC_API_KEY ALLOWED_USER_IDS; do
  if grep -q "^$k=." .env 2>/dev/null; then echo "✅ $k is set"; else echo "❌ $k is empty or missing"; fi
done

echo; echo "== 3. Can the server reach the internet services? =="
for host in api.telegram.org api.anthropic.com api.openai.com sheets.googleapis.com api.todoist.com ntfy.sh; do
  if curl -s -o /dev/null --max-time 8 "https://$host"; then echo "✅ $host"; else echo "❌ $host is NOT reachable"; fi
done

echo; echo "== 4. Disk and memory =="
df -h / | awk 'NR==2 {print "Disk: " $4 " free (" $5 " used)"}'
free -m | awk '/Mem:/ {print "Memory: " $7 " MB available"}'

echo; echo "== 5. Last errors in the bot's log =="
journalctl -u assistant --no-pager -n 500 2>/dev/null | grep -iE "error|exception|traceback" | tail -n 8 || true

echo; echo "== 6. Last 10 log lines =="
journalctl -u assistant --no-pager -n 10 2>/dev/null
echo; echo "Done. If something is ❌ and unclear, send a screenshot of this screen (it shows no keys)."
