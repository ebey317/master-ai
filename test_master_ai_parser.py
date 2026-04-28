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
        self._orig_pill = master_ai._pill
        self._orig_log = master_ai.log
        self._orig_url_exists = master_ai._url_exists_with_curl
        self._orig_launch_desktop = master_ai._launch_desktop_argv
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
        master_ai._pill = lambda label, msg="": f"{label} {msg}"
        master_ai.log = lambda *args, **kwargs: None
        def _launch_desktop(argv, label="desktop app"):
            self.calls.append(("desktop", argv, label))
            return master_ai.RunResult("opened", ok=True, exit_code=0, command=" ".join(argv))
        master_ai._launch_desktop_argv = _launch_desktop

    def tearDown(self):
        master_ai.confirm_run = self._orig_run
        master_ai.confirm_runterm = self._orig_runterm
        master_ai.confirm_create = self._orig_create
        master_ai.confirm_edit = self._orig_edit
        master_ai.render_reply = self._orig_render
        master_ai._router_metric = self._orig_metric
        master_ai._pill = self._orig_pill
        master_ai.log = self._orig_log
        master_ai._url_exists_with_curl = self._orig_url_exists
        master_ai._launch_desktop_argv = self._orig_launch_desktop

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

    def test_malformed_create_requests_repair(self):
        history = []
        result = master_ai.process_reply(
            "CREATE: /tmp/master-ai-parser-test.txt\n"
            "Here is the file content in prose but no markers.",
            history,
            streamed=False,
        )
        self.assertIsNone(result)
        self.assertEqual(self.calls, [])
        self.assertIn("Directive repair", history[-1]["content"])
        self.assertIn("complete content block", history[-1]["content"])

    def test_malformed_edit_requests_repair(self):
        history = []
        result = master_ai.process_reply(
            "EDIT: /tmp/master-ai-parser-test.txt\n"
            "replace old with new",
            history,
            streamed=False,
        )
        self.assertIsNone(result)
        self.assertEqual(self.calls, [])
        self.assertIn("Directive repair", history[-1]["content"])
        self.assertIn("complete", history[-1]["content"])

    def test_thin_html_demo_requests_repair(self):
        history = [{"role": "user", "content": "build a polished HTML UI demo"}]
        result = master_ai.process_reply(
            "CREATE: /tmp/master-ai-parser-test.html\n"
            "<<<CONTENT\n"
            "<html><body><h1>Demo</h1><p>Coming soon</p></body></html>\n"
            ">>>CONTENT",
            history,
            streamed=False,
        )
        self.assertIsNone(result)
        self.assertEqual(self.calls, [])
        self.assertIn("HTML demo", history[-1]["content"])
        self.assertIn("product-demo quality bar", history[-1]["content"])

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

    def test_link_lookup_phrase_routes_to_live_search(self):
        low = "ensure it fetches accurate links not placeholders"
        words = set(low.split())
        self.assertTrue(master_ai._looks_link_lookup(low, words))

    def test_placeholder_urls_are_removed_from_search_output(self):
        text = (
            "[DuckDuckGo]\n"
            "• Fake: placeholder\n"
            "  https://example.com/download\n"
            "• Real: official page\n"
            "  https://github.com/ebey317\n"
        )
        cleaned = master_ai._filter_placeholder_links(text)
        self.assertIsNotNone(cleaned)
        self.assertNotIn("https://example.com/download", cleaned)
        self.assertIn("https://github.com/ebey317", cleaned)

    def test_all_placeholder_search_output_is_rejected(self):
        self.assertIsNone(
            master_ai._filter_placeholder_links("Use https://github.com/username/repo")
        )

    def test_direct_github_lookup_verifies_before_returning(self):
        seen = []
        def _exists(url):
            seen.append(url)
            return url == "https://github.com/ebey317"
        master_ai._url_exists_with_curl = _exists
        result = master_ai._direct_verified_link_lookup("official GitHub ebey317")
        self.assertIn("https://github.com/ebey317", result)
        self.assertIn("https://github.com/ebey317", seen)

    def test_runterm_xdg_open_redirects_to_desktop_launcher(self):
        result = self._orig_runterm("xdg-open https://github.com/ebey317")
        self.assertTrue(result.ok)
        self.assertEqual(self.calls, [("desktop", ["xdg-open", "https://github.com/ebey317"], "desktop target")])

    def test_runterm_libreoffice_redirects_to_desktop_launcher(self):
        result = self._orig_runterm("libreoffice ~/Documents/example.odt")
        self.assertTrue(result.ok)
        self.assertEqual(
            self.calls,
            [("desktop", ["libreoffice", os.path.expanduser("~/Documents/example.odt")], "desktop target")],
        )

    def test_open_libreoffice_intent_is_desktop_app(self):
        argv, label = master_ai._try_desktop_open_intent("open libre office")
        self.assertEqual(argv, ["libreoffice"])
        self.assertEqual(label, "libre office")


if __name__ == "__main__":
    unittest.main()
