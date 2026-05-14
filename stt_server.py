#!/usr/bin/env python3
import sys, os, json, tempfile, re, gzip, urllib.request, urllib.error, threading, time, uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

_CLIENT_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)

SCRIPTS    = os.path.expanduser("~/scripts")
_DEFAULT_CHATS_DIR  = os.path.expanduser("~/.master_ai_chats")
os.makedirs(_DEFAULT_CHATS_DIR, exist_ok=True)

def _active_profile():
    """Return active profile name, or '' for default/legacy."""
    try:
        p = os.path.expanduser('~/.master_ai_active_profile')
        if os.path.exists(p):
            name = open(p).read().strip()
            if name and os.path.isdir(os.path.expanduser(f'~/.master_ai_profiles/{name}')):
                return name
    except Exception:
        pass
    return ''

def _chats_dir():
    """Profile-aware chats dir. Falls back to legacy global dir."""
    prof = _active_profile()
    if prof:
        d = os.path.expanduser(f'~/.master_ai_profiles/{prof}/chats')
        os.makedirs(d, exist_ok=True)
        return d
    return _DEFAULT_CHATS_DIR

# Module-level alias for backwards-compat; per-request handlers should call _chats_dir()
CHATS_DIR = _DEFAULT_CHATS_DIR

_API_HANDLE_LOCK = threading.Lock()
_API_HISTORY_LOCK = threading.Lock()
_API_HISTORIES = {}
_API_MAX_HISTORY_MESSAGES = 24

# M9 — Agentic Continuation Loop (scaffold 2026-05-12).
# Each /chat call mints a turn_id. /chat/continue references it via parent_turn_id
# and feeds the extension-reported action_results back into the model. Round
# budget caps runaway loops; user Stop button is the hard interrupt. The model
# emitting an empty actions[] AND no DONE directive also terminates.
_API_TURNS = {}  # {turn_id: {session_key, round_num, round_budget, created_at, parent_turn_id}}
_API_TURNS_LOCK = threading.Lock()
_API_DEFAULT_ROUND_BUDGET = 3
_API_MAX_ROUND_BUDGET = 8  # Hard ceiling; extension can't ask for more.
_HEALTH_CACHE_LOCK = threading.Lock()
_HEALTH_CACHE_TTL_S = 3.0
_HEALTH_CACHE = {"ts": 0.0, "payload": None}
_ACTION_LINE_RE = re.compile(
    r"^\s*(RUNTERM|RUN|READ|CREATE|EDIT|REMEMBER|BROWSER_CLICK|BROWSER_FILL|BROWSER_READ|BROWSER_NAV|BROWSER_SCREENSHOT):\s*(.*?)\s*$",
    re.IGNORECASE,
)


def _health_payload():
    now = time.time()
    with _HEALTH_CACHE_LOCK:
        cached = _HEALTH_CACHE.get("payload")
        if cached and now - float(_HEALTH_CACHE.get("ts") or 0.0) < _HEALTH_CACHE_TTL_S:
            out = dict(cached)
            out["cached"] = True
            return out

    ollama_state = 'down'
    model_name = 'master-ai'
    probe_ms = 0
    t0 = time.time()
    try:
        req = urllib.request.Request('http://127.0.0.1:11434/api/tags')
        with urllib.request.urlopen(req, timeout=2) as resp:
            json.loads(resp.read().decode())
        ollama_state = 'active'
    except Exception:
        ollama_state = 'down'
    finally:
        probe_ms = int((time.time() - t0) * 1000)

    payload = {
        'ok': True,
        'ollama': ollama_state,
        'model': model_name,
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'probe_ms': probe_ms,
        'cached': False,
    }
    with _HEALTH_CACHE_LOCK:
        _HEALTH_CACHE["ts"] = time.time()
        _HEALTH_CACHE["payload"] = dict(payload)
    return payload


def _scripts_on_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    return here


def _api_session_key(source, session_id):
    session_id = (session_id or "").strip()
    if not session_id:
        return ""
    source = (source or "pupil").strip()[:80] or "pupil"
    return f"{source}:{session_id[:160]}"


def _trim_api_history(history):
    if not isinstance(history, list):
        return []
    return history[-_API_MAX_HISTORY_MESSAGES:]


def _safe_context_text(value, limit=1800):
    if value is None:
        return ""
    text = str(value).replace("\r", " ").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


# ─── RANK 1: page_context prompt-injection defense ───────────────────────────
# Plan: ~/.claude/plans/auto-did-not-actually-stateful-wozniak.md
# Step order is fixed: (1) strip bidi/zero-width, (2) collapse whitespace inside
# candidate uppercase tokens, (3) match case-insensitively against the sentinel
# list, (4) replace inline with [scrubbed directive]. Inline replace keeps page
# understanding intact; whole-field omission would trigger compensatory
# hallucination. Audit log records pattern names + counts only — never the
# scrubbed bytes.

_BIDI_ZWSP_CHARS = (
    "​‌‍‎‏"   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "‪‫‬‭‮"   # LRE, RLE, PDF, LRO, RLO
    "⁦⁧⁨⁩"         # LRI, RLI, FSI, PDI
    "﻿"                            # BOM
)
_BIDI_ZWSP_RE = re.compile(f"[{_BIDI_ZWSP_CHARS}]")

# Full sentinel set surfaced by Pre-Check #1 (handoff doc 2026-05-13).
_DIRECTIVE_VERBS = (
    # Order: longest first so RUNTERM matches before RUN.
    "RUNTERM", "REMEMBER", "BROWSER",  # BROWSER handled separately below
    "CREATE", "READ", "EDIT", "THINK", "DONE", "RUN", "ASK",
)
# Strip the BROWSER placeholder — it gets its own pattern that allows the
# `_<SUFFIX>` shape (`BROWSER_CLICK:`, `BROWSER_NAV:`, etc.).
_VERB_LIST = tuple(v for v in _DIRECTIVE_VERBS if v != "BROWSER")


def _build_verb_pattern(verb):
    """Standard form: `\\bVERB\\s*:` — case-insensitive.

    Catches `RUN:`, `Run:`, `run:`, `RUN  :`. Does NOT catch `R U N :` —
    that's the spaced-obfuscation form handled by `_build_spaced_verb_pattern`.
    Per-verb literal match avoids the greedy-consumption bug where a long
    English phrase ending in a verb gets matched as a single candidate and
    returned unchanged (swallowing the inner directive verbatim).
    """
    return re.compile(rf'\b{re.escape(verb)}\s*:', flags=re.IGNORECASE)


def _build_spaced_verb_pattern(verb):
    """Spaced-obfuscation form: each letter separated by exactly one whitespace.

    Catches `R U N :` (space between each char). Requires AT LEAST one space
    between each pair of letters (using `[ \\t]` not `[ \\t]?`) so it doesn't
    overlap with the standard pattern — the standard pattern already catches
    `RUN:`. 8-char-window constraint is implicit: a 3-letter verb with single
    spaces = 5 chars; a 7-letter verb = 13 chars (still tight).
    """
    spaced = r'[ \t]'.join(re.escape(c) for c in verb)
    return re.compile(rf'\b{spaced}\s*:', flags=re.IGNORECASE)


_VERB_PATTERNS = [
    (verb + ":", _build_verb_pattern(verb)) for verb in _VERB_LIST
]
# Spaced-obfuscation patterns only apply to verbs of length >= 2 (single-letter
# verbs would have no internal whitespace gap to detect).
_SPACED_VERB_PATTERNS = [
    (verb + ":", _build_spaced_verb_pattern(verb))
    for verb in _VERB_LIST if len(verb) >= 2
]

# BROWSER_<UPPER+UNDERSCORE>: — `BROWSER_CLICK:`, `BROWSER_NAV:`, etc.
# Internal whitespace not handled here (rare obfuscation form).
_BROWSER_PATTERN = re.compile(
    r'\bBROWSER_[A-Z_]+\s*:',
    flags=re.IGNORECASE,
)

_BLOCK_MARKERS = (
    "<<<CONTENT", ">>>CONTENT",
    "<<<FIND", ">>>FIND",
    "<<<REPLACE", ">>>REPLACE",
)
_BLOCK_MARKER_RE = re.compile(
    "|".join(re.escape(m) for m in _BLOCK_MARKERS),
    flags=re.IGNORECASE,
)

# <PLAN READY> matched FIRST so <PLAN> doesn't shadow it.
_PLAN_MARKERS = ("<PLAN READY>", "</PLAN>", "<PLAN>")
_PLAN_MARKER_RE = re.compile(
    "|".join(re.escape(m) for m in _PLAN_MARKERS),
    flags=re.IGNORECASE,
)

_SCRUB_REPLACEMENT = "[scrubbed directive]"


def _sanitize_pass(text):
    """Return (sanitized_text, list_of_pattern_names_fired_in_order).

    Pattern names are stable identifiers used in the audit log — never the
    scrubbed bytes themselves. Caller may dedupe; this function preserves
    every firing in order so cross-field accumulation is honest.
    """
    if not text:
        return text or "", []
    fired = []

    # Step 1 — strip bidi/zero-width controls.
    cleaned = _BIDI_ZWSP_RE.sub("", text)
    if cleaned != text:
        fired.append("bidi_strip")

    # Step 2 — scrub standard verb forms (`RUN:`, `RUNTERM:`, etc.) case-
    # insensitively. Per-verb literal match avoids the greedy-candidate bug
    # where a long English phrase ending in `<verb>:` matched as one
    # candidate and returned unchanged, swallowing the inner directive.
    for verb_name, pattern in _VERB_PATTERNS:
        def _scrub_verb(m, vn=verb_name):
            fired.append(vn)
            return _SCRUB_REPLACEMENT
        cleaned = pattern.sub(_scrub_verb, cleaned)

    # Step 2b — spaced-obfuscation forms (`R U N :`). Separate pass so the
    # standard pattern's behavior is unchanged.
    for verb_name, pattern in _SPACED_VERB_PATTERNS:
        def _scrub_spaced(m, vn=verb_name):
            fired.append(vn)
            return _SCRUB_REPLACEMENT
        cleaned = pattern.sub(_scrub_spaced, cleaned)

    # Step 3 — BROWSER_<SUFFIX>: directives.
    def _scrub_browser(m):
        token = re.sub(r'\s+', '', m.group(0).upper()).rstrip(':')
        fired.append(f"{token}:")
        return _SCRUB_REPLACEMENT
    cleaned = _BROWSER_PATTERN.sub(_scrub_browser, cleaned)

    # Step 4 — block markers (`<<<CONTENT`, `>>>CONTENT`, etc.).
    def _scrub_block(m):
        fired.append(m.group(0).upper())
        return _SCRUB_REPLACEMENT
    cleaned = _BLOCK_MARKER_RE.sub(_scrub_block, cleaned)

    # Step 5 — plan markers (`<PLAN READY>` matched FIRST so `<PLAN>` doesn't
    # shadow it; that ordering lives in the regex alternation order).
    def _scrub_plan(m):
        fired.append(m.group(0).upper())
        return _SCRUB_REPLACEMENT
    cleaned = _PLAN_MARKER_RE.sub(_scrub_plan, cleaned)

    return cleaned, fired


def _sanitize_page_context_field(value, field_name, fired_acc, fields_acc):
    """Per-field sanitize. Mutates fired_acc (list) and fields_acc (set)."""
    if value is None:
        return ""
    cleaned, fired = _sanitize_pass(str(value))
    if fired:
        fired_acc.extend(fired)
        fields_acc.add(field_name)
    return cleaned


def _sanitize_assembled_context_block(text, fired_acc, fields_acc):
    """Post-assembly sanitize. Catches cross-field directive splits where a
    hostile page placed half a directive in one field and half in an adjacent
    field — concatenation only assembles them after _format_page_context joins."""
    cleaned, fired = _sanitize_pass(text)
    if fired:
        fired_acc.extend(fired)
        fields_acc.add("_assembled_block")
    return cleaned


def _write_sanitize_audit(*, request_id, source, scrub_meta):
    """Write one audit row when page_context sanitization fired anything.

    Schema (every field required by plan):
      ts, kind, request_id, source, scrub_count, patterns, fields.
    Audit log NEVER stores raw scrubbed bytes — pattern names + counts only,
    so the log itself cannot become a secondary leak surface for hostile page
    content. Test #7 enforces this.
    """
    if not scrub_meta or scrub_meta.get("count", 0) == 0:
        return
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": "page_context_sanitize",
        "request_id": (request_id or "")[:160],
        "source": (source or "")[:80],
        "scrub_count": int(scrub_meta.get("count", 0)),
        "patterns": list(scrub_meta.get("patterns", [])),
        "fields": list(scrub_meta.get("fields", [])),
    }
    try:
        from pathlib import Path as _P
        with _P.home().joinpath('.master_ai_audit_typed.jsonl').open('a') as f:
            f.write(json.dumps(rec) + '\n')
    except Exception:
        pass


def _format_page_context(page_context):
    """Format browser page_context dict to model-facing text.

    Returns (formatted_text, scrub_meta) where scrub_meta is:
      {"count": int, "patterns": list[str], "fields": list[str]}.

    Per-field sanitization runs BEFORE the per-field cap so the directive
    pattern can't be split by the cap. Assembled-block sanitization runs AFTER
    field concatenation to catch cross-field directive splits.
    """
    scrub_meta = {"count": 0, "patterns": [], "fields": []}
    if not isinstance(page_context, dict):
        return "", scrub_meta

    fired_acc = []
    fields_acc = set()

    fields = []
    for key, limit in (
        ("url", 500),
        ("title", 300),
        ("selection", 1200),
        ("focused_text", 1200),
        ("interactive_elements", 2400),
        ("visible_text", 1800),
    ):
        raw = page_context.get(key)
        if raw is None:
            continue
        sanitized = _sanitize_page_context_field(raw, key, fired_acc, fields_acc)
        val = _safe_context_text(sanitized, limit=limit)
        if val:
            fields.append(f"{key}: {val}")
    if not fields:
        if fired_acc:
            # Even with no formatted fields, audit truthfully if scrubbing fired.
            scrub_meta.update(_finalize_scrub_meta(fired_acc, fields_acc))
        return "", scrub_meta

    block = "[BROWSER PAGE CONTEXT]\n" + "\n".join(fields)
    block = _sanitize_assembled_context_block(block, fired_acc, fields_acc)

    if fired_acc:
        scrub_meta.update(_finalize_scrub_meta(fired_acc, fields_acc))
    return block, scrub_meta


def _finalize_scrub_meta(fired_acc, fields_acc):
    """Dedupe pattern names (preserve order) and sort fields for stable audit."""
    seen = set()
    unique_patterns = []
    for p in fired_acc:
        if p not in seen:
            seen.add(p)
            unique_patterns.append(p)
    return {
        "count": len(fired_acc),
        "patterns": unique_patterns,
        "fields": sorted(fields_acc),
    }


def _api_prompt(prompt, *, source="", page_context=None, schedule_id="",
                action_results=None, round_num=1, round_budget=None,
                request_id=""):
    context, scrub_meta = _format_page_context(page_context)
    # Audit even if no formatted context survived (e.g., every field was empty
    # after sanitize) — the scrub still happened and Elijah needs the row.
    if scrub_meta.get("count", 0) > 0:
        _write_sanitize_audit(
            request_id=request_id,
            source=source or "pupil",
            scrub_meta=scrub_meta,
        )
    results_block = _format_action_results(action_results)
    if not (source or context or schedule_id or results_block):
        return prompt
    lines = [
        "[API REQUEST]",
        f"source: {_safe_context_text(source or 'pupil', 80)}",
    ]
    if schedule_id:
        lines.append(f"schedule_id: {_safe_context_text(schedule_id, 120)}")
    if round_num and round_num > 1:
        budget_str = f"/{round_budget}" if round_budget else ""
        lines.append(f"continuation_round: {round_num}{budget_str}")
    lines.extend([
        "Branch B: do not execute local machine or browser actions inside the backend request.",
        "If browser work is needed, emit BROWSER_CLICK, BROWSER_FILL, BROWSER_READ, BROWSER_NAV, or BROWSER_SCREENSHOT directives.",
        "The HTTP API will return directives as actions[] for the extension to confirm.",
        "Do not say a browser action has been completed until [PREVIOUS ROUND RESULTS] shows the extension completed it.",
        "Do not emit DONE in the same reply as BROWSER_* directives; wait for the extension's results first.",
    ])
    if round_num and round_num > 1:
        lines.append(
            "M9 LOOP: the extension already dispatched your previous round's actions. "
            "Read [PREVIOUS ROUND RESULTS] below, decide if the user's goal is met, "
            "and either propose more BROWSER_* actions or reply with a final answer "
            "(empty actions[] = goal complete)."
        )
    if context:
        if scrub_meta.get("count", 0) > 0:
            lines.append("")
            lines.append(f"[SAFETY: {scrub_meta['count']} page-context tokens scrubbed]")
        lines.extend(["", context])
    if results_block:
        lines.extend(["", results_block])
    lines.extend(["", "[USER PROMPT]", prompt])
    return "\n".join(lines)


def _write_turn_audit(rec):
    """M9 turn-level audit: one JSON record per terminated turn so behavioral
    analytics can query 'what did the user ask, what did the model propose
    across all rounds, and what was the net outcome' from a single source.
    Sibling to /extension/action_result rows but at turn granularity."""
    try:
        from pathlib import Path as _P
        with _P.home().joinpath('.master_ai_audit_typed.jsonl').open('a') as f:
            f.write(json.dumps(rec) + '\n')
    except Exception:
        pass  # Audit is observability, not a blocker.


def _build_terminal_turn(*, turn_id, turn_root, round_num, round_budget,
                         parent_turn_id, session_key, reply, route, model,
                         t0, terminal_reason):
    """Synthesize a final-round response without calling the model. Used by
    the M9 short-circuit (duplicate failure detection) and any other forced
    termination path. Always returns done=true."""
    round_remaining = max(0, round_budget - round_num)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _API_TURNS_LOCK:
        _API_TURNS[turn_id] = {
            "session_key": session_key,
            "round_num": round_num,
            "round_budget": round_budget,
            "turn_root": turn_root,
            "parent_turn_id": parent_turn_id or None,
            "created_at": now,
            "done": True,
        }
        if len(_API_TURNS) > 256:
            oldest = sorted(_API_TURNS.items(), key=lambda kv: kv[1].get("created_at", ""))[:64]
            for k, _ in oldest:
                _API_TURNS.pop(k, None)
    _write_turn_audit({
        "ts": now,
        "source": "api_handle",
        "kind": "turn_terminal",
        "turn_id": turn_id,
        "turn_root": turn_root,
        "round_num": round_num,
        "round_budget": round_budget,
        "terminal_reason": terminal_reason,
        "route": route,
        "model": model,
        "actions_count": 0,
    })
    return {
        "reply": reply,
        "route": route,
        "model": model,
        "latency_ms": int((time.time() - t0) * 1000),
        "actions": [],
        "blocked_actions": [],
        "turn_id": turn_id,
        "turn_root": turn_root,
        "round_num": round_num,
        "round_budget": round_budget,
        "round_remaining": round_remaining,
        "done": True,
        "ts": now,
    }


def _duplicate_failure_reason(action_results):
    """M9 safety: if the same (kind, target) failed twice in the incoming batch,
    return a reason string for short-circuit termination. Returns "" otherwise.
    Prevents the loop from burning rounds when the model retries a bad selector."""
    if not isinstance(action_results, list) or not action_results:
        return ""
    seen_failures = {}
    for ar in action_results:
        if not isinstance(ar, dict):
            continue
        if (ar.get("result") or "").lower() != "failure":
            continue
        act = ar.get("action") or {}
        kind = str(act.get("kind") or ar.get("kind") or "").upper()
        target = str(act.get("target") or ar.get("target") or "")[:300]
        if not kind or not target:
            continue
        key = (kind, target)
        seen_failures[key] = seen_failures.get(key, 0) + 1
        if seen_failures[key] >= 2:
            return f"same target failed twice in one round: {kind} {target!r}"
    return ""


def _format_action_results(action_results):
    """Format extension-reported action outcomes into a prompt block (M9 loop)."""
    if not isinstance(action_results, list) or not action_results:
        return ""
    rows = []
    for ar in action_results[:20]:  # Cap to keep prompt bounded.
        if not isinstance(ar, dict):
            continue
        kind = str((ar.get("action") or {}).get("kind") or ar.get("kind") or "").upper()
        target = str((ar.get("action") or {}).get("target") or ar.get("target") or "")[:300]
        verdict = str(ar.get("verdict") or "").lower()
        result = str(ar.get("result") or "").lower()
        final_state = ar.get("final_state") or {}
        detail = ""
        if isinstance(final_state, dict):
            for key in ("error", "text", "value", "navigated", "reason"):
                v = final_state.get(key)
                if v:
                    detail = f" — {key}: {_safe_context_text(str(v), 240)}"
                    break
        # M9.2: irreversible-action heuristic label from the extension. When
        # present, surface it to the model so the next round's reasoning
        # acknowledges the safety category that the user explicitly approved.
        gated_by = ar.get("gated_by") if isinstance(ar.get("gated_by"), str) else None
        gated = f" (gated by {gated_by})" if gated_by else ""
        rows.append(f"  · {kind} {target!r} → verdict={verdict} result={result}{gated}{detail}")
    if not rows:
        return ""
    return "[PREVIOUS ROUND RESULTS]\n" + "\n".join(rows)


def _fallback_action(kind, target, *, model="", source_text="", cwd=None):
    kind = (kind or "").upper()
    target = (target or "").strip()
    if not kind or not target:
        return None
    risk = "safe" if kind in ("READ", "BROWSER_READ") else "normal"
    return {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "target": target,
        "cwd": cwd,
        "risk": risk,
        "requires_confirm": True,
        "timeout_s": 60,
        "created_by_model": model or "",
        "source_text": source_text or f"{kind}: {target}",
        "parsed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "pending_approval",
        "extras": {},
    }


def _api_parse_actions(reply, *, model="", source="", session_id="", schedule_id="", page_context=None):
    actions = []
    seen = set()

    def add(action):
        if not isinstance(action, dict):
            return
        kind = str(action.get("kind") or "").upper()
        target = str(action.get("target") or "").strip()
        if not kind or not target:
            return
        key = (kind, target)
        if key in seen:
            return
        seen.add(key)
        action["kind"] = kind
        action["target"] = target
        action["status"] = "pending_approval"
        action["requires_confirm"] = True
        action.setdefault("id", str(uuid.uuid4()))
        action.setdefault("created_by_model", model or "")
        action.setdefault("parsed_at", datetime.now().astimezone().isoformat(timespec="seconds"))
        extras = action.get("extras") if isinstance(action.get("extras"), dict) else {}
        extras.update({
            "api_branch": "B",
            "source": source or "pupil",
        })
        if session_id:
            extras["session_id"] = session_id
        if schedule_id:
            extras["schedule_id"] = schedule_id
        if isinstance(page_context, dict) and page_context.get("url"):
            extras["page_url"] = _safe_context_text(page_context.get("url"), 500)
        action["extras"] = extras
        actions.append(action)

    try:
        _scripts_on_path()
        import typed_actions as _ta
        for parsed in _ta.parse_reply(reply or "", model=model or "", cwd=os.getcwd()):
            try:
                add(parsed.to_dict())
            except Exception:
                pass
    except Exception:
        pass

    for raw in (reply or "").splitlines():
        m = _ACTION_LINE_RE.match(raw)
        if not m:
            continue
        action = _fallback_action(
            m.group(1),
            m.group(2),
            model=model or "",
            source_text=raw,
            cwd=os.getcwd(),
        )
        add(action)

    return actions


_DONE_DIRECTIVE_RE = re.compile(r"^\s*DONE:\s*\S")


def _reply_has_done_directive(reply):
    """Return True if `reply` contains an explicit `DONE: <summary>` line.

    M9.1 termination signal: when the model says it's finished, the agent loop
    ends with terminal_reason="done_directive" — taking priority over the
    implicit no_actions / budget terminal branches. The line must be at column
    0 (whitespace allowed), match `DONE:` verbatim (parser-style), and have at
    least one non-whitespace character after the colon (rejects bare `DONE:`).
    """
    if not reply or not isinstance(reply, str):
        return False
    for line in reply.splitlines():
        if _DONE_DIRECTIVE_RE.match(line):
            return True
    return False


def _api_terminal_state(reply, captured_actions, round_remaining):
    """Return (done, terminal_reason) for an API turn."""
    if captured_actions and round_remaining > 0:
        return False, ""
    if captured_actions and round_remaining <= 0:
        return True, "budget"
    if _reply_has_done_directive(reply):
        return True, "done_directive"
    return True, "no_actions"


def _api_blocked_actions(module, extra_blocked=None):
    out = []
    for blocked in (extra_blocked or []):
        if isinstance(blocked, dict):
            out.append(blocked)
    blocked = getattr(module, "_LAST_BLOCKED_ACTION", {}) or {}
    if isinstance(blocked, dict) and blocked:
        item = {
            "kind": str(blocked.get("kind") or "").upper(),
            "target": blocked.get("command") or blocked.get("path") or "",
            "reason": blocked.get("reason") or "blocked by Sensei policy",
        }
        if blocked.get("audit_kind"):
            item["audit_kind"] = blocked.get("audit_kind")
        out.append(item)
    return out


def api_handle(payload):
    """Non-interactive /chat bridge into master_ai.handle().

    Branch B contract: the backend can propose typed actions, but it must not
    call the TUI confirmation/execution path. The Chrome extension confirms and
    dispatches browser actions separately, then reports results back.

    M9 (2026-05-12): supports continuation rounds. If payload includes
    parent_turn_id + action_results, the previous round's outcomes are
    formatted into [PREVIOUS ROUND RESULTS] and the model decides whether to
    propose more actions or reply with a final answer (empty actions[] = done).
    Round budget caps the loop.
    """
    payload = payload if isinstance(payload, dict) else {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("missing prompt")
    mode_req = (payload.get("mode") or "").strip().lower()
    if mode_req and mode_req not in ("plan", "review", "auto"):
        raise ValueError("invalid mode")

    source_raw = payload.get("source")
    source = _safe_context_text(source_raw or "pupil", 80)
    prompt_source = _safe_context_text(source_raw or "", 80)
    session_id = _safe_context_text(payload.get("session_id") or "", 160)
    schedule_id = _safe_context_text(payload.get("schedule_id") or "", 120)
    page_context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else None
    requested_model = (payload.get("model") or "").strip()
    t0 = time.time()

    # M9 continuation context
    parent_turn_id = _safe_context_text(payload.get("parent_turn_id") or "", 80)
    action_results = payload.get("action_results") if isinstance(payload.get("action_results"), list) else None
    try:
        req_budget = int(payload.get("round_budget") or _API_DEFAULT_ROUND_BUDGET)
    except (TypeError, ValueError):
        req_budget = _API_DEFAULT_ROUND_BUDGET
    req_budget = max(1, min(req_budget, _API_MAX_ROUND_BUDGET))

    # M9 safety: detect duplicate-target failures in the incoming round and
    # short-circuit before burning another model turn. If the same target
    # failed twice in the latest action_results batch, the model is almost
    # certainly going to retry the same selector. Force termination instead.
    short_circuit_reason = _duplicate_failure_reason(action_results)

    # Resolve turn lineage. Continuation references parent; fresh /chat mints new.
    if parent_turn_id:
        with _API_TURNS_LOCK:
            parent_meta = dict(_API_TURNS.get(parent_turn_id, {}))
        if parent_meta:
            round_budget = int(parent_meta.get("round_budget") or req_budget)
            round_num = int(parent_meta.get("round_num", 1)) + 1
            turn_root = parent_meta.get("turn_root") or parent_turn_id
        else:
            # Unknown parent — treat as fresh turn but echo the id back to caller.
            round_budget = req_budget
            round_num = 1
            turn_root = parent_turn_id
    else:
        round_budget = req_budget
        round_num = 1
        turn_root = None

    turn_id = str(uuid.uuid4())

    # M9 short-circuit: same-target-twice-failed in this round → terminate
    # without calling the model. Returns a synthetic done=true response.
    if short_circuit_reason:
        return _build_terminal_turn(
            turn_id=turn_id,
            turn_root=turn_root or turn_id,
            round_num=round_num,
            round_budget=round_budget,
            parent_turn_id=parent_turn_id,
            session_key=_api_session_key(source, session_id),
            reply=f"[loop terminated: {short_circuit_reason}]",
            route="loop_safety",
            model="m9_short_circuit",
            t0=t0,
            terminal_reason="duplicate_failure",
        )

    session_key = _api_session_key(source, session_id)
    with _API_HISTORY_LOCK:
        history = list(_API_HISTORIES.get(session_key, [])) if session_key else []

    api_user_text = _api_prompt(
        prompt,
        source=prompt_source,
        page_context=page_context,
        schedule_id=schedule_id,
        action_results=action_results,
        round_num=round_num,
        round_budget=round_budget,
        request_id=turn_id,
    )

    with _API_HANDLE_LOCK:
        _scripts_on_path()
        import master_ai as _m
        import capabilities as _caps
        import verifiers as _verifiers  # noqa: F401  -- resolved lazily by Capability.resolve_verifier(), imported here so import errors surface at request time, not mid-dispatch
        import prompt_versions as _pv

        captured_actions = []
        captured_blocked = []
        patches = []
        # Registry-handled actions get aggregated here for audit-row derivation
        # AFTER the with-block. Each entry is the full _action dict carrying
        # capability + verification_result metadata. captured_actions is
        # reassigned to _browser_only mid-dispatch, so registry actions need
        # their own sibling list to survive that reassignment.
        _registry_handled = []
        prev_mode = getattr(_m, "MODE", "plan")
        prev_pinned = getattr(_m, "PINNED_MODEL", None)

        def patch(name, value):
            if hasattr(_m, name):
                patches.append((name, getattr(_m, name)))
                setattr(_m, name, value)

        def collect_only(reply, history_ref, streamed=False, continue_after_tools=False):
            nonlocal captured_actions
            model = getattr(_m, "LAST_MODEL", "") or requested_model or "master-ai"
            captured_actions = _api_parse_actions(
                reply or "",
                model=model,
                source=source,
                session_id=session_id,
                schedule_id=schedule_id,
                page_context=page_context,
            )
            return reply

        def noninteractive_confirm(cmd="", *args, **kwargs):
            detail = cmd
            if not detail and args:
                detail = args[0]
            captured_blocked.append({
                "kind": "ACTION",
                "target": str(detail or "")[:1000],
                "reason": "api_handle is non-interactive; action returned for extension confirmation",
            })
            try:
                return _m.RunResult(
                    "Blocked: API requests do not execute TUI-confirmed actions.",
                    ok=False,
                    exit_code=None,
                    command=str(detail or ""),
                    error="api_non_interactive",
                )
            except Exception:
                return False

        def noninteractive_create(filepath, content="", *args, **kwargs):
            captured_blocked.append({
                "kind": "CREATE",
                "target": str(filepath or "")[:1000],
                "reason": "api_handle is non-interactive; create action returned for confirmation",
            })
            return False

        def noninteractive_edit(filepath, find_text="", replace_text="", *args, **kwargs):
            captured_blocked.append({
                "kind": "EDIT",
                "target": str(filepath or "")[:1000],
                "reason": "api_handle is non-interactive; edit action returned for confirmation",
            })
            return False

        try:
            patch("process_reply", collect_only)
            patch("confirm_run", noninteractive_confirm)
            patch("confirm_runterm", noninteractive_confirm)
            patch("confirm_create", noninteractive_create)
            patch("confirm_edit", noninteractive_edit)
            patch("_try_desktop_open_intent", lambda user_text: None)
            patch("_try_open_url_intent", lambda user_text: None)
            patch("handle_save_refresh", lambda history_ref: None)
            try:
                _m._LAST_BLOCKED_ACTION = {}
            except Exception:
                pass
            if mode_req:
                _m.MODE = mode_req
            if requested_model and requested_model != "master-ai":
                _m.PINNED_MODEL = requested_model
            reply = _m.handle(api_user_text, history)
            route = getattr(_m, "LAST_ROUTE", "") or "local"
            model = getattr(_m, "LAST_MODEL", "") or requested_model or "master-ai"
            if not captured_actions:
                captured_actions = _api_parse_actions(
                    reply or "",
                    model=model,
                    source=source,
                    session_id=session_id,
                    schedule_id=schedule_id,
                    page_context=page_context,
                )
            blocked_actions = _api_blocked_actions(_m, captured_blocked)

            # Chrome extension auto mode — server-side dispatch for non-BROWSER
            # directives. The extension only knows how to execute BROWSER_*;
            # RUN/RUNTERM/READ/CREATE/EDIT get run here through the real
            # master_ai handlers. Auto-mode gates still apply (policy,
            # cleanup-safety, blocked-patterns, hallucination guard, sudo
            # handoff, TTY-refusal for destructive). BROWSER_* stays in
            # captured_actions for the extension to dispatch on the page;
            # local output gets appended to the reply text.
            effective_mode = (mode_req or getattr(_m, "MODE", "plan") or "plan").lower()
            if source == "chrome_extension" and effective_mode == "auto":
                _real = {n: o for n, o in patches}
                for _name in ("confirm_run", "confirm_runterm", "confirm_create", "confirm_edit"):
                    if _name in _real:
                        setattr(_m, _name, _real[_name])
                _m.MODE = "auto"
                _server_out = []
                _browser_only = []
                for _action in captured_actions:
                    _kind = (_action.get("kind") or "").upper()
                    _target = _action.get("target") or ""
                    if _kind.startswith("BROWSER_"):
                        _browser_only.append(_action)
                        continue

                    # Registry consultation BEFORE generic dispatch. Matched
                    # capability owns the execution path (executor + verifier
                    # + audit metadata). Unmatched falls through to legacy
                    # dispatch below — keeps the registry opt-in during
                    # phase 1.
                    _decision = _caps.get_registry().lookup(_kind, _target)
                    if _decision.capability is not None:
                        _cap = _decision.capability
                        _action["capability"] = _cap.name
                        _action["decision_reason"] = _decision.reason
                        # Record at the top of the decision branch so refused,
                        # requires_confirmation, and executed branches all
                        # land in the audit aggregation. The _action dict is
                        # mutated by reference in each branch below, so at
                        # audit time this carries the final state.
                        _registry_handled.append(_action)
                        if not _decision.allow:
                            _server_out.append(f"[{_cap.name}] refused: {_decision.reason}")
                            _action["verification_result"] = None
                            _action["blocked_reason"] = _decision.reason
                            continue
                        if _decision.requires_confirmation:
                            # Don't execute server-side; surface as action
                            # card to the extension for confirm UI. Phase 2
                            # wires the actual confirm surface in side_panel.
                            _action["requires_confirmation"] = True
                            _action["risk_tier"] = _cap.risk_tier
                            _browser_only.append(_action)
                            continue
                        try:
                            _executor = _cap.resolve_executor()
                            # Prefer verify_target when the registry extracted
                            # a specific argument (e.g., bare app name for
                            # desktop.launch_app); otherwise pass the raw
                            # directive target.
                            _exec_arg = _decision.verify_target if _decision.verify_target else _target
                            _exec_result = _executor(_exec_arg)
                            _exec_stdout = getattr(_exec_result, "stdout", "") or ""
                            _verifier = _cap.resolve_verifier()
                            _verify_result = _verifier(
                                _decision.verify_target,
                                max_wait_s=_cap.verification_policy.max_wait_s,
                                poll_ms=_cap.verification_policy.poll_ms,
                            )
                            _action["verification_result"] = {
                                "ok": _verify_result.ok,
                                "observed": _verify_result.observed,
                                "elapsed_ms": _verify_result.elapsed_ms,
                                "reason": _verify_result.reason,
                            }
                            _lines = [f"$ {_target}"]
                            if _exec_stdout.strip():
                                _lines.append(_exec_stdout.rstrip())
                            if _verify_result.ok:
                                _lines.append(
                                    f"[{_cap.name}] verified: {_verify_result.observed} "
                                    f"({_verify_result.elapsed_ms}ms)"
                                )
                            else:
                                _lines.append(
                                    f"[{_cap.name}] not verified: {_verify_result.reason}"
                                )
                            _server_out.append("\n".join(_lines))
                        except Exception as _e:
                            _action["verification_result"] = None
                            _action["executor_error"] = str(_e)
                            _server_out.append(
                                f"[{_cap.name}] dispatch error: {type(_e).__name__}: {_e}"
                            )
                        continue

                    try:
                        if _kind == "RUN":
                            _r = _m.confirm_run(_target)
                            if _r is None:
                                _server_out.append(f"$ {_target}\n[blocked or refused]")
                            else:
                                _stdout = getattr(_r, "stdout", "") or ""
                                _ok = getattr(_r, "ok", True)
                                _suffix = "" if _ok else " (exit nonzero)"
                                _server_out.append(f"$ {_target}{_suffix}\n{_stdout}".rstrip())
                        elif _kind == "RUNTERM":
                            _m.confirm_runterm(_target)
                            _server_out.append(f"[RUNTERM] dispatched: {_target}")
                        elif _kind == "READ":
                            _expanded = os.path.expanduser(_target)
                            if hasattr(_m, "_read_path_ok"):
                                try:
                                    _read_ok, _reason = _m._read_path_ok(_expanded)
                                except Exception:
                                    _read_ok, _reason = True, ""
                                if not _read_ok:
                                    _server_out.append(f"[READ {_target}] blocked: {_reason}")
                                    continue
                            try:
                                with open(_expanded, "r", errors="replace") as _f:
                                    _content = _f.read()
                                if len(_content) > 4000:
                                    _content = _content[:4000] + f"\n... [truncated, {len(_content)} chars total]"
                                _server_out.append(f"READ {_target}:\n{_content}")
                            except Exception as _e:
                                _server_out.append(f"[READ {_target}] error: {_e}")
                        elif _kind == "CREATE":
                            _content_body = _action.get("content") or _action.get("body") or ""
                            _ok = _m.confirm_create(_target, _content_body)
                            _server_out.append(f"[CREATE {_target}] {'written' if _ok else 'blocked or refused'}")
                        elif _kind == "EDIT":
                            _find = _action.get("find") or _action.get("find_text") or ""
                            _replace = _action.get("replace") or _action.get("replace_text") or ""
                            _ok = _m.confirm_edit(_target, _find, _replace)
                            _server_out.append(f"[EDIT {_target}] {'applied' if _ok else 'blocked or refused'}")
                        else:
                            _browser_only.append(_action)
                    except Exception as _e:
                        _server_out.append(f"[{_kind} {_target}] dispatch error: {_e}")
                if _server_out:
                    reply = (reply or "") + "\n\n— server-dispatched output —\n" + "\n\n".join(_server_out)
                captured_actions = _browser_only

            try:
                _m._LAST_BLOCKED_ACTION = {}
            except Exception:
                pass
        finally:
            for name, old in reversed(patches):
                try:
                    setattr(_m, name, old)
                except Exception:
                    pass
            try:
                _m.MODE = prev_mode
                _m.PINNED_MODEL = prev_pinned
            except Exception:
                pass

    if session_key:
        with _API_HISTORY_LOCK:
            _API_HISTORIES[session_key] = _trim_api_history(history)

    # M9 termination signal. Browser actions keep the turn open until the
    # extension reports real results; DONE is terminal only with no actions.
    round_remaining = max(0, round_budget - round_num)
    done, terminal_reason = _api_terminal_state(reply, captured_actions, round_remaining)

    # Register this turn so a continuation request can find it.
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    with _API_TURNS_LOCK:
        _API_TURNS[turn_id] = {
            "session_key": session_key,
            "round_num": round_num,
            "round_budget": round_budget,
            "turn_root": turn_root or turn_id,
            "parent_turn_id": parent_turn_id or None,
            "created_at": now_iso,
            "done": done,
        }
        # Bounded registry — drop oldest entries if it grows past 256.
        if len(_API_TURNS) > 256:
            oldest = sorted(_API_TURNS.items(), key=lambda kv: kv[1].get("created_at", ""))[:64]
            for k, _ in oldest:
                _API_TURNS.pop(k, None)

    # M9 turn-level audit on terminal rounds only. Mid-loop rounds (done=false)
    # stay out of the JSONL — only the closing row per turn-root is recorded,
    # so behavioral analytics can query terminal_reason ∈ {done_directive,
    # no_actions, budget, duplicate_failure} per goal without filtering noise.
    if done:
        # Phase 1 audit-column extensions per
        # ~/.claude/plans/reactive-waddling-papert.md:
        # - task_id / correlation_id / causation_id: explicit aliases over the
        #   existing turn_id / turn_root / parent_turn_id so audit queries can
        #   join across the agentic vocabulary the rest of the system uses.
        # - capabilities_fired / verification_results: aggregated from
        #   _registry_handled so a single audit row carries the full evidence
        #   chain for the turn (capability name + full VerifyResult shape:
        #   ok, observed, elapsed_ms, reason). Forward-only: old rows without
        #   these fields stay valid; readers tolerate missing keys.
        # - prompt_version family: content-hash-first stamping from the
        #   system-prompt assembly site in master_ai.py, so behavior can be
        #   correlated to the exact config that produced it.
        try:
            import prompt_versions as _pv_audit
            _pv_dict = _pv_audit.current()
        except Exception:
            _pv_dict = {}
        _write_turn_audit({
            "ts": now_iso,
            "source": "api_handle",
            "kind": "turn_terminal",
            "turn_id": turn_id,
            "task_id": turn_id,
            "turn_root": turn_root or turn_id,
            "correlation_id": turn_root or turn_id,
            "parent_turn_id": parent_turn_id or None,
            "causation_id": parent_turn_id or None,
            "round_num": round_num,
            "round_budget": round_budget,
            "terminal_reason": terminal_reason,
            "route": route,
            "model": model,
            "actions_count": len(captured_actions),
            "blocked_count": len(blocked_actions),
            "capabilities_fired": [a.get("capability") for a in _registry_handled if a.get("capability")],
            "verification_results": [a.get("verification_result") for a in _registry_handled if a.get("verification_result")],
            "prompt_version": _pv_dict.get("prompt_version"),
            "prompt_sha256_short": _pv_dict.get("prompt_sha256_short"),
            "git_commit_short": _pv_dict.get("git_commit_short"),
            "registry_version": _pv_dict.get("registry_version"),
            "safety_policy_version": _pv_dict.get("safety_policy_version"),
        })

    return {
        "reply": reply or "",
        "route": route,
        "model": model,
        "latency_ms": int((time.time() - t0) * 1000),
        "actions": captured_actions,
        "blocked_actions": blocked_actions,
        "turn_id": turn_id,
        "turn_root": turn_root or turn_id,
        "round_num": round_num,
        "round_budget": round_budget,
        "round_remaining": round_remaining,
        "done": done,
        "terminal_reason": terminal_reason,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

def safe_filename(name):
    name = re.sub(r'[^\w\s-]', '', name).strip()
    return re.sub(r'\s+', '_', name)[:60]

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPTS, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # Bare / would show a directory listing of cwd (privacy leak); send to Pupil.
        if self.path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', '/pupil.html')
            self.end_headers()
            return

        # /sdcpp/* → reverse-proxy to local sd-server on 127.0.0.1:7860.
        # Keeps the image engine loopback-bound while letting Pupil reach it
        # from any host that can reach :8080 (LAN, Tailscale). Same-origin.
        if self.path.startswith('/sdcpp/'):
            return self._proxy_sdcpp()

        # /project_summary?name=X[&refresh=1] — precomputed project briefing.
        # Reads the project's PROJECTS.md block + recent sessions, asks local
        # Ollama for a 5-bullet summary, caches under
        # ~/.master_ai_briefings/<slug>.json (or per-profile equivalent).
        # Returned immediately from cache when fresh (<6h); regenerated when
        # stale or when ?refresh=1. This is the "AI pre-reads your stuff so
        # you don't wait at the door" mechanism.
        if self.path == '/pupil.webmanifest':
            try:
                body = json.dumps({
                    'name': 'Pupil - Master AI',
                    'short_name': 'Pupil',
                    'description': 'Master AI browser UI for iOS, Android, and desktop.',
                    'start_url': '/pupil.html',
                    'scope': '/',
                    'display': 'standalone',
                    'orientation': 'portrait',
                    'background_color': '#F0F6FF',
                    'theme_color': '#2266CC',
                    'icons': [
                        {'src': '/pupil-icon.svg', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any maskable'}
                    ],
                }).encode()
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/manifest+json')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path == '/pupil-icon.svg':
            try:
                svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#2266CC"/>
<circle cx="256" cy="206" r="98" fill="#F0F6FF"/>
<path d="M138 374c20-70 69-108 118-108s98 38 118 108" fill="none" stroke="#F0F6FF" stroke-width="54" stroke-linecap="round"/>
<path d="M174 190h164" stroke="#042C53" stroke-width="34" stroke-linecap="round"/>
<circle cx="222" cy="218" r="15" fill="#042C53"/>
<circle cx="290" cy="218" r="15" fill="#042C53"/>
</svg>'''.encode()
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'image/svg+xml')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Content-Length', len(svg))
                self.end_headers()
                self.wfile.write(svg)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path == '/pupil-sw.js':
            try:
                body = b"""const CACHE = 'pupil-shell-v1';
const ASSETS = ['/pupil.html', '/pupil.webmanifest', '/pupil-icon.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('/pupil.html'))));
});
"""
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path.startswith('/project_summary'):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                name = (qs.get('name', [''])[0] or '').strip()
                force = qs.get('refresh', ['0'])[0] == '1'
                if not name:
                    self._json({'error': 'missing name param'}, 400); return

                # Profile-aware cache dir
                active_profile = ''
                try: active_profile = open(os.path.expanduser('~/.master_ai_active_profile')).read().strip()
                except Exception: pass
                if active_profile and os.path.isdir(os.path.expanduser(f'~/.master_ai_profiles/{active_profile}')):
                    cache_dir = os.path.expanduser(f'~/.master_ai_profiles/{active_profile}/briefings')
                else:
                    cache_dir = os.path.expanduser('~/.master_ai_briefings')
                os.makedirs(cache_dir, exist_ok=True)

                slug = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').lower()
                cache_path = os.path.join(cache_dir, slug + '.json')

                # Return cached if fresh and not forced
                import time as _time
                if (not force) and os.path.exists(cache_path):
                    try:
                        cached = json.load(open(cache_path))
                        if _time.time() - cached.get('cached_at', 0) < 6 * 3600:
                            cached['source'] = 'cache'
                            self._json(cached); return
                    except Exception:
                        pass

                # Build context: PROJECTS.md block + last 3 session tails
                pfile = os.path.expanduser('~/scripts/PROJECTS.md')
                block = ''
                try:
                    in_p = False
                    for ln in open(pfile).read().splitlines():
                        if ln.strip() == f'### {name}':
                            in_p = True; continue
                        if in_p and (ln.startswith('### ') or ln.startswith('## ')):
                            break
                        if in_p: block += ln + '\n'
                except Exception:
                    block = '(no PROJECTS.md entry)'

                sessions_tail = ''
                sessions_dir = os.path.expanduser('~/scripts/sessions')
                if os.path.isdir(sessions_dir):
                    logs = sorted(
                        [f for f in os.listdir(sessions_dir) if f.endswith('.log')],
                        key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
                        reverse=True
                    )[:3]
                    for f in logs:
                        try:
                            tail = open(os.path.join(sessions_dir, f)).read()[-2500:]
                            sessions_tail += f'\n=== {f} ===\n{tail}\n'
                        except Exception:
                            pass

                # Ask local Ollama for a bulletin
                # Trim inputs — shorter prompt = faster cold start.
                # The 7B coder model loads quicker than the 14B master model
                # and is fine for a 5-bullet summarization.
                block_trim = block[:1500]
                tail_trim = sessions_tail[-2500:] if sessions_tail else ''
                prompt = f"""Project briefing for someone returning after a break.
Project: {name}
Board:
{block_trim}

Recent snippet:
{tail_trim}

Output EXACTLY 5 short bullets, each starting with "- ". No preamble. No closing.
- state in one line
- what's blocking in one line
- last thing done in one line
- next move in one line
- anything easy to forget in one line"""
                summary_text = ''
                try:
                    req = urllib.request.Request(
                        'http://localhost:11434/api/generate',
                        data=json.dumps({
                            'model': 'qwen2.5:3b',
                            'prompt': prompt,
                            'stream': False,
                            'keep_alive': 0,
                            'options': {'num_predict': 140, 'temperature': 0.3},
                        }).encode(),
                        headers={'Content-Type': 'application/json'},
                    )
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        data = json.loads(resp.read().decode())
                        summary_text = data.get('response', '').strip()
                except Exception as _e:
                    summary_text = f'(briefing generation failed: {_e}) — fallback to project board below.'

                payload = {
                    'name': name,
                    'summary': summary_text,
                    'project_block': block,
                    'cached_at': int(_time.time()),
                    'source': 'fresh',
                }
                # Only cache SUCCESSFUL briefings so a cold-Ollama timeout on
                # first try doesn't stick. Next request retries.
                if not summary_text.startswith('(briefing generation failed'):
                    with open(cache_path, 'w') as f:
                        json.dump(payload, f, indent=2)
                self._json(payload); return
            except Exception as e:
                self._error(str(e)); return

        # /sys — quick RAM + swap + loaded-model snapshot for the Pupil
        # sidebar. Cheap to compute; cheap to poll every 5s. Lets the user
        # see pressure before they open a third tab.
        if self.path == '/sys':
            try:
                mem = {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'swap_used_mb': 0}
                try:
                    with open('/proc/meminfo') as f:
                        m = {}
                        for line in f:
                            k, _, v = line.partition(':')
                            v = v.strip().split()[0]
                            m[k] = int(v) // 1024   # KB → MB
                    mem['total_mb']     = m.get('MemTotal', 0)
                    mem['available_mb'] = m.get('MemAvailable', 0)
                    mem['used_mb']      = mem['total_mb'] - mem['available_mb']
                    mem['swap_used_mb'] = m.get('SwapTotal', 0) - m.get('SwapFree', 0)
                except Exception:
                    pass
                # Ask Ollama what's currently loaded (returns fast even cold)
                loaded = []
                try:
                    req = urllib.request.Request('http://localhost:11434/api/ps')
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        d = json.loads(resp.read().decode())
                        for m in d.get('models', []):
                            loaded.append({
                                'name': m.get('name'),
                                'size_mb': int(m.get('size_vram', m.get('size', 0))) // (1024*1024),
                            })
                except Exception:
                    pass
                self._json({'mem': mem, 'loaded_models': loaded})
            except Exception as e:
                self._error(str(e))
            return

        # Pupil API v1 — see ~/scripts/pupil_api.md.
        # /health — cheap liveness + Ollama reachability.
        if self.path == '/health':
            self._json(_health_payload())
            return

        # /status — richer state for the Pupil status card.
        if self.path == '/status':
            try:
                mode = 'plan'
                try:
                    mp = os.path.expanduser('~/.master_ai_mode')
                    if os.path.exists(mp):
                        v = open(mp).read().strip().lower()
                        if v in ('plan', 'review', 'auto'):
                            mode = v
                except Exception:
                    pass
                memory_facts = 0
                try:
                    mem_path = os.path.expanduser('~/.master_ai_memory')
                    if os.path.exists(mem_path):
                        with open(mem_path) as f:
                            memory_facts = sum(1 for _ in f)
                except Exception:
                    pass
                last_route = ''
                try:
                    rm = os.path.expanduser('~/.master_ai_router_metrics.jsonl')
                    if os.path.exists(rm):
                        with open(rm) as f:
                            last_line = ''
                            for line in f:
                                if line.strip():
                                    last_line = line
                            if last_line:
                                last_route = (json.loads(last_line).get('route') or '')
                except Exception:
                    pass
                # Reuse /sys logic for mem + loaded models
                mem = {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'swap_used_mb': 0}
                try:
                    with open('/proc/meminfo') as f:
                        m = {}
                        for line in f:
                            k, _, v = line.partition(':')
                            v = v.strip().split()[0]
                            m[k] = int(v) // 1024
                    mem['total_mb']     = m.get('MemTotal', 0)
                    mem['available_mb'] = m.get('MemAvailable', 0)
                    mem['used_mb']      = mem['total_mb'] - mem['available_mb']
                    mem['swap_used_mb'] = m.get('SwapTotal', 0) - m.get('SwapFree', 0)
                except Exception:
                    pass
                loaded = []
                try:
                    req = urllib.request.Request('http://127.0.0.1:11434/api/ps')
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        d = json.loads(resp.read().decode())
                        for m in d.get('models', []):
                            loaded.append({
                                'name': m.get('name'),
                                'size_mb': int(m.get('size_vram', m.get('size', 0))) // (1024*1024),
                            })
                except Exception:
                    pass
                self._json({
                    'mode': mode,
                    'model': 'master-ai',
                    'memory_facts': memory_facts,
                    'last_route': last_route,
                    'queue_depth': 0,
                    'loaded_models': loaded,
                    'mem': mem,
                    'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
                })
            except Exception as e:
                self._error(str(e))
            return

        # P1.7 /metrics — observability rollup over router metrics +
        # typed audit. Same summary the Sensei `stats` command renders;
        # Pupil can poll this to populate its stats panel.
        if self.path == '/metrics':
            try:
                import sys as _sys
                _scripts_dir = os.path.expanduser('~/scripts')
                if _scripts_dir not in _sys.path:
                    _sys.path.insert(0, _scripts_dir)
                import observability as _obs
                summary = _obs.summarize(limit=500)
                self._json(summary)
            except Exception as e:
                self._error(str(e))
            return

        # /events — SSE stream. P0.1 ships hello + heartbeat only.
        # Typed-action events (P0.4) and mode_changed (P1.4 wiring) come later.
        if self.path == '/events':
            try:
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                import time as _time
                def _write_event(name, payload):
                    msg = f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()
                    self.wfile.write(msg)
                    self.wfile.flush()
                _write_event('hello', {'ts': datetime.now().astimezone().isoformat(timespec='seconds')})
                # Bounded loop — exits on client disconnect (BrokenPipeError).
                # 15s heartbeat; max 1 hour per connection so a stuck client doesn't pin a thread.
                end = _time.time() + 3600
                while _time.time() < end:
                    _time.sleep(15)
                    _write_event('heartbeat', {'ts': datetime.now().astimezone().isoformat(timespec='seconds')})
            except _CLIENT_DISCONNECTS:
                pass
            except Exception:
                pass
            return

        # /thoughts — canonical Master AI voice (trademark quotes + tips +
        # thinking phrases). Shared by Sensei and Pupil so both UIs speak in
        # one accord. Source of truth: ~/scripts/master_ai_voice.json.
        if self.path == '/thoughts':
            try:
                vpath = os.path.expanduser('~/scripts/master_ai_voice.json')
                if os.path.exists(vpath):
                    data = json.load(open(vpath))
                else:
                    data = {}
                self._json(data); return
            except Exception as e:
                self._error(str(e)); return

        # /node_info — public info this node announces to mesh peers.
        # Returned from any /node_info GET (localhost or Tailscale).
        # Scaffolding only: no auth yet, no routing yet. Enough for a
        # peer to confirm "yes there's a Master AI at this IP".
        if self.path == '/node_info':
            try:
                import socket as _sk, platform as _pl
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                mesh_cfg = {}
                try:
                    if os.path.exists(mesh_path):
                        mesh_cfg = json.load(open(mesh_path))
                except Exception:
                    mesh_cfg = {}
                active_model = ''
                try:
                    am = os.path.expanduser('~/.master_ai_active_model')
                    if os.path.exists(am):
                        active_model = open(am).read().strip()
                except Exception:
                    pass
                info = {
                    'node_name': mesh_cfg.get('node_name') or _sk.gethostname(),
                    'version': 'master-ai v1.8-testing',
                    'platform': _pl.system().lower(),
                    'active_model': active_model or 'auto',
                    'profile': _active_profile(),
                    'ports': {'stt': 8080, 'ollama': 11434, 'tts': 5050},
                }
                self._json(info); return
            except Exception as e:
                self._error(str(e)); return

        # /peers — list of peer nodes this node knows about, read from
        # ~/.master_ai_mesh.json. No live ping here — that's a separate
        # client-side job. This just exposes the address book.
        if self.path == '/peers':
            try:
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                peers = []
                if os.path.exists(mesh_path):
                    cfg = json.load(open(mesh_path))
                    peers = cfg.get('peers', []) or []
                self._json({'peers': peers}); return
            except Exception as e:
                self._error(str(e)); return

        # /profile — return the active Master AI profile name (empty string if
        # none). Pupil uses this to namespace its localStorage so each user
        # gets their own settings/sessions in the browser.
        if self.path == '/profile':
            try:
                p = os.path.expanduser('~/.master_ai_active_profile')
                name = open(p).read().strip() if os.path.exists(p) else ''
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'profile': name}).encode())
            except Exception as e:
                self._error(str(e))
            return

        # /keys — bridge between menu 11's ~/.master_ai_keys and Pupil's
        # localStorage-based wizard. Only exposed on localhost; the underlying
        # file is already chmod 600 owned by the user. Returns the JSON as-is.
        # Pupil uses this so you don't have to paste the same key twice.
        if self.path == '/keys':
            try:
                keys_file = os.path.expanduser('~/.master_ai_keys')
                if os.path.exists(keys_file):
                    with open(keys_file) as f:
                        data = json.load(f)
                else:
                    data = {}
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self._error(str(e))
            return

        if self.path == '/sessions':
            try:
                chats = _chats_dir()
                all_files = os.listdir(chats)
                gz_files  = [f for f in all_files if f.endswith('.json.gz')]
                json_files = [f for f in all_files if f.endswith('.json') and not f.endswith('.gz')]
                files = sorted(
                    gz_files + json_files,
                    key=lambda f: os.path.getmtime(os.path.join(chats, f)),
                    reverse=True
                )
                sessions = []
                for f in files:
                    try:
                        path = os.path.join(chats, f)
                        if f.endswith('.json.gz'):
                            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                                data = json.load(fh)
                        else:
                            with open(path) as fh:
                                data = json.load(fh)
                        sessions.append({
                            'file': f,
                            'name': data.get('name', f),
                            'date': data.get('date', ''),
                            'ts':   data.get('ts', 0),
                            'source': data.get('source', 'Web UI'),
                            'messages': data.get('messages', [])
                        })
                    except Exception:
                        pass
                # Also load PC Control .log sessions from ~/scripts/sessions/
                pc_sessions_dir = os.path.join(SCRIPTS, 'sessions')
                if os.path.isdir(pc_sessions_dir):
                    for f in sorted(os.listdir(pc_sessions_dir), reverse=True):
                        if not f.endswith('.log'): continue
                        try:
                            path = os.path.join(pc_sessions_dir, f)
                            with open(path) as fh:
                                lines = fh.readlines()
                            msgs = []
                            for line in lines:
                                line = line.strip()
                                if line.startswith('[') and '] You: ' in line:
                                    msgs.append({'role':'user','content': line.split('] You: ',1)[1]})
                                elif line.startswith('[') and '] AI: ' in line:
                                    msgs.append({'role':'assistant','content': line.split('] AI: ',1)[1]})
                            if msgs:
                                ts = int(os.path.getmtime(path) * 1000)
                                sessions.append({
                                    'file': f,
                                    'name': f.replace('.log','').replace('_',' '),
                                    'date': datetime.fromtimestamp(ts/1000).strftime('%-m/%-d/%Y'),
                                    'ts': ts,
                                    'source': 'PC Control',
                                    'messages': msgs
                                })
                        except Exception:
                            pass
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(sessions).encode())
            except Exception as e:
                self._error(str(e))
        else:
            try:
                super().do_GET()
            except _CLIENT_DISCONNECTS:
                return

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data   = self.rfile.read(length)

        # /sdcpp/* → reverse-proxy to local sd-server (see do_GET note).
        if self.path.startswith('/sdcpp/'):
            return self._proxy_sdcpp(body=data)

        # /extension/action_result — extension reports outcome of a typed
        # BROWSER_* dispatch. Audit-only sink (the extension already executed
        # the action in the tab per Branch B; backend never reaches DOM).
        # Body: {action_id, verdict: accept|reject|timeout, result: success|
        # failure|blocked, final_state?}. Requires X-Master-AI-Token when
        # called from a chrome-extension origin.
        if self.path == '/extension/action_result':
            if not self._require_extension_auth():
                return
            try:
                payload = json.loads(data or b'{}')
            except Exception:
                return self._json({'error': 'bad json'}, 400)
            try:
                from pathlib import Path as _P
                import time as _t
                rec = {
                    'ts': _t.strftime('%Y-%m-%dT%H:%M:%S'),
                    'source': 'extension',
                    'kind': 'extension_action_result',
                    'action_id': payload.get('action_id'),
                    'verdict':   payload.get('verdict'),
                    'result':    payload.get('result'),
                    'final_state': payload.get('final_state'),
                    # M9.2: irreversible-action heuristic label from side_panel.js
                    # classifyBrowserAction. None when the action wasn't gated.
                    # Stored alongside the verdict so analytics can answer
                    # "how often does the user approve gated purchases vs deletes?"
                    'gated_by': (
                        payload.get('gated_by') if isinstance(payload.get('gated_by'), str)
                        else (payload.get('action') or {}).get('gated_by')
                    ),
                    'raw': payload,
                }
                with _P.home().joinpath('.master_ai_audit_typed.jsonl').open('a') as f:
                    f.write(json.dumps(rec) + '\n')
            except Exception:
                pass  # Audit is observability, not a blocker.
            return self._json({'ok': True})

        # /ask — federated routing endpoint. Accepts {prompt, model?} and runs
        # it through the LOCAL Ollama on this node, returning the response.
        # Auth: X-Mesh-Token header must match the token in ~/.master_ai_mesh.json.
        # No token configured → endpoint refuses all requests (fail-closed).
        # This is the mesh's "question on node A → answer from node B" pipe.
        if self.path == '/ask':
            try:
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                expected_token = ''
                if os.path.exists(mesh_path):
                    try:
                        expected_token = (json.load(open(mesh_path)).get('mesh_token') or '').strip()
                    except Exception:
                        expected_token = ''
                if not expected_token:
                    self._json({'error': 'mesh not configured (no mesh_token set in ~/.master_ai_mesh.json)'}, 503); return
                supplied = (self.headers.get('X-Mesh-Token') or '').strip()
                if supplied != expected_token:
                    self._json({'error': 'unauthorized (bad or missing X-Mesh-Token)'}, 401); return

                payload = json.loads(data or b'{}')
                prompt  = (payload.get('prompt') or '').strip()
                model   = (payload.get('model')  or 'qwen2.5:3b').strip()
                if not prompt:
                    self._json({'error': 'missing prompt'}, 400); return

                import urllib.request, time as _time
                t0 = _time.time()
                body = json.dumps({
                    'model': model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {'num_predict': 512, 'temperature': 0.7}
                }).encode()
                req = urllib.request.Request('http://localhost:11434/api/generate',
                    data=body, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                self._json({
                    'response': d.get('response', ''),
                    'model': model,
                    'elapsed_s': round(_time.time() - t0, 2),
                    'node': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
                }); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # Pupil API v1 — see ~/scripts/pupil_api.md.
        # POST /chat — Pupil's same-machine chat endpoint. No mesh-token gate.
        # M0a: non-interactive master_ai.handle() wrapper. It preserves the
        # v1 response shape while returning proposed actions for extension-side
        # confirmation; the backend never enters the TUI confirm_run path here.
        if self.path == '/chat':
            if not self._require_extension_auth():
                return
            try:
                payload = json.loads(data or b'{}')
                self._json(api_handle(payload)); return
            except ValueError as e:
                msg = str(e)
                status = 400 if msg in ('missing prompt', 'invalid mode') else 500
                self._json({'error': msg}, status); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # POST /chat/continue — M9 Agentic Continuation Loop (2026-05-12).
        # The extension calls this AFTER dispatching the prior round's actions
        # and reporting their results to /extension/action_result. Body shape:
        #   {parent_turn_id, action_results:[{action_id,verdict,result,final_state,action}],
        #    prompt?, session_id, source}
        # If prompt is omitted, a synthetic "continue" is used so the model
        # reads only the [PREVIOUS ROUND RESULTS] block and the user goal in
        # history. Round budget caps runaway loops; the response includes
        # `done` so the extension knows when to stop auto-continuing.
        if self.path == '/chat/continue':
            if not self._require_extension_auth():
                return
            try:
                payload = json.loads(data or b'{}')
                if not (payload.get("prompt") or "").strip():
                    payload["prompt"] = "continue"
                if not payload.get("parent_turn_id"):
                    self._json({'error': 'missing parent_turn_id'}, 400); return
                self._json(api_handle(payload)); return
            except ValueError as e:
                msg = str(e)
                status = 400 if msg in ('missing prompt', 'invalid mode', 'missing parent_turn_id') else 500
                self._json({'error': msg}, status); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # POST /mode — change current Sensei mode. Persists to ~/.master_ai_mode.
        if self.path == '/mode':
            try:
                payload = json.loads(data or b'{}')
                mode = (payload.get('mode') or '').strip().lower()
                if mode not in ('plan', 'review', 'auto'):
                    self._json({'error': 'invalid mode'}, 400); return
                mp = os.path.expanduser('~/.master_ai_mode')
                with open(mp, 'w') as f:
                    f.write(mode)
                self._json({'ok': True, 'mode': mode}); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # POST /voice — toggle Pupil TTS preference. Stored at ~/.master_ai_voice_enabled.
        if self.path == '/voice':
            try:
                payload = json.loads(data or b'{}')
                if 'enabled' not in payload or not isinstance(payload.get('enabled'), bool):
                    self._json({'error': "missing or invalid 'enabled' (must be boolean)"}, 400); return
                enabled = payload['enabled']
                engine = (payload.get('engine') or 'piper').strip() or 'piper'
                vp = os.path.expanduser('~/.master_ai_voice_enabled')
                with open(vp, 'w') as f:
                    json.dump({'enabled': enabled, 'engine': engine}, f)
                self._json({
                    'ok': True,
                    'voice_state': {'enabled': enabled, 'engine': engine},
                }); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # /fetch_url — Pupil's read-a-URL endpoint. Accepts {url} and
        # returns {url, markdown} by calling master_ai.firecrawl_fetch().
        # Needs a Firecrawl API key configured (see /keys). Different from
        # /web_search: that one returns snippets from many pages; this one
        # returns ONE page's full clean markdown content.
        if self.path == '/fetch_url':
            try:
                payload = json.loads(data or b'{}')
                url = (payload.get('url') or '').strip()
                if not url:
                    self._json({'error': 'missing url'}, 400); return
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                if _here not in _sys.path:
                    _sys.path.insert(0, _here)
                import master_ai as _m
                markdown = _m.firecrawl_fetch(url)
                self._json({'url': url, 'markdown': markdown}); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # /web_search — live web search for Pupil (the browser UI). Pupil
        # detects time-sensitive questions client-side and POSTs here so
        # the same Gemini-grounded-then-DDG blend Sensei uses is available
        # in the browser. Returns {query, results, have_gemini} so Pupil
        # can display results and show the user which engine answered.
        # No auth — localhost / Tailscale only. No secrets returned.
        if self.path == '/web_search':
            try:
                payload = json.loads(data or b'{}')
                query = (payload.get('query') or '').strip()
                # engine: optional. "all" or omitted → full blender.
                # Anything else → single engine, header-wrapped so the
                # downstream detection dict still reports which answered.
                engine = (payload.get('engine') or '').strip().lower()
                # stream: when true AND running the blend, emit NDJSON
                # lines live — one per engine as it completes — so the
                # client can show results progressively instead of
                # waiting for the slowest engine (Gemini, ~20s).
                stream = bool(payload.get('stream'))
                if not query:
                    self._json({'error': 'missing query'}, 400); return
                # Import master_ai lazily — avoids a heavy import at server
                # startup and keeps stt_server functional even if master_ai
                # has a runtime issue.
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                if _here not in _sys.path:
                    _sys.path.insert(0, _here)
                import master_ai as _m
                _engine_map = {
                    'gemini_grounded':    (_m.gemini_grounded_search, '[Google (via Gemini grounding)]'),
                    'brave':              (_m.brave_search,            '[Brave Search]'),
                    'serper':             (_m.serper_search,           '[Google (via Serper)]'),
                    'wikipedia':          (_m.wikipedia_search,        '[Wikipedia]'),
                    'duckduckgo':         (_m.duckduckgo_search,       '[DuckDuckGo]'),
                    'duckduckgo_instant': (_m.ddg_instant_answer,      '[DuckDuckGo Instant Answer]'),
                    'wikihow':            (_m.wikihow_via_gemini,      '[WikiHow (via Google site:)]'),
                }

                # ── Live-stream path ──
                # NDJSON over a Connection: close response. Each engine
                # emits start / done / empty / error. Client parses
                # line-by-line and renders as it reads. Fast engines
                # (Wikipedia ~1s) show up long before slow ones (Gemini).
                if stream and (not engine or engine == 'all'):
                    self.send_response(200)
                    self._cors()
                    self.send_header('Content-Type', 'application/x-ndjson')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Accel-Buffering', 'no')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    def _emit(obj):
                        try:
                            self.wfile.write((json.dumps(obj) + '\n').encode())
                            self.wfile.flush()
                        except Exception:
                            pass
                    _emit({'type': 'start', 'query': query,
                           'engines': list(_engine_map.keys())})
                    for key, (fn, header) in _engine_map.items():
                        _emit({'type': 'engine_start', 'engine': key})
                        try:
                            out = fn(query)
                        except Exception as e:
                            _emit({'type': 'engine_error', 'engine': key,
                                   'error': str(e)})
                            continue
                        if out:
                            _emit({'type': 'engine_done', 'engine': key,
                                   'header': header, 'result': out})
                        else:
                            _emit({'type': 'engine_empty', 'engine': key})
                    _emit({'type': 'done'})
                    return

                if engine and engine != 'all' and engine in _engine_map:
                    fn, header = _engine_map[engine]
                    out = fn(query)
                    results = f"{header}\n{out}" if out else f"Search unavailable: {engine} returned nothing."
                else:
                    results = _m.web_search(query)
                # Report which engines contributed so Pupil can show a
                # badge listing exactly what answered. Detection is by
                # the section headers master_ai.web_search() emits.
                r = results or ''
                engines = {
                    'gemini_grounded':     '[Google (via Gemini grounding)]' in r,
                    'brave':               '[Brave Search]' in r,
                    'serper':              '[Google (via Serper)]' in r,
                    'wikipedia':           '[Wikipedia]' in r,
                    'duckduckgo':          '[DuckDuckGo]' in r,
                    'duckduckgo_instant':  '[DuckDuckGo Instant Answer]' in r,
                    'wikihow':             '[WikiHow (via Google site:)]' in r,
                }
                self._json({
                    'query': query,
                    'results': results,
                    'engines': engines,
                }); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        if self.path == '/stt':
            if not self._require_extension_auth():
                return
            tmp = tempfile.NamedTemporaryFile(suffix='.webm', delete=False)
            tmp.write(data)
            tmp.close()
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    import whisper
                    model = whisper.load_model('base')
                    result = model.transcribe(tmp.name)
                text = result['text'].strip()
                self._json({'text': text})
            except Exception as e:
                self._json({'error': str(e)}, 500)
            finally:
                try: os.unlink(tmp.name)
                except Exception: pass

        elif self.path == '/sessions':
            try:
                chats = _chats_dir()
                session = json.loads(data)
                name    = session.get('name', 'chat')
                ts      = session.get('ts', int(datetime.now().timestamp() * 1000))
                fname   = f"{ts}_{safe_filename(name)}.json.gz"
                with gzip.open(os.path.join(chats, fname), 'wt', encoding='utf-8') as f:
                    json.dump(session, f, separators=(',', ':'))
                # Auto-generate summary via local AI
                try:
                    import urllib.request
                    msgs = session.get('messages', [])
                    if len(msgs) >= 4:
                        transcript = "\n".join(
                            f"{m['role'].upper()}: {str(m.get('content',''))[:300]}"
                            for m in msgs[-30:] if m.get('role') in ('user','assistant')
                        )
                        prompt = ("Summarize this AI session in exactly 4 bullets. "
                                  "What was worked on, decided, unfinished, next steps. "
                                  "Format: • bullet\n\n" + transcript)
                        payload = json.dumps({'model':'qwen2.5:7b',
                                              'messages':[{'role':'user','content':prompt}],
                                              'stream':False}).encode()
                        req = urllib.request.Request('http://localhost:11434/api/chat',
                            data=payload, headers={'Content-Type':'application/json'})
                        with urllib.request.urlopen(req, timeout=30) as r:
                            summary = json.loads(r.read())['message']['content'].strip()
                        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        summary_fname = fname.replace('.json.gz', '.summary')
                        summary_path = os.path.join(chats, summary_fname)
                        with open(summary_path, 'w') as sf:
                            sf.write(f"[Session {date_str}]\n{summary}\n")
                        # Append to memory (profile-aware)
                        prof = _active_profile()
                        if prof:
                            mem_file = os.path.expanduser(f"~/.master_ai_profiles/{prof}/memory")
                        else:
                            mem_file = os.path.expanduser("~/.master_ai_memory")
                        try:
                            existing = open(mem_file).read() if os.path.exists(mem_file) else ""
                            lines = [l for l in existing.splitlines() if not l.startswith("[Session ")]
                            session_lines = [l for l in existing.splitlines() if l.startswith("[Session ")][-4:]
                            with open(mem_file, 'w') as mf:
                                mf.write("\n".join(lines + session_lines +
                                    [f"[Session {date_str}]"] + summary.splitlines()) + "\n")
                        except Exception:
                            pass
                except Exception:
                    pass
                self._json({'saved': fname})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif self.path == '/keys':
            # Merge incoming key(s) into ~/.master_ai_keys. Body shape:
            #   {"field": "groq", "value": "gsk_..."} — sets one
            #   OR {"merge": {"groq": "...", "openai": "..."}} — merges many
            # Duplicate protection: if a value for "field" exists and differs,
            # it becomes "{field}_2" instead of overwriting.
            try:
                payload   = json.loads(data)
                keys_file = os.path.expanduser('~/.master_ai_keys')
                try:
                    existing = json.load(open(keys_file)) if os.path.exists(keys_file) else {}
                except Exception:
                    existing = {}
                incoming = {}
                if isinstance(payload.get('merge'), dict):
                    incoming.update(payload['merge'])
                if payload.get('field') and payload.get('value') is not None:
                    incoming[payload['field']] = payload['value']
                for field, value in incoming.items():
                    if field in existing and existing[field] and existing[field] != value:
                        existing[field + '_2'] = value   # backup slot
                    else:
                        existing[field] = value
                with open(keys_file, 'w') as f:
                    json.dump(existing, f, indent=2)
                os.chmod(keys_file, 0o600)
                self._json({'saved': list(incoming.keys()), 'count': len(existing)})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif self.path == '/sessions/delete':
            try:
                payload = json.loads(data)
                fname   = os.path.basename(payload.get('file', ''))
                chats   = _chats_dir()
                # support both .json and .json.gz
                path    = os.path.join(chats, fname)
                if not (fname and os.path.exists(path)):
                    alt = fname + '.gz' if not fname.endswith('.gz') else fname[:-3]
                    path = os.path.join(chats, alt)
                    fname = alt
                if fname and os.path.exists(path):
                    os.unlink(path)
                    self._json({'deleted': fname})
                else:
                    self._json({'error': 'not found'}, 404)
            except Exception as e:
                self._json({'error': str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(status)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_DISCONNECTS:
            return

    def _error(self, msg):
        self._json({'error': msg}, 500)

    def _cors(self):
        """Origin-aware CORS (M0a hardening 2026-05-12).
        - chrome-extension://... → echo Origin back; requests must carry X-Master-AI-Token.
        - Same-origin (no Origin header) → no Allow-Origin needed; browser allows.
        - Same-host (Pupil from LAN/Tailscale IPs matching request Host) → echo.
        - Anything else → no Allow-Origin → browser blocks.
        """
        origin = self.headers.get('Origin', '') or ''
        if origin.startswith('chrome-extension://'):
            self.send_header('Access-Control-Allow-Origin', origin)
        elif origin:
            host = self.headers.get('Host', '') or ''
            try:
                from urllib.parse import urlsplit
                o_netloc = urlsplit(origin).netloc
                if o_netloc and (o_netloc == host or o_netloc.split(':')[0] == host.split(':')[0]):
                    self.send_header('Access-Control-Allow-Origin', origin)
            except Exception:
                pass
        # else: no Origin header (same-origin) — nothing to echo.
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Master-AI-Token, X-Mesh-Token')

    def _extension_token(self):
        """Read the shared token from ~/.master_ai_extension_token. Cached on the class."""
        cls = self.__class__
        if not hasattr(cls, '_EXT_TOKEN'):
            try:
                from pathlib import Path
                cls._EXT_TOKEN = Path.home().joinpath('.master_ai_extension_token').read_text().strip() or None
            except Exception:
                cls._EXT_TOKEN = None
        return cls._EXT_TOKEN

    def _origin_is_extension(self):
        return (self.headers.get('Origin', '') or '').startswith('chrome-extension://')

    def _require_extension_auth(self):
        """If request comes from a chrome-extension origin, require a valid
        X-Master-AI-Token. Same-origin (Pupil) requests pass without a token.
        Returns True if the request should proceed; sends 401 and returns False otherwise."""
        if not self._origin_is_extension():
            return True  # Same-origin Pupil — legacy trust.
        sent = self.headers.get('X-Master-AI-Token', '') or ''
        expected = self._extension_token()
        if expected and sent and sent == expected:
            return True
        self.send_response(401)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            self.wfile.write(b'{"error":"extension token required"}')
        except Exception:
            pass
        return False

    def _proxy_sdcpp(self, body=b""):
        """Reverse-proxy /sdcpp/* to local sd-server on 127.0.0.1:7860.

        Keeps sd-server loopback-bound while letting Pupil reach it from any
        host that can reach :8080 (LAN, Tailscale). Same-origin → no CORS.
        Times: image gens take ~56s on this CPU, so timeout is generous.
        """
        upstream = "http://127.0.0.1:7860" + self.path
        req_headers = {}
        ct = self.headers.get("Content-Type")
        if ct:
            req_headers["Content-Type"] = ct
        try:
            req = urllib.request.Request(
                upstream, data=(body if body else None),
                headers=req_headers, method=self.command)
            with urllib.request.urlopen(req, timeout=180) as r:
                status = r.status
                up_ct = r.headers.get("Content-Type", "application/octet-stream")
                payload = r.read()
        except urllib.error.HTTPError as e:
            status = e.code
            up_ct = e.headers.get("Content-Type", "text/plain")
            payload = e.read() or str(e).encode()
        except Exception as e:
            status = 502
            up_ct = "application/json"
            payload = json.dumps({"error": f"sd-server unreachable: {e}"}).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", up_ct)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except _CLIENT_DISCONNECTS:
            pass

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    _prof = _active_profile()
    _prof_tag = f"  |  Profile: {_prof}" if _prof else ""
    print(f"🚀 Master AI server on :{port}  |  STT: Whisper  |  Sessions: {_chats_dir()}{_prof_tag}")
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
