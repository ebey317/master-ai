#!/usr/bin/env python3
"""
sensei_mcp_server.py — Sensei MCP for Claude Code (secretary-mode).

Six tools: chat, browse, click, fill, read, search.
3-tool limit only applies when local 7B is the brain. Max account = no limit.
JSON-RPC over stdio. Talks to the Sensei bridge at 127.0.0.1:8080.
"""

import json
import re
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, Iterator

# Optional universal form-fill engine lives in the CLAF tools directory.
_SFF_ERR = None
try:
    sys.path.insert(0, str(Path.home() / "projects/claf/tools"))
    import smart_form_fill as _sff
    _HAS_SFF = True
except Exception as _e:
    _HAS_SFF = False
    _sff = None
    _SFF_ERR = str(_e)

BRIDGE = "http://127.0.0.1:8080"
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
DEFAULT_SESSION = "mcp-default"
WAIT_SECONDS = 30
POLL_MS = 100
CLAF_HEALTHZ = os.environ.get("CLAF_URL", "http://127.0.0.1:8000").rstrip("/") + "/healthz"
OLLAMA_TAGS = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
LOG_PATH = os.environ.get("SENSEI_LOG", os.path.expanduser("~/scripts/sensei_mcp.log"))

# Mirror stderr to log file — same pattern as secretary_agent.py
try:
    _log_file = open(LOG_PATH, "a", buffering=1)
    _orig_stderr = sys.stderr

    class _Tee:
        def write(self, s):
            _orig_stderr.write(s)
            _log_file.write(s)
        def flush(self):
            _orig_stderr.flush()
            _log_file.flush()
        def __getattr__(self, name):
            return getattr(_orig_stderr, name)

    sys.stderr = _Tee()
except Exception:
    pass


def _log(msg: str):
    sys.stderr.write(f"[sensei] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# bridge helpers
# ---------------------------------------------------------------------------

def _http(method, path, body=None, timeout=5.0):
    url = f"{BRIDGE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return {"ok": True, "status": resp.status, "json": json.loads(raw)}
            except Exception:
                return {"ok": True, "status": resp.status, "text": raw}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _bridge_alive():
    r = _http("GET", "/extension/queue_state", timeout=1.0)
    return bool(r.get("ok"))

def _cdp_alive():
    r = _http_abs("GET", f"{CDP_URL}/json/version", timeout=1.0)
    return r.get("ok")


def _cdp_new_tab(url="about:blank"):
    import urllib.parse
    target = urllib.parse.quote(url, safe=":/?=&%#")
    r = _http_abs("PUT", f"{CDP_URL}/json/new?{target}", timeout=5.0)
    if r.get("ok"):
        tab = r.get("json") or {}
        return {"ok": True, "tab_id": tab.get("id"), "url": tab.get("url"), "title": tab.get("title")}
    return {"ok": False, "reason": r.get("error", "cdp_new_tab_failed")}


def _ensure_cdp():
    """Lazy-launch a CDP Chrome instance if none is listening on port 9222."""
    if _cdp_alive():
        return True
    import subprocess, time
    env = dict(__import__('os').environ, DISPLAY=':0')
    subprocess.Popen(
        ['google-chrome', '--remote-debugging-port=9222',
         '--user-data-dir=/tmp/chrome-cdp', '--no-first-run',
         '--no-default-browser-check'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(12):
        time.sleep(0.5)
        if _cdp_alive():
            return True
    return False

def _claf_alive():
    r = _http_abs("GET", CLAF_HEALTHZ, timeout=1.5)
    return bool(r.get("ok"))

def _ollama_alive():
    r = _http_abs("GET", OLLAMA_TAGS, timeout=1.5)
    return bool(r.get("ok"))

def _http_abs(method, url, body=None, timeout=5.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return {"ok": True, "status": resp.status, "json": json.loads(raw)}
            except Exception:
                return {"ok": True, "status": resp.status, "text": raw}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _push(action, session=DEFAULT_SESSION):
    _log(f"bridge push {action.get('kind')} session={session}")
    body = {"session_id": session, "actions": [action]}
    return _http("POST", "/extension/queue", body=body, timeout=3.0)


def _await_result(action_id, session=DEFAULT_SESSION, wait_seconds=WAIT_SECONDS):
    """Poll the bridge for a completed result. Returns the result dict or a
    timeout shape. Does not raise."""
    if not action_id:
        return {"ok": False, "reason": "no_action_id"}
    _log(f"await result action_id={action_id} timeout={wait_seconds}s")
    deadline = time.time() + wait_seconds
    last = None
    while time.time() < deadline:
        r = _http(
            "GET",
            f"/extension/result?session_id={session}&action_id={action_id}",
            timeout=2.0,
        )
        if r.get("ok") and r.get("json"):
            j = r["json"]
            # Only resolve when bridge confirms done (ok:true + result present).
            # Pending responses also carry action_id so can't use that as signal.
            if j.get("ok") and j.get("result") is not None:
                _log(f"result received action_id={action_id}")
                return j
            last = j
        time.sleep(POLL_MS / 1000.0)
    _log(f"await timeout action_id={action_id}")
    return {"ok": False, "reason": "timeout", "last": last}


def _action_id_from_push(push_response):
    """The bridge has shipped two shapes historically:
       - { action_id: "..." }
       - { action_ids: ["..."] }
       Accept either and return the single id or None."""
    if not push_response or not push_response.get("ok"):
        return None
    j = push_response.get("json") or {}
    aid = j.get("action_id")
    if isinstance(aid, str) and aid:
        return aid
    aids = j.get("action_ids")
    if isinstance(aids, list) and aids:
        return aids[0]
    return None


def _dispatch(kind, payload, session=DEFAULT_SESSION, wait=WAIT_SECONDS):
    """Push an action to the bridge and await the result. Returns a result
    dict shaped for the MCP content envelope."""
    _log(f"dispatch {kind} session={session}")
    if not _bridge_alive():
        return {"ok": False, "reason": "bridge_unreachable",
                "hint": "Open Chrome, click the Sensei icon, pin the side panel."}
    action = {"kind": kind, **payload}
    push = _push(action, session=session)
    if not push.get("ok"):
        return {"ok": False, "reason": "push_failed", "detail": push}
    aid = _action_id_from_push(push)
    result = _await_result(aid, session=session, wait_seconds=wait)
    if result.get("ok") and result.get("result") is not None:
        return result["result"]  # unwrap the bridge envelope
    return result


# ---------------------------------------------------------------------------
# tool handlers — each takes flat string parameters only
# ---------------------------------------------------------------------------

def tool_chat(args):
    msg = str(args.get("msg") or "")
    if not msg:
        return {"content": [{"type": "text", "text": "ok"}]}
    try:
        from sensei_router import ask_cloud
        messages = [{"role": "user", "content": msg}]
        reply = ask_cloud(messages, provider="groq") or msg
        return {"content": [{"type": "text", "text": reply}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"router error: {e}"}]}

def tool_health(args):
    # Keep this small and deterministic: Claude Code uses it as a physical
    # "is the domino chain wired" check.
    bridge = _bridge_alive()
    claf = _claf_alive()
    ollama = _ollama_alive()
    rep = {
        "ok": True,
        "bridge": bridge,
        "claf": claf,
        "ollama": ollama,
        "session_default": DEFAULT_SESSION,
    }
    return {"content": [{"type": "text", "text": json.dumps(rep)}]}


DEFAULT_BROWSE_URL = os.environ.get("SENSEI_DEFAULT_URL", "https://www.google.com")


def tool_browse(args):
    url = str(args.get("url") or "").strip()
    if not url:
        url = DEFAULT_BROWSE_URL
    if not url.startswith("http"):
        url = "https://" + url
    out = _dispatch("BROWSER_NAV", {"target": url})
    text = f"navigate {url} -> {json.dumps(out)[:600]}"
    return {"content": [{"type": "text", "text": text}]}


def tool_click(args):
    what = str(args.get("what") or "").strip()
    if not what:
        return {"content": [{"type": "text", "text": "click: what is required — pass the visible label, ref_N name, or CSS selector from the last read_full."}]}
    payload = {"target": what}
    if args.get("intercept_popup"):
        payload["intercept_popup"] = True
    out = _dispatch("BROWSER_CLICK", payload)
    text = f"click '{what}' -> {json.dumps(out)[:400]}"
    return {"content": [{"type": "text", "text": text}]}


def tool_fill(args):
    where = str(args.get("where") or "").strip()
    text = str(args.get("text") or "")
    if not where:
        return {"content": [{"type": "text", "text": "fill: where is required"}]}
    out = _dispatch("BROWSER_FILL", {"target": where, "value": text})
    rep = f"fill '{where}' = {text[:60]} -> {json.dumps(out)[:400]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_fill_form(args):
    """Universal form filler. X-rays the page, discovers every field, picks a
    sensible value, and fills it. Works around the extension's BROWSER_FILL
    value bug by using the :: delimiter internally."""
    if not _HAS_SFF:
        return {"content": [{"type": "text", "text": f"fill_form: smart_form_fill engine not available ({_SFF_ERR})"}]}

    dry_run = str(args.get("dry_run") or "").lower() in ("true", "1", "yes")
    submit = bool(args.get("submit"))

    profile = {}
    raw_profile = args.get("profile") or "{}"
    if isinstance(raw_profile, str):
        try:
            profile = json.loads(raw_profile)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"fill_form: profile must be valid JSON: {e}"}]}
    elif isinstance(raw_profile, dict):
        profile = raw_profile

    # Snapshot the page. _dispatch returns the bridge's inner envelope, so unwrap
    # one more level to reach the actual BROWSER_READ_PAGE_FULL result dict.
    page = _dispatch("BROWSER_READ_PAGE_FULL", {}, wait=20)
    page = page.get("result", page)
    url = page.get("url", "")
    title = page.get("title", "")
    soup = _sff._fetch_page_source(url) if url else None

    # Apply custom profile values to the engine defaults for this call.
    original_defaults = dict(_sff.DEFAULTS)
    _sff.DEFAULTS.update(profile)
    _sff.refresh_patterns()
    try:
        fields = _sff.discover_fields({"result": page})

        plan = []
        radio_groups = set()
        for field in fields:
            value, reason = _sff.decide_value(field, soup)
            radio_target = None
            if value is not None:
                src = _sff._source_lookup(field["selector"], soup) if soup else None
                if src and src.name == "input" and src.get("type", "").lower() == "radio":
                    name = src.get("name") or field["selector"]
                    if name in radio_groups:
                        value, reason = None, "radio: duplicate group member"
                    else:
                        radio_groups.add(name)
                        radio_target = f'input[name="{name}"][value="{value}"]'
            plan.append({**field, "value": value, "reason": reason, "radio_target": radio_target})

        if dry_run:
            lines = [f"fill_form plan for {title} ({url}):"]
            for p in plan:
                status = p["value"] if p["value"] is not None else "SKIP"
                lines.append(f"  {p['selector']:30} {p['type']:10} -> {status!r} ({p['reason']})")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        filled = skipped = failed = 0
        filled_sels = []
        for p in plan:
            if p["value"] is None:
                skipped += 1
                continue
            if p.get("radio_target"):
                out = _dispatch("BROWSER_CLICK", {"target": p["radio_target"], "intercept_popup": True})
            else:
                out = _dispatch("BROWSER_FILL", {"target": f"{p['selector']} :: {p['value']}"})
            inner = out.get("result", out)
            if inner.get("ok"):
                filled += 1
                filled_sels.append(p["selector"])
            else:
                failed += 1

        # Optional submit click.
        submit_result = None
        if submit:
            submit_sel = None
            for el in page.get("elements", []):
                if el.get("role") == "button" and "submit" in (el.get("name") or "").lower():
                    submit_sel = el.get("selector")
                    break
            if submit_sel:
                submit_result = _dispatch("BROWSER_CLICK", {"target": submit_sel, "intercept_popup": True})

        # Verify by re-reading.
        page2 = _dispatch("BROWSER_READ_PAGE_FULL", {}, wait=20)
        page2 = page2.get("result", page2)
        fields2 = {f["selector"]: f for f in _sff.discover_fields({"result": page2})}
        verified = 0
        for sel in filled_sels:
            f2 = fields2.get(sel)
            if f2 and f2.get("value_present"):
                verified += 1

        summary = (
            f"fill_form: {title}\n"
            f"  discovered: {len(fields)} | filled: {filled} | skipped: {skipped} | failed: {failed} | verified: {verified}/{len(filled_sels)}"
        )
        if submit_result:
            summary += f"\n  submit: {json.dumps(submit_result.get('result', submit_result))[:200]}"
        return {"content": [{"type": "text", "text": summary}]}
    finally:
        _sff.DEFAULTS.update(original_defaults)
        _sff.refresh_patterns()


def tool_read(args):
    out = _dispatch("BROWSER_READ_PAGE", {})
    rep = json.dumps(out)
    if len(rep) > 500:
        rep = rep[:500] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_get_dom(args):
    """Return the outerHTML of the current page or a selected element.
    selector: optional CSS selector (empty returns the whole page HTML)."""
    selector = str(args.get("selector") or "").strip()
    out = _dispatch("BROWSER_GET_DOM", {"selector": selector})
    inner = out.get("result", out) if isinstance(out, dict) else {}
    html = inner.get("html", "") if isinstance(inner, dict) else ""
    if len(html) > 5000:
        html = html[:5000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": json.dumps({"ok": bool(html), "html": html, "selector": selector})}]}


def tool_search(args):
    query = str(args.get("query") or "").strip()
    if not query:
        return {"content": [{"type": "text", "text": "search: query is required"}]}
    url = "https://www.google.com/search?q=" + query.replace(" ", "+")
    out = _dispatch("BROWSER_NAV", {"target": url})
    rep = f"search '{query}' -> {json.dumps(out)[:400]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_find_doc_link(args):
    """Fetch a docs landing page and return links whose URL or anchor text match a term.

    Use this when the user asks for documentation/help but didn't give the exact URL.
    Example: start_url='https://docs.anthropic.com/en/docs/claude-code/overview',
    term='cli reference'.
    """
    start_url = str(args.get("start_url") or "").strip()
    term = str(args.get("term") or "").strip().lower()
    if not start_url:
        return {"content": [{"type": "text", "text": "find_doc_link: start_url is required"}]}
    if not term:
        return {"content": [{"type": "text", "text": "find_doc_link: term is required"}]}
    try:
        req = urllib.request.Request(
            start_url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            base = resp.geturl()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"find_doc_link: fetch failed: {e}"}]}

    # Pull out href and link text, keep only http(s) links.
    matches = []
    seen = set()
    for m in re.finditer(r'<a\s+([^>]*?)href="([^"]+)"([^>]*)>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        attrs_before, href, attrs_after, text = m.groups()
        href = href.strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = urllib.parse.urljoin(base, href)
        if not abs_url.startswith(("http://", "https://")):
            continue
        # Strip simple HTML tags from anchor text.
        clean_text = re.sub(r"<[^>]+>", " ", text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        haystack = (abs_url + " " + clean_text).lower()
        if term not in haystack:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        matches.append({"url": abs_url, "text": clean_text[:120]})
        if len(matches) >= 10:
            break

    if not matches:
        return {"content": [{"type": "text", "text": f"find_doc_link: no links matched '{term}' on {base}"}]}
    lines = [f"find_doc_link: {len(matches)} matches for '{term}' on {base}"]
    for i, m in enumerate(matches, 1):
        lines.append(f"{i}. {m['url']} — {m['text']}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_run(args):
    cmd = str(args.get("cmd") or "").strip()
    if not cmd:
        return {"content": [{"type": "text", "text": "run: cmd is required"}]}
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        rep = out if out else err if err else "(no output)"
        if len(rep) > 800:
            rep = rep[:800] + " ...[truncated]"
        return {"content": [{"type": "text", "text": rep}]}
    except subprocess.TimeoutExpired:
        return {"content": [{"type": "text", "text": "run: timed out after 30s"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"run error: {e}"}]}


def tool_write_file(args):
    path = str(args.get("path") or "").strip()
    content = str(args.get("content") or "")
    if not path:
        return {"content": [{"type": "text", "text": "write_file: path is required"}]}
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return {"content": [{"type": "text", "text": f"wrote {len(content)} chars to {path}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"write_file error: {e}"}]}


def tool_read_file(args):
    path = str(args.get("path") or "").strip()
    if not path:
        return {"content": [{"type": "text", "text": "read_file: path is required"}]}
    path = os.path.expanduser(path)
    try:
        with open(path, "r") as f:
            content = f.read(4000)
        return {"content": [{"type": "text", "text": content}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"read_file error: {e}"}]}


def tool_screenshot(args):
    """Take a screenshot of the current browser page. Returns file path to saved PNG."""
    import base64, tempfile, time, urllib.request, urllib.error
    bridge = BRIDGE
    session = DEFAULT_SESSION

    # 1. Queue the action directly via the bridge HTTP API
    payload = json.dumps({
        "session_id": session,
        "actions": [{"kind": "BROWSER_SCREENSHOT", "session_id": session}]
    }).encode()
    try:
        req = urllib.request.Request(
            f"{bridge}/extension/queue",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            queued = json.loads(r.read())
    except Exception as e:
        return {"content": [{"type": "text", "text": f"screenshot queue error: {e}"}]}

    action_id = (queued.get("action_ids") or [""])[0]
    if not action_id:
        return {"content": [{"type": "text", "text": f"screenshot: no action_id returned: {queued}"}]}

    # 2. Poll for result (up to 12 s)
    deadline = time.time() + 12
    rec = None
    while time.time() < deadline:
        time.sleep(0.15)
        try:
            url = f"{bridge}/extension/result?action_id={action_id}&session_id={session}"
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            if data.get("ok") and data.get("status") != "pending":
                rec = data
                break
            if data.get("ok") is False and data.get("status") != "pending":
                break
        except Exception:
            pass

    if rec is None:
        return {"content": [{"type": "text", "text": "screenshot timed out waiting for bridge result"}]}

    # 3. Walk the result tree to find b64
    def _find_b64(obj):
        if isinstance(obj, dict):
            if obj.get("b64"):
                return obj["b64"]
            for v in obj.values():
                found = _find_b64(v)
                if found:
                    return found
        return ""

    b64 = _find_b64(rec)
    if not b64:
        return {"content": [{"type": "text", "text": f"screenshot: no b64 in result: {json.dumps(rec)[:400]}"}]}

    tmp = tempfile.mktemp(suffix=".png", prefix="/tmp/sensei_")
    try:
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(b64))
        return {"content": [{"type": "text", "text": f"screenshot saved: {tmp}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"screenshot decode error: {e}"}]}


def tool_scroll(args):
    """Scroll the current browser page. direction: up/down/top/bottom or pixel amount."""
    direction = str(args.get("direction") or "down").strip()
    out = _dispatch("BROWSER_SCROLL", {"target": direction})
    rep = f"scroll '{direction}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_js_eval(args):
    """Execute JavaScript in the current browser page. Returns result as text."""
    code = str(args.get("code") or "").strip()
    if not code:
        return {"content": [{"type": "text", "text": "js_eval: code is required"}]}
    out = _dispatch("BROWSER_JS", {"target": code})
    result = out.get("result", {})
    inner = result.get("result", result)
    val = inner.get("result", inner) if isinstance(inner, dict) else inner
    rep = json.dumps(val) if not isinstance(val, str) else val
    if len(rep) > 2000:
        rep = rep[:2000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_photos_search(args):
    """Navigate to Google Photos search and extract image URLs from the JS-rendered page."""
    query = str(args.get("query") or "biovega").strip()
    wait_sec = int(args.get("wait") or 4)
    url = f"https://photos.google.com/search/{query.replace(' ', '%20')}"
    # navigate
    nav = _dispatch("BROWSER_NAV", {"target": url})
    if not nav.get("ok"):
        return {"content": [{"type": "text", "text": f"photos_search: nav failed -> {json.dumps(nav)[:300]}"}]}
    # wait for JS to render thumbnails
    import time
    time.sleep(wait_sec)
    # extract image urls
    out = _dispatch("BROWSER_READ_IMAGES", {})
    result = out.get("result", {})
    # bridge wraps: result -> result -> final_state -> {count, images}
    inner = result.get("result", result)
    final_state = inner.get("final_state", inner)
    images = final_state.get("images") or []
    count = final_state.get("count", len(images))
    if not images:
        raw = json.dumps(out)[:800]
        return {"content": [{"type": "text", "text": f"photos_search '{query}': 0 images found. raw={raw}"}]}
    lines = [f"photos_search '{query}' at {url} -> {count} images found:"]
    for i, img in enumerate(images[:40]):
        lines.append(f"  [{i}] {img.get('url','')} ({img.get('w',0)}x{img.get('h',0)})")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def _resolve_profile_path(profile: dict, key_path: str):
    """Resolve a dot-notation key path into a profile value.

    "personal.first_name" → profile["personal"]["first_name"]
    "experience.0.employer" → profile["experience"][0]["employer"]
    Returns None if any segment is missing.
    """
    node = profile
    for segment in key_path.split("."):
        if isinstance(node, list):
            try:
                node = node[int(segment)]
            except (IndexError, ValueError):
                return None
        elif isinstance(node, dict):
            node = node.get(segment)
        else:
            return None
        if node is None:
            return None
    return node if isinstance(node, str) else str(node) if node is not None else None


def tool_autofill_job_form(args):
    """Layer 3 — Code-First/LLM-Last autofill for job application forms.

    Phase 1 (code-fill): fingerprint the ATS, look up its selector map,
    fill every standard field from ~/.master_ai_profile.json without LLM involvement.
    Phase 2 result: return the list of unfilled fields (essay/custom questions)
    for the LLM to generate targeted answers.

    Args:
        dry_run (str): "true" to simulate without writing to the page.
        session (str): optional session id for the bridge (default: mcp-default).
        profile_path (str): override path to the profile JSON.
    """
    import os, sys, pathlib

    import re as _re
    dry_run = str(args.get("dry_run") or "false").lower() in ("true", "1", "yes")
    session = str(args.get("session") or DEFAULT_SESSION)

    # client_name → auto-derive /tmp/profile_{slug}.json (business workflow)
    client_name = str(args.get("client_name") or "").strip()
    if client_name:
        slug = _re.sub(r"[^a-z0-9]+", "_", client_name.lower()).strip("_")
        profile_path = f"/tmp/profile_{slug}.json"
    else:
        profile_path = str(args.get("profile_path") or os.path.expanduser("~/.master_ai_profile.json"))

    # ── Load master profile ───────────────────────────────────────────────────
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
    except FileNotFoundError:
        return {"content": [{"type": "text", "text":
            f"autofill_job_form: profile not found at {profile_path}. "
            "Operator must curate ~/.master_ai_profile.json first."}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"autofill_job_form: profile load error: {e}"}]}

    # ── Read current page URL + content for fingerprinting ───────────────────
    read_out = _dispatch("BROWSER_READ", {}, session=session, wait=20)
    page_text = ""
    current_url = ""
    try:
        res = read_out.get("result", {})
        inner = res.get("result", res)
        final = inner.get("final_state", inner) if isinstance(inner, dict) else {}
        page_text = final.get("content") or final.get("text") or ""
        current_url = final.get("url") or ""
    except Exception:
        pass

    # ── Fingerprint ATS ───────────────────────────────────────────────────────
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _scripts_dir)
    try:
        from ats_fingerprint import fingerprint_ats
        from ats_maps import greenhouse, lever
        try:
            from ats_maps import workday, smartrecruiters
        except ImportError:
            workday = None
            smartrecruiters = None
    except ImportError as e:
        return {"content": [{"type": "text", "text": f"autofill_job_form: import error: {e}"}]}

    ats = fingerprint_ats(page_text, url=current_url)

    _ats_map_lookup = {
        "greenhouse":      greenhouse,
        "lever":           lever,
    }
    if workday:
        _ats_map_lookup["workday"] = workday
    if smartrecruiters:
        _ats_map_lookup["smartrecruiters"] = smartrecruiters
    ats_map_module = _ats_map_lookup.get(ats)

    if ats_map_module is None:
        return {"content": [{"type": "text", "text":
            f"autofill_job_form: ATS detected as '{ats}' — "
            "no selector map available for this ATS. "
            f"URL: {current_url or '(could not read)'}\n"
            "Hand off to LLM-driven fill or operator."}]}

    selector_map: dict = ats_map_module.SELECTORS
    field_types: dict = ats_map_module.FIELD_TYPES

    # ── Phase 1: code-fill via deterministic selector map ────────────────────
    filled: list[dict] = []
    skipped_no_value: list[dict] = []
    skipped_file: list[dict] = []

    for selector, key_path in selector_map.items():
        value = _resolve_profile_path(profile, key_path)

        # Placeholder values (start with "?") count as missing
        if value and value.startswith("?"):
            value = None

        if not value:
            skipped_no_value.append({"selector": selector, "key": key_path})
            continue

        field_type = field_types.get(key_path, "text")

        if field_type == "file":
            # File uploads require operator confirmation — collect and report
            skipped_file.append({"selector": selector, "key": key_path, "value": value})
            continue

        if dry_run:
            filled.append({"selector": selector, "key": key_path,
                           "value": value[:60], "dry_run": True})
            continue

        # Dispatch BROWSER_FILL with CSS selector as target
        fill_out = _dispatch("BROWSER_FILL", {
            "target": selector,
            "value": value,
            "field_type": field_type,
        }, session=session, wait=15)

        ok = fill_out.get("ok", False)
        filled.append({
            "selector": selector,
            "key": key_path,
            "value": value[:60],
            "ok": ok,
            "error": fill_out.get("result", {}).get("error") if not ok else None,
        })

    # ── Compose report ────────────────────────────────────────────────────────
    lines = [
        f"autofill_job_form {'(DRY RUN) ' if dry_run else ''}— ATS: {ats}",
        f"URL: {current_url or '(unknown)'}",
        f"Fields filled: {len(filled)}",
        f"Fields skipped (no profile value): {len(skipped_no_value)}",
        f"File uploads (need operator action): {len(skipped_file)}",
        "",
    ]

    if filled:
        lines.append("Filled:")
        for f in filled:
            status = "(dry)" if f.get("dry_run") else ("OK" if f.get("ok") else f"ERR: {f.get('error','?')}")
            lines.append(f"  [{status}]  {f['key']} = \"{f['value']}\"")
        lines.append("")

    if skipped_file:
        lines.append("Resume / file uploads (operator must upload manually or use file_upload tool):")
        for f in skipped_file:
            lines.append(f"  {f['key']} → {f['selector']} (value: {f['value'][:80]})")
        lines.append("")

    if skipped_no_value:
        lines.append("Profile fields missing (operator should fill ~/.master_ai_profile.json):")
        for f in skipped_no_value[:10]:
            lines.append(f"  {f['key']} ({f['selector']})")
        if len(skipped_no_value) > 10:
            lines.append(f"  ... and {len(skipped_no_value) - 10} more")
        lines.append("")

    lines.append("Phase 2 — LLM should now generate answers for any remaining empty fields")
    lines.append("(use 'read' to get the current list of unfilled inputs).")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_read_full(args):
    """Read the FULL accessibility tree of the current page including all interactive elements and ref IDs.
    Use this when read() truncates and you need to see all form fields."""
    out = _dispatch("BROWSER_READ_PAGE_FULL", {}, wait=20)
    rep = json.dumps(out)
    # Allow operators to lift the truncation cap for deep DOM reads (e.g. the
    # Daddy DOM Tool). Default stays conservative so normal MCP chatter isn't
    # swamped by huge pages.
    max_chars = int(os.environ.get("SENSEI_READ_FULL_MAX_CHARS", "8000"))
    if max_chars > 0 and len(rep) > max_chars:
        rep = rep[:max_chars] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_double_click(args):
    """Double-click an element by visible label or selector."""
    what = str(args.get("what") or "").strip()
    if not what:
        return {"content": [{"type": "text", "text": "double_click: what is required"}]}
    out = _dispatch("BROWSER_DOUBLE_CLICK", {"target": what})
    rep = f"double_click '{what}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_key_press(args):
    """Press a keyboard key on the active page. Useful for Enter, Escape, Tab, arrow keys.
    key: the key name (e.g. Enter, Escape, Tab, ArrowDown)."""
    key = str(args.get("key") or "").strip()
    if not key:
        return {"content": [{"type": "text", "text": "key_press: key is required"}]}
    out = _dispatch("BROWSER_CDP_KEY", {"target": f"press {key}"})
    rep = f"key_press '{key}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_upload_file(args):
    """Upload a file from the local filesystem to a file input on the page.
    selector: CSS selector or label for the file input. path: absolute path to the file."""
    selector = str(args.get("selector") or "").strip()
    path = str(args.get("path") or "").strip()
    if not selector or not path:
        return {"content": [{"type": "text", "text": "upload_file: selector and path are required"}]}
    target = f"{selector} :: {path}"
    out = _dispatch("BROWSER_UPLOAD_FILE", {"target": target}, wait=20)
    rep = f"upload_file '{selector}' <- '{path}' -> {json.dumps(out)[:400]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_wait(args):
    """Pause for a number of milliseconds (100-15000) before the next action."""
    ms = int(args.get("ms") or 1000)
    ms = max(100, min(ms, 15000))
    out = _dispatch("BROWSER_WAIT", {"target": str(ms)})
    rep = f"wait {ms}ms -> {json.dumps(out)[:200]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_batch(args):
    """Execute a sequence of browser actions atomically. actions: JSON array of objects
    with fields: kind (click/fill/scroll/wait/nav/double_click), target, value (for fill).
    Example: [{"kind":"click","target":"Submit"},{"kind":"fill","target":"#email","value":"me@example.com"}]"""
    raw = args.get("actions") or "[]"
    if isinstance(raw, str):
        try:
            actions = json.loads(raw)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"batch: actions must be valid JSON array: {e}"}]}
    elif isinstance(raw, list):
        actions = raw
    else:
        return {"content": [{"type": "text", "text": "batch: actions must be a JSON array"}]}

    KIND_MAP = {
        "click": "BROWSER_CLICK",
        "fill": "BROWSER_FILL",
        "scroll": "BROWSER_SCROLL",
        "wait": "BROWSER_WAIT",
        "nav": "BROWSER_NAV",
        "navigate": "BROWSER_NAV",
        "double_click": "BROWSER_DOUBLE_CLICK",
    }

    results = []
    for i, action in enumerate(actions):
        kind_raw = str(action.get("kind") or "").lower()
        kind = KIND_MAP.get(kind_raw, kind_raw.upper())
        target = str(action.get("target") or "")
        value = str(action.get("value") or "")
        payload = {"target": f"{target} :: {value}" if (kind == "BROWSER_FILL" and value) else target}
        out = _dispatch(kind, payload)
        ok = out.get("ok", True)
        results.append({"step": i + 1, "kind": kind, "target": target[:60], "ok": ok,
                         "error": out.get("result", {}).get("error") if not ok else None})
        if not ok:
            results.append({"step": "STOPPED", "reason": f"step {i+1} failed"})
            break

    lines = [f"batch: {len(results)} steps executed"]
    for r in results:
        if "reason" in r:
            lines.append(f"  → STOP: {r['reason']}")
        else:
            status = "✓" if r["ok"] else f"✗ {r.get('error','?')}"
            lines.append(f"  {r['step']}. [{status}] {r['kind']}: {r['target']}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_hover(args):
    """Hover over an element by visible label, ref_N name, or CSS selector.
    Dispatches mouseenter/mouseover/mousemove in the page so tooltips, dropdowns,
    and hover states appear."""
    what = str(args.get("what") or "").strip()
    if not what:
        return {"content": [{"type": "text", "text": "hover: what is required"}]}
    out = _dispatch("BROWSER_HOVER", {"target": what})
    rep = f"hover '{what}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_right_click(args):
    """Right-click an element to open its context menu."""
    what = str(args.get("what") or "").strip()
    if not what:
        return {"content": [{"type": "text", "text": "right_click: what is required"}]}
    out = _dispatch("BROWSER_RIGHT_CLICK", {"target": what})
    return {"content": [{"type": "text", "text": f"right_click '{what}' -> {json.dumps(out)[:300]}"}]}


def tool_tab_list(args):
    """List all open browser tabs with their IDs, titles, and URLs."""
    out = _dispatch("BROWSER_TAB_LIST", {})
    rep = json.dumps(out)
    if len(rep) > 3000:
        rep = rep[:3000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_tab_create(args):
    """Open a new browser tab. url: the URL to navigate to (optional — blank tab if omitted)."""
    url = str(args.get("url") or "").strip()
    out = _dispatch("BROWSER_TAB_CREATE", {"target": url or "about:blank"})
    # Auto-focus: the extension creates tabs in the BACKGROUND, so the operator
    # never sees them open. Pull the new tab id out of the result and switch to
    # it so the created tab is the screen the operator is viewing.
    try:
        _m = re.search(r'"tab_created"\s*:\s*{[^}]*"id"\s*:\s*(\d+)', json.dumps(out))
        if _m:
            _dispatch("BROWSER_TAB_SWITCH", {"target": _m.group(1)})
    except Exception:
        pass
    rep = f"tab_create url='{url}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_tab_switch(args):
    """Switch Chrome focus to a tab by its numeric ID (from tab_list). Use after intercept_popup click opens a new tab."""
    tab_id = str(args.get("tab_id") or "").strip()
    if not tab_id:
        return {"content": [{"type": "text", "text": "tab_switch: tab_id is required (get it from tab_list)"}]}
    out = _dispatch("BROWSER_TAB_SWITCH", {"target": tab_id})
    rep = f"tab_switch {tab_id} -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_tab_close(args):
    """Close a browser tab by its numeric tab ID (from tab_list)."""
    tab_id = str(args.get("tab_id") or "").strip()
    if not tab_id:
        return {"content": [{"type": "text", "text": "tab_close: tab_id is required (get it from tab_list)"}]}
    out = _dispatch("BROWSER_TAB_CLOSE", {"target": tab_id})
    rep = f"tab_close id={tab_id} -> {json.dumps(out)[:200]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_console_logs(args):
    """Read captured browser console messages. pattern: optional substring filter (e.g. 'error')."""
    pattern = str(args.get("pattern") or "").strip()
    out = _dispatch("BROWSER_CONSOLE", {"target": pattern or "all"})
    rep = json.dumps(out)
    if len(rep) > 4000:
        rep = rep[:4000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_network_requests(args):
    """Read recent network requests made by the current page. url_pattern: optional URL filter substring."""
    url_pattern = str(args.get("url_pattern") or "").strip()
    out = _dispatch("BROWSER_NETWORK", {"target": url_pattern or "all"})
    rep = json.dumps(out)
    if len(rep) > 4000:
        rep = rep[:4000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


def tool_resize_window(args):
    """Resize the browser window. width and height in pixels."""
    width = int(args.get("width") or 1280)
    height = int(args.get("height") or 900)
    out = _dispatch("BROWSER_RESIZE_WINDOW", {"target": f"{width}x{height}"})
    rep = f"resize_window {width}x{height} -> {json.dumps(out)[:200]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_drag(args):
    """Drag from one element to another (drag and drop). from_target: source element label/selector.
    to_target: destination element label/selector."""
    from_target = str(args.get("from_target") or "").strip()
    to_target = str(args.get("to_target") or "").strip()
    if not from_target or not to_target:
        return {"content": [{"type": "text", "text": "drag: from_target and to_target are required"}]}
    out = _dispatch("BROWSER_DRAG", {"target": from_target, "to": to_target})
    rep = f"drag '{from_target}' → '{to_target}' -> {json.dumps(out)[:300]}"
    return {"content": [{"type": "text", "text": rep}]}


def tool_list_client_profiles(args):
    """List cached client profile JSON files in /tmp (profile_{slug}.json).
    Returns each file's slug, full path, size, and age in seconds.
    Use this to confirm a client profile was saved before calling autofill_job_form."""
    import glob, os, time
    pattern = "/tmp/profile_*.json"
    files = sorted(glob.glob(pattern))
    if not files:
        return {"content": [{"type": "text", "text": "list_client_profiles: no cached profiles found in /tmp/profile_*.json"}]}
    now = time.time()
    lines = [f"Cached client profiles ({len(files)}):"]
    for fp in files:
        try:
            stat = os.stat(fp)
            slug = os.path.basename(fp)[len("profile_"):-len(".json")]
            age_s = int(now - stat.st_mtime)
            size_b = stat.st_size
            lines.append(f"  {slug}  ({size_b}B, {age_s}s ago)  →  {fp}")
        except Exception as e:
            lines.append(f"  {fp}  (stat error: {e})")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_get_cookies(args):
    """Read all cookies for the active tab's URL."""
    out = _dispatch("BROWSER_GET_COOKIES", {})
    rep = out.get("result", {}).get("result", json.dumps(out))
    if len(str(rep)) > 4000:
        rep = str(rep)[:4000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": str(rep)}]}


def tool_get_storage(args):
    """Read localStorage and/or sessionStorage for the active tab.
    storage_type: 'local', 'session', or 'both' (default)."""
    storage_type = str(args.get("storage_type") or "both").strip()
    out = _dispatch("BROWSER_GET_STORAGE", {"target": storage_type})
    rep = out.get("result", {}).get("result", json.dumps(out))
    if len(str(rep)) > 4000:
        rep = str(rep)[:4000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": str(rep)}]}


def tool_get_network_body(args):
    """Get the response body for a recent network request matching url (substring).
    Requires the request to have been made after network monitoring started."""
    url = str(args.get("url") or "").strip()
    out = _dispatch("BROWSER_GET_NETWORK_BODY", {"target": url})
    rep = out.get("result", {}).get("result", json.dumps(out))
    if len(str(rep)) > 6000:
        rep = str(rep)[:6000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": str(rep)}]}


def tool_get_performance(args):
    """Get performance metrics and resource timing for the active tab."""
    out = _dispatch("BROWSER_GET_PERFORMANCE", {})
    rep = out.get("result", {}).get("result", json.dumps(out))
    if len(str(rep)) > 4000:
        rep = str(rep)[:4000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": str(rep)}]}


def tool_drive_inspect(args):
    """Inspect the current Google Drive page and return visible file/folder items
    with selectors, names, and roles. Useful for finding a target file before
    clicking or hovering."""
    out = _dispatch("BROWSER_DRIVE_INSPECT_FOLDER", {})
    # _dispatch returns the bridge envelope; unwrap the inner result/drive_state.
    inner = out.get("result", out) if isinstance(out, dict) else out
    state = inner.get("drive_state") if isinstance(inner, dict) else None
    if state:
        items = state.get("items", [])
        files = [it for it in items if it.get("role") == "row" and it.get("name")]
        lines = [f"Drive: {state.get('title')} — {len(files)} file(s)/folder(s) visible"]
        for it in files:
            lines.append(f"- {it['name']}\n  selector: {it.get('selector','')}\n  text: {it.get('text','')[:120]}")
        rep = "\n".join(lines)
    else:
        rep = json.dumps(out)[:6000]
    return {"content": [{"type": "text", "text": rep}]}


def tool_execute_js(args):
    """Run a CSP-safe JavaScript action in the active tab, across all frames.
    This reaches inside iframes and shadow DOM that the normal click/fill tools cannot see.
    command: click_text | click_selector | fill_selector | select_option
    For click_text: text (required), tag (optional, default "button, a, [role='button']")
    For click_selector: selector (required)
    For fill_selector: selector, value (required)
    For select_option: selector, option_text (required)"""
    command = str(args.get("command") or "").strip()
    if not command:
        return {"content": [{"type": "text", "text": "execute_js: command is required (click_text, click_selector, fill_selector, select_option, query)"}]}
    payload = {"command": command, "all_frames": args.get("all_frames", True)}
    for k in ["text", "selector", "value", "option_text", "tag", "attribute", "limit"]:
        if k in args and args[k] is not None:
            payload[k] = str(args[k]) if k != "limit" else int(args[k])
    out = _dispatch("BROWSER_JS", payload, wait=15)
    rep = json.dumps(out)
    if len(rep) > 6000:
        rep = rep[:6000] + " ...[truncated]"
    return {"content": [{"type": "text", "text": rep}]}


# Trimmed tool surface: smart_form_fill.py handles complex universal form filling,
# so we drop the old profile-based autofill plus a raft of unsupported/duplicate
# tools that were bloating the model context. Keep the browser primitives.
HANDLERS = {
    "health": tool_health,
    "browse": tool_browse,
    "click": tool_click,
    "fill": tool_fill,
    "fill_form": tool_fill_form,
    "read": tool_read,
    "read_full": tool_read_full,
    "get_dom": tool_get_dom,
    "drive_inspect": tool_drive_inspect,
    "execute_js": tool_execute_js,
    "search": tool_search,
    "screenshot": tool_screenshot,
    "scroll": tool_scroll,
    "wait": tool_wait,
    "double_click": tool_double_click,
    "hover": tool_hover,
    "key_press": tool_key_press,
    "upload_file": tool_upload_file,
    "batch": tool_batch,
    "tab_list": tool_tab_list,
    "tab_create": tool_tab_create,
    "tab_switch": tool_tab_switch,
    "tab_close": tool_tab_close,
    # DevTools / debugging
    "console_logs": tool_console_logs,
    "network_requests": tool_network_requests,
    "get_cookies": tool_get_cookies,
    "get_storage": tool_get_storage,
    "get_network_body": tool_get_network_body,
    "get_performance": tool_get_performance,
    # Extra interactions
    "right_click": tool_right_click,
    "resize_window": tool_resize_window,
    "drag": tool_drag,
    # Shell + filesystem
    "run": tool_run,
    # Job workflow
    "list_client_profiles": tool_list_client_profiles,
    "autofill_job_form": tool_autofill_job_form,
}


# ---------------------------------------------------------------------------
# tool schemas — descriptions cut to a single short sentence each.
# every parameter is a flat string. no nested objects. no optional fields
# with defaults. no enums. nothing the 7B model can hallucinate the shape of.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "health",
        "description": "Report whether bridge/CLAF/Ollama are reachable (wiring check).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browse",
        "description": "Open a URL in the browser.",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "click",
        "description": "Click an element by visible label, ref_N name, or CSS selector. The `what` parameter is REQUIRED — never call click without a concrete target taken from the last read_full. Set intercept_popup=true to bypass first_submit_pause AND intercept window.open (required for Indeed Apply button).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "what": {"type": "string", "description": "Exact visible text, ref_N label, or CSS selector of the element to click (from the last read_full)."},
                "intercept_popup": {"type": "boolean", "description": "If true, bypasses first_submit_pause and intercepts window.open — use for Indeed's Apply button."},
            },
            "required": ["what"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into a single field by label or selector. For the currently-loaded extension you must put the value inside the target with ` :: `, e.g. `#email :: me@example.com`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "where": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["where", "text"],
        },
    },
    {
        "name": "fill_form",
        "description": "Universal form filler. X-rays the current page and fills every field it can (text, email, tel, select, radio, checkbox, textarea, date, number, URL). Uses smart defaults; pass a profile JSON object to override any default value.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string", "description": "Optional JSON object mapping default keys (first_name, last_name, email, phone, address1, city, state, zip, country, company, job_title, website, salary, experience_years, start_date, birth_date, number, generic_text) to custom values."},
                "dry_run": {"type": "string", "description": "Set 'true' to preview the plan without filling anything."},
                "submit": {"type": "boolean", "description": "If true, click the first submit button after filling."},
            },
            "required": [],
        },
    },
    {
        "name": "read",
        "description": "Read the visible content of the current page.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_full",
        "description": "Read the FULL accessibility tree of the current page — all interactive elements, ref IDs, selectors, rects. Use this before clicking or filling.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dom",
        "description": "Return the outerHTML of the current page or a selected element. Pass a CSS selector to narrow it; omit for the whole page.",
        "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "Optional CSS selector. Empty returns full page HTML."}}},
    },
    {
        "name": "drive_inspect",
        "description": "Inspect the current Google Drive page and return visible files/folders with selectors, names, and roles.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "execute_js",
        "description": "Run a CSP-safe JavaScript action in the active tab across all frames, to click/fill/query inside iframes and shadow DOM. Commands: click_text, click_selector, fill_selector, select_option, query.",
        "inputSchema": {"type": "object", "properties": {"command": {"type": "string", "description": "click_text | click_selector | fill_selector | select_option | query"}, "text": {"type": "string"}, "selector": {"type": "string"}, "value": {"type": "string"}, "option_text": {"type": "string"}, "tag": {"type": "string"}, "attribute": {"type": "string"}, "limit": {"type": "integer"}, "all_frames": {"type": "boolean"}}, "required": ["command"]},
    },
    {
        "name": "search",
        "description": "Search Google for a query.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current browser page. Returns path to saved PNG file.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "scroll",
        "description": "Scroll the current browser page. Use direction: up, down, top, bottom, or a pixel number.",
        "inputSchema": {"type": "object", "properties": {"direction": {"type": "string"}}, "required": ["direction"]},
    },
    {
        "name": "wait",
        "description": "Pause for ms milliseconds (100–15000) before the next action. Use after page loads or animations.",
        "inputSchema": {"type": "object", "properties": {"ms": {"type": "integer", "description": "Milliseconds to pause, 100–15000."}}, "required": ["ms"]},
    },
    {
        "name": "double_click",
        "description": "Double-click an element by visible label or CSS selector.",
        "inputSchema": {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]},
    },
    {
        "name": "hover",
        "description": "Hover over an element by visible label or CSS selector to reveal tooltips, dropdowns, or hover states before clicking.",
        "inputSchema": {"type": "object", "properties": {"what": {"type": "string", "description": "Exact visible text, ref_N label, or CSS selector of the element to hover over."}}, "required": ["what"]},
    },
    {
        "name": "key_press",
        "description": "Press a keyboard key (Enter, Escape, Tab, ArrowDown, etc.) on the active page.",
        "inputSchema": {"type": "object", "properties": {"key": {"type": "string", "description": "Key name, e.g. Enter, Escape, Tab, ArrowDown."}}, "required": ["key"]},
    },
    {
        "name": "upload_file",
        "description": "Upload a local file to a file input element on the page. selector: CSS selector or label for the input. path: absolute filesystem path to the file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["selector", "path"],
        },
    },
    {
        "name": "batch",
        "description": "Execute multiple browser actions in sequence atomically. actions: JSON array, each item has kind (click/fill/scroll/wait/nav/double_click), target, and optional value (for fill).",
        "inputSchema": {
            "type": "object",
            "properties": {"actions": {"type": "string", "description": "JSON array of action objects. Example: [{\"kind\":\"fill\",\"target\":\"#email\",\"value\":\"me@example.com\"}]"}},
            "required": ["actions"],
        },
    },
    {
        "name": "tab_list",
        "description": "List all open browser tabs with their numeric IDs, titles, and URLs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tab_create",
        "description": "Open a new browser tab and navigate to a URL. Returns the new tab's ID.",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": []},
    },
    {
        "name": "tab_switch",
        "description": "Switch Chrome focus to a tab by its numeric ID (from tab_list). Use after intercept_popup click opens a new tab to bring it to the front.",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "string"}}, "required": ["tab_id"]},
    },
    {
        "name": "tab_close",
        "description": "Close a browser tab by its numeric tab ID. Get IDs from tab_list.",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "string"}}, "required": ["tab_id"]},
    },
    {
        "name": "console_logs",
        "description": "Read captured browser console messages (errors, warnings, log output). Use pattern to filter, e.g. 'error' or 'fetch'.",
        "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Optional substring to filter messages. Omit for all messages."}}},
    },
    {
        "name": "network_requests",
        "description": "Read recent network requests made by the current page (XHR, fetch, resources). Use url_pattern to filter, e.g. '/api/'.",
        "inputSchema": {"type": "object", "properties": {"url_pattern": {"type": "string", "description": "Optional URL substring to filter. Omit for all requests."}}},
    },
    {
        "name": "get_cookies",
        "description": "Read all cookies for the active tab's URL. Useful for checking auth/session state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_storage",
        "description": "Read localStorage and/or sessionStorage for the active tab. storage_type: 'local', 'session', or 'both'.",
        "inputSchema": {"type": "object", "properties": {"storage_type": {"type": "string", "description": "'local', 'session', or 'both' (default)"}}},
    },
    {
        "name": "get_network_body",
        "description": "Get the response body for a recent network request. url: substring of the request URL to match.",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL substring to match against recent requests."}}, "required": ["url"]},
    },
    {
        "name": "get_performance",
        "description": "Get browser performance metrics and resource timing for the active tab.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "right_click",
        "description": "Right-click an element by visible label or CSS selector to open its context menu.",
        "inputSchema": {"type": "object", "properties": {"what": {"type": "string", "description": "Visible text, ref_N label, or CSS selector of element to right-click."}}, "required": ["what"]},
    },
    {
        "name": "resize_window",
        "description": "Resize the browser window. width and height in pixels. Default 1280x900.",
        "inputSchema": {"type": "object", "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}}},
    },
    {
        "name": "drag",
        "description": "Drag from one element to another (drag-and-drop). from_target: source element. to_target: drop destination.",
        "inputSchema": {"type": "object", "properties": {"from_target": {"type": "string", "description": "Label or CSS selector of source element."}, "to_target": {"type": "string", "description": "Label or CSS selector of drop destination."}}, "required": ["from_target", "to_target"]},
    },
    {
        "name": "run",
        "description": "Run a shell command on the local machine and return its output (stdout+stderr). Timeout 30s. Use for ls, grep, curl, systemctl, etc.",
        "inputSchema": {"type": "object", "properties": {"cmd": {"type": "string", "description": "Shell command to execute."}}, "required": ["cmd"]},
    },
    {
        "name": "list_client_profiles",
        "description": "List cached client profile JSON files in /tmp (profile_{slug}.json). Shows slug, path, size, and age. Use before autofill_job_form to confirm a profile exists.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "autofill_job_form",
        "description": "Detect the ATS on the current page (Greenhouse, Lever, Workday, SmartRecruiters) and fill all standard fields from a profile JSON. Returns unfilled fields for LLM to answer. dry_run=true to preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dry_run": {"type": "string", "description": "Set 'true' to preview without filling."},
                "profile_path": {"type": "string", "description": "Absolute path to profile JSON. Defaults to ~/.master_ai_profile.json."},
                "client_name": {"type": "string", "description": "Client name slug — auto-resolves to /tmp/profile_{slug}.json (Fair Chance workflow)."},
                "session": {"type": "string", "description": "Bridge session ID (default: mcp-default)."},
            },
        },
    },
]
# ---------------------------------------------------------------------------
# JSON-RPC stdio loop
# ---------------------------------------------------------------------------

def _send(obj, *, framed: bool = False):
    payload = json.dumps(obj).encode("utf-8")
    if framed:
        sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(payload.decode("utf-8") + "\n")
        sys.stdout.flush()


def _err(msg_id, code, message):
    _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sensei", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text",
                                            "text": f"unknown tool: {name}"}],
                               "isError": True}}
        try:
            result = handler(args if isinstance(args, dict) else {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text",
                                            "text": f"tool error: {e}"}],
                               "isError": True}}

    if mid is None:
        # notification we don't handle — silently drop
        return None

    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    for msg, framed in _iter_rpc_messages():
        try:
            resp = _handle(msg if isinstance(msg, dict) else {})
        except Exception as e:
            sys.stderr.write(f"[sensei] handler crash: {e}\n")
            sys.stderr.flush()
            resp = {"jsonrpc": "2.0", "id": (msg or {}).get("id"),
                    "error": {"code": -32603, "message": f"internal: {e}"}}
        if resp is not None:
            _send(resp, framed=framed)
    return 0

def _read_exact(n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sys.stdin.buffer.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _iter_rpc_messages() -> Iterator[Tuple[dict, bool]]:
    """Yield parsed JSON-RPC dicts from stdin.

    Supports both:
    - MCP/LSP-style framed messages: Content-Length: N\\r\\n\\r\\n{...}
    - newline-delimited JSON (older local scripts / ad-hoc tests)
    """
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue

        # Framed: Content-Length: N
        if line_str.lower().startswith("content-length:"):
            try:
                n = int(line_str.split(":", 1)[1].strip())
            except Exception:
                sys.stderr.write(f"[sensei] bad content-length line: {line_str}\n")
                sys.stderr.flush()
                continue

            # Read headers until blank line
            while True:
                h = sys.stdin.buffer.readline()
                if not h:
                    return
                if h in (b"\r\n", b"\n"):
                    break

            raw = _read_exact(n)
            if not raw:
                return
            try:
                yield json.loads(raw.decode("utf-8", errors="replace")), True
            except Exception as e:
                sys.stderr.write(f"[sensei] parse error: {e}\n")
                sys.stderr.flush()
            continue

        # Newline-delimited JSON
        try:
            yield json.loads(line_str), False
        except Exception as e:
            sys.stderr.write(f"[sensei] parse error: {e}\n")
            sys.stderr.flush()
            continue


if __name__ == "__main__":
    sys.exit(main())
