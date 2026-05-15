#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "usage: $0 <chrome-extension-id>" >&2
  exit 2
fi

ext_id="$1"
host_dir="$HOME/.config/google-chrome/NativeMessagingHosts"
host_path="$host_dir/com.master_ai.sensei_extension.json"
src="$(cd "$(dirname "$0")" && pwd)/native_messaging/com.master_ai.sensei_extension.json"

mkdir -p "$host_dir"
python3 - "$src" "$host_path" "$ext_id" <<'PY'
import json, sys
src, dest, ext_id = sys.argv[1:4]
with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)
data["allowed_origins"] = [f"chrome-extension://{ext_id}/"]
with open(dest, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
chmod +x "$HOME/scripts/sensei_native_host.py"
echo "installed $host_path"
