#!/usr/bin/env python3
# sync_hard_limits.py — propagate Claude Code's feedback memories
# (the "hard limits" / behavioral rules) into Sensei's flat memory file
# so both AIs follow the same guardrails. Universal limits, no Skynet.
#
# Usage:
#   python3 ~/scripts/sync_hard_limits.py            # dry run, preview
#   python3 ~/scripts/sync_hard_limits.py --write    # actually write
#
# Idempotent — re-running replaces the marked block, never duplicates.
# Hand-edited content above/below the markers is preserved verbatim.

import os, re, sys
from pathlib import Path

SRC = Path.home() / ".claude/projects/-home-elijah/memory"
DST = Path.home() / ".master_ai_memory"
START = "<<< CLAUDE-SYNC HARD LIMITS — auto-managed, do not hand-edit >>>"
END   = "<<< END CLAUDE-SYNC >>>"


def parse(path):
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return None, None, None
    front, body = m.group(1), m.group(2).strip()
    name = re.search(r"^name:\s*(.+)$", front, re.M)
    desc = re.search(r"^description:\s*(.+)$", front, re.M)
    return (
        name.group(1).strip() if name else path.stem,
        desc.group(1).strip() if desc else "",
        body,
    )


def build_block(full=False):
    out = [START, ""]
    out.append("These rules + project state are SYNCED from Claude Code's memory store at")
    out.append(f"  {SRC}")
    out.append("They define how Sensei must behave (rules) AND give her the same")
    out.append("project context Claude Code carries (project memory) — so when")
    out.append("Elijah mentions a project, Sensei can surface the same thread")
    out.append("Claude can. Re-run ~/scripts/sync_hard_limits.py to refresh after")
    out.append("a memory update (add --full for verbose feedback bodies).")
    out.append("")
    feedback_files = sorted(SRC.glob("feedback_*.md"))
    for f in feedback_files:
        name, desc, body = parse(f)
        if not name:
            continue
        if full:
            out.append(f"RULE: {name}")
            if desc:
                out.append(f"  ({desc})")
            for line in body.splitlines():
                out.append(f"  {line}" if line.strip() else "")
            out.append("")
        else:
            line = f"- {name}: {desc}" if desc else f"- {name}"
            out.append(line)
    # Project memory section — state, ongoing threads, design decisions.
    # Compact only (description, not full body) — full bodies would balloon
    # Sensei's per-turn context. Description carries the headline; if she
    # needs depth, she can ask Claude for the full memory file. Added
    # 2026-04-24 so Sensei surfaces the same project threads Claude does.
    project_files = sorted(SRC.glob("project_*.md"))
    if project_files:
        out.append("")
        out.append("--- PROJECT MEMORY (state + ongoing threads — not rules) ---")
        out.append("")
        for f in project_files:
            name, desc, _ = parse(f)
            if not name:
                continue
            out.append(f"- {name}: {desc}" if desc else f"- {name}")
    out.append("")
    out.append(END)
    return "\n".join(out), len(feedback_files) + len(project_files)


def splice(existing, new_block):
    if START in existing and END in existing:
        return re.sub(
            re.escape(START) + r".*?" + re.escape(END),
            lambda _: new_block,
            existing,
            count=1,
            flags=re.DOTALL,
        )
    sep = "\n\n" if existing.strip() else ""
    return existing.rstrip() + sep + "\n" + new_block + "\n"


def main():
    if not SRC.exists():
        sys.exit(f"ERR: source memory dir not found: {SRC}")
    new_block, n_files = build_block()
    existing = DST.read_text() if DST.exists() else ""
    new_full = splice(existing, new_block)
    n_rules = new_block.count("\nRULE:") + new_block.count("\n- ")
    print(f"source: {SRC}")
    print(f"  found {n_files} feedback_*.md files → {n_rules} rules")
    print(f"target: {DST}")
    print(f"  size: {len(existing):,} → {len(new_full):,} bytes")
    if new_full == existing:
        print("no changes — synced block already current")
        return
    if "--write" not in sys.argv:
        print()
        print("DRY RUN — pass --write to apply")
        return
    tmp = DST.with_suffix(DST.suffix + ".tmp")
    tmp.write_text(new_full)
    tmp.replace(DST)
    print()
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
