#!/usr/bin/env python3
"""
Local password audit. Reads Chrome's CSV export, flags weak/reused/breached
entries, and writes a report. Passwords NEVER leave this machine — only the
first 5 chars of each SHA-1 hash are sent to Have I Been Pwned (k-anonymity).
Passwords are NEVER printed or written to the report.
"""

import csv
import hashlib
import re
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path
from datetime import datetime

CSV_PATH = Path.home() / "Documents" / "Chrome Passwords.csv"
REPORT_PATH = Path.home() / "Desktop" / "password_audit.txt"
HIBP_URL = "https://api.pwnedpasswords.com/range/{}"

WEAK_LEN = 12
COMMON_PATTERNS = {
    "password", "passw0rd", "letmein", "welcome", "qwerty", "qwerty123",
    "abc123", "iloveyou", "admin", "monkey", "dragon", "111111", "123123",
    "12345678", "1234567890", "00000000",
}


def classify_weak(pw: str) -> list[str]:
    flags = []
    if len(pw) < WEAK_LEN:
        flags.append(f"short:{len(pw)}")
    if pw.isdigit():
        flags.append("all-digits")
    elif pw.isalpha() and pw.islower():
        flags.append("all-lowercase")
    if pw.lower() in COMMON_PATTERNS:
        flags.append("common-pattern")
    if re.fullmatch(r"(.)\1+", pw):
        flags.append("repeated-char")
    if re.fullmatch(r"(?:0?123456789|abcdefgh\w*)", pw.lower()):
        flags.append("sequence")
    return flags


def hibp_check(pw: str, cache: dict) -> int:
    """Returns breach count via k-anonymity. 0 = not seen."""
    sha1 = hashlib.sha1(pw.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    if prefix not in cache:
        try:
            req = urllib.request.Request(
                HIBP_URL.format(prefix),
                headers={"User-Agent": "local-password-audit"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                cache[prefix] = r.read().decode("utf-8")
        except urllib.error.URLError as e:
            cache[prefix] = ""
            print(f"  ! network error on {prefix}: {e}", file=sys.stderr)
            return -1
        time.sleep(0.05)
    for line in cache[prefix].splitlines():
        if not line:
            continue
        h, _, count = line.partition(":")
        if h.strip() == suffix:
            return int(count.strip())
    return 0


def main():
    if not CSV_PATH.exists():
        print(f"Not found: {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pw = (row.get("password") or "").strip()
            if not pw:
                continue
            rows.append({
                "name": (row.get("name") or "").strip(),
                "url": (row.get("url") or "").strip(),
                "username": (row.get("username") or "").strip(),
                "password": pw,
            })

    print(f"Loaded {len(rows)} entries with passwords.")

    by_password = defaultdict(list)
    for r in rows:
        by_password[r["password"]].append(r)

    weak = []
    for r in rows:
        flags = classify_weak(r["password"])
        if flags:
            weak.append((r, flags))

    reused_groups = [grp for grp in by_password.values() if len(grp) > 1]
    reused_groups.sort(key=lambda g: -len(g))

    print(f"Checking {len(by_password)} unique passwords against HIBP…")
    cache = {}
    breached = []
    for i, (pw, group) in enumerate(by_password.items(), 1):
        count = hibp_check(pw, cache)
        if count > 0:
            for r in group:
                breached.append((r, count))
        if i % 50 == 0:
            print(f"  {i}/{len(by_password)}…")
    breached.sort(key=lambda x: -x[1])

    lines = []
    lines.append(f"PASSWORD AUDIT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("TOTALS")
    lines.append(f"  Entries scanned : {len(rows)}")
    lines.append(f"  Unique passwords: {len(by_password)}")
    lines.append(f"  Breached entries: {len(breached)}")
    lines.append(f"  Reused passwords: {len(reused_groups)} "
                 f"(across {sum(len(g) for g in reused_groups)} entries)")
    lines.append(f"  Weak entries    : {len(weak)}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("SECTION 1 — BREACHED (change these first)")
    lines.append("=" * 60)
    if not breached:
        lines.append("  None. Nice.")
    for r, count in breached:
        site = r["url"] or r["name"] or "(unknown)"
        lines.append(f"  [{count:>9,} breaches]  {site}  —  {r['username']}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("SECTION 2 — REUSED PASSWORDS")
    lines.append("=" * 60)
    if not reused_groups:
        lines.append("  None.")
    for idx, group in enumerate(reused_groups):
        label = chr(ord("A") + idx) if idx < 26 else f"#{idx+1}"
        lines.append(f"  Password {label} — used on {len(group)} sites:")
        for r in group:
            site = r["url"] or r["name"] or "(unknown)"
            lines.append(f"    - {site}  —  {r['username']}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("SECTION 3 — WEAK")
    lines.append("=" * 60)
    if not weak:
        lines.append("  None.")
    for r, flags in weak:
        site = r["url"] or r["name"] or "(unknown)"
        lines.append(f"  [{','.join(flags)}]  {site}  —  {r['username']}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("PRIORITY")
    lines.append("=" * 60)
    lines.append("  1. Change every entry in SECTION 1 (breached).")
    lines.append("  2. Pick a unique password for each site in SECTION 2.")
    lines.append("  3. Lengthen the SECTION 3 entries to 16+ chars.")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")
    print(f"  breached: {len(breached)}   reused groups: {len(reused_groups)}   weak: {len(weak)}")


if __name__ == "__main__":
    main()
