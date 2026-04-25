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
        self._orig_metric = master_ai._router_metric
        def _run(cmd):
            self.calls.append(("run", cmd))
            return True
        def _runterm(cmd):
            self.calls.append(("runterm", cmd))
            return True
        def _create(path, content):
            self.calls.append(("create", path, content))
            return True
        def _edit(path, old, new):
            self.calls.append(("edit", path, old, new))
            return True
        master_ai.confirm_run = _run
        master_ai.confirm_runterm = _runterm
        master_ai.confirm_create = _create
        master_ai.confirm_edit = _edit
        master_ai.render_reply = lambda *args, **kwargs: None
        master_ai._router_metric = lambda *args, **kwargs: None

    def tearDown(self):
        master_ai.confirm_run = self._orig_run
        master_ai.confirm_runterm = self._orig_runterm
        master_ai.confirm_create = self._orig_create
        master_ai.confirm_edit = self._orig_edit
        master_ai.render_reply = self._orig_render
        master_ai._router_metric = self._orig_metric

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

    def test_failed_create_aborts_downstream_run(self):
        def _deny_create(path, content):
            self.calls.append(("create-denied", path, content))
            return False
        master_ai.confirm_create = _deny_create
        master_ai.process_reply(
            "CREATE: /tmp/master-ai-parser-test.txt\n"
            "<<<CONTENT\n"
            "hello\n"
            ">>>CONTENT\n"
            "RUN: bash /tmp/master-ai-parser-test.txt",
            [],
            streamed=False,
        )
        self.assertEqual(self.calls, [("create-denied", "/tmp/master-ai-parser-test.txt", "hello")])

    def test_failed_run_aborts_downstream_runterm(self):
        def _fail_run(cmd):
            self.calls.append(("run-failed", cmd))
            return master_ai.RunResult("boom", ok=False, exit_code=1, command=cmd)
        master_ai.confirm_run = _fail_run
        master_ai.process_reply(
            "RUN: bash -c 'exit 9'\n"
            "RUN: echo should-not-run\n"
            "RUNTERM: htop",
            [],
            streamed=False,
        )
        self.assertEqual(self.calls, [("run-failed", "bash -c 'exit 9'")])

    def test_pipefail_marks_pipeline_failure(self):
        result = master_ai.run_command("printf 'yes\\n' | grep no")
        self.assertFalse(result.ok)
        self.assertNotEqual(result.exit_code, 0)

    def test_interactive_run_is_blocked(self):
        self.assertTrue(master_ai._looks_interactive_run("grep -ri foo ~/Mail | less"))


if __name__ == "__main__":
    unittest.main()
