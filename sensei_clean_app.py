#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
import webbrowser
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

from sensei_clean.apply import load_undo_records
from sensei_clean.connectors import detect_sources
from sensei_clean.engine import scan_run
from sensei_clean.runner import apply_per_adapter, undo_per_adapter


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


def _short_path(path: str, limit: int = 78) -> str:
    if len(path) <= limit:
        return path
    return "..." + path[-(limit - 3):]


def _action_words(action) -> str:
    name = Path(action.source_path).name
    if action.action_type == "quarantine_move":
        verb = "extra copy -> Safe Quarantine"
    elif action.action_type == "cloud_move":
        verb = "extra cloud copy -> Cloud Quarantine"
    elif action.action_type == "archive_move":
        verb = "file -> organized folder"
    else:
        verb = "file move"
    need = " (needs extra YES)" if action.lane == "monitored" else ""
    return f"- {name}: {verb}{need}\n  from: {_short_path(action.source_path)}\n  to:   {_short_path(action.destination_path or '')}"


def _open_review_page(path: Path) -> None:
    try:
        webbrowser.open(path.resolve().as_uri())
    except Exception:
        pass


def run_interactive() -> int:
    message_dialog(
        title=BANNER,
        text=(
            "Clean up without guessing.\n\n"
            "Sensei scans the places you pick, shows you the list, then asks before moving anything.\n"
            "Extra copies go to Safe Quarantine. If something looks wrong, Undo puts it back."
        ),
    ).run()

    task = radiolist_dialog(
        title=BANNER,
        text="Choose what to do:",
        values=[
            ("dups", "Find duplicate files"),
            ("organize", "Organize messy Downloads"),
            ("both", "Find duplicates + organize Downloads"),
            ("office", "Clean Office, PDF, and LibreOffice files"),
        ],
    ).run()
    if not task:
        return 0

    demo = bool(yes_no_dialog(title=BANNER, text="Try a safe demo first?").run())

    sha256 = False
    include_text = False
    include_previews = False
    list_cloud = False
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
            text="Check for true duplicate files?\n\n"
                 "Sensei reads each file locally to prove two files are exactly the same.",
        ).run())

        if sha256:
            include_text = bool(yes_no_dialog(
                title=BANNER,
                text="Show tiny text previews in the review page?\n\n"
                     "Use this only when you want to see what readable text files contain.",
            ).run())
        else:
            include_text = False

        include_previews = bool(yes_no_dialog(
            title=BANNER,
            text="Make a visual review page?\n\n"
                 "It shows file names, where files are now, and where Sensei wants to move them.",
        ).run())

        # Cloud listing toggle — only ask when an rclone source was picked.
        has_cloud_root = any(r.startswith("rclone:") for r in roots)
        list_cloud = False
        if has_cloud_root:
            list_cloud = bool(yes_no_dialog(
                title=BANNER,
                text=(
                    "Look inside the cloud folder you picked?\n\n"
                    "No = only check that the cloud account connects.\n"
                    "Yes = read the file list in that cloud folder so Sensei can find duplicates.\n\n"
                    "Cloud files will never be deleted. Any cloud move asks for extra approval."
                ),
            ).run())

        # Keep run artifacts local and contained by default.
        run_dir = mkdtemp(prefix="sensei_clean_run_", dir="/tmp")
        quarantine_root = str((Path.home() / "Sensei-Quarantine").resolve())

        sensitive = [r for r in roots if _sensitive_root(r)]
        if sensitive:
            ok = _require_typed_approval(
                "You picked private folders:\n"
                + "\n".join(f"  - {r}" for r in sensitive)
                + "\n\nSensei will read file names there, and may read file contents if duplicate checking is on."
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
            list_cloud=list_cloud,
            progress=progress_cb,
        )
        scan_counter.done = True
        if hash_counter is not None:
            hash_counter.done = True

    report_path = run_path / "reports" / "summary.md"
    review_path = run_path / "reports" / "review.html"
    monitored = sum(1 for a in actions if a.lane == "monitored")
    unattended = sum(1 for a in actions if a.lane == "unattended")

    message_dialog(
        title=BANNER,
        text=(
            f"Scan finished.\n\n"
            f"Files checked: {len(items)}\n"
            f"Duplicate groups found: {len(findings)}\n"
            f"Moves ready: {unattended}\n"
            f"Moves needing extra YES: {monitored}\n\n"
            f"Visual review page:\n  {review_path}\n\n"
            f"Text report:\n  {report_path}"
        ),
    ).run()

    if review_path.exists():
        if bool(yes_no_dialog(title=BANNER, text="Open the visual review page now?").run()):
            _open_review_page(review_path)

    # ---- move (optional) ----
    if not actions:
        message_dialog(title=BANNER, text="Nothing to move. Your selected places are clean for this scan.").run()
        return 0

    preview_lines = "\n\n".join(_action_words(a) for a in actions[:6])
    if len(actions) > 6:
        preview_lines += f"\n\n...and {len(actions) - 6} more move(s). Open the review page to see all of them."

    do_move = bool(yes_no_dialog(
        title=BANNER,
        text=(
            "Move the safe files now?\n\n"
            "Nothing gets deleted. Extra copies go to Safe Quarantine.\n\n"
            f"{preview_lines}"
        ),
    ).run())
    if do_move:
        approve_monitored = False
        if monitored:
            approve_monitored = bool(yes_no_dialog(
                title=BANNER,
                text="Also move the files that need extra approval?\n\n"
                     "Choose No unless you clearly understand those moves.",
            ).run())

        selected = actions if approve_monitored else [a for a in actions if a.lane != "monitored"]

        if not selected:
            message_dialog(title=BANNER, text="No safe moves selected. Nothing changed.").run()
        else:
            with ProgressBar(title=f"{BANNER} - moving files") as pb:
                it = pb(selected, label="Moving")
                results = apply_per_adapter(it, capabilities, str(run_path / "undo.jsonl"))
            applied = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            message_dialog(
                title=BANNER,
                text=f"Move finished.\n\nMoved: {applied}\nProblems: {failed}\nUndo file:\n  {run_path / 'undo.jsonl'}",
            ).run()

    # ---- undo (optional) ----
    if (run_path / "undo.jsonl").exists():
        do_undo = bool(yes_no_dialog(title=BANNER, text="Put the moved files back now?").run())
        if do_undo:
            if not _require_typed_approval("Undo will move files back to their original paths."):
                return 0
            undo_records = load_undo_records(str(run_path / "undo.jsonl"))
            with ProgressBar(title=f"{BANNER} - putting files back") as pb:
                it = pb(list(reversed(undo_records)), label="Undoing")
                results = undo_per_adapter(it)
            undone = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            message_dialog(title=BANNER, text=f"Undo finished.\n\nMoved back: {undone}\nProblems: {failed}").run()

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
    results = apply_per_adapter(actions, caps, str(run_path / "undo.jsonl"))
    if not all(r.success for r in results):
        return 2
    undo_records = load_undo_records(str(run_path / "undo.jsonl"))
    undo_results = undo_per_adapter(list(reversed(undo_records)))
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
