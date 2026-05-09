#!/usr/bin/env python3
"""Offline regression tests for Master AI directive parsing.

These tests monkeypatch action handlers, so they never run shell commands,
open terminals, or write requested CREATE/EDIT targets.
"""
import os
import sys
import unittest
from pathlib import Path

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

    def test_auto_context_codex_md_alias_reads_claude_handoff(self):
        inject_ctx, meta = master_ai.auto_inject_context("read whole file Codex.md")
        self.assertIn("/home/elijah/scripts/CLAUDE.md", inject_ctx)
        self.assertTrue(meta["whole_file_requested"])

    def test_local_read_target_resolves_codex_possessive_md(self):
        target = master_ai._resolve_local_text_target("codex's md")
        self.assertEqual(str(target), "/home/elijah/scripts/CLAUDE.md")

    def test_local_read_target_resolves_codex_memory_alias(self):
        target = master_ai._resolve_local_text_target("~/scripts/codex_memory.md")
        self.assertEqual(str(target), "/home/elijah/scripts/CLAUDE.md")

    def test_matrix_credit_screen_is_tool_required(self):
        self.assertTrue(master_ai._is_tool_required("make a matrix credit screen"))

    def test_matrix_credit_screen_routes_to_local_tool_lane(self):
        decision = master_ai.orchestrate([], "make a matrix credit screen")
        self.assertEqual(decision["route"], "local")
        self.assertEqual(decision["model"], master_ai.MODELS["master"])
        self.assertIn("tool-required", decision["reason"])

    def test_imaginative_terminal_build_is_tool_required(self):
        self.assertTrue(master_ai._is_tool_required("make a neon dragon fly across the terminal"))

    def test_imaginative_game_build_routes_to_local_tool_lane(self):
        decision = master_ai.orchestrate([], "create an interactive gravity toy")
        self.assertEqual(decision["route"], "local")
        self.assertEqual(decision["model"], master_ai.MODELS["master"])
        self.assertIn("tool-required", decision["reason"])

    def test_plain_non_code_make_request_is_not_tool_required(self):
        self.assertFalse(master_ai._is_tool_required("make me a list of dinner ideas"))

    def test_big_markdown_without_scope_asks_before_model(self):
        orig_auto_context = master_ai.auto_inject_context
        orig_orchestrate = master_ai.orchestrate
        try:
            master_ai.auto_inject_context = lambda *args, **kwargs: (
                "\n\n[AUTO-CONTEXT]\n--- /tmp/big.md (250 lines) -- name mentioned ---",
                {
                    "big_file_no_symbol_match": [Path("/tmp/big.md")],
                    "whole_file_requested": False,
                    "inject_chars": 72,
                    "sliced": [],
                },
            )

            def _unexpected_orchestrate(*args, **kwargs):
                raise AssertionError("large unscoped file should ask before model routing")

            master_ai.orchestrate = _unexpected_orchestrate
            history = []
            result = master_ai.handle("read big.md", history)
        finally:
            master_ai.auto_inject_context = orig_auto_context
            master_ai.orchestrate = orig_orchestrate

        self.assertIn("Which heading", result)
        self.assertIn("whole file", result)
        self.assertEqual(history[-1]["content"], result)

    def test_plain_cloud_route_dispatches_to_orchestrator_provider(self):
        # When orchestrate() returns route='cloud' + a specific provider model,
        # handle() must honor it and call ask_cloud(provider=<that model>).
        # Without this branch, detect_route() can override and route the turn
        # through Ollama's qwen3.5:cloud lane — exactly the bug the orchestrator
        # decision was trying to avoid.
        orig_orchestrate = master_ai.orchestrate
        orig_detect_route = master_ai.detect_route
        orig_ask_cloud = master_ai.ask_cloud
        orig_ask_local_stream = master_ai.ask_local_stream
        orig_thinking_start = master_ai.local_thinking_start
        orig_thinking_stop = master_ai.local_thinking_stop
        orig_git_context = master_ai.git_context
        orig_load_memory = master_ai.load_memory
        orig_load_behavior = master_ai.load_behavior
        orig_auto_context = master_ai.auto_inject_context
        captured = []
        try:
            master_ai.orchestrate = lambda history, user_text, image_path=None: {
                "route": "cloud",
                "model": "fireworks",
                "reason": "scored -> Fireworks",
            }
            master_ai.detect_route = lambda text, has_image=False: (
                "local", master_ai.MODELS["qwen3"], "would have downgraded to qwen3.5:cloud",
            )
            master_ai.ask_local_stream = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("plain cloud route must NOT fall through to ask_local_stream"),
            )
            def _fake_cloud(messages, provider=None):
                captured.append(provider)
                return "ok via Fireworks."
            master_ai.ask_cloud = _fake_cloud
            master_ai.local_thinking_start = lambda: None
            master_ai.local_thinking_stop = lambda handle: None
            master_ai.git_context = lambda: ""
            master_ai.load_memory = lambda: ""
            master_ai.load_behavior = lambda: ""
            master_ai.auto_inject_context = lambda *args, **kwargs: (
                "", {"big_file_no_symbol_match": [], "whole_file_requested": False,
                     "inject_chars": 0, "sliced": []},
            )
            history = []
            result = master_ai.handle("explain this thing", history)
        finally:
            master_ai.orchestrate = orig_orchestrate
            master_ai.detect_route = orig_detect_route
            master_ai.ask_cloud = orig_ask_cloud
            master_ai.ask_local_stream = orig_ask_local_stream
            master_ai.local_thinking_start = orig_thinking_start
            master_ai.local_thinking_stop = orig_thinking_stop
            master_ai.git_context = orig_git_context
            master_ai.load_memory = orig_load_memory
            master_ai.load_behavior = orig_load_behavior
            master_ai.auto_inject_context = orig_auto_context

        self.assertEqual(result, "ok via Fireworks.")
        self.assertEqual(captured, ["fireworks"])


if __name__ == "__main__":
    unittest.main()
