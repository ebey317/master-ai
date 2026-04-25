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
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer, Float, FloatContainer, HSplit, Window, WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea


HISTORY_FILE = str(Path.home() / ".master_ai_history")

COMPLETER_WORDS: List[str] = [
    "hub", "menu", "home", "help", "tips", "model", "model auto",
    "mode plan", "mode review", "mode auto", "mode",
    "memory", "remember:", "forget:",
    "task", "task add", "task list", "task done", "task clear", "tasks",
    "save session", "load summary", "load session", "transcript", "log", "preview", "open preview",
    "clear", "clear history", "clear cache", "clear approved", "clear chats", "chats",
    "doctor", "health", "refresh", "reload", "restart", "kick",
    "up", "down", "top", "bottom", "last",
    "mouse remote", "mouse local", "mouse status",
    "projects", "apps", "autotips", "slideshow", "tour", "keys", "approved",
    "cache", "perms", "tutorial", "hints on", "hints off",
    "tts on", "tts off", "tts", "hints", "project",
    "search", "dl", "gdrive",
    "git", "git status", "git diff", "git log", "git commit",
    "go", "cancel", "accessibility", "x", "e", "resize",
]

LEGEND_WORDS = [
    "hub", "help", "tips", "model", "mode plan", "chats", "tts",
    "Ctrl+T transcript", "Ctrl+L log", "Ctrl+P preview", "Ctrl+K cache",
    "e=edit label", "x=exit",
]

IDLE_TIPS = [
    "type 'hub' for the full command menu",
    "'mode plan' brainstorms + drafts plans (default — no execution)",
    "'mode review' confirms every command one at a time",
    "'mode auto' runs commands without asking — destructive still pauses",
    "'fast: your prompt' routes through Groq (fast cloud, needs key)",
    "'deep: your prompt' routes to DeepSeek-R1 (deep reasoning)",
    "'local: your prompt' forces local model explicitly",
    "'mode connected' switches the whole session to cloud-first",
    "on a pending plan — press 1 or Enter to accept, 4 to keep talking",
    "'copy chat' saves the full session to a markdown file",
    "'clear cache' if Sensei is serving the same cached answer",
    "'doctor' shows URLs, services, mode, mouse, and current task",
    "'chats' to browse saved sessions",
    "'up' / 'down' scrolls output; 'top' / 'bottom' jumps",
    "'mouse remote' for phone scrolling; 'mouse local' for drag-copy",
    "'refresh' soft-reloads the engine; 'kick' forces a supervisor respawn",
    "'e' edits this thread's label",
    "'model' switches the active AI model",
    "'tts on' speaks replies out loud (Piper voice)",
    "'remember: <fact>' saves a fact across all sessions",
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


class SafeFormattedTextControl(FormattedTextControl):
    """FormattedTextControl that never throws IndexError from get_line.

    Reason: prompt_toolkit's render loop calls get_line(i) where i can
    come from the cursor position, ScrollState, or wrap calculations.
    If a background thread mutates the output text between frame-start
    and line-fetch, `fragment_lines[i]` can trip `list index out of
    range` (controls.py:413) and crash the render. We wrap the returned
    UIContent's get_line callable so out-of-range indices return an
    empty fragment list (rendered as a blank line) instead of throwing.
    The next frame will re-measure with the current content.
    """

    def create_content(self, width, height):
        content = super().create_content(width, height)
        # prompt_toolkit caches UIContent between frames with the same
        # (width, height). Without this guard, every frame re-wraps the
        # previous wrapper, building a chain that blows the recursion
        # limit after ~1000 frames. Tag the wrapper so we only wrap once.
        if getattr(content.get_line, "_sensei_safe_wrapped", False):
            return content
        original_get_line = content.get_line
        def safe_get_line(i):
            try:
                return original_get_line(i)
            except IndexError:
                return []
        safe_get_line._sensei_safe_wrapped = True
        content.get_line = safe_get_line
        return content


class SenseiApp:
    def __init__(self) -> None:
        self._label = ""
        self._status = ""
        self._output_chunks: List[str] = []
        self._output_lock = threading.Lock()
        # Micro-cache for _render_output. prompt_toolkit calls the text
        # getter multiple times per frame (line-count then get_line); if
        # the chunks grow between those calls the returned fragment list
        # shrinks/grows and triggers "list index out of range" inside
        # FormattedTextControl. Caching for one render tick (~50ms) makes
        # every getter call within a single frame return identical
        # content. Frame interval is 1s, so 50ms is safe.
        self._output_render_cache = None
        self._output_render_cache_ts = 0.0
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

        # Three thought-states: IDLE (rotating hints), THINKING (AI working),
        # HANDOFF (Plan→Review transition). Handoff suppresses idle + thinking
        # so the dispatch moment isn't drowned out by other thoughts.
        # Elijah 2026-04-21: "animate the handoff plan with thoughts and turn
        # off all the other thoughts during the handoff plan. three different
        # modes for the thoughts."
        self._plan_pending = False
        self._handoff_active = False
        self._handoff_cycle = itertools.cycle([
            "⚡ handing off to Review...",
            "🥋 → 🔴 mode flipping...",
            "plan accepted — Review taking over...",
            "executing plan step by step...",
            "🥋 Review mode active...",
        ])
        self._handoff_line = "⚡ handing off to Review..."
        self._handoff_last = 0.0
        self._handoff_interval = 1.0

        self._input = TextArea(
            prompt="🥷  ",
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
            # Reduced from min=3,preferred=3 to min=2,preferred=2 — Elijah
            # 2026-04-20 needs max reading space on phone-over-RustDesk.
            # Input still grows up to max=8 if the user types a long block.
            height=Dimension(min=2, max=8, preferred=2),
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

        # SafeFormattedTextControl catches IndexError inside get_line so
        # a mid-frame race (output thread appending while renderer is
        # measuring) never crashes the render loop. Last-frame content
        # simply blanks the affected line; next frame re-measures fresh.
        self._output_control = SafeFormattedTextControl(
            text=self._render_output,
            focusable=False,
            show_cursor=False,
            get_cursor_position=self._get_output_cursor,
        )
        self._output_window = Window(
            content=self._output_control,
            wrap_lines=True,
            always_hide_cursor=True,
            # class:chat is defined as `noinherit` in _build_style so the
            # Frame's mode-accent color does NOT bleed into chat content.
            # Elijah's rule 2026-04-21: chrome follows mode, TEXT stays on
            # stable semantic colors (blue=file/info, yellow=plan steps,
            # green=voice, red=warning, etc.) so his eye trains on meaning
            # instead of being re-tinted every mode change.
            style="class:chat",
            # display_arrows=False — ▲/▼ arrows at top+bottom of the track
            # read as a little pennant flag on screen, which distracts from
            # the chat content. Keep the track (useful scroll indicator),
            # drop the arrows. Typed `up`/`down`/`top`/`bottom` still scroll.
            right_margins=[ScrollbarMargin(display_arrows=False)],
        )
        # Route mouse-wheel events on the chat window into OUR scroll_offset.
        # Window's default handlers bump self.vertical_scroll, but our
        # rendering re-anchors to the invisible cursor each frame, so the
        # wheel would otherwise snap back every repaint. Overriding these
        # two methods keeps wheel + Ctrl+Up + PageUp on the same offset.
        def _wheel_up():
            self._scroll_offset += 5
            try: self._app.invalidate()
            except Exception: pass

        def _wheel_down():
            self._scroll_offset = max(0, self._scroll_offset - 5)
            try: self._app.invalidate()
            except Exception: pass

        self._output_window._scroll_up = _wheel_up
        self._output_window._scroll_down = _wheel_down
        # Framed chat region — wraps the output window in a bordered box so
        # text stays inside the frame on scroll instead of bleeding past the
        # edges. Title is mode-tinted (class:frame picks up the mode accent
        # color). 2026-04-20 per Elijah: "keep everything in frame instead
        # of bleeding out… we get that whole slideshow that comes down."
        self._output_frame = Frame(
            self._output_window,
            title=" 🥋  chat ",
            style="class:frame",
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

        # Tip/thinking slot ABOVE the ninja — rotating idle hints (💭) or
        # thinking animation (🥷 [thinking] ...) depending on state.
        # Restored 2026-04-20 per Elijah: "make sure the thoughts for
        # idle and thinking are on" — 1 row cost, real feedback benefit.
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
            self._output_frame,
            self._frame,
        ])

        self._on_submit: Optional[Callable[[str], None]] = None

        # Mode-aware palette — set_mode() rebuilds the Style with one of
        # these accent colors so the header, frame, status, and legend
        # all visually signal the current mode at a glance. Default
        # 'plan' at startup — chat-only brainstorm mode, no execution.
        self._mode = "plan"
        self._app = Application(
            layout=Layout(root, focused_element=self._input),
            key_bindings=self._build_keys(),
            full_screen=True,
            # Mouse OFF by default — keeps the input box truly locked at
            # bottom and lets gnome-terminal handle native click-drag copy.
            # Opt-in with SENSEI_MOUSE=1 if you want wheel scroll inside the app.
            mouse_support=os.environ.get("SENSEI_MOUSE", "0") == "1",
            refresh_interval=1.0,
            style=self._build_style("plan"),
            # Force 24-bit truecolor so hex values like #ef4444 / #dc143c
            # render exactly instead of being quantized to the nearest of
            # 256 palette colors. Elijah 2026-04-20: "didnt render like
            # yours" — the issue was prompt_toolkit defaulting to 256
            # mode even though COLORTERM=truecolor.
            color_depth=ColorDepth.DEPTH_24_BIT,
        )

    # ── mode-aware theming ────────────────────────────────────
    # Accent color per mode — traffic-light scheme, dimmed so nothing
    # blares on the monitor. Header gets solid bg; frame/status/legend
    # get the color as foreground. Tip and thinking stay on their own
    # warm colors so they're always readable on any accent.
    # Dimmed down 2026-04-19 — original #c62828 was too bright on RustDesk-over-phone.
    _MODE_ACCENT = {
        # Stoplight remapped 2026-04-21 by semantic, not by old habit:
        #   Plan = full STOP (no execution ever) → RED
        #   Review = CAUTION (approve each step)  → AMBER
        #   Auto = GO (runs freely)               → GREEN
        # Plan's red is #cc0000 — the "true red without glare or tint" that
        # Elijah locked 2026-04-20 after the full tuning walk (#8b1a1a →
        # #b91c1c → #ef4444 → #dc2626 → #ef4444 → #dc143c → #ef4444 →
        # #c0392b → #ef4444 → #cc0000). Do NOT re-tune without his ask.
        "plan":   "#cc0000",  # true red — STOP: drafting only, no execution. Approved hex 2026-04-20.
        "review": "#c7761a",  # amber — CAUTION: per-command confirm, press 1/Enter to approve each
        "auto":   "#1a7a3a",  # forest green — GO: runs without asking (destructive still pauses)
    }

    def _build_style(self, mode: str) -> Style:
        accent = self._MODE_ACCENT.get(mode, "#2266cc")
        # Chrome follows the mode accent — frame borders, header, and
        # label all shift color when the mode changes. Plan=muted red,
        # Review=amber, Auto=green. The stoplight signal spans the full
        # chrome so the mode is visible at a glance, not just in status.
        return Style.from_dict({
            "status":      f"{accent} bold",
            "frame":       f"{accent} bold",
            "frame.label": f"{accent} bold",
            "legend":      f"{accent}",
            "sep":         "#999999",
            "tip":         "#1a7a3a italic bold",
            "thinking":    "#c7761a bold",
            "textinput":   "#ffffff noinherit",
            "header":      f"{accent} bold",
            # Chat content — noinherit so the Frame's mode color doesn't
            # bleed onto text. Semantic ANSI codes from _paint_line render
            # true (blue=file/info, yellow=plan, green=voice, red=warning).
            "chat":        "noinherit",
        })

    def set_mode(self, mode: str) -> None:
        """Swap the accent color when MODE changes. Called by master_ai.py
        on `mode plan|review|auto`. Silent no-op for unknown modes."""
        if mode not in self._MODE_ACCENT:
            return
        self._mode = mode
        try:
            self._app.style = self._build_style(mode)
            self._app.invalidate()
        except Exception:
            pass

    # ── rendering callbacks ────────────────────────────────────

    def _render_output(self):
        """Return the FULL output as ANSI — scroll is handled by positioning
        an invisible cursor that Window tracks (see _get_output_cursor).

        Per-frame micro-cache: prompt_toolkit calls this getter multiple
        times per render cycle (height measure → then per-line fetch). If
        a background thread appends between calls, the fragment lists
        have different lengths and FormattedTextControl trips on `list
        index out of range` (controls.py:413). Caching locks the content
        to one consistent snapshot per frame; the line count is cached
        alongside so _get_output_cursor can't report a y beyond the
        cached fragments.
        """
        now = time.time()
        if self._output_render_cache is not None and (now - self._output_render_cache_ts) < 0.05:
            return self._output_render_cache
        with self._output_lock:
            text = "".join(self._output_chunks)
        rendered = ANSI(text)
        self._output_render_cache = rendered
        self._output_render_cache_ts = now
        # Line count matched to the rendered snapshot. Using count("\n")
        # here may differ from fragment-list length by 1 (trailing empty
        # split), so we subtract one defensively — better to under-report
        # the cursor y than over-report and trip IndexError.
        self._output_render_lines = max(0, text.count("\n") - 1)
        return rendered

    def _get_output_cursor(self):
        """Invisible cursor that Window auto-scrolls to keep visible.
        - scroll_offset == 0 → cursor at bottom of buffer → Window shows latest
        - scroll_offset  > 0 → cursor N lines above bottom → Window shows N back

        Uses the line count cached by _render_output so cursor y can
        never exceed what the control's fragment_lines actually contains.
        Prevents `list index out of range` in FormattedTextControl when
        output is appended between render-cycle getter calls.
        """
        # Ensure cache is populated for this frame. If _render_output
        # hasn't been called yet this tick (cold start), populate now.
        if self._output_render_cache is None:
            self._render_output()
        total = self._output_render_lines
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
        # Legend's mode slot is now word-for-word identical to what
        # the TOP status line shows: uppercase "MODE:SAFE" / "MODE:PLAN"
        # / "MODE:AUTO". When you toggle with `mode X`, BOTH update.
        # Elijah 2026-04-19: "don't look at the color look at the
        # words" — match the literal string exactly.
        current_mode = getattr(self, "_mode", "plan").upper()
        words = []
        for w in LEGEND_WORDS:
            if w == "mode plan":
                words.append(f"MODE:{current_mode}")
            else:
                words.append(w)
        parts = []
        for i, w in enumerate(words):
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

        def _dispatch_command(text: str, echo: str = "") -> None:
            now = time.monotonic()
            last_text, last_ts = getattr(self, "_last_shortcut_dispatch", ("", 0.0))
            if text == last_text and (now - last_ts) < 0.75:
                return
            self._last_shortcut_dispatch = (text, now)
            if echo:
                self.write(f"\n\033[2m[{echo}]\033[0m\n")
            if self._on_submit:
                threading.Thread(
                    target=self._safe_dispatch, args=(text,), daemon=True,
                ).start()

        @kb.add("enter", filter=has_focus(self._input))
        def _submit(event):
            # Multi-line paste fix (2026-04-24): pasted text contains \n
            # characters that arrive as rapid-fire Enter events. Real
            # human Enters are always >50ms apart. If this Enter is within
            # 50ms of the previous one, it's part of a paste — insert as
            # newline instead of submitting. Without this, pasted prompts
            # get chopped into per-line submissions and Plan mode never
            # sees the full request (the slideshow-prompt-fragmented bug).
            import time as _t
            _now = _t.monotonic()
            _last = getattr(self, '_last_enter_time', 0.0)
            self._last_enter_time = _now
            if (_now - _last) < 0.05:
                self._input.buffer.insert_text("\n")
                return
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

        # Standard app-style shortcuts. These dispatch the same word commands
        # a user can type, so keyboard and voice paths stay in sync.
        @kb.add("c-t")
        def _shortcut_transcript(event):
            _dispatch_command("transcript", "Ctrl+T transcript")

        @kb.add("c-l")
        def _shortcut_log(event):
            _dispatch_command("log", "Ctrl+L log")

        @kb.add("c-o")
        def _shortcut_open(event):
            _dispatch_command("open preview", "Ctrl+O open")

        @kb.add("c-p")
        def _shortcut_preview(event):
            _dispatch_command("preview", "Ctrl+P preview")

        @kb.add("c-k")
        def _shortcut_cache(event):
            _dispatch_command("clear cache", "Ctrl+K clear cache")

        @kb.add("c-r")
        def _shortcut_refresh(event):
            _dispatch_command("refresh", "Ctrl+R refresh")

        @kb.add("c-m")
        def _shortcut_mouse(event):
            _dispatch_command("mouse toggle", "Ctrl+M mouse toggle")

        @kb.add("c-b")
        def _shortcut_keyboard(event):
            _dispatch_command("mouse local", "Ctrl+B keyboard/copy")

        @kb.add("c-s")
        def _shortcut_save(event):
            _dispatch_command("save session", "Ctrl+S save")

        @kb.add("c-q")
        def _shortcut_quit(event):
            _dispatch_command("x", "Ctrl+Q quit")

        # Bracketed paste — PROPER fix for multi-line paste-split bug
        # (2026-04-24). When the terminal sends bracketed-paste sequences
        # (ESC[200~ ... ESC[201~), prompt_toolkit fires a single
        # Keys.BracketedPaste event with the full pasted text in
        # event.data. Insert it directly into the buffer — newlines stay
        # as text characters, NOT as separate Enter key events. This
        # supersedes the time-heuristic in _submit which only catches
        # consecutive newlines but misses the first one in any burst.
        # The slideshow-prompt-split bug Elijah hit — this is the cure.
        @kb.add(Keys.BracketedPaste)
        def _paste(event):
            event.current_buffer.insert_text(event.data)

        # Single scroll binding — Shift+Up / Shift+Down. Elijah's pick
        # 2026-04-19: "only want one" + "hold is scroll." Shift is a real
        # modifier, so terminal key-repeat fires continuous Shift+Up
        # events while held → smooth scroll. Tap = one event = 3 lines.
        # Plain Up/Down stay reserved for input history.
        @kb.add("s-up")
        @kb.add("c-up")
        @kb.add("pageup")
        def _scroll_up(event):
            self._scroll_offset += 8
            event.app.invalidate()

        @kb.add("s-down")
        @kb.add("c-down")
        @kb.add("pagedown")
        def _scroll_down(event):
            self._scroll_offset = max(0, self._scroll_offset - 8)
            event.app.invalidate()

        @kb.add("home")
        @kb.add("c-home")
        def _scroll_top(event):
            self._scroll_offset = 10_000
            event.app.invalidate()

        @kb.add("end")
        @kb.add("c-end")
        def _scroll_bottom(event):
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
        # Chat-app behavior: new assistant/tool output follows the live bottom
        # so handoff prompts and approval choices do not land off-screen after
        # the user previously scrolled up.
        self._scroll_offset = 0
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

    def enable_number_confirm(self, check_fn: Callable[[], bool],
                               submit_fn: Callable[[str], None]) -> None:
        """Make number keys (1-5) auto-submit during confirm prompts.

        check_fn() — return True when a confirm prompt is awaiting input.
        submit_fn(digit_str) — called with "1" / "2" / "3" / "4" / "5"
            when the user presses that key while a confirm is awaiting.

        Registered with a Condition filter so number keys ONLY auto-submit
        when (a) a confirm is awaiting AND (b) the input field is empty
        (so the user can still type "type 1 2 3" as a normal message).

        Elijah 2026-04-21: "if I press the number, make sure it automatically
        enters. I don't wanna press one enter." Numbers without Enter is the
        target UX on his phone keyboard — Enter is a two-tap motion.
        """
        kb = self._app.key_bindings

        def _filter():
            try:
                return bool(check_fn()) and not self._input.text
            except Exception:
                return False

        cond = Condition(_filter)

        def _make_handler(digit: str):
            def _h(event):
                try:
                    submit_fn(digit)
                except Exception:
                    pass
            return _h

        for d in ("1", "2", "3", "4", "5"):
            kb.add(d, filter=cond)(_make_handler(d))


__all__ = [
    "SenseiApp", "COMPLETER_WORDS", "LEGEND_WORDS", "IDLE_TIPS",
    "TUIStdout",
]


# Public alias for the stdout-shim helper (master_ai.py imports this)
TUIStdout = _TUIStdout
