#!/usr/bin/env bash
# Phase 1.5 — refresh ~/.master_ai_domain_classes.json for Sensei's safety
# classifier. Designed to be run weekly via the maintenance window timer
# (~/scripts/deep_clean.sh) and on demand by Elijah.
#
# What it does:
#   - Preserves user-curated entries in ~/.master_ai_domain_classes.user.json
#     (always merged into the output, never overwritten by a remote pull).
#   - Pulls a category-1 (malicious/phishing) list from URLhaus by abuse.ch
#     when DOMAIN_CLASSES_FETCH=1 is set in the environment AND curl is on
#     PATH. URLhaus is free, public, and host-only — no API key, no PII
#     leak. The remote URL is configurable via DOMAIN_CLASSES_URLHAUS_URL.
#   - Skips remote pull if offline or DOMAIN_CLASSES_FETCH is unset — the
#     local file is updated from user.json + seed only.
#   - Writes atomically (tmp file + mv) so a partial network failure can't
#     leave Sensei with a half-written classifier list.
#   - Caps the category_1 list at 50000 entries to keep load+match fast.
#
# Exit codes: 0 = wrote a fresh list; 0 also covers "skipped remote pull,
# preserved local". 1 = local merge failed (file system / parse error).
#
# Triggered from:
#   - ~/scripts/deep_clean.sh weekly window (Phase 1.5 hook to add there)
#   - Manual: `bash ~/scripts/refresh_domain_classes.sh`
#   - With remote pull: `DOMAIN_CLASSES_FETCH=1 bash ~/scripts/refresh_domain_classes.sh`

set -u

OUT_FILE="${DOMAIN_CLASSES_OUT:-$HOME/.master_ai_domain_classes.json}"
USER_FILE="${DOMAIN_CLASSES_USER:-$HOME/.master_ai_domain_classes.user.json}"
SEED_FILE="${DOMAIN_CLASSES_SEED:-$HOME/scripts/master_ai_domain_classes.seed.json}"
URLHAUS_URL="${DOMAIN_CLASSES_URLHAUS_URL:-https://urlhaus.abuse.ch/downloads/hostfile/}"
FETCH_TIMEOUT_S="${DOMAIN_CLASSES_FETCH_TIMEOUT:-30}"
MAX_CAT1="${DOMAIN_CLASSES_MAX_CAT1:-50000}"
TMP_DIR="$(mktemp -d -t domain_classes_refresh.XXXXXX)" || { echo "refresh: mktemp failed" >&2; exit 1; }
trap 'rm -rf "$TMP_DIR"' EXIT

# 1. Pull the remote list when asked. Failure here is non-fatal; we just
#    skip the fetched category_1 additions.
URLHAUS_HOSTS="$TMP_DIR/urlhaus.txt"
: > "$URLHAUS_HOSTS"
if [ "${DOMAIN_CLASSES_FETCH:-0}" = "1" ] && command -v curl >/dev/null 2>&1; then
  if curl -sS -f --max-time "$FETCH_TIMEOUT_S" -A 'python-requests/2.31.0' \
       "$URLHAUS_URL" -o "$URLHAUS_HOSTS"; then
    echo "refresh: fetched URLhaus host file ($(wc -l < "$URLHAUS_HOSTS") lines)"
  else
    echo "refresh: URLhaus fetch failed; preserving local list" >&2
    : > "$URLHAUS_HOSTS"
  fi
fi

# 2. Merge in Python. Stdlib only, deterministic. Atomic write at the end.
OUT_TMP="$TMP_DIR/out.json"
python3 - "$OUT_FILE" "$USER_FILE" "$SEED_FILE" "$URLHAUS_HOSTS" "$OUT_TMP" "$MAX_CAT1" <<'PYEOF' || exit 1
import json, os, sys, time

out_path, user_path, seed_path, urlhaus_path, out_tmp, max_cat1 = sys.argv[1:7]
max_cat1 = int(max_cat1)

def _load(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}

# Base = whatever's already on disk, falling back to the seed shipped in the repo.
base = _load(out_path) or _load(seed_path)
user = _load(user_path)

def _bucket(d, key):
    val = d.get(key)
    return dict(val) if isinstance(val, dict) else {}

cat1 = _bucket(base, "category_1")
cat2 = _bucket(base, "category_2")
cat3 = _bucket(base, "category_3")

# Layer user additions LAST so they win conflicts.
for src, target in (
    (_bucket(user, "category_1"), cat1),
    (_bucket(user, "category_2"), cat2),
    (_bucket(user, "category_3"), cat3),
):
    for k, v in src.items():
        target[str(k).lower().strip('.')] = str(v or "")[:500]

# Pull URLhaus into cat1. Host file format is `127.0.0.1 host.example` per
# line, with comments. We just want the host column.
try:
    with open(urlhaus_path, 'r', encoding='utf-8') as f:
        added = 0
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            host = parts[-1].lower().strip('.') if parts else ""
            if not host or '.' not in host:
                continue
            if host in cat1:
                continue
            cat1[host] = "URLhaus by abuse.ch"
            added += 1
            if len(cat1) >= max_cat1:
                break
except OSError:
    added = 0

# Re-apply user.json cat_1 over the URLhaus pull so user reasons win.
for k, v in _bucket(user, "category_1").items():
    cat1[str(k).lower().strip('.')] = str(v or "")[:500]

out = {
    "_meta": {
        "version": 1,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "refresh_domain_classes.sh",
        "cat1_count": len(cat1),
        "cat2_count": len(cat2),
        "cat3_count": len(cat3),
        "urlhaus_added": added,
    },
    "category_1": cat1,
    "category_2": cat2,
    "category_3": cat3,
}
with open(out_tmp, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, sort_keys=True, ensure_ascii=False)
    f.write("\n")
PYEOF

# 3. Atomic move.
if [ ! -s "$OUT_TMP" ]; then
  echo "refresh: merge produced empty output, refusing to overwrite $OUT_FILE" >&2
  exit 1
fi
mv "$OUT_TMP" "$OUT_FILE"
echo "refresh: wrote $OUT_FILE"
