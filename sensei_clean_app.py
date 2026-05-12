#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from tempfile import mkdtemp

from prompt_toolkit.shortcuts import (
    checkboxlist_dialog,
    input_dialog,
    message_dialog,
    radiolist_dialog,
    yes_no_dialog,
)
from prompt_toolkit.shortcuts.progress_bar import ProgressBar

from sensei_clean.apply import apply_actions, load_undo_records, undo_actions
from sensei_clean.adapters.local_fs import LocalFSAdapter
from sensei_clean.connectors import detect_sources
from sensei_clean.engine import scan_run


BANNER = "Sensei Clean"


def _expand_roots(raw: str) -> list[str]:
    parts = shlex.split(raw)
    return [str(Path(p).expanduser().resolve()) for p in parts if p.strip()]


def _sensitive_root(path: str) -> bool:
    # Same high-risk roots Sensei commonly treats as private-by-default.
    p = str(Path(path).expanduser().resolve())
    home = str(Path.home())
    if not p.startswith(home + os.sep):
        return False
    rel = p[len(home) + 1 :]
    top = rel.split(os.sep, 1)[0]
    return top in {"Desktop", "Downloads", "Documents", "Pictures", "Videos"}


def _pick_roots_ui() -> list[str] | None:
    """Return chosen roots (absolute paths) or None if cancelled."""
    values = [conn.to_choice() for conn in detect_sources() if conn.available]

    chosen = checkboxlist_dialog(
        title=BANNER,
        text="Select folders to scan:",
        values=values,
    ).run()
    if chosen is None:
        return None
    roots = [str(Path(p).expanduser().resolve()) for p in chosen]
    if roots:
        return roots
    # Allow advanced entry if none selected.
    raw = input_dialog(title=BANNER, text="No folders selected. Enter roots to scan (space-separated paths):").run()
    if not raw:
        return None
    roots = _expand_roots(raw)
    return roots or None


def _require_typed_approval(reason: str) -> bool:
    ans = input_dialog(
        title=BANNER,
        text=f"{reason}\n\nType YES to continue:",
    ).run()
    return (ans or "").strip().upper() == "YES"


def run_interactive() -> int:
    message_dialog(
        title=BANNER,
        text=(
            "Review-first local cleanup.\n\n"
            "This tool does not move anything unless you explicitly run Apply.\n"
            "Sensitive items are routed to the monitored lane and require extra approval."
        ),
    ).run()

    task = radiolist_dialog(
        title=BANNER,
        text="Choose what to do:",
        values=[
            ("dups", "Clean: find exact duplicates (quarantine the extras)"),
            ("organize", "Organize: sort Downloads by file type (reversible)"),
            ("both", "Both: duplicates + organize"),
            ("office", "Office/Libre: focus on Office file types (duplicates + organize)"),
        ],
    ).run()
    if not task:
        return 0

    demo = bool(yes_no_dialog(title=BANNER, text="Run in Demo mode (safe /tmp only)?").run())

    sha256 = False
    include_text = False
    include_previews = False
    roots: list[str]
    suffix_allowlist = None
    organize = task in {"organize", "both", "office"}

    if demo:
        demo_root = Path(mkdtemp(prefix="sensei_clean_demo_", dir="/tmp"))
        (demo_root / "A").mkdir(parents=True, exist_ok=True)
        (demo_root / "B").mkdir(parents=True, exist_ok=True)
        (demo_root / "C").mkdir(parents=True, exist_ok=True)
        (demo_root / "A" / "dup.txt").write_text("hello world\n", encoding="utf-8")
        (demo_root / "B" / "dup.txt").write_text("hello world\n", encoding="utf-8")
        (demo_root / "C" / "unique.txt").write_text("unique\n", encoding="utf-8")

        roots = [str(demo_root)]
        sha256 = task in {"dups", "both", "office"}  # dups needs hashing
        include_text = False
        include_previews = True
        run_dir = mkdtemp(prefix="sensei_clean_run_", dir="/tmp")
        quarantine_root = str(demo_root / "Quarantine")
    else:
        picked = _pick_roots_ui()
        if not picked:
            return 0
        roots = picked

        sha256 = task in {"dups", "both", "office"} and bool(yes_no_dialog(
            title=BANNER,
            text="Compute SHA256 to detect exact duplicates?\n\n"
                 "This reads file contents locally (no network).",
        ).run())

        if sha256:
            include_text = bool(yes_no_dialog(
                title=BANNER,
                text="Include short text snippets in the report?\n\n"
                     "This reads the first ~280 chars of .txt/.md locally.\n"
                     "Recommended: No unless you need it.",
            ).run())
        else:
            include_text = False

        include_previews = bool(yes_no_dialog(
            title=BANNER,
            text="Generate a local preview index with file paths and readable document excerpts?\n\n"
                 "This writes excerpts to the local run report. Recommended: No for private folders unless you need review.",
        ).run())

        # Keep run artifacts local and contained by default.
        run_dir = mkdtemp(prefix="sensei_clean_run_", dir="/tmp")
        quarantine_root = str((Path.home() / "Sensei-Quarantine").resolve())

        sensitive = [r for r in roots if _sensitive_root(r)]
        if sensitive:
            ok = _require_typed_approval(
                "You selected sensitive home folders:\n"
                + "\n".join(f"  - {r}" for r in sensitive)
                + "\n\nScan is local-only, but it will read filenames and optionally file contents for hashing/snippets."
            )
            if not ok:
                return 0

    if task == "office":
        suffix_allowlist = {
            ".doc", ".docx", ".odt", ".rtf",
            ".xls", ".xlsx", ".ods", ".csv",
            ".ppt", ".pptx", ".odp",
            ".pdf", ".txt", ".md",
        }

    # ---- scan with progress ----
    # We intentionally avoid a full pre-count pass (which can double IO on
    # large trees). Progress bars run with unknown totals and show
    # monotonically increasing counts instead.
    with ProgressBar(title=f"{BANNER} — scan") as pb:
        scan_counter = pb(None, label="Scanning files", total=None)
        hash_counter = None
        prev_scan = 0
        prev_hash = 0

        def progress_cb(p: str, d: int, t: int) -> None:
            nonlocal hash_counter, prev_scan, prev_hash
            if p == "scan":
                scan_counter.label = f"Scanning files ({d})"
                delta = max(0, d - prev_scan)
                prev_scan = d
                for _ in range(delta):
                    scan_counter.item_completed()
            elif p == "hash":
                if hash_counter is None:
                    hash_counter = pb(None, label="Hashing files (sha256)", total=max(1, t or d or 1))
                hash_counter.label = f"Hashing files (sha256) ({d}/{hash_counter.total or t or '?'} )"
                delta = max(0, d - prev_hash)
                prev_hash = d
                for _ in range(delta):
                    hash_counter.item_completed()
            elif p == "done":
                scan_counter.done = True
                if hash_counter is not None:
                    hash_counter.done = True

        run_path, capabilities, items, findings, actions = scan_run(
            roots=roots,
            sha256=sha256,
            quarantine_root=quarantine_root,
            run_dir=run_dir,
            include_text_snippets=include_text,
            include_previews=include_previews,
            suffix_allowlist=suffix_allowlist,
            organize=organize,
            organize_root=str((Path.home() / "Sensei-Organized").resolve()),
            progress=progress_cb,
        )
        # The local capability is the one we drive for apply/undo this round.
        # Cloud caps land in the same list but their adapters are probe-only.
        capability = next(
            (c for c in capabilities if c.capability == "local"),
            capabilities[0] if capabilities else None,
        )

        scan_counter.done = True
        if hash_counter is not None:
            hash_counter.done = True

    report_path = run_path / "reports" / "summary.md"
    monitored = sum(1 for a in actions if a.lane == "monitored")
    unattended = sum(1 for a in actions if a.lane == "unattended")

    message_dialog(
        title=BANNER,
        text=(
            f"Scan complete.\n\n"
            f"Run dir: {run_path}\n"
            f"Items: {len(items)}\n"
            f"Findings: {len(findings)}\n"
            f"Actions: {len(actions)} (unattended={unattended}, monitored={monitored})\n\n"
            f"Report:\n  {report_path}"
        ),
    ).run()

    # ---- apply (optional) ----
    do_apply = bool(yes_no_dialog(title=BANNER, text="Apply unattended-lane actions now?").run())
    if do_apply:
        approve_monitored = False
        if monitored:
            approve_monitored = bool(yes_no_dialog(
                title=BANNER,
                text="Also include monitored (sensitive) actions?\n\n"
                     "Recommended: No unless you explicitly intend to move sensitive items.",
            ).run())

        cap = capability
        adapter = LocalFSAdapter(run_id=cap.root.split(";")[0] if cap.root else "run", roots=roots, quarantine_root=quarantine_root)
        # Note: LocalFSAdapter.run_id is used only for item ids; apply uses paths.
        # We reuse a fresh adapter for apply/undo operations.
        selected = actions if approve_monitored else [a for a in actions if a.lane != "monitored"]

        if not selected:
            message_dialog(title=BANNER, text="No actions selected to apply.").run()
        else:
            with ProgressBar(title=f"{BANNER} — apply") as pb:
                it = pb(selected, label="Applying")
                # apply_actions already enforces policy.can_apply; this is just UI progress.
                results = apply_actions(adapter, it, cap, str(run_path / "undo.jsonl"))
            applied = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            message_dialog(
                title=BANNER,
                text=f"Apply complete.\n\nApplied: {applied}\nFailed: {failed}\nJournal: {run_path / 'undo.jsonl'}",
            ).run()

    # ---- undo (optional) ----
    if (run_path / "undo.jsonl").exists():
        do_undo = bool(yes_no_dialog(title=BANNER, text="Undo moves from this run now?").run())
        if do_undo:
            if not _require_typed_approval("Undo will move files back to their original paths."):
                return 0
            undo_records = load_undo_records(str(run_path / "undo.jsonl"))
            adapter = LocalFSAdapter(run_id="undo", roots=roots, quarantine_root=quarantine_root)
            with ProgressBar(title=f"{BANNER} — undo") as pb:
                it = pb(list(reversed(undo_records)), label="Undoing")
                results = undo_actions(adapter, it)
            undone = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            message_dialog(title=BANNER, text=f"Undo complete.\n\nUndone: {undone}\nFailed: {failed}").run()

    return 0


def run_selftest() -> int:
    # Non-interactive demo pipeline: scan -> apply -> undo under /tmp.
    demo_root = Path(mkdtemp(prefix="sensei_clean_demo_", dir="/tmp"))
    (demo_root / "A").mkdir(parents=True, exist_ok=True)
    (demo_root / "B").mkdir(parents=True, exist_ok=True)
    (demo_root / "A" / "dup.txt").write_text("hello\n", encoding="utf-8")
    (demo_root / "B" / "dup.txt").write_text("hello\n", encoding="utf-8")
    run_dir = mkdtemp(prefix="sensei_clean_run_", dir="/tmp")
    run_path, caps, _items, _findings, actions = scan_run(
        roots=[str(demo_root)],
        sha256=True,
        quarantine_root=str(demo_root / "Quarantine"),
        run_dir=run_dir,
        include_text_snippets=False,
        include_previews=True,
        progress=None,
    )
    cap = next((c for c in caps if c.capability == "local"), caps[0])
    adapter = LocalFSAdapter(run_id="apply", roots=[str(demo_root)], quarantine_root=str(demo_root / "Quarantine"))
    results = apply_actions(adapter, actions, cap, str(run_path / "undo.jsonl"))
    if not all(r.success for r in results):
        return 2
    undo_records = load_undo_records(str(run_path / "undo.jsonl"))
    undo_results = undo_actions(adapter, list(reversed(undo_records)))
    if not all(r.success for r in undo_results):
        return 3
    print(f"selftest ok: run={run_path}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="non-interactive demo scan/apply/undo")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
