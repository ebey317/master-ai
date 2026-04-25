#!/usr/bin/env python3
"""Offline regression tests for Master AI directive parsing.

These tests monkeypatch action handlers, so they never run shell commands,
open terminals, or write requested CREATE/EDIT targets.
"""
import os
import sys
import unittest

os.environ["SENSEI_TUI"] = "0"
sys.path.insert(0, os.path.expanduser("~/scripts"))

import master_ai  # noqa: E402


class DirectiveParserTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig_run = master_ai.confirm_run
        self._orig_runterm = master_ai.confirm_runterm
        self._orig_create = master_ai.confirm_create
        self._orig_edit = master_ai.confirm_edit
        self._orig_render = master_ai.render_reply
        master_ai.confirm_run = lambda cmd: self.calls.append(("run", cmd))
        master_ai.confirm_runterm = lambda cmd: self.calls.append(("runterm", cmd))
        master_ai.confirm_create = lambda path, content: self.calls.append(("create", path, content))
        master_ai.confirm_edit = lambda path, old, new: self.calls.append(("edit", path, old, new))
        master_ai.render_reply = lambda *args, **kwargs: None

    def tearDown(self):
        master_ai.confirm_run = self._orig_run
        master_ai.confirm_runterm = self._orig_runterm
        master_ai.confirm_create = self._orig_create
        master_ai.confirm_edit = self._orig_edit
        master_ai.render_reply = self._orig_render

    def test_run_directive_is_case_insensitive(self):
        master_ai.process_reply("run: echo hi", [], streamed=False)
        self.assertEqual(self.calls, [("run", "echo hi")])

    def test_inline_run_directive_is_extracted_once(self):
        master_ai.process_reply("Reason first. RUN: echo hi", [], streamed=False)
        self.assertEqual(self.calls, [("run", "echo hi")])

    def test_runterm_directive_is_case_insensitive(self):
        master_ai.process_reply("runterm: htop", [], streamed=False)
        self.assertEqual(self.calls, [("runterm", "htop")])

    def test_create_markers_are_case_insensitive(self):
        master_ai.process_reply(
            "create: /tmp/master-ai-parser-test.txt\n"
            "<<<content\n"
            "hello\n"
            ">>>content",
            [],
            streamed=False,
        )
        self.assertEqual(self.calls, [("create", "/tmp/master-ai-parser-test.txt", "hello")])

    def test_edit_markers_are_case_insensitive(self):
        master_ai.process_reply(
            "edit: /tmp/master-ai-parser-test.txt\n"
            "<<<find\n"
            "old\n"
            ">>>find\n"
            "<<<replace\n"
            "new\n"
            ">>>replace",
            [],
            streamed=False,
        )
        self.assertEqual(self.calls, [("edit", "/tmp/master-ai-parser-test.txt", "old", "new")])


if __name__ == "__main__":
    unittest.main()
