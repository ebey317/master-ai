"""
rclone-backed cloud adapter.

Wraps any rclone-configured remote (gdrive:, onedrive:, dropbox:, s3:,
b2:, ...) so we leverage the user's existing OAuth/auth in
~/.config/rclone/rclone.conf instead of re-implementing each provider's
SDK. rclone is treated as a stable subprocess surface; no network is
required to LIST configured remotes — only to probe quota or list
files.

# Default mode: PROBE ONLY
The instruction from this session was: "probe only account/availability
metadata first, not list private file names." This adapter honors that
explicitly. scan() yields nothing unless `list_enabled=True` is passed
at construction time. probe() runs `rclone about <remote>:` which
returns ONLY quota / account metadata — no file names, no IDs.

# Mutations
apply() and undo() are intentionally not wired. Cloud mutations need
a tested apply path on a small subset (e.g. a single quarantine folder
in the remote) before we expose them. Until then both return
success=False with a clear message.

# Tests
The rclone binary call is wrapped in `_run_rclone()`. Tests can
monkey-patch that or set SENSEI_CLEAN_RCLONE to point at a fake binary
shim so the test suite never depends on real network.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Iterator, List, Optional, Tuple

from ..schemas import AccessGrant, ActionRecord, ApplyResult, CapabilityReport, ItemRecord, UndoRecord
from .cloud_drive import CloudDriveAdapter


RCLONE_BIN_ENV = "SENSEI_CLEAN_RCLONE"
DEFAULT_TIMEOUT = 15  # seconds — network call may be slow


def _rclone_bin() -> str:
    return os.environ.get(RCLONE_BIN_ENV) or shutil.which("rclone") or "rclone"


def _run_rclone(argv: list[str], timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, str, str]:
    """Run rclone with the given args. Returns (returncode, stdout, stderr).
    Exit code 127 + empty stdout/stderr means rclone wasn't found."""
    bin_ = _rclone_bin()
    if not shutil.which(bin_):
        return 127, "", "rclone not on PATH"
    try:
        out = subprocess.run([bin_, *argv], capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout, out.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"rclone timed out after {timeout}s: {e}"
    except OSError as e:
        return 1, "", f"rclone exec failed: {e}"


def rclone_listremotes(timeout: int = 5) -> list[str]:
    """Return configured rclone remote names (without trailing colon).
    Empty list when rclone is missing or fails — never raises."""
    rc, out, _ = _run_rclone(["listremotes"], timeout=timeout)
    if rc != 0:
        return []
    return [line.rstrip(":") for line in out.splitlines() if line.endswith(":")]


def rclone_about(remote: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run `rclone about <remote>: --json` and return parsed JSON. On
    any error returns a dict with an 'error' key — never raises. Reads
    only account/quota metadata, never file names."""
    rc, out, err = _run_rclone(["about", f"{remote.rstrip(':')}:", "--json"], timeout=timeout)
    if rc != 0:
        return {"error": (err or out).strip()[:240] or f"rc={rc}"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "non-json output from rclone about"}


class RcloneRemoteAdapter(CloudDriveAdapter):
    """One adapter per rclone remote. Probe-only by default."""

    def __init__(
        self,
        run_id: str,
        remote: str,
        *,
        list_enabled: bool = False,
        path_in_remote: str = "",
    ) -> None:
        clean_remote = remote.rstrip(":")
        self.remote = clean_remote
        self.list_enabled = list_enabled
        self.path_in_remote = path_in_remote
        super().__init__(run_id=run_id, root=f"rclone:{clean_remote}:{path_in_remote}")
        # Per-instance name so action.adapter routes back to the right remote.
        self.name = f"rclone:{clean_remote}"
        self.provider_id = f"rclone-{clean_remote}"
        self.provider_label = f"rclone:{clean_remote}"

    @classmethod
    def is_configured(cls) -> bool:
        # Class-level cheap check: rclone is present and at least one
        # remote is configured. Per-instance probe verifies the specific
        # remote actually authenticates.
        return bool(shutil.which(_rclone_bin())) and bool(rclone_listremotes())

    def probe(self) -> CapabilityReport:
        blockers: list[str] = []
        if not shutil.which(_rclone_bin()):
            blockers.append("rclone-not-installed")
            account_info: dict = {}
        else:
            account_info = rclone_about(self.remote)
            if "error" in account_info:
                blockers.append(f"rclone-about-failed: {account_info['error']}")
        used = account_info.get("used")
        total = account_info.get("total")
        quota_note = (
            f"Quota: {used} used of {total} bytes"
            if isinstance(used, int) and isinstance(total, int) and total
            else "Quota unknown"
        )
        return CapabilityReport(
            adapter=self.name,
            provider=self.provider_id,
            capability="api",
            account_label=self.remote,
            root=self.root,
            available=not blockers,
            supported_actions=[],  # no mutations in this round
            blockers=blockers,
            notes=[
                f"rclone remote {self.remote!r} (uses ~/.config/rclone/rclone.conf).",
                "Probe-only: scan yields nothing unless list_enabled=True at construction.",
                "Move/delete actions are not wired yet — review/approval flow first.",
                quota_note,
            ],
        )

    def authorize(self, mode: str) -> AccessGrant:
        info = rclone_about(self.remote)
        granted = "error" not in info and bool(info)
        return AccessGrant(mode=mode, granted=granted, details={
            "provider": self.provider_id,
            "remote": self.remote,
            "rclone_about_keys": sorted(info.keys()) if info else [],
        })

    def scan(self, cursor: Optional[str] = None) -> Iterator[ItemRecord]:
        # Probe-only by default. Listing is gated behind list_enabled
        # AND not yet implemented — would call
        # `rclone lsjson <remote>:<path> --recursive --files-only --hash`
        # and yield one ItemRecord per file. Until that lands, return
        # an empty iterator so the engine treats this source as "zero
        # items right now" without crashing.
        if not self.list_enabled:
            return
            yield  # pragma: no cover — keeps generator shape
        # TODO: implement listing once a small-scope subset and the apply
        # path are reviewed. Honest state: this branch is unreachable.
        return
        yield  # pragma: no cover

    def enrich(self, item: ItemRecord, jobs: List[str]) -> ItemRecord:
        # No-op for the cloud side until listing + per-file metadata
        # fetch (hash, web view link) is wired.
        return item

    def apply(self, action: ActionRecord) -> ApplyResult:
        return ApplyResult(
            action_id=action.action_id,
            success=False,
            message=f"{self.name}: cloud mutations not wired — needs a tested apply path "
                    f"on a small remote subset first",
        )

    def undo(self, undo_record: UndoRecord) -> ApplyResult:
        return ApplyResult(
            action_id=undo_record.action_id,
            success=False,
            message=f"{self.name}: cloud undo not wired",
        )

    def open_view(self, item: ItemRecord) -> str:
        # rclone doesn't expose web view URLs uniformly. For Drive we
        # could synthesize when provider_id is populated during a future
        # listing pass. For other providers (Dropbox, OneDrive) this is
        # per-provider; leave empty until listing lands.
        return ""
