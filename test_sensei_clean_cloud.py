"""
Cloud connector contract tests for sensei_clean.

Covers:
  * FakeDriveAdapter implements the full provider contract (no network).
  * RcloneRemoteAdapter is probe-only and refuses mutations.
  * GoogleDriveAdapter stub surfaces specific not-configured blockers.
  * detect_sources surfaces rclone remotes via the cloud_api kind.
  * engine.scan_run accepts a mix of local + rclone roots and records
    the cloud capability without crashing.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from sensei_clean import connectors as _connectors
from sensei_clean.adapters.cloud_drive import CloudDriveAdapter
from sensei_clean.adapters.fake_drive import FakeDriveAdapter, FakeFile
from sensei_clean.adapters.gdrive import GoogleDriveAdapter
from sensei_clean.adapters.rclone_remote import RcloneRemoteAdapter
from sensei_clean.engine import scan_run
from sensei_clean.schemas import ActionRecord, UndoRecord


def _move_action(file_id: str) -> ActionRecord:
    return ActionRecord(
        schema_version="sensei.action.v1",
        run_id="r1",
        action_id=f"act:{file_id}",
        action_type="cloud_move",
        adapter="fake_drive",
        item_id=f"fake_drive:{file_id}",
        source_path=f"fake_drive:{file_id}",
        destination_path="Quarantine/duplicates",
        confidence=1.0,
        risk=10,
        reversible=True,
        lane="unattended",
        reason="test move",
        approval_required=False,
        metadata={"sensitivity": "documents"},
    )


class FakeDriveContractTests(unittest.TestCase):
    """Pin the cloud adapter contract via the in-memory fake."""

    def test_scan_emits_item_per_file(self):
        files = [
            FakeFile(id="a", name="invoice.pdf", mime_type="application/pdf",
                     size_bytes=10, sha256="aaaa"),
            FakeFile(id="b", name="resume.docx", mime_type="application/octet-stream",
                     size_bytes=20, sha256="bbbb"),
        ]
        adapter = FakeDriveAdapter(run_id="r1", files=files)
        items = list(adapter.scan())
        self.assertEqual(len(items), 2)
        names = sorted(i.display_name for i in items)
        self.assertEqual(names, ["invoice.pdf", "resume.docx"])
        # Resume should be flagged career-sensitive
        sensitivities = {i.display_name: i.sensitivity for i in items}
        self.assertEqual(sensitivities["resume.docx"], "career")

    def test_apply_and_undo_round_trip(self):
        f = FakeFile(id="x1", name="dup.txt", parent="root", size_bytes=5, sha256="ccc")
        adapter = FakeDriveAdapter(run_id="r1", files=[f])
        action = _move_action("x1")
        result = adapter.apply(action)
        self.assertTrue(result.success, result.message)
        self.assertEqual(adapter._files["x1"].parent, "Quarantine")
        self.assertIsNotNone(result.undo_record)
        undo_result = adapter.undo(result.undo_record)
        self.assertTrue(undo_result.success)
        self.assertEqual(adapter._files["x1"].parent, "root")

    def test_probe_reports_configured_and_supported_actions(self):
        adapter = FakeDriveAdapter(run_id="r1", files=[])
        cap = adapter.probe()
        self.assertTrue(cap.available)
        # contract: no delete action exposed even on the fake
        self.assertIn("cloud_move", cap.supported_actions)
        self.assertNotIn("cloud_delete", cap.supported_actions)

    def test_open_view_returns_provider_link(self):
        f = FakeFile(id="vp", name="x.pdf", web_view_link="https://example.test/x")
        adapter = FakeDriveAdapter(run_id="r1", files=[f])
        item = next(adapter.scan())
        self.assertEqual(adapter.open_view(item), "https://example.test/x")

    def test_can_apply_refuses_unknown_action_type(self):
        adapter = FakeDriveAdapter(run_id="r1", files=[])
        weird = _move_action("z")
        # Mutate to an unsupported action type — must be refused.
        from dataclasses import replace
        weird = replace(weird, action_type="cloud_delete")
        self.assertFalse(adapter.can_apply(weird))
        result = adapter.apply(weird)
        self.assertFalse(result.success)


class RcloneRemoteProbeOnlyTests(unittest.TestCase):
    """RcloneRemoteAdapter must default to probe-only: scan yields
    nothing, apply/undo refuse with clear messages."""

    def _stub_rclone(self, listremotes_return, about_return):
        return mock.patch.multiple(
            "sensei_clean.adapters.rclone_remote",
            rclone_listremotes=mock.Mock(return_value=listremotes_return),
            rclone_about=mock.Mock(return_value=about_return),
        )

    def test_scan_default_is_empty(self):
        with self._stub_rclone(["gdrive"], {"used": 100, "total": 1000}):
            adapter = RcloneRemoteAdapter(run_id="r1", remote="gdrive")
            self.assertEqual(list(adapter.scan()), [])

    def test_probe_surfaces_quota_when_about_succeeds(self):
        with self._stub_rclone(["gdrive"], {"used": 500, "total": 9999}):
            adapter = RcloneRemoteAdapter(run_id="r1", remote="gdrive")
            cap = adapter.probe()
            self.assertTrue(cap.available)
            joined = "\n".join(cap.notes)
            self.assertIn("500 used of 9999 bytes", joined)

    def test_probe_blockers_when_about_fails(self):
        with self._stub_rclone(["gdrive"], {"error": "token refresh failed"}):
            adapter = RcloneRemoteAdapter(run_id="r1", remote="gdrive")
            cap = adapter.probe()
            self.assertFalse(cap.available)
            self.assertTrue(any("rclone-about-failed" in b for b in cap.blockers))

    def test_apply_refuses_with_clear_message(self):
        with self._stub_rclone(["gdrive"], {"used": 0, "total": 1}):
            adapter = RcloneRemoteAdapter(run_id="r1", remote="gdrive")
            action = _move_action("anything")
            from dataclasses import replace
            action = replace(action, adapter=adapter.name)
            result = adapter.apply(action)
            self.assertFalse(result.success)
            self.assertIn("not wired", result.message)


class GoogleDriveStubTests(unittest.TestCase):
    """The google-api-python-client path is intentionally a stub.
    Probe must report the specific missing-piece signal."""

    def test_probe_surfaces_missing_deps_or_client(self):
        adapter = GoogleDriveAdapter(run_id="r1")
        cap = adapter.probe()
        # We're not running this on a box with the libs + client + token
        # all wired — at least one of those blockers must fire.
        self.assertFalse(cap.available)
        self.assertTrue(cap.blockers, "expected at least one blocker on the stub")
        joined = " ".join(cap.blockers)
        # one of these specific signals must be in the blockers
        self.assertTrue(
            any(tag in joined for tag in (
                "gdrive-missing-deps", "gdrive-missing-client-secret",
                "gdrive-not-authorized",
            )),
            f"expected a gdrive-specific blocker, got: {cap.blockers}",
        )

    def test_apply_refuses_until_configured(self):
        adapter = GoogleDriveAdapter(run_id="r1")
        action = _move_action("g")
        from dataclasses import replace
        action = replace(action, adapter="gdrive")
        result = adapter.apply(action)
        self.assertFalse(result.success)
        self.assertIn("not configured", result.message)


class ConnectorsDiscoveryTests(unittest.TestCase):
    """detect_sources must surface rclone remotes as cloud_api kind."""

    def test_rclone_remotes_appear_with_cloud_api_kind(self):
        with TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            # Stub rclone_listremotes to return 2 remotes so we don't
            # depend on the test box having rclone configured.
            with mock.patch(
                "sensei_clean.connectors._rclone_connectors",
                return_value=[
                    _connectors.SourceConnector(
                        connector_id="rclone_gdrive",
                        label="gdrive (rclone)",
                        path="rclone:gdrive:",
                        kind="cloud_api",
                        available=True,
                        notes=("real cloud API connector via rclone",),
                    ),
                ],
            ):
                sources = _connectors.detect_sources(
                    home=home, gvfs_root=home / "gvfs", media_root=home / "media",
                )
        kinds = {s.kind for s in sources}
        self.assertIn("cloud_api", kinds)
        cloud = [s for s in sources if s.kind == "cloud_api"]
        self.assertTrue(any(c.path.startswith("rclone:") for c in cloud))


class EngineMultiAdapterTests(unittest.TestCase):
    """scan_run must accept a mix of local and rclone roots and record
    a capability for each, without crashing on the cloud side even when
    rclone is mocked-out."""

    def test_local_plus_cloud_root_records_both_capabilities(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Local").mkdir()
            (root / "Local" / "a.txt").write_text("hi", encoding="utf-8")
            run_dir = root / "run"
            with mock.patch(
                "sensei_clean.adapters.rclone_remote.rclone_listremotes",
                return_value=["gdrive"],
            ), mock.patch(
                "sensei_clean.adapters.rclone_remote.rclone_about",
                return_value={"used": 100, "total": 1000},
            ), mock.patch(
                "sensei_clean.adapters.rclone_remote.shutil.which",
                return_value="/usr/bin/rclone",
            ):
                run_path, caps, items, findings, actions = scan_run(
                    roots=[str(root / "Local"), "rclone:gdrive:"],
                    sha256=False,
                    quarantine_root=str(root / "Q"),
                    run_dir=str(run_dir),
                )
        # Local items present, cloud probe-only yields nothing
        self.assertGreaterEqual(len(items), 1)
        cap_providers = {c.provider for c in caps}
        self.assertIn("local", cap_providers)
        self.assertTrue(any(p.startswith("rclone-") for p in cap_providers))


if __name__ == "__main__":
    unittest.main()
