#!/bin/bash
KEYS_FILE="$HOME/.master_ai_keys"
[ ! -f "$KEYS_FILE" ] && exit 0

python3 - <<'PYEOF'
import json, datetime, subprocess, os, sys

KEYS_FILE = os.path.expanduser("~/.master_ai_keys")
ALERT_LOG = os.path.expanduser("~/.master_ai_key_alert_log")
THRESHOLDS = [7, 3, 1, 0]  # days-remaining thresholds that trigger alerts

try:
    keys = json.load(open(KEYS_FILE))
except:
    sys.exit(0)

today = datetime.date.today()

logged = set()
if os.path.exists(ALERT_LOG):
    for line in open(ALERT_LOG):
        logged.add(line.strip())

new_logs = []

for k, v in keys.items():
    if not k.endswith("_expires"):
        continue
    field = k[:-8]  # strip _expires suffix
    try:
        exp = datetime.date.fromisoformat(v)
    except:
        continue
    days_left = (exp - today).days

    for threshold in THRESHOLDS:
        if days_left <= threshold:
            log_key = f"{field}:{threshold}:{today.isoformat()}"
            if log_key not in logged:
                if days_left < 0:
                    msg = f"⛔ {field.upper()} key EXPIRED {abs(days_left)}d ago — rotate now!"
                    urgency = "critical"
                elif days_left == 0:
                    msg = f"🚨 {field.upper()} key expires TODAY — rotate immediately!"
                    urgency = "critical"
                elif days_left == 1:
                    msg = f"⚠️  {field.upper()} key expires TOMORROW ({v})"
                    urgency = "normal"
                elif days_left <= 3:
                    msg = f"⚠️  {field.upper()} key expires in {days_left} days ({v})"
                    urgency = "normal"
                else:
                    msg = f"🔔 {field.upper()} key expires in {days_left} days ({v})"
                    urgency = "low"
                subprocess.run(
                    ["notify-send", "-u", urgency, "-t", "10000",
                     "Master AI — Key Expiry", msg],
                    check=False
                )
                new_logs.append(log_key)
            break  # fire most urgent threshold only

if new_logs:
    with open(ALERT_LOG, "a") as f:
        f.write("\n".join(new_logs) + "\n")
PYEOF
