const DEFAULT_CONFIG = {
  backendUrl: "http://127.0.0.1:8080",
  token: "",
  mode: "review",
  sessionId: "",
  actionPermissionMode: "ask",
  approvedOrigins: [],
  permissionHistory: []
};

const REQUEST_TIMEOUTS = {
  default: 60000,
  health: 3500,
  chat: 600000,
  stt: 180000,
  audit: 5000
};
const PAGE_CONTEXT_TTL_MS = 1500;
const PAGE_CONTEXT_TEXT_LIMIT = 1800;
const PAGE_CONTEXT_PROMPT_RE =
  /\b(browser|button|click|current\s+(page|tab|site)|field|fill|form|link|page|read|screen|screenshot|select|selected|selection|tab|this|visible|website)\b/i;

const state = {
  config: { ...DEFAULT_CONFIG },
  mediaRecorder: null,
  mediaStream: null,
  chunks: [],
  injectedTabs: new Set(),
  contextCache: null,
  auditQueue: [],
  auditFlushing: false,
  // M9 — Agentic Continuation Loop (scaffold 2026-05-12). After /chat returns
  // proposed actions, the user approves/rejects each one. As each result is
  // reported to /extension/action_result, it's also appended to loop.results.
  // When all actions in a round have a verdict AND loop.active AND none were
  // rejected, the next round fires automatically via /chat/continue. Stop
  // button hard-interrupts. Budget caps runaway loops.
  loop: {
    active: false,
    turn_id: null,
    round_num: 0,
    round_budget: 3,
    pending: 0,
    rejected: false,
    results: [],
    stopped: false
  }
};

const $ = (selector) => document.querySelector(selector);

function chromeGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function chromeSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

async function loadConfig() {
  const stored = await chromeGet(Object.keys(DEFAULT_CONFIG));
  state.config = { ...DEFAULT_CONFIG, ...stored };
  if (!Array.isArray(state.config.approvedOrigins)) state.config.approvedOrigins = [];
  if (!Array.isArray(state.config.permissionHistory)) state.config.permissionHistory = [];
  if (!["ask", "act"].includes(state.config.actionPermissionMode)) state.config.actionPermissionMode = "ask";
  if (!state.config.sessionId) {
    state.config.sessionId = `sensei-${crypto.randomUUID()}`;
    await chromeSet({ sessionId: state.config.sessionId });
  }
  state.config.backendUrl = String(state.config.backendUrl || DEFAULT_CONFIG.backendUrl).replace(/\/+$/, "");
  $("#modeSelect").value = state.config.mode || "review";
}

async function saveMode(mode) {
  state.config.mode = mode;
  await chromeSet({ mode });
}

function backendHeaders(extra = {}) {
  return {
    "X-Master-AI-Token": state.config.token || "",
    ...extra
  };
}

function requestTimeout(path, options = {}) {
  if (Number.isFinite(options.timeoutMs)) return options.timeoutMs;
  if (path === "/health") return REQUEST_TIMEOUTS.health;
  if (path === "/stt") return REQUEST_TIMEOUTS.stt;
  if (path === "/extension/action_result") return REQUEST_TIMEOUTS.audit;
  if (path === "/chat" || path === "/chat/continue") return REQUEST_TIMEOUTS.chat;
  return REQUEST_TIMEOUTS.default;
}

async function backendFetch(path, options = {}) {
  let body = options.body;
  const headers = backendHeaders(options.headers || {});
  const timeoutMs = requestTimeout(path, options);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  if (body !== undefined && !(body instanceof Blob) && typeof body !== "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  } else if (body instanceof Blob) {
    headers["Content-Type"] = body.type || "application/octet-stream";
  }

  let res;
  let text;
  try {
    res = await fetch(`${state.config.backendUrl}${path}`, {
      method: options.method || (body === undefined ? "GET" : "POST"),
      headers,
      body,
      signal: controller.signal
    });
    text = await res.text();
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new Error(`${path} timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_err) {
    data = { raw: text };
  }
  if (!res.ok) {
    // HTTP 503 from wedge protection is a temporary backend busy signal
    // (stt_server.py raises ApiHandleBusy when a runaway local inference
    // holds _API_HANDLE_LOCK past _API_HANDLE_LOCK_TIMEOUT_S). Surface
    // it as a recoverable retry message, not a raw error — the user
    // just has to wait and re-send. Same shape `_chat` endpoint emits.
    if (res.status === 503 && data?.error === "system_busy") {
      const retryAfter = Number(data.retry_after_s) || 15;
      const err = new Error(
        `Sensei is busy with another task on the local model — ` +
        `please retry in about ${retryAfter} seconds. ` +
        `(For an immediate answer, prefix your prompt with "fast:" ` +
        `to route to the cloud lane.)`
      );
      err.code = "system_busy";
      err.retryAfterS = retryAfter;
      throw err;
    }
    const message = data.error || `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return data;
}

function setConnection(text, tone = "") {
  const el = $("#connectionState");
  el.textContent = text;
  el.dataset.tone = tone;
}

function cleanReply(text) {
  const lines = String(text || "").split(/\n/);
  const cleaned = lines.filter((line) => {
    return !/^\s*(RUNTERM|RUN|READ|CREATE|EDIT|REMEMBER|BROWSER_CLICK|BROWSER_FILL|BROWSER_READ|BROWSER_NAV|BROWSER_SCREENSHOT):/i.test(line)
      && !/^\s*<<<(CONTENT|FIND|REPLACE)\s*$/i.test(line)
      && !/^\s*>>>(CONTENT|FIND|REPLACE)\s*$/i.test(line);
  }).join("\n").trim();
  return cleaned || "Action ready for review.";
}

function appendMessage(role, text, meta = "") {
  const log = $("#chatLog");
  const item = document.createElement("article");
  item.className = `message ${role}`;
  item.textContent = text;
  if (meta) {
    const small = document.createElement("span");
    small.className = "meta";
    small.textContent = meta;
    item.appendChild(small);
  }
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function appendError(text) {
  appendMessage("error", text);
}

// Phase A.2 — visible warning when the model's reply claims a browser
// action but emits no directive (silent-failure case from 2026-05-14
// trace). Catches "I took a screenshot" / "I clicked the button" prose
// with empty actions[]. Pattern is intentionally narrower than just
// "screenshot|click|fill" — pairs the verb with a target noun to reduce
// false positives on incidental chat use.
// Three patterns OR'd together:
//   (1) self-contained verb phrases that include their own target noun
//       (e.g., "took a screenshot", "navigated to", "opened the page")
//   (2) verb-then-target pairs within 40 chars (e.g., "clicked the
//       Sign in button" — the noun isn't adjacent to the verb).
//   (3) any literal BROWSER_<verb> mention. Covers [BROWSER_SCREENSHOT],
//       "BROWSER_SCREENSHOT", `BROWSER_SCREENSHOT`, and anywhere the
//       model wraps/quotes the directive instead of emitting it at
//       column 0 (witnessed live 2026-05-14 from local master-ai on
//       pinterest.com — model returned "[BROWSER_SCREENSHOT] url: ...").
//       The parser only matches ^\s*BROWSER_X: so any non-column-0 or
//       wrapped form needs the warning path.
const CLAIMED_BROWSER_ACTION_RE = /(?:\b(?:captur(?:ed|ing)|took (?:a |the )?(?:screenshot|snapshot|picture|photo)|taking (?:a |the )?(?:screenshot|snapshot|picture|photo)|screenshot(?:ted|ed)?|navigated to|opened (?:the |this )?(?:page|tab|link|url|site|website))\b)|(?:\b(?:clicked|filled (?:in |out )?(?:the )?|typed (?:into )?(?:the )?|pressed (?:the )?|scrolled (?:to |up |down )?)\b.{0,40}\b(?:button|link|field|form|input|tab|key|enter|return|escape|element|icon|email|password|down|up|bottom|top)\b)|(?:BROWSER_(?:NAV|CLICK|FILL|READ|SCREENSHOT|WAIT|SCROLL|KEY))/i;

function appendWarning(text) {
  appendMessage("error", `⚠ ${text}`);
}

// DONE: directives at column 0 mean the loop terminated cleanly; the
// model is reporting on already-completed actions, not trying to emit
// new ones. False-positives in those rounds (e.g., "DONE: Screenshot
// captured successfully") were firing the warning even though the
// actual action already ran in an earlier round.
const DONE_DIRECTIVE_RE = /^\s*DONE:\s*\S/m;

function maybeWarnSilentClaim(reply, actions, data) {
  if (Array.isArray(actions) && actions.length > 0) return;
  const text = String(reply || "");
  if (DONE_DIRECTIVE_RE.test(text)) return;
  if (data && (data.done === true || data.terminal_reason)) return;
  if (!CLAIMED_BROWSER_ACTION_RE.test(text)) return;
  appendWarning(
    "Model claimed a browser action but didn't emit a directive. " +
    "Try rephrasing concretely (e.g., \"take a screenshot of this page\", " +
    "\"click the Sign in button\") or switch the mode dropdown to " +
    "\"Act without asking.\""
  );
}

async function timed(timings, key, fn) {
  const start = performance.now();
  try {
    return await fn();
  } finally {
    timings[key] = Math.round(performance.now() - start);
  }
}

function formatMeta(data, timings = {}) {
  const parts = [data.route, data.model];
  if (Number.isFinite(data.latency_ms)) parts.push(`${data.latency_ms} ms server`);
  if (Number.isFinite(timings.context)) parts.push(`ctx ${timings.context} ms`);
  if (Number.isFinite(timings.total)) parts.push(`${timings.total} ms client`);
  return parts.filter(Boolean).join(" | ");
}

function promptNeedsPageContext(prompt) {
  return PAGE_CONTEXT_PROMPT_RE.test(String(prompt || ""));
}

async function activeTab() {
  const result = await chrome.runtime.sendMessage({ type: "SENSEI_ACTIVE_TAB" });
  return result?.tab || null;
}

function canInjectIntoTab(tab) {
  return Boolean(tab?.id && /^(https?:|file:)/i.test(String(tab.url || "")));
}

function contextCacheKey(tab, includeVisibleText) {
  return `${tab.id}:${tab.url || ""}:${includeVisibleText ? "full" : "shell"}`;
}

function invalidatePageContext(tabId = null) {
  if (!tabId || state.contextCache?.tabId === tabId) state.contextCache = null;
  if (tabId) state.injectedTabs.delete(tabId);
}

async function ensureContentScript(tab, timings = {}) {
  if (!canInjectIntoTab(tab)) return false;
  if (state.injectedTabs.has(tab.id)) return true;

  try {
    const ping = await chrome.tabs.sendMessage(tab.id, { type: "SENSEI_PING" });
    if (ping?.ok) {
      state.injectedTabs.add(tab.id);
      return true;
    }
  } catch (_err) {
    // Missing content script is expected with lazy injection.
  }

  await timed(timings, "inject", async () => {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content_script.js"] });
  });
  state.injectedTabs.add(tab.id);
  return true;
}

async function pageContext(prompt = "", timings = {}) {
  const tab = await timed(timings, "tab", activeTab);
  if (!tab?.id) return {};
  const fallback = { url: tab.url || "", title: tab.title || "" };
  const includeVisibleText = promptNeedsPageContext(prompt);
  const key = contextCacheKey(tab, includeVisibleText);
  if (state.contextCache?.key === key && performance.now() - state.contextCache.ts < PAGE_CONTEXT_TTL_MS) {
    return state.contextCache.value;
  }

  if (!includeVisibleText || !canInjectIntoTab(tab)) {
    state.contextCache = { key, tabId: tab.id, ts: performance.now(), value: fallback };
    return fallback;
  }

  try {
    await ensureContentScript(tab, timings);
    const response = await timed(timings, "context", () => chrome.tabs.sendMessage(tab.id, {
      type: "SENSEI_PAGE_CONTEXT",
      options: {
        includeVisibleText,
        visibleTextLimit: PAGE_CONTEXT_TEXT_LIMIT
      }
    }));
    const value = response?.page_context || fallback;
    state.contextCache = { key, tabId: tab.id, ts: performance.now(), value };
    return value;
  } catch (_err) {
    return fallback;
  }
}

function normalizeUrl(target) {
  const raw = String(target || "").trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^[\w.-]+\.[a-z]{2,}(\/.*)?$/i.test(raw)) return `https://${raw}`;
  return raw;
}

function currentExecutionMode() {
  const selected = $("#modeSelect")?.value || state.config.mode || "review";
  if (selected === "auto") return "act";
  return state.config.actionPermissionMode || "ask";
}

function originForUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.origin;
  } catch (_err) {
    return "";
  }
}

function actionOrigin(action, tab) {
  const kind = String(action?.kind || "").toUpperCase();
  if (kind === "BROWSER_NAV") {
    const target = normalizeUrl(action.target);
    const origin = originForUrl(target);
    if (origin) return origin;
  }
  return originForUrl(tab?.url || "");
}

async function rememberPermission(decision, origin, action) {
  const entry = {
    ts: new Date().toISOString(),
    decision,
    origin: origin || "",
    kind: action?.kind || "",
    target: String(action?.target || "").slice(0, 300)
  };
  state.config.permissionHistory = [entry, ...(state.config.permissionHistory || [])].slice(0, 100);
  await chromeSet({ permissionHistory: state.config.permissionHistory });
}

async function allowOrigin(origin, action) {
  if (!origin) return;
  if (!state.config.approvedOrigins.includes(origin)) {
    state.config.approvedOrigins = [...state.config.approvedOrigins, origin].sort();
    await chromeSet({ approvedOrigins: state.config.approvedOrigins });
  }
  await rememberPermission("always_allow_site", origin, action);
}

async function sendToContent(tab, action, timings = {}) {
  const ready = await ensureContentScript(tab, timings);
  if (!ready) throw new Error("cannot access this tab");
  return chrome.tabs.sendMessage(tab.id, { type: "SENSEI_EXECUTE_ACTION", action });
}

function truncateDataUrlForAudit(dataUrl) {
  const text = String(dataUrl || "");
  return text.length > 200 ? text.slice(0, 200) : text;
}

function renderScreenshot(row, dataUrl) {
  if (!row || !dataUrl) return;
  const existing = row.querySelector(".screenshot-preview");
  if (existing) existing.remove();
  const img = document.createElement("img");
  img.className = "screenshot-preview";
  img.alt = "Captured browser tab screenshot";
  img.src = dataUrl;
  row.appendChild(img);
}

function reportAction(action, verdict, result, finalState = {}) {
  state.auditQueue.push({
    action_id: action.id,
    action,
    verdict,
    result,
    final_state: finalState,
    gated_by: action?.gated_by || action?.classification?.gated_by || null
  });
  flushAuditQueue();
}

async function flushAuditQueue() {
  if (state.auditFlushing) return;
  state.auditFlushing = true;
  try {
    while (state.auditQueue.length) {
      const payload = state.auditQueue[0];
      try {
        await backendFetch("/extension/action_result", {
          method: "POST",
          body: payload,
          timeoutMs: REQUEST_TIMEOUTS.audit
        });
      } catch (err) {
        appendError(`Action audit failed: ${err.message}`);
      } finally {
        state.auditQueue.shift();
      }
    }
  } finally {
    state.auditFlushing = false;
  }
}

function setActionStatus(row, text) {
  const status = row.querySelector(".status");
  if (status) status.textContent = text;
}

function classifyBrowserAction(action) {
  const kind = String(action?.kind || "").toUpperCase();
  const target = String(action?.target || "").toLowerCase();

  const PURCHASE_RE = /\b(buy|purchase|pay|checkout|order|subscribe|add to cart)\b/i;
  const DELETE_RE = /\b(delete|remove|destroy|uninstall|erase|wipe|cancel.*(account|subscription))\b/i;
  const AUTH_RE = /\b(sign[-_\s]*up|sign[-_\s]*in|log[-_\s]*in|log[-_\s]*out|register|authorize|grant\s*access|oauth|api\s*key)\b/i;
  const SENSITIVE_RE = /\b(password|ssn|social.*security|credit.*card|cvv|cvc|api.*key|bank.*account|routing.*number)\b/i;
  const PASSWORD_SEL = /type=["']?password["']?|name=["']?(password|pwd|passwd)["']?/i;

  if (kind === "BROWSER_FILL" && (PASSWORD_SEL.test(target) || SENSITIVE_RE.test(target))) {
    return { safe: false, requires_confirm: true, gated_by: "irreversible_heuristic:sensitive_fill" };
  }
  if (kind === "BROWSER_CLICK") {
    if (PURCHASE_RE.test(target)) return { safe: false, requires_confirm: true, gated_by: "irreversible_heuristic:purchase" };
    if (DELETE_RE.test(target)) return { safe: false, requires_confirm: true, gated_by: "irreversible_heuristic:delete" };
    if (AUTH_RE.test(target)) return { safe: false, requires_confirm: true, gated_by: "irreversible_heuristic:auth" };
  }
  if (kind === "BROWSER_NAV") {
    if (PURCHASE_RE.test(target) || /\/(checkout|cart|pay|order)\b/i.test(target)) {
      return { safe: false, requires_confirm: true, gated_by: "irreversible_heuristic:purchase_url" };
    }
  }
  if (kind === "BROWSER_READ" || kind === "BROWSER_SCREENSHOT") {
    return { safe: true, requires_confirm: false, gated_by: null };
  }
  return { safe: true, requires_confirm: false, gated_by: null };
}

function gateLabel(gatedBy) {
  if (!gatedBy) return "";
  const reason = String(gatedBy).split(":").pop().replace(/_/g, " ");
  return `gated_by: ${reason}`;
}

function shouldAutoRunAction(action, origin = "") {
  // Phase 1 commit 1.3: respect the backend's mode-aware status taxonomy.
  // The dispatcher (not the model, not the client) decides safe vs sensitive.
  // Previously this auto-ran BROWSER_READ/SCREENSHOT regardless of mode —
  // Plan-mode contract violation. Closed.
  const status = String(action?.status || "").toLowerCase();
  const kind = String(action?.kind || "").toUpperCase();

  // Backend status takes precedence. waiting_for_approval / pending_approval
  // (legacy name) / blocked all mean "do NOT auto-run."
  if (status === "waiting_for_approval" || status === "pending_approval" || status === "blocked") {
    return false;
  }

  // Non-browser actions never dispatch from the side panel. In Auto the
  // backend already dispatched them server-side; in Review they go through
  // /extension/approve_action (commit 1.4).
  if (!kind.startsWith("BROWSER_")) return false;

  // Plan + Review: never auto-run, regardless of action kind. Closes the
  // BROWSER_READ/SCREENSHOT auto-run-in-Plan loophole at the old line 464.
  const mode = ($("#modeSelect")?.value || state.config.mode || "review").toLowerCase();
  if (mode !== "auto") return false;

  // Auto: dispatcher already marked sensitive ones as gated_by; respect it.
  if (action?.classification?.requires_confirm) return false;
  if (action?.gated_by) return false;

  // Auto-mode safe BROWSER_*: approved-origin auto-run, plus READ/SCREENSHOT
  // (read-only, no page-state change).
  if (origin && state.config.approvedOrigins.includes(origin)) return true;
  if (kind === "BROWSER_READ" || kind === "BROWSER_SCREENSHOT") return true;
  return false;
}

async function approveAction(action, row, permissionDecision = "allow_once") {
  const kind = String(action.kind || "").toUpperCase();
  const timings = {};
  setActionStatus(row, "Running");
  row.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });

  if (!kind.startsWith("BROWSER_")) {
    setActionStatus(row, "Backend-only — switch the mode dropdown to \"Act without asking\" to dispatch");
    reportAction(action, "accept", "blocked", { reason: "non-browser action; backend dispatches in auto mode" });
    recordLoopResult(action, "accept", "blocked", { reason: "non-browser action; backend dispatches in auto mode" });
    return;
  }

  try {
    const tab = await activeTab();
    if (!tab?.id) throw new Error("no active tab");
    const origin = actionOrigin(action, tab);
    if (permissionDecision !== "auto") await rememberPermission(permissionDecision, origin, action);

    let result;
    if (kind === "BROWSER_SCREENSHOT") {
      const capture = await chrome.runtime.sendMessage({
        type: "SENSEI_CAPTURE_VISIBLE_TAB",
        windowId: tab.windowId
      });
      if (!capture?.ok || !capture?.dataUrl) {
        throw new Error(capture?.error || "screenshot capture failed; try reopening the side panel from this tab");
      }
      renderScreenshot(row, capture.dataUrl);
      result = {
        ok: true,
        screenshot: "visible_tab_png",
        dataUrl: truncateDataUrlForAudit(capture.dataUrl)
      };
    } else if (kind === "BROWSER_NAV") {
      const url = normalizeUrl(action.target);
      await chrome.tabs.update(tab.id, { url });
      result = { ok: true, navigated: url };
      invalidatePageContext(tab.id);
    } else {
      result = await sendToContent(tab, action, timings);
      invalidatePageContext(tab.id);
    }

    const ok = Boolean(result?.ok);
    const suffix = timings.inject ? ` (${timings.inject} ms inject)` : "";
    setActionStatus(row, ok ? `Done${suffix}` : (result?.error || "Failed"));
    const observedTabUrl = await readObservedTabUrl(tab);
    const finalState = {
      ...(result || {}),
      permission: permissionDecision,
      origin,
      observed_tab_url: observedTabUrl,
    };
    reportAction(action, "accept", ok ? "success" : "failure", finalState);
    recordLoopResult(action, "accept", ok ? "success" : "failure", finalState);
  } catch (err) {
    const observedTabUrl = await readObservedTabUrl(tab);
    setActionStatus(row, err.message);
    reportAction(action, "accept", "failure", { error: err.message, observed_tab_url: observedTabUrl });
    recordLoopResult(action, "accept", "failure", { error: err.message, observed_tab_url: observedTabUrl });
  }
}

// Ground-truth tab URL after an action settles. For BROWSER_NAV the
// chrome.tabs.update promise resolves before the actual navigation may
// complete; small settle delay covers the common case. Returns null on
// failure rather than throwing — observability shouldn't block dispatch.
async function readObservedTabUrl(tab) {
  if (!tab?.id) return null;
  try {
    await new Promise((r) => setTimeout(r, 75));
    const refreshed = await chrome.tabs.get(tab.id);
    return refreshed?.url || null;
  } catch (_err) {
    return null;
  }
}

async function rejectAction(action, row) {
  row.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
  setActionStatus(row, "Rejected");
  const tab = await activeTab().catch(() => null);
  await rememberPermission("decline", actionOrigin(action, tab), action);
  reportAction(action, "reject", "blocked", {});
  recordLoopResult(action, "reject", "blocked", {});
}

async function renderActions(actions = [], blockedActions = []) {
  const dock = $("#actionDock");
  const list = $("#actionList");
  list.textContent = "";
  const tab = await activeTab().catch(() => null);

  const all = [
    ...actions.map((action) => {
      const classification = classifyBrowserAction(action);
      return { ...action, blocked: false, classification, gated_by: classification.gated_by };
    }),
    ...blockedActions.map((action) => ({ ...action, blocked: true }))
  ];

  dock.hidden = all.length === 0;
  if (!all.length) return;

  // Mode-aware rendering. Plan mode = inert preview cards (no buttons,
  // "Plan only" footer). Review / Auto = current behavior, with backend
  // status taxonomy already honored by shouldAutoRunAction.
  const currentMode = ($("#modeSelect")?.value || state.config.mode || "review").toLowerCase();

  for (const action of all) {
    const row = document.createElement("section");
    row.className = "action-item";
    const origin = actionOrigin(action, tab);
    const backendStatus = String(action?.status || "").toLowerCase();
    const isPlanned = backendStatus === "planned";
    const isPlanInert = currentMode === "plan" && isPlanned && !action.blocked;
    const autoRun = !action.blocked && !isPlanInert && shouldAutoRunAction(action, origin);

    const main = document.createElement("div");
    main.className = "action-main";

    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = action.kind || "ACTION";

    const buttons = document.createElement("div");
    buttons.className = "action-buttons";

    // Plan-mode preview cards get no buttons; everything else with a
    // pending status gets Allow/Decline.
    if (!action.blocked && !autoRun && !isPlanInert) {
      const approve = document.createElement("button");
      approve.className = "primary";
      approve.type = "button";
      approve.textContent = "Allow once";
      approve.addEventListener("click", () => approveAction(action, row, "allow_once"));
      buttons.appendChild(approve);

      if (origin && !action.classification?.requires_confirm) {
        const always = document.createElement("button");
        always.className = "secondary";
        always.type = "button";
        always.textContent = "Always allow site";
        always.addEventListener("click", async () => {
          await allowOrigin(origin, action);
          approveAction(action, row, "always_allow_site");
        });
        buttons.appendChild(always);
      }

      const reject = document.createElement("button");
      reject.className = "reject";
      reject.type = "button";
      reject.textContent = "Decline";
      reject.addEventListener("click", () => rejectAction(action, row));
      buttons.appendChild(reject);
    }

    main.append(kind, buttons);

    const target = document.createElement("div");
    target.className = "target";
    target.textContent = action.target || action.reason || "";

    const gatedBy = action.gated_by || action.classification?.gated_by || null;
    const policy = document.createElement("div");
    policy.className = "policy-marker";
    policy.hidden = !gatedBy;
    policy.textContent = gateLabel(gatedBy);

    const status = document.createElement("div");
    status.className = "status";
    if (action.blocked) {
      status.textContent = action.reason || "Blocked";
    } else if (isPlanInert) {
      status.textContent = "Plan only — preview, not executed";
    } else if (autoRun) {
      status.textContent = "Queued";
    } else {
      status.textContent = "Waiting for permission";
    }

    row.append(main, target, policy, status);
    list.appendChild(row);

    if (autoRun) {
      setTimeout(() => approveAction(action, row, "auto"), 0);
    }
  }
}

async function sendPrompt() {
  const input = $("#promptInput");
  const prompt = input.value.trim();
  if (!prompt) return;

  // Bridge-state gate: if the heartbeat shows the backend unreachable,
  // refuse with a structured "would have sent" message rather than fake
  // success or a generic network-error stack trace. The user sees both
  // their prompt (so they know it was received) and the honest failure.
  // Phase 1 negative-test gate per
  // ~/.claude/plans/reactive-waddling-papert.md.
  const bridge = bridgeState();
  if (!bridge.ok) {
    appendMessage("user", prompt);
    input.value = "";
    const detail = bridge.lastError || "no heartbeat";
    appendError(
      `Bridge unreachable (${detail}). Would have sent: "${prompt}". ` +
      `Restart master-ai-ui.service to reconnect, then try again.`,
    );
    setConnection("Bridge unreachable", "error");

    // Queue a refusal record so this attempt leaves an audit row when the
    // bridge recovers. Honest-failure principle: every dispatch attempt
    // should leave evidence, even when the bridge was unreachable at the
    // moment of refusal. crypto.randomUUID assigns a stable
    // correlation_id at refusal time so client clock skew never reorders
    // the audit trail.
    state.refusalQueue = state.refusalQueue || [];
    state.refusalQueue.push({
      correlation_id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      blocked_reason: "bridge_unreachable",
      prompt: prompt,
      source: "chrome_extension",
      session_id: state.config.sessionId,
      capabilities_fired: [],
      bridge_error: detail,
    });
    // Optimistic flush attempt — almost certainly fails (bridge is down),
    // but if /health happened to recover between bridgeState() and now,
    // we don't want to wait for the next heartbeat tick. The heartbeat
    // recovery edge retries either way.
    flushRefusalQueue().catch(() => {});
    return;
  }

  const timings = {};
  const totalStart = performance.now();

  // Fresh user prompt clears any active loop from a prior goal.
  resetLoop();

  input.value = "";
  appendMessage("user", prompt);
  $("#sendButton").disabled = true;
  $("#micButton").disabled = true;
  setConnection("Thinking");

  try {
    const ctx = await pageContext(prompt, timings);
    const body = {
      prompt,
      mode: $("#modeSelect").value,
      source: "chrome_extension",
      session_id: state.config.sessionId,
      page_context: ctx,
      client_timings: { ...timings }
    };
    // Phase 2.1: surface the configured local résumé path to the model so it
    // can reference it in file-upload BROWSER_FILL targets. Empty when unset.
    if (state.config.resumePath) body.resume_path = state.config.resumePath;
    const data = await timed(timings, "chat", () => backendFetch("/chat", { method: "POST", body }));
    timings.total = Math.round(performance.now() - totalStart);
    const meta = formatMeta(data, timings);
    startLoop(data);
    appendMessage("assistant", cleanReply(data.reply), meta);
    $("#routeMeta").textContent = meta;
    await renderActions(data.actions || [], data.blocked_actions || []);
    maybeWarnSilentClaim(data.reply, data.actions || [], data);
    setConnection("Backend ready");
  } catch (err) {
    appendError(err.message);
    setConnection("Backend error", "error");
  } finally {
    $("#sendButton").disabled = false;
    $("#micButton").disabled = false;
    input.focus();
  }
}

// ── M9 Agentic Continuation Loop ──────────────────────────────────────────

function resetLoop() {
  state.loop = {
    active: false,
    turn_id: null,
    round_num: 0,
    round_budget: 3,
    pending: 0,
    rejected: false,
    results: [],
    stopped: false
  };
  const bar = $("#loopBar");
  if (bar) bar.hidden = true;
  const counter = $("#roundCounter");
  if (counter) counter.textContent = "";
}

function startLoop(data) {
  const actions = data.actions || [];
  // Browser actions are pending work even if a model mistakenly emitted DONE.
  const willContinue = actions.length > 0 && (data.round_remaining || 0) > 0;
  state.loop.turn_id = data.turn_id || null;
  state.loop.round_num = data.round_num || 1;
  state.loop.round_budget = data.round_budget || 3;
  state.loop.pending = actions.length;
  state.loop.rejected = false;
  state.loop.results = [];
  state.loop.stopped = false;
  state.loop.active = willContinue;

  const bar = $("#loopBar");
  if (bar) bar.hidden = !willContinue;
  const counter = $("#roundCounter");
  if (counter) {
    counter.textContent = willContinue
      ? `Round ${state.loop.round_num}/${state.loop.round_budget}`
      : "";
  }
}

function recordLoopResult(action, verdict, result, finalState) {
  if (!state.loop.active && state.loop.pending === 0) return;
  state.loop.results.push({
    action_id: action.id,
    verdict,
    result,
    final_state: finalState || {},
    action: { kind: action.kind, target: action.target },
    gated_by: action?.gated_by || action?.classification?.gated_by || null
  });
  if (verdict === "reject") state.loop.rejected = true;
  state.loop.pending = Math.max(0, state.loop.pending - 1);
  if (state.loop.pending === 0 && state.loop.active) {
    // Defer the continuation so UI status updates flush first.
    setTimeout(() => continueLoop(), 50);
  }
}

async function continueLoop() {
  if (state.loop.stopped || !state.loop.active || !state.loop.turn_id) {
    resetLoop();
    return;
  }
  // If the user rejected anything in this round, treat as a stop signal.
  // Model already heard "no" — don't burn round budget paraphrasing.
  if (state.loop.rejected) {
    appendMessage("assistant", "(Loop stopped — at least one action rejected.)");
    resetLoop();
    setConnection("Backend ready");
    return;
  }

  const counter = $("#roundCounter");
  if (counter) counter.textContent = `Round ${state.loop.round_num + 1}/${state.loop.round_budget} (continuing)`;
  setConnection("Continuing");
  const timings = {};
  const totalStart = performance.now();

  try {
    const body = {
      parent_turn_id: state.loop.turn_id,
      source: "chrome_extension",
      session_id: state.config.sessionId,
      action_results: state.loop.results,
      client_timings: {
        audit_queue_depth: state.auditQueue.length
      }
    };
    const data = await timed(timings, "chat", () => backendFetch("/chat/continue", { method: "POST", body }));
    timings.total = Math.round(performance.now() - totalStart);
    const meta = formatMeta(data, timings);
    startLoop(data);
    appendMessage("assistant", cleanReply(data.reply), meta);
    $("#routeMeta").textContent = meta;
    await renderActions(data.actions || [], data.blocked_actions || []);
    maybeWarnSilentClaim(data.reply, data.actions || [], data);
    if (!(data.actions || []).length) {
      resetLoop();
      setConnection("Backend ready");
    } else if (!state.loop.active) {
      setConnection("Backend ready");
    }
  } catch (err) {
    appendError(`Loop continuation failed: ${err.message}`);
    resetLoop();
    setConnection("Backend error", "error");
  }
}

function stopLoop() {
  state.loop.stopped = true;
  state.loop.active = false;
  appendMessage("assistant", "(Loop stopped by user.)");
  resetLoop();
  setConnection("Backend ready");
}

// Bridge heartbeat — recurring /health probe so the side panel knows in
// near-real-time whether the local backend is reachable. Gates dispatch so
// prompt submissions don't fake success when the bridge is down. Phase 1 of
// the agentic-follow-through layer per ~/.claude/plans/reactive-waddling-papert.md.
const HEARTBEAT_INTERVAL_MS = 7000;
const HEARTBEAT_STALE_MS = 20000;
let _heartbeatTimer = null;

function bridgeState() {
  const last = state.bridge?.lastOkAt || 0;
  const sinceMs = last > 0 ? performance.now() - last : Infinity;
  return {
    ok: last > 0 && sinceMs < HEARTBEAT_STALE_MS,
    sinceMs,
    lastError: state.bridge?.lastError || null,
  };
}

async function flushRefusalQueue() {
  // Drains queued bridge-unreachable refusal records to
  // /extension/refusal_audit. Called on heartbeat recovery so audit rows
  // get ingested as soon as the bridge is reachable again. Each record
  // carries its own correlation_id assigned at refusal time so client
  // and server clocks don't have to agree on ordering.
  if (!Array.isArray(state.refusalQueue) || state.refusalQueue.length === 0) return;
  const batch = state.refusalQueue.slice();
  for (const rec of batch) {
    try {
      await backendFetch("/extension/refusal_audit", { method: "POST", body: rec });
      const idx = state.refusalQueue.indexOf(rec);
      if (idx >= 0) state.refusalQueue.splice(idx, 1);
    } catch (_err) {
      // Bridge flapped down again or endpoint missing on this server
      // version. Leave the records in queue; next recovery edge will retry.
      break;
    }
  }
}

async function heartbeat() {
  state.bridge = state.bridge || { lastOkAt: 0, lastError: null };
  const wasOk = state.bridge.lastOkAt > 0
    && (performance.now() - state.bridge.lastOkAt) < HEARTBEAT_STALE_MS;
  try {
    const data = await backendFetch("/health");
    if (data.ok) {
      state.bridge.lastOkAt = performance.now();
      state.bridge.lastError = null;
      setConnection("Backend ready");
      // Recovery edge — flush any refusal records queued during the
      // unreachable window. Fire-and-forget; flush failures will retry
      // on the next recovery edge.
      if (!wasOk) {
        flushRefusalQueue().catch(() => {});
      }
    } else {
      state.bridge.lastError = "degraded";
      setConnection("Backend degraded", "error");
    }
  } catch (err) {
    state.bridge.lastError = err.message || String(err);
    setConnection(`Bridge unreachable: ${state.bridge.lastError}`, "error");
  }
}

function startHeartbeat() {
  heartbeat();
  if (_heartbeatTimer) clearInterval(_heartbeatTimer);
  _heartbeatTimer = setInterval(heartbeat, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat() {
  if (_heartbeatTimer) {
    clearInterval(_heartbeatTimer);
    _heartbeatTimer = null;
  }
}

// Back-compat: callers that used the one-shot healthCheck() get the new
// heartbeat path. Future code should call startHeartbeat() directly.
async function healthCheck() {
  return heartbeat();
}

async function transcribe(blob) {
  setConnection("Transcribing");
  const data = await backendFetch("/stt", { method: "POST", body: blob });
  $("#promptInput").value = data.text || "";
  $("#promptInput").focus();
  setConnection("Backend ready");
}

async function toggleMic() {
  if (state.mediaRecorder?.state === "recording") {
    state.mediaRecorder.stop();
    $("#micButton").textContent = "Mic";
    return;
  }

  try {
    state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.chunks = [];
    const options = MediaRecorder.isTypeSupported("audio/webm") ? { mimeType: "audio/webm" } : {};
    state.mediaRecorder = new MediaRecorder(state.mediaStream, options);
    state.mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) state.chunks.push(event.data);
    });
    state.mediaRecorder.addEventListener("stop", async () => {
      const blob = new Blob(state.chunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
      state.mediaStream?.getTracks().forEach((track) => track.stop());
      try {
        await transcribe(blob);
      } catch (err) {
        appendError(`Transcription failed: ${err.message}`);
        setConnection("Backend error", "error");
      }
    });
    state.mediaRecorder.start();
    $("#micButton").textContent = "Stop";
    setConnection("Recording");
  } catch (err) {
    appendError(`Microphone unavailable: ${err.message}`);
  }
}

function installTabCacheInvalidation() {
  chrome.tabs.onUpdated?.addListener((tabId, changeInfo) => {
    if (changeInfo.url || changeInfo.status === "loading") invalidatePageContext(tabId);
  });
  chrome.tabs.onRemoved?.addListener((tabId) => invalidatePageContext(tabId));
  chrome.tabs.onActivated?.addListener(() => {
    state.contextCache = null;
  });
}

async function prewarmActiveTab() {
  try {
    const tab = await activeTab();
    await ensureContentScript(tab, {});
  } catch (_err) {
    // Prewarming is best-effort; restricted browser pages still use fallback context.
  }
}

async function init() {
  await loadConfig();
  installTabCacheInvalidation();
  $("#composer").addEventListener("submit", (event) => {
    event.preventDefault();
    sendPrompt();
  });
  $("#promptInput").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      sendPrompt();
    }
  });
  $("#modeSelect").addEventListener("change", (event) => saveMode(event.target.value));
  $("#micButton").addEventListener("click", toggleMic);
  $("#clearActions").addEventListener("click", () => {
    $("#actionList").textContent = "";
    $("#actionDock").hidden = true;
  });
  $("#openOptions").addEventListener("click", () => chrome.runtime.openOptionsPage());
  $("#stopButton")?.addEventListener("click", stopLoop);
  prewarmActiveTab();
  startHeartbeat();
  appendMessage("assistant", "Ready.");
}

init().catch((err) => appendError(err.message));
