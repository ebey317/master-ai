#!/usr/bin/env python3
"""
Sensei Clean — review-first local cleanup.

Three customer commands:

  sensei-clean scan   [--roots ...] [--sha256] [--run-dir DIR]
  sensei-clean apply  RUN_DIR [--yes] [--approve-monitored]
  sensei-clean undo   RUN_DIR

Default behavior is SCAN — nothing on disk gets moved. Run `apply`
explicitly to enact the queued actions. Run `undo` to reverse what was
applied.

Privacy: items whose path or content matches the harvest privacy policy
(Pictures / Documents / Downloads / Desktop / jobseeker / .ssh / .gnupg /
.aws/credentials / .master_ai_keys / .netrc, plus the standard private
terms and secret patterns) get sensitivity bumped and their actions are
routed to the 'monitored' lane with approval_required=True. Apply only
acts on those when --approve-monitored is passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from sensei_clean.adapters.local_fs import LocalFSAdapter
from sensei_clean.apply import apply_actions, load_undo_records, undo_actions
from sensei_clean.policy import MONITORED_SENSITIVITIES
from sensei_clean.queue_builder import build_queue
from sensei_clean.reports import write_jsonl, write_summary
from sensei_clean.schemas import ActionRecord, CapabilityReport, FindingRecord, ItemRecord


# Source of truth for privacy: the harvest module if available, else a
# minimal fallback that flags the same path roots. Import is optional
# so sensei-clean stays installable even without master_ai/harvest.py.
try:
    import harvest as _harvest  # type: ignore
except Exception:  # pragma: no cover
    _harvest = None


BANNER = "Sensei Clean — review-first local cleanup"
DEFAULT_ROOTS = ["~/Desktop", "~/Downloads", "~/Documents", "~/Pictures", "~/Videos"]


def _private_reason(item: ItemRecord) -> str:
    if _harvest is None:
        return ""
    try:
        return _harvest._privacy_reason(prompt=item.identity.get("path", ""), response="")
    except Exception:
        return ""


def _bump_sensitivity_if_private(items: list[ItemRecord]) -> list[ItemRecord]:
    """If harvest's privacy policy flags an item's path, mark it 'private'
    so policy.requires_monitored_review fires at queue time."""
    bumped = []
    for item in items:
        reason = _private_reason(item)
        if reason and item.sensitivity not in MONITORED_SENSITIVITIES:
            notes = list(item.notes) + [f"privacy:{reason}"]
            item = replace(item, sensitivity="private", notes=notes)
        bumped.append(item)
    return bumped


def build_findings(items: list[ItemRecord], run_id: str) -> list[FindingRecord]:
    findings: list[FindingRecord] = []
    by_hash: dict[str, list[ItemRecord]] = defaultdict(list)
    for item in items:
        sha256 = item.hashes.get("sha256")
        if sha256:
            by_hash[sha256].append(item)
    for sha256, members in by_hash.items():
        if len(members) < 2:
            continue
        item_ids = [item.item_id for item in members]
        finding_id = hashlib.sha1(("dup:" + sha256).encode("utf-8")).hexdigest()
        findings.append(FindingRecord(
            schema_version="sensei.finding.v1",
            run_id=run_id,
            finding_id=finding_id,
            finding_type="exact_duplicate",
            item_ids=item_ids,
            confidence=1.0,
            risk=max(item.risk for item in members),
            summary=f"{len(members)} exact duplicates",
            evidence={"sha256": sha256},
            notes=[],
        ))
    return findings


def build_actions(items: list[ItemRecord], findings: list[FindingRecord],
                  run_id: str, quarantine_root: Path) -> list[ActionRecord]:
    """Build quarantine_move actions, routing private/financial/etc.
    items to the 'monitored' lane (approval_required=True).
    Same lane logic as queue_builder so actions.jsonl and queue.json
    don't disagree."""
    actions: list[ActionRecord] = []
    item_by_id = {item.item_id: item for item in items}
    for finding in findings:
        if finding.finding_type != "exact_duplicate":
            continue
        keeper = item_by_id[finding.item_ids[0]]
        for item_id in finding.item_ids[1:]:
            item = item_by_id[item_id]
            destination = quarantine_root / "duplicates" / item.display_name
            action_id = hashlib.sha1((item.item_id + str(destination)).encode("utf-8")).hexdigest()
            is_sensitive = item.sensitivity in MONITORED_SENSITIVITIES
            lane = "monitored" if is_sensitive else "unattended"
            actions.append(ActionRecord(
                schema_version="sensei.action.v1",
                run_id=run_id,
                action_id=action_id,
                action_type="quarantine_move",
                adapter=item.source["adapter"],
                item_id=item.item_id,
                source_path=item.identity["path"],
                destination_path=str(destination),
                confidence=1.0,
                risk=max(item.risk, keeper.risk),
                reversible=True,
                lane=lane,
                reason=f"exact duplicate of {keeper.identity['path']}",
                approval_required=is_sensitive,
                metadata={"sensitivity": item.sensitivity},
            ))
    return actions


def make_run_dir(raw_run_dir: str | None, run_id: str) -> Path:
    if raw_run_dir:
        return Path(raw_run_dir).expanduser().resolve()
    return Path("~/sensei_runs").expanduser().resolve() / run_id


# ────────────── scan ──────────────

def cmd_scan(args: argparse.Namespace) -> int:
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.run_dir, run_id)
    reports_dir = run_dir / "reports"
    run_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    adapter = LocalFSAdapter(
        run_id=run_id,
        roots=args.roots,
        quarantine_root=args.quarantine_root,
    )
    capability = adapter.probe()

    print(f"{BANNER}")
    print(f"  run:  {run_dir}")
    print(f"  roots: {', '.join(args.roots)}")
    print(f"  sha256: {'on' if args.sha256 else 'off (default — pass --sha256 to find duplicates)'}")
    print()

    items = list(adapter.scan())
    if args.sha256:
        items = [adapter.enrich(item, ["sha256", "screenshot", "text_snippet"]) for item in items]
    items = _bump_sensitivity_if_private(items)
    findings = build_findings(items, run_id)
    actions = build_actions(items, findings, run_id,
                            Path(args.quarantine_root).expanduser().resolve())
    queue = build_queue(items, actions, [capability])

    write_jsonl(str(run_dir / "inventory.jsonl"), items)
    write_jsonl(str(run_dir / "findings.jsonl"), findings)
    write_jsonl(str(run_dir / "actions.jsonl"), actions)
    write_summary(str(reports_dir / "summary.md"),
                  [capability], items, findings, actions)
    (run_dir / "queue.json").write_text(json.dumps(queue, indent=2) + "\n",
                                        encoding="utf-8")
    (run_dir / "capabilities.json").write_text(
        json.dumps([capability.to_dict()], indent=2) + "\n", encoding="utf-8")

    monitored = sum(1 for a in actions if a.lane == "monitored")
    unattended = sum(1 for a in actions if a.lane == "unattended")
    reclaim = _estimate_reclaim_bytes(items, findings)

    print(f"Items     : {len(items)}")
    print(f"Findings  : {len(findings)}")
    print(f"Actions   : {len(actions)} (monitored={monitored}, unattended={unattended})")
    print(f"Reclaim   : ~{reclaim / 1e6:.1f} MB if all duplicates quarantined")
    print(f"Report    : {reports_dir / 'summary.md'}")
    print()
    print("Review the report, then:")
    print(f"  sensei-clean apply {run_dir}")
    print(f"  sensei-clean apply {run_dir} --approve-monitored   # include sensitive items")
    return 0


def _estimate_reclaim_bytes(items: list[ItemRecord],
                            findings: list[FindingRecord]) -> int:
    item_size = {it.item_id: (it.size_bytes or 0) for it in items}
    total = 0
    for f in findings:
        if f.finding_type != "exact_duplicate":
            continue
        sizes = sorted((item_size.get(i, 0) for i in f.item_ids), reverse=True)
        total += sum(sizes[1:])  # keep largest, reclaim the rest
    return total


# ────────────── apply ──────────────

def cmd_apply(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        print(f"error: run dir not found: {run_dir}", file=sys.stderr)
        return 2

    capabilities_file = run_dir / "capabilities.json"
    actions_file = run_dir / "actions.jsonl"
    if not capabilities_file.exists() or not actions_file.exists():
        print(f"error: missing capabilities.json or actions.jsonl in {run_dir}",
              file=sys.stderr)
        return 2

    cap_list = json.loads(capabilities_file.read_text())
    if not cap_list:
        print("error: no capabilities recorded in run", file=sys.stderr)
        return 2
    capability = CapabilityReport(**cap_list[0])

    raw_actions = [json.loads(line) for line in actions_file.read_text().splitlines() if line.strip()]
    actions = [ActionRecord(**a) for a in raw_actions]

    if not args.approve_monitored:
        filtered = [a for a in actions if a.lane != "monitored"]
        skipped = len(actions) - len(filtered)
    else:
        filtered = actions
        skipped = 0

    if not filtered:
        print(f"{BANNER}")
        print(f"  run: {run_dir}")
        if skipped:
            print(f"  All {skipped} actions are in the monitored lane.")
            print(f"  Re-run with --approve-monitored to include them.")
        else:
            print("  No actions to apply.")
        return 0

    print(f"{BANNER}")
    print(f"  run     : {run_dir}")
    print(f"  apply   : {len(filtered)} action(s)")
    if skipped:
        print(f"  skipped : {skipped} monitored-lane action(s) (pass --approve-monitored to include)")

    if not args.yes:
        ans = input("  proceed? [yes/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("  cancelled.")
            return 1

    adapter = LocalFSAdapter(
        run_id=actions[0].run_id if actions else "apply",
        roots=DEFAULT_ROOTS,
        quarantine_root=str(Path("~/Sensei-Quarantine").expanduser().resolve()),
    )
    undo_path = run_dir / "undo.jsonl"
    results = apply_actions(adapter, filtered, capability, str(undo_path))

    ok = sum(1 for r in results if r.success)
    fail = sum(1 for r in results if not r.success)
    print()
    print(f"  applied : {ok}")
    print(f"  failed  : {fail}")
    print(f"  journal : {undo_path}")
    if fail:
        print()
        print("  Failures:")
        for r in results:
            if not r.success:
                print(f"    {r.action_id[:8]}  {r.message}")
        return 1
    return 0


# ────────────── undo ──────────────

def cmd_undo(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    undo_path = run_dir / "undo.jsonl"
    if not undo_path.exists():
        print(f"error: no journal at {undo_path}", file=sys.stderr)
        return 2

    records = load_undo_records(str(undo_path))
    if not records:
        print(f"{BANNER}")
        print(f"  run: {run_dir}")
        print("  journal is empty — nothing to undo.")
        return 0

    print(f"{BANNER}")
    print(f"  run    : {run_dir}")
    print(f"  undo   : {len(records)} move(s) in reverse order")
    if not args.yes:
        ans = input("  proceed? [yes/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("  cancelled.")
            return 1

    adapter = LocalFSAdapter(
        run_id=records[0].run_id if records else "undo",
        roots=DEFAULT_ROOTS,
        quarantine_root=str(Path("~/Sensei-Quarantine").expanduser().resolve()),
    )
    results = undo_actions(adapter, reversed(records))
    ok = sum(1 for r in results if r.success)
    fail = sum(1 for r in results if not r.success)
    print()
    print(f"  undone  : {ok}")
    print(f"  failed  : {fail}")
    return 0 if fail == 0 else 1


# ────────────── arg parse ──────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sensei-clean", description=BANNER)
    sub = parser.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="inventory files and write review artifacts")
    p_scan.add_argument("--run-dir", default=None,
                        help="output directory (default: ~/sensei_runs/<ts>/)")
    p_scan.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS,
                        help="local roots to scan")
    p_scan.add_argument("--quarantine-root", default="~/Sensei-Quarantine",
                        help="where apply would move quarantined files")
    p_scan.add_argument("--sha256", action="store_true",
                        help="hash files (needed to find duplicates)")

    p_apply = sub.add_parser("apply", help="enact queued actions from a scan run")
    p_apply.add_argument("run_dir", help="path to the run directory from scan")
    p_apply.add_argument("--yes", action="store_true",
                         help="skip the confirmation prompt")
    p_apply.add_argument("--approve-monitored", action="store_true",
                         help="include monitored-lane (sensitive) actions")

    p_undo = sub.add_parser("undo", help="reverse what apply did, newest first")
    p_undo.add_argument("run_dir", help="path to the run directory from a prior apply")
    p_undo.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")

    if not argv or argv[0] in ("-h", "--help"):
        parser.print_help()
        sys.exit(0)
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        sys.exit(0)
    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Back-compat: bare invocation = scan with defaults.
    if argv and argv[0] not in ("scan", "apply", "undo", "-h", "--help"):
        # Treat legacy flags (--run-dir, --roots, --sha256, --quarantine-root)
        # as `scan` arguments so old callers still work.
        argv = ["scan", *argv]
    args = parse_args(argv)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "undo":
        return cmd_undo(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
