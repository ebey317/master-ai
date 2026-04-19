"""Sensei full-screen TUI shell (v1.8).

Stationary bottom "input station":
  ┌─ ✏ label ──────────────────────────────┐
  │ 🥷  cursor lives here, text wraps      │
  │ hub · help · tips · model · mode plan  │  (blue legend)
  │ 💭 rotating tip while idle             │
  └─────────────────────────────────────────┘

Everything else — AI replies, status line, scrollable history — overlays /
moves above this fixed box. The input area never shifts, so the cursor is
ALWAYS right after the ninja.

Public API (used by master_ai.py):
    app = SenseiApp()
    app.set_label("thread-name")
    app.set_status("MODE:SAFE  │  MODEL:AUTO  │  MEM:42")
    app.write(text_with_ansi)          # append to output region
    app.run(on_submit=handler)         # blocks until user exits
    app.run_in_terminal(lambda: ...)   # suspend for classic input()
    app.scroll("up" | "down" | "top" | "bottom")
    app.exit()                         # clean shutdown
"""
from __future__ import annotations

import itertools
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import has_focus
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer, Float, FloatContainer, HSplit, Window, WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea


HISTORY_FILE = str(Path.home() / ".master_ai_history")

COMPLETER_WORDS: List[str] = [
    "hub", "menu", "home", "help", "tips", "model", "model auto",
    "mode safe", "mode plan", "mode auto", "mode",
    "memory", "remember:", "forget:",
    "task", "task add", "task list", "task done", "task clear", "tasks",
    "save session", "load summary", "load session",
    "clear", "clear history", "clear cache", "clear approved", "clear chats", "chats",
    "refresh", "reload", "restart", "kick",
    "up", "down", "top", "bottom", "last",
    "projects", "apps", "autotips", "slideshow", "tour", "keys", "approved",
    "cache", "perms", "tutorial", "hints on", "hints off",
    "tts on", "tts off", "tts", "hints", "project",
    "search", "dl", "gdrive",
    "git", "git status", "git diff", "git log", "git commit",
    "go", "cancel", "accessibility", "x", "e", "resize",
]

LEGEND_WORDS = [
    "hub", "help", "tips", "model", "mode plan", "chats", "tts",
    "e=edit label", "x=exit",
]

IDLE_TIPS = [
    "type 'hub' for the full command menu",
    "'mode plan' previews commands before they run",
    "'chats' to browse saved sessions",
    "'up' / 'down' scrolls output; 'top' / 'bottom' jumps",
    "'refresh' soft-reloads the engine",
    "'e' edits this thread's label",
    "'model' switches the active AI model",
    "'tts on' speaks replies out loud (Piper voice)",
    "'remember: <fact>' saves a fact across all sessions",
    "'mode auto' runs commands without asking — disclaimer pops up first",
    "'kick' force-restarts if things are stuck",
]


class _TUIStdout:
    """Replacement for sys.stdout that writes to the TUI's output buffer.
    Every write is defensively try/excepted — a raise from here would take
    down the worker thread and silently exit the app."""
    def __init__(self, app: "SenseiApp", original):
        self._app = app
        self._original = original
        self._buf = ""

    def write(self, s):
        try:
            if not s:
                return 0
            self._buf += s
            if "\n" in self._buf or len(self._buf) >= 256:
                self._app.write(self._buf)
                self._buf = ""
            return len(s)
        except Exception:
            try: self._original.write(s)
            except Exception: pass
            return len(s) if s else 0

    def flush(self):
        try:
            if self._buf:
                self._app.write(self._buf)
                self._buf = ""
        except Exception:
            pass

    def isatty(self):
        return True

    def fileno(self):
        try: return self._original.fileno()
        except Exception: return -1


class SenseiApp:
    def __init__(self) -> None:
        self._label = ""
        self._status = ""
        self._output_chunks: List[str] = []
        self._output_lock = threading.Lock()
        self._tip_cycle = itertools.cycle(IDLE_TIPS)
        self._tip = next(self._tip_cycle)
        self._tip_last = time.time()
        self._tip_interval = 30.0  # rotate every 30s (was 5s)

        # Thinking-mode state: when the AI is generating, we rotate a different
        # set of narrative lines in the tip slot every 1.8s.
        self._thinking = False
        self._thinking_cycle = itertools.cycle([
            "Grinding...", "Pushing through...", "In deep meditation...",
            "Leveling up...", "Getting to the goal...", "Ninja-ing...",
            "Doing what ninjas do...",
        ])
        self._thinking_line = "Grinding..."
        self._thinking_last = 0.0
        self._thinking_interval = 1.8
        self._scroll_offset = 0  # lines scrolled up from bottom

        self._input = TextArea(
            prompt="🥷  ",
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
            height=Dimension(min=3, max=8, preferred=3),
            history=FileHistory(HISTORY_FILE),
            completer=WordCompleter(
                COMPLETER_WORDS, ignore_case=True,
                match_middle=False, sentence=True,
            ),
            complete_while_typing=False,
            focusable=True,
            # User-typed text stays the terminal's default color — no blue.
            style="class:textinput",
        )

        self._output_control = FormattedTextControl(
            text=self._render_output,
            focusable=False,
            show_cursor=False,
            get_cursor_position=self._get_output_cursor,
        )
        self._output_window = Window(
            content=self._output_control,
            wrap_lines=True,
            always_hide_cursor=True,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )

        self._status_control = FormattedTextControl(text=self._render_status)
        self._status_window = Window(
            content=self._status_control,
            height=1,
            align=WindowAlign.RIGHT,
            style="class:status",
        )

        self._legend_control = FormattedTextControl(text=self._render_legend)
        self._legend_window = Window(
            content=self._legend_control, height=1, style="class:legend",
        )

        self._tip_control = FormattedTextControl(text=self._render_tip)
        self._tip_window = Window(
            content=self._tip_control, height=1, style="class:tip",
        )

        # Tip sits ABOVE the ninja inside the frame — same "text area",
        # always visible next to the input like original classic mode.
        input_stack = HSplit([
            self._tip_window,
            self._input,
            self._legend_window,
        ])

        self._frame = Frame(input_stack, title=self._render_label,
                            style="class:frame")

        # Persistent "MASTER AI" header — single blue line pinned at the top
        # so the brand is always visible even when chat output scrolls.
        self._header_control = FormattedTextControl(
            text=lambda: FormattedText([
                ("class:header", " 🥷  MASTER  AI  —  SENSEI "),
            ])
        )
        self._header_window = Window(
            content=self._header_control, height=1,
            align=WindowAlign.CENTER, style="class:header",
        )

        root = HSplit([
            self._header_window,
            self._status_window,
            self._output_window,
            self._frame,
        ])

        self._on_submit: Optional[Callable[[str], None]] = None

        self._app = Application(
            layout=Layout(root, focused_element=self._input),
            key_bindings=self._build_keys(),
            full_screen=True,
            # Mouse OFF by default — keeps the input box truly locked at
            # bottom and lets gnome-terminal handle native click-drag copy.
            # Opt-in with SENSEI_MOUSE=1 if you want wheel scroll inside the app.
            mouse_support=os.environ.get("SENSEI_MOUSE", "0") == "1",
            refresh_interval=1.0,
            style=Style.from_dict({
                "status":      "#2266cc bold",
                "frame":       "#2266cc bold",
                "frame.label": "#2266cc bold",
                "legend":      "#2266cc",
                "sep":         "#999999",
                "tip":         "#1a7a3a italic bold",   # warmer: forest green on light bg
                "thinking":    "#c7761a bold",           # amber — clearly distinct from idle tip
                "textinput":   "#ffffff noinherit",      # white typed text, no cascade from frame
                "header":      "bg:#2266cc #ffffff bold", # brand header: blue bg, white text
            }),
        )

    # ── rendering callbacks ────────────────────────────────────

    def _render_output(self):
        """Return the FULL output as ANSI — scroll is handled by positioning
        an invisible cursor that Window tracks (see _get_output_cursor)."""
        with self._output_lock:
            text = "".join(self._output_chunks)
        return ANSI(text)

    def _get_output_cursor(self):
        """Invisible cursor that Window auto-scrolls to keep visible.
        - scroll_offset == 0 → cursor at bottom of buffer → Window shows latest
        - scroll_offset  > 0 → cursor N lines above bottom → Window shows N back
        """
        with self._output_lock:
            text = "".join(self._output_chunks)
        total = text.count("\n")
        y = max(0, total - self._scroll_offset)
        return Point(x=0, y=y)

    def _render_status(self):
        return FormattedText([("class:status", f" {self._status} ")])

    def _render_label(self):
        lbl = f" ✏ {self._label} " if self._label else " ✏ "
        return FormattedText([("class:frame.label", lbl)])

    def _render_label_with_tip(self):
        """Frame title: label + rotating tip, inline with the ninja's frame.
        One line, always visible, doesn't scroll away."""
        lbl = f" ✏ {self._label} " if self._label else " ✏ "
        # Freeze rotation while user is typing
        typing = bool(self._input.text)
        if not typing:
            now = time.time()
            if now - self._tip_last >= self._tip_interval:
                self._tip = next(self._tip_cycle)
                self._tip_last = now
        return FormattedText([
            ("class:frame.label", lbl),
            ("class:tip", f"  💭 {self._tip} "),
        ])

    def _render_legend(self):
        parts = []
        for i, w in enumerate(LEGEND_WORDS):
            if i:
                parts.append(("class:sep", " · "))
            parts.append(("class:legend", w))
        return FormattedText(parts)

    def _render_tip(self):
        """Tip line has three states:
          - typing    → empty (disappears completely)
          - thinking  → '🥷 [thinking] <rotating>' every 1.8s
          - idle      → '💭 <rotating hint>' every 30s
        """
        typing = bool(self._input.text)
        if typing:
            return FormattedText([])
        now = time.time()
        if self._thinking:
            if now - self._thinking_last >= self._thinking_interval:
                self._thinking_line = next(self._thinking_cycle)
                self._thinking_last = now
            return FormattedText([
                ("class:thinking", f"🥷 [thinking] {self._thinking_line}"),
            ])
        if now - self._tip_last >= self._tip_interval:
            self._tip = next(self._tip_cycle)
            self._tip_last = now
        return FormattedText([("class:tip", f"💭 {self._tip}")])

    # ── key bindings ───────────────────────────────────────────

    def _build_keys(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter", filter=has_focus(self._input))
        def _submit(event):
            text = self._input.text.rstrip("\n")
            self._input.text = ""
            self._scroll_offset = 0
            # Echo the user's message into the chat scrollback so they can
            # scroll up later and reference what they asked.
            if text:
                self.write(f"\n\033[1m> {text}\033[0m\n")
            if self._on_submit:
                # run handler in worker so the app keeps repainting
                t = threading.Thread(
                    target=self._safe_dispatch, args=(text,), daemon=True,
                )
                t.start()

        @kb.add("escape", "enter", filter=has_focus(self._input))
        def _newline(event):
            self._input.buffer.insert_text("\n")

        @kb.add("c-c")
        def _sigint(event):
            # Let the handler decide — we mark the input as empty submit
            # so master_ai.py's save-on-exit runs.
            if self._on_submit:
                threading.Thread(
                    target=self._safe_dispatch, args=("x",), daemon=True,
                ).start()
            else:
                event.app.exit()

        @kb.add("pageup")
        def _pgup(event):
            self._scroll_offset += 10
            event.app.invalidate()

        @kb.add("pagedown")
        def _pgdn(event):
            self._scroll_offset = max(0, self._scroll_offset - 10)
            event.app.invalidate()

        @kb.add("c-home")
        def _home(event):
            self._scroll_offset = 10_000
            event.app.invalidate()

        @kb.add("c-end")
        def _end(event):
            self._scroll_offset = 0
            event.app.invalidate()

        return kb

    def _safe_dispatch(self, text: str) -> None:
        try:
            if self._on_submit:
                self._on_submit(text)
        except SystemExit:
            try: self._app.exit()
            except Exception: pass
        except Exception as e:
            self.write(f"\n[tui handler error: {e}]\n")

    # ── public API ─────────────────────────────────────────────

    def start_thinking(self) -> None:
        """Switch the tip line into rotating [thinking] mode."""
        self._thinking = True
        self._thinking_last = 0.0  # force immediate refresh
        try: self._app.invalidate()
        except Exception: pass

    def stop_thinking(self) -> None:
        """Return the tip line to idle mode."""
        self._thinking = False
        self._tip_last = 0.0  # force idle tip to refresh
        try: self._app.invalidate()
        except Exception: pass

    def set_label(self, label: str) -> None:
        self._label = (label or "").strip()
        try: self._app.invalidate()
        except Exception: pass

    def set_status(self, text: str) -> None:
        self._status = text or ""
        try: self._app.invalidate()
        except Exception: pass

    def write(self, text: str) -> None:
        if not text:
            return
        with self._output_lock:
            self._output_chunks.append(str(text))
        try: self._app.invalidate()
        except Exception: pass

    def clear_output(self) -> None:
        with self._output_lock:
            self._output_chunks.clear()
        try: self._app.invalidate()
        except Exception: pass

    def run(self, on_submit: Callable[[str], None]) -> None:
        """Blocks until the app exits. Caller is responsible for any stdout
        shimming — see _TUIStdout class in this module for a ready helper."""
        self._on_submit = on_submit
        self._app.run()

    def run_in_terminal(self, fn: Callable[[], object]):
        """Suspend the TUI, run a classic stdin/stdout block, then redraw."""
        return self._app.run_in_terminal(fn, in_executor=False)

    def scroll(self, direction: str, n: int = 10) -> None:
        if direction == "up":
            self._scroll_offset += n
        elif direction == "down":
            self._scroll_offset = max(0, self._scroll_offset - n)
        elif direction == "top":
            self._scroll_offset = 10_000
        elif direction == "bottom":
            self._scroll_offset = 0
        try: self._app.invalidate()
        except Exception: pass

    def exit(self) -> None:
        try: self._app.exit()
        except Exception: pass


__all__ = [
    "SenseiApp", "COMPLETER_WORDS", "LEGEND_WORDS", "IDLE_TIPS",
    "TUIStdout",
]


# Public alias for the stdout-shim helper (master_ai.py imports this)
TUIStdout = _TUIStdout
