"""Typed action envelope for Master AI directives (P0.4).

The legacy executor in master_ai.process_reply() parses ``RUN:``/``READ:``/
``CREATE:``/``EDIT:``/``RUNTERM:`` lines with regex and dispatches them
directly. That works, but the agent-standards report has flagged it as a
WARN: there is no typed boundary between "parsed text" and "action about
to run." Hooks (P1.4), subagents (P1.5), the observability dashboard
(P1.7), and the eventual sandbox layer (P2) all need a stable schema to
hang off.

This module provides that schema. It does NOT replace the legacy parser;
the existing executor still works on raw text. typed_actions.py is a
SUPERSET — callers that want structured access (audit jsonl, hooks,
subagents) build TypedAction objects via :func:`parse_directive` or
:func:`make_audit_record`. The legacy text path continues to operate
unchanged behind it.

Public API:

    TypedAction               — dataclass with the full lifecycle fields
    Kind, Risk, Status        — enum-like string constants
    parse_directive(line, …)  — single-line parser → TypedAction or None
    parse_reply(text, …)      — full reply parser → list[TypedAction]
    classify_risk(action)     — set/return action.risk from heuristics
    make_audit_record(...)    — snapshot dict suitable for jsonl writing
    audit_outcome_from_kind() — map legacy audit kinds → outcome string
    DIRECTIVE_KINDS           — frozenset of recognized kind tokens

No master_ai or router imports here — typed_actions stays standalone so
tests can import it without any side effects, and so hooks/subagents can
depend on it without pulling in the orchestrator.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


class Kind:
    RUN = "RUN"
    RUNTERM = "RUNTERM"
    READ = "READ"
    CREATE = "CREATE"
    EDIT = "EDIT"


class Risk:
    SAFE = "safe"       # READ, harmless RUN (ls, cat, file existence checks)
    NORMAL = "normal"   # RUN/RUNTERM/CREATE/EDIT with side effects
    HIGH = "high"       # destructive RUN (rm -rf, dd, mkfs, chmod -R 777, etc.)
    BLOCKED = "blocked" # safeguard refused; never executes


class Status:
    PARSED = "parsed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


DIRECTIVE_KINDS = frozenset({Kind.RUN, Kind.RUNTERM, Kind.READ, Kind.CREATE, Kind.EDIT})


# Heuristic patterns for risk classification. Conservative — false-positives
# (treating safe commands as HIGH) are fine because risk is observability +
# hooks input here, not authoritative enforcement. The real enforcement
# lives in master_ai.is_blocked / _cleanup_safety_issue / _SELF_MOD_DENYLIST.
_HIGH_RISK_RUN_PATTERNS = (
    re.compile(r"\brm\s+-[rRfF]+[a-zA-Z]*\s+/", re.I),       # rm -rf /path
    re.compile(r"\brm\s+-[rRfF]+\b(?!.*\.cache)", re.I),     # rm -rf without cache exception
    re.compile(r"\bdd\s+if=", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bchmod\s+-R\s+777\b", re.I),
    re.compile(r"\bchown\s+-R\s+root\b", re.I),
    re.compile(r">\s*/dev/sd[a-z]", re.I),
    re.compile(r">\s*/dev/nvme", re.I),
    re.compile(r"\bcurl\s.*\|\s*(?:bash|sh)\b", re.I),
    re.compile(r"\bwget\s.*\|\s*(?:bash|sh)\b", re.I),
)

_SAFE_RUN_PREFIXES = (
    "ls", "cat", "file", "head", "tail", "wc", "stat", "which", "type",
    "pwd", "echo", "date", "uptime", "uname", "id", "hostname", "df",
    "du", "free", "ps", "top", "true", "test ", "[ ",
)

_DIRECTIVE_LINE_RE = re.compile(
    r"^\s*(RUN|RUNTERM|READ|CREATE|EDIT):\s*(.*?)\s*$",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TypedAction:
    """Structured envelope around a single parsed directive.

    Lifecycle:
        PARSED → (PENDING_APPROVAL → APPROVED) → EXECUTING → COMPLETED
                                                          ↘ FAILED
        Any state can transition to BLOCKED (safeguard refused) or
        SKIPPED (mode-aware skip, e.g. plan-mode RUN: queue).
    """

    kind: str
    target: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cwd: Optional[str] = None
    risk: str = Risk.NORMAL
    requires_confirm: bool = True
    timeout_s: int = 60
    created_by_model: str = ""
    source_text: str = ""
    parsed_at: str = field(default_factory=_now_iso)
    status: str = Status.PARSED
    create_content: Optional[str] = None
    edit_old: Optional[str] = None
    edit_new: Optional[str] = None
    read_range: Optional[tuple] = None  # (start_line, end_line) inclusive
    extras: dict = field(default_factory=dict)

    def __post_init__(self):
        # Normalize kind case so callers can pass "run" or "RUN".
        if isinstance(self.kind, str):
            self.kind = self.kind.upper()
        if self.kind not in DIRECTIVE_KINDS:
            raise ValueError(f"unknown kind {self.kind!r}; expected one of {sorted(DIRECTIVE_KINDS)}")
        if not self.risk:
            self.risk = Risk.NORMAL

    def to_dict(self) -> dict:
        d = asdict(self)
        if isinstance(self.read_range, tuple):
            d["read_range"] = list(self.read_range)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TypedAction":
        if not isinstance(d, dict):
            raise TypeError(f"from_dict expects dict, got {type(d).__name__}")
        if "kind" not in d or "target" not in d:
            raise ValueError("TypedAction requires 'kind' and 'target'")
        d2 = dict(d)
        rr = d2.get("read_range")
        if isinstance(rr, list) and len(rr) == 2:
            d2["read_range"] = tuple(rr)
        known = {f for f in cls.__dataclass_fields__}
        extras_in = {k: v for k, v in d2.items() if k not in known}
        kwargs = {k: v for k, v in d2.items() if k in known}
        if extras_in:
            base_extras = kwargs.get("extras") or {}
            base_extras.update(extras_in)
            kwargs["extras"] = base_extras
        return cls(**kwargs)


def classify_risk(action: TypedAction) -> str:
    """Set and return action.risk based on kind + target heuristics.

    Conservative for RUN/RUNTERM: anything matching a destructive pattern
    is HIGH; the rest defaults to NORMAL (or SAFE for read-only commands).
    READ is always SAFE. CREATE/EDIT default to NORMAL — destination-path
    risk (self-modification of master_ai.py etc.) is enforced separately
    by master_ai._SELF_MOD_DENYLIST and is not duplicated here.
    """
    if action.kind == Kind.READ:
        action.risk = Risk.SAFE
        return action.risk
    if action.kind in (Kind.RUN, Kind.RUNTERM):
        t = (action.target or "").strip()
        low = t.lower()
        for pat in _HIGH_RISK_RUN_PATTERNS:
            if pat.search(t):
                action.risk = Risk.HIGH
                return action.risk
        if low.startswith("sudo "):
            action.risk = Risk.HIGH
            return action.risk
        first_token = low.split(None, 1)[0] if low else ""
        if first_token in {p.strip().rstrip() for p in _SAFE_RUN_PREFIXES if not p.endswith(" ")} or any(
            low.startswith(p) for p in _SAFE_RUN_PREFIXES
        ):
            if "&&" not in t and ";" not in t and "|" not in t:
                action.risk = Risk.SAFE
                return action.risk
        action.risk = Risk.NORMAL
        return action.risk
    if action.kind in (Kind.CREATE, Kind.EDIT):
        action.risk = Risk.NORMAL
        return action.risk
    action.risk = Risk.NORMAL
    return action.risk


def parse_directive(line: str, *, model: str = "", source_text: str = "",
                    cwd: Optional[str] = None) -> Optional[TypedAction]:
    """Single-line parser. Returns a TypedAction if `line` matches one of the
    directive keywords on its own line, else None.

    Intentionally simpler than master_ai.process_reply's full parser: this
    is the helper subagents/hooks/audit consumers use, where the input is
    already isolated to one directive. Multi-line CREATE/EDIT bodies and
    backtick-parity edge cases stay in master_ai's parser; callers there
    can construct a TypedAction directly via the dataclass.
    """
    if not isinstance(line, str):
        return None
    m = _DIRECTIVE_LINE_RE.match(line)
    if not m:
        return None
    kind = m.group(1).upper()
    target = m.group(2).strip()
    if not target:
        return None
    action = TypedAction(
        kind=kind,
        target=target,
        cwd=cwd,
        created_by_model=model or "",
        source_text=source_text or line,
        requires_confirm=(kind in (Kind.RUN, Kind.RUNTERM, Kind.CREATE, Kind.EDIT)),
    )
    classify_risk(action)
    return action


def parse_reply(text: str, *, model: str = "",
                cwd: Optional[str] = None) -> list:
    """Parse a multi-line reply for directive lines. Multi-line CREATE/EDIT
    bodies are NOT reassembled here — use master_ai.process_reply for that.
    This helper is for single-line scans (audit, observability previews).
    """
    out: list = []
    if not isinstance(text, str):
        return out
    for raw in text.splitlines():
        action = parse_directive(raw, model=model, source_text=raw, cwd=cwd)
        if action is not None:
            out.append(action)
    return out


# Mapping from legacy audit kinds (master_ai._audit calls) to the typed
# outcome field. Keys are matched by exact match OR longest-prefix match,
# whichever is more specific.
_AUDIT_OUTCOME_MAP = {
    "RUN":                    ("RUN", Status.COMPLETED),
    "RUN-AUTO":               ("RUN", Status.COMPLETED),
    "RUN-ALWAYS":             ("RUN", Status.COMPLETED),
    "RUN-EMPTY":              ("RUN", Status.BLOCKED),
    "RUN-BLOCK":              ("RUN", Status.BLOCKED),
    "RUN-BLOCK-CLEANUP":      ("RUN", Status.BLOCKED),
    "RUN-BLOCK-MISSING":      ("RUN", Status.BLOCKED),
    "RUN-BLOCK-CONTINUATION": ("RUN", Status.BLOCKED),
    "RUN-SUDO-HANDOFF":       ("RUN", Status.PENDING_APPROVAL),
    "RUN-SUDO-RESUME":        ("RUN", Status.COMPLETED),
    "RUN-SUDO-SKIP":          ("RUN", Status.SKIPPED),
    "RUNTERM":                ("RUNTERM", Status.COMPLETED),
    "RUNTERM-EMPTY":          ("RUNTERM", Status.BLOCKED),
    "RUNTERM-BLOCK":          ("RUNTERM", Status.BLOCKED),
    "RUNTERM-REDIRECT":       ("RUNTERM", Status.COMPLETED),
    "RUNTERM-REDIRECT-DESKTOP": ("RUNTERM", Status.COMPLETED),
    "RUNTERM-BLOCK-CONTINUATION": ("RUNTERM", Status.BLOCKED),
    "RUNTERM-BLOCK-MISSING":  ("RUNTERM", Status.BLOCKED),
    "RUNTERM-EMPTY-PAYLOAD":  ("RUNTERM", Status.BLOCKED),
    "READ":                   ("READ", Status.COMPLETED),
    "READ-BLOCK":             ("READ", Status.BLOCKED),
    "CREATE":                 ("CREATE", Status.COMPLETED),
    "CREATE-BLOCK":           ("CREATE", Status.BLOCKED),
    "EDIT":                   ("EDIT", Status.COMPLETED),
    "EDIT-BLOCK":             ("EDIT", Status.BLOCKED),
    "DESKTOP-OPEN":           ("RUN", Status.COMPLETED),
    "DESKTOP-REDIRECT":       ("RUN", Status.COMPLETED),
    "POLICY-CMD-BLOCK":       ("RUN", Status.BLOCKED),
    "POLICY-RUNTERM-BLOCK":   ("RUNTERM", Status.BLOCKED),
    "POLICY-REQUEST-BLOCK":   ("REQUEST", Status.BLOCKED),
    "DENY-NO-TTY":            ("RUN", Status.BLOCKED),
    "DENY-EOF":               ("RUN", Status.BLOCKED),
}


def audit_outcome_from_kind(audit_kind: str) -> tuple:
    """Return (directive_kind, status) for a legacy audit kind string.

    Falls back to a best-guess prefix match for kinds not in the table.
    Returns (None, None) if no directive kind can be inferred (e.g. a
    non-directive audit line for menu navigation).
    """
    if not isinstance(audit_kind, str) or not audit_kind:
        return (None, None)
    if audit_kind in _AUDIT_OUTCOME_MAP:
        return _AUDIT_OUTCOME_MAP[audit_kind]
    # Longest-prefix fallback
    for prefix in ("RUNTERM", "RUN", "READ", "CREATE", "EDIT"):
        if audit_kind.upper().startswith(prefix):
            inferred_status = (
                Status.BLOCKED if "BLOCK" in audit_kind.upper()
                else Status.SKIPPED if "SKIP" in audit_kind.upper()
                else Status.PENDING_APPROVAL if "HANDOFF" in audit_kind.upper()
                else Status.COMPLETED
            )
            return (prefix, inferred_status)
    return (None, None)


def make_audit_record(*, kind: str, detail: str,
                      profile: str = "default",
                      mode: str = "",
                      cwd: str = "",
                      model: str = "",
                      action_id: Optional[str] = None) -> Optional[dict]:
    """Build a typed jsonl audit record from a legacy _audit() call.

    Returns None if the audit kind is NOT a directive kind (so callers can
    skip non-directive audit lines). The returned dict is JSON-serializable
    and stable across versions — adding fields here is a SemVer minor
    change; renaming or removing is major.
    """
    directive_kind, status = audit_outcome_from_kind(kind)
    if directive_kind is None or directive_kind == "REQUEST":
        return None
    detail = detail or ""
    try:
        action = TypedAction(
            kind=directive_kind,
            target=detail[:1000],
            cwd=cwd or None,
            created_by_model=model or "",
            source_text=detail[:200],
            status=status,
        )
        classify_risk(action)
    except ValueError:
        return None
    return {
        "id": action.id,
        "ts": _now_iso(),
        "profile": profile or "default",
        "mode": mode or "",
        "cwd": cwd or "",
        "audit_kind": kind,
        "kind": action.kind,
        "target": action.target,
        "risk": action.risk,
        "status": action.status,
        "created_by_model": action.created_by_model,
    }


def serialize(action: TypedAction) -> str:
    """JSON-encode a TypedAction for jsonl logs."""
    return json.dumps(action.to_dict(), default=str, sort_keys=True)
