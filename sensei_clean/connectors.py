from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SourceConnector:
    connector_id: str
    label: str
    path: str
    kind: str
    available: bool
    notes: tuple[str, ...] = ()

    def to_choice(self) -> tuple[str, str]:
        suffix = "" if self.available else " (not found)"
        note = f" - {'; '.join(self.notes)}" if self.notes else ""
        return self.path, f"{self.label}{suffix}  ({self.path}){note}"


def _xdg_dir(name: str, fallback: Path, *, home: Path) -> Path:
    user_dirs = home / ".config" / "user-dirs.dirs"
    if not user_dirs.exists():
        return fallback
    try:
        for line in user_dirs.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line.startswith(f"XDG_{name}_DIR="):
                continue
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            raw = raw.replace("$HOME", str(home))
            return Path(raw).expanduser().resolve()
    except Exception:
        return fallback
    return fallback


def _home_folder_connectors(home: Path) -> list[SourceConnector]:
    specs = [
        ("downloads", "Downloads", "DOWNLOAD", "local", "most common cleanup target"),
        ("desktop", "Desktop", "DESKTOP", "local", "customer-visible files"),
        ("documents", "Documents", "DOCUMENTS", "local", "sensitive: asks for approval"),
        ("pictures", "Pictures", "PICTURES", "local", "sensitive: asks for approval"),
        ("videos", "Videos", "VIDEOS", "local", "sensitive: asks for approval"),
        ("music", "Music", "MUSIC", "local", "media"),
    ]
    out: list[SourceConnector] = []
    for cid, label, xdg, kind, note in specs:
        default = home / label
        path = _xdg_dir(xdg, default, home=home)
        out.append(SourceConnector(
            connector_id=cid,
            label=label,
            path=str(path),
            kind=kind,
            available=path.exists() and path.is_dir(),
            notes=(note,),
        ))
    return out


def _synced_folder_connectors(home: Path) -> list[SourceConnector]:
    candidates = [
        ("google_drive", "Google Drive", ["Google Drive", "GoogleDrive", "Drive"]),
        ("onedrive", "OneDrive", ["OneDrive", "OneDrive - Personal", "OneDrive - Business", "OneDrive - Work"]),
        ("dropbox", "Dropbox", ["Dropbox"]),
        ("nextcloud", "Nextcloud", ["Nextcloud"]),
        ("icloud", "iCloud Drive", ["iCloud Drive", "iCloudDrive"]),
        ("syncthing", "Syncthing", ["Sync", "Syncthing"]),
    ]
    out: list[SourceConnector] = []
    for cid, label, names in candidates:
        for name in names:
            path = home / name
            if path.exists() and path.is_dir():
                out.append(SourceConnector(
                    connector_id=cid,
                    label=label,
                    path=str(path),
                    kind="synced_cloud_folder",
                    available=True,
                    notes=("local sync folder", "not OAuth/API"),
                ))
    try:
        for child in home.iterdir():
            if child.is_dir() and child.name.startswith("OneDrive"):
                out.append(SourceConnector(
                    connector_id="onedrive",
                    label="OneDrive",
                    path=str(child),
                    kind="synced_cloud_folder",
                    available=True,
                    notes=("local sync folder", "not OAuth/API"),
                ))
    except Exception:
        pass
    return _dedupe(out)


def _rclone_connectors() -> list[SourceConnector]:
    """Discover configured rclone remotes (gdrive:, onedrive:, dropbox:, ...).
    The remote being LISTED here does not imply it is currently
    authenticated — that's the adapter's probe() job. Listing only reads
    ~/.config/rclone/rclone.conf via `rclone listremotes`."""
    try:
        from .adapters.rclone_remote import rclone_listremotes
    except Exception:
        return []
    try:
        remotes = rclone_listremotes()
    except Exception:
        remotes = []
    out: list[SourceConnector] = []
    for r in remotes:
        out.append(SourceConnector(
            connector_id=f"rclone_{r}",
            label=f"{r} (rclone)",
            path=f"rclone:{r}:",
            kind="cloud_api",
            available=True,  # listed; live auth is a separate probe
            notes=(
                "real cloud API connector via rclone",
                "probe-only this round — listing/mutations not wired yet",
            ),
        ))
    return out


def _android_connectors(*, gvfs_root: Path, media_root: Path) -> list[SourceConnector]:
    out: list[SourceConnector] = []
    if gvfs_root.exists():
        try:
            for child in gvfs_root.iterdir():
                name = child.name.lower()
                if "mtp" in name or "android" in name:
                    out.append(SourceConnector(
                        connector_id="android_mtp",
                        label="Android device",
                        path=str(child),
                        kind="android_mounted_storage",
                        available=True,
                        notes=("mounted MTP storage",),
                    ))
        except Exception:
            pass
    if media_root.exists():
        try:
            for child in media_root.iterdir():
                if child.is_dir():
                    out.append(SourceConnector(
                        connector_id="removable_media",
                        label="Removable/media storage",
                        path=str(child),
                        kind="removable_storage",
                        available=True,
                        notes=("mounted local storage",),
                    ))
        except Exception:
            pass
    return out


def _dedupe(connectors: Iterable[SourceConnector]) -> list[SourceConnector]:
    seen: set[tuple[str, str]] = set()
    out: list[SourceConnector] = []
    for conn in connectors:
        key = (conn.connector_id, conn.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(conn)
    return out


def detect_sources(
    *,
    home: Path | None = None,
    gvfs_root: Path | None = None,
    media_root: Path | None = None,
) -> list[SourceConnector]:
    home = (home or Path.home()).expanduser().resolve()
    uid = os.getuid()
    gvfs_root = gvfs_root or Path(f"/run/user/{uid}/gvfs")
    media_root = media_root or (Path("/media") / os.environ.get("USER", "user"))
    return _dedupe(
        _home_folder_connectors(home)
        + _synced_folder_connectors(home)
        + _android_connectors(gvfs_root=gvfs_root, media_root=media_root)
        + _rclone_connectors()
    )

