#!/usr/bin/env python3
"""Focused tests for Chrome extension Phases 7-10 support code."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["SENSEI_TUI"] = "0"
sys.path.insert(0, os.path.expanduser("~/scripts"))

import subagent_registry as sr  # noqa: E402
import typed_actions as ta  # noqa: E402
import sensei_native_host as nh  # noqa: E402
import stt_server  # noqa: E402


AX_TREE = {
    "buttons": [
        {"ref": "r-1", "role": "button", "name": "Submit application", "selector": "#submit"},
        {"ref": "r-2", "role": "button", "name": "Send my resume in", "selector": "#send"},
        {"ref": "r-3", "role": "button", "name": "Apply now", "selector": "#apply"},
        {"ref": "r-4", "role": "button", "name": "Cancel", "selector": "#cancel"},
    ],
    "inputs": [
        {"ref": "r-5", "role": "textbox", "name": "Email address", "selector": "#email"},
    ],
}


class SemanticFindTests(unittest.TestCase):
    def test_find_subagent_matches_paraphrased_apply_controls(self):
        result = sr.run("find", "apply button", context={"ax_tree": AX_TREE})
        names = [m["name"] for m in result["matches"][:3]]
        self.assertIn("Apply now", names)
        self.assertTrue(any(name in names for name in ("Submit application", "Send my resume in")))

    def test_tool_find_endpoint_helper_normalizes_shape(self):
        result = stt_server._tool_find({"query": "send resume", "ax_tree": AX_TREE})
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["matches"]), 20)
        self.assertTrue(any(m["ref"] == "r-2" for m in result["matches"]))


class WorkflowDescribeTests(unittest.TestCase):
    def test_workflow_describer(self):
        result = stt_server._tool_describe_step({
            "step": {"kind": "BROWSER_FILL", "target": "#email", "value": "elijah@example.com"}
        })
        self.assertTrue(result["ok"])
        self.assertIn("Fill", result["description"])


class RemoteMcpTypedActionTests(unittest.TestCase):
    def test_remote_mcp_parses_as_typed_action(self):
        action = ta.parse_directive('REMOTE_MCP: {"server":"demo","method":"tools/list","params":{}}')
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "REMOTE_MCP")
        self.assertTrue(action.requires_confirm)
        self.assertEqual(action.risk, ta.Risk.SAFE)


class NativeHostTests(unittest.TestCase):
    def test_ping_pong(self):
        self.assertEqual(nh.handle_message({"type": "ping", "id": "1"}), {
            "type": "pong", "id": "1", "ok": True
        })

    def test_tool_request_refuses_missing_token(self):
        with tempfile.TemporaryDirectory() as td:
            old = nh.TOKEN_PATH
            try:
                nh.TOKEN_PATH = str(Path(td) / "token")
                Path(nh.TOKEN_PATH).write_text("secret", encoding="utf-8")
                result = nh.handle_message({
                    "type": "tool_request",
                    "id": "2",
                    "payload": {"endpoint": "/health"},
                })
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "auth_failed")
            finally:
                nh.TOKEN_PATH = old

    def test_tool_request_refuses_eval_payload(self):
        with tempfile.TemporaryDirectory() as td:
            old = nh.TOKEN_PATH
            try:
                nh.TOKEN_PATH = str(Path(td) / "token")
                Path(nh.TOKEN_PATH).write_text("secret", encoding="utf-8")
                result = nh.handle_message({
                    "type": "tool_request",
                    "id": "3",
                    "token": "secret",
                    "payload": {"endpoint": "/tool/find", "eval": "1+1"},
                })
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "eval_refused")
            finally:
                nh.TOKEN_PATH = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
