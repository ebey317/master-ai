const DEFAULT_CONFIG = {
  backendUrl: "http://127.0.0.1:8080",
  token: "",
  mode: "review",
  sessionId: "",
  actionPermissionMode: "ask",
  approvedOrigins: [],
  blockedOrigins: [
    "https://accounts.google.com",
    "https://pay.google.com",
  ],
  permissionHistory: [],
  resumePath: ""
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
const PAGE_TREE_BYTE_LIMIT = 24 * 1024;
const AX_TREE_TEXT_LIMIT = 14 * 1024;
const PAGE_STABLE_WAIT_MS = 650;
const PAGE_CONTEXT_PROMPT_RE =
  /\b(application|apply|browser|button|click|current\s+(page|tab|site)|drive|folder|field|fill|form|indeed|job|link|page|read|resume|résumé|screen|screenshot|search|select|selected|selection|simplify|tab|this|upload|visible|website|ziprecruiter)\b/i;
const READONLY_BROWSER_KINDS = new Set([
  "BROWSER_READ",
  "BROWSER_READ_PAGE",
  "BROWSER_OBSERVE",
  "BROWSER_SCREENSHOT",
  "BROWSER_WAIT",
  "BROWSER_SCROLL",
  "BROWSER_FIND",
  "BROWSER_EXTRACT_LIST",
  "BROWSER_DRIVE_INSPECT_FOLDER",
]);
const CONTEXT_SETTLING_BROWSER_KINDS = new Set([
  "BROWSER_NAV",
  "BROWSER_CLICK",
  "BROWSER_DOUBLE_CLICK",
  "BROWSER_FILL",
  "BROWSER_SCROLL",
  "BROWSER_WAIT",
]);

const state = {
  config: { ...DEFAULT_CONFIG },
  mediaRecorder: null,
  mediaStream: null,
  chunks: [],
  injectedTabs: new Set(),
  contextCache: null,
  auditQueue: [],
  auditFlushing: false,
  // Phase 1.1 — Domain classifier cache. host -> {result, ts}. Result shape:
  // {category, reason, matched, host, ttl_s}. Pre-warmed before renderActions
  // for the active-tab origin and any BROWSER_NAV targets in the round.
  domainClassCache: new Map(),
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
  if (!Array.isArray(state.config.blockedOrigins)) state.config.blockedOrigins = [];
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
    return !/^\s*(RUNTERM|RUN|READ|CREATE|EDIT|REMEMBER|BROWSER_[A-Z_]+):/i.test(line)
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
const CLAIMED_BROWSER_ACTION_RE = /(?:\b(?:captur(?:ed|ing)|took (?:a |the )?(?:screenshot|snapshot|picture|photo)|taking (?:a |the )?(?:screenshot|snapshot|picture|photo)|screenshot(?:ted|ed)?|navigated to|opened (?:the |this )?(?:page|tab|link|url|site|website))\b)|(?:\b(?:clicked|filled (?:in |out )?(?:the )?|typed (?:into )?(?:the )?|pressed (?:the )?|scrolled (?:to |up |down )?)\b.{0,40}\b(?:button|link|field|form|input|tab|key|enter|return|escape|element|icon|email|password|down|up|bottom|top)\b)|(?:BROWSER_[A-Z_]+)/i;

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

function jsonByteLength(value) {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).length;
  } catch (_err) {
    return String(JSON.stringify(value || "")).length;
  }
}

function clipStringField(obj, field, limit) {
  if (typeof obj?.[field] === "string" && obj[field].length > limit) {
    obj[field] = `${obj[field].slice(0, limit).trim()}...`;
    return true;
  }
  return false;
}

function trimPageContextToBudget(context, budgetBytes = PAGE_TREE_BYTE_LIMIT) {
  if (!context || typeof context !== "object") return context || {};
  const out = typeof structuredClone === "function" ? structuredClone(context) : JSON.parse(JSON.stringify(context));
  out.context_budget = {
    bytes: budgetBytes,
    truncated: false,
    strategy: "24KB local-lane cap; trim visible text, semantic tail, then low-priority interactives",
  };
  const mark = () => { out.context_budget.truncated = true; };

  if (jsonByteLength(out) <= budgetBytes) return out;
  if (clipStringField(out, "visible_text", 2400)) mark();
  if (jsonByteLength(out) <= budgetBytes) return out;

  if (out.semantic_tree?.text) {
    out.semantic_tree.text = `${String(out.semantic_tree.text).slice(0, 9000).trim()}...`;
    out.semantic_tree.truncated = true;
    mark();
  }
  if (jsonByteLength(out) <= budgetBytes) return out;

  if (Array.isArray(out.semantic_fallback)) {
    out.semantic_fallback = out.semantic_fallback.slice(0, 60);
    mark();
  }
  if (jsonByteLength(out) <= budgetBytes) return out;

  if (typeof out.interactive_elements === "string") {
    out.interactive_elements = `${out.interactive_elements.slice(0, 5000).trim()}...`;
    mark();
  }
  if (Array.isArray(out.iframes) && out.iframes.length > 12) {
    out.iframes = out.iframes.slice(0, 12);
    mark();
  }
  if (jsonByteLength(out) <= budgetBytes) return out;

  if (out.dom_state?.forms) {
    out.dom_state.forms = out.dom_state.forms.slice(0, 8).map((form) => ({
      ...form,
      fields: Array.isArray(form.fields) ? form.fields.slice(0, 18) : []
    }));
    mark();
  }
  if (jsonByteLength(out) <= budgetBytes) return out;

  if (clipStringField(out, "visible_text", 1200)) mark();
  if (out.console_state) {
    out.console_state = Array.isArray(out.console_state) ? out.console_state.slice(-8) : [];
    mark();
  }
  return out;
}

function axValue(raw) {
  if (!raw) return "";
  if (typeof raw.value === "string" || typeof raw.value === "number" || typeof raw.value === "boolean") {
    return String(raw.value);
  }
  return "";
}

function axProp(node, name) {
  const prop = Array.isArray(node?.properties)
    ? node.properties.find((entry) => entry?.name === name)
    : null;
  return axValue(prop?.value);
}

function axRole(node) {
  return axValue(node?.role) || "";
}

function axName(node) {
  return axValue(node?.name) || axProp(node, "label") || "";
}

function keepAxNode(node) {
  if (!node || node.ignored) return false;
  const role = axRole(node);
  const name = axName(node);
  const value = axValue(node.value);
  if (name || value) return true;
  return /^(RootWebArea|main|navigation|banner|contentinfo|search|form|dialog|alert|heading|button|link|textbox|searchbox|combobox|checkbox|radio|switch|tab|menuitem|row|cell|grid|table|list|listitem|iframe)$/i.test(role);
}

function compactAccessibilityTree(nodes, maxBytes = AX_TREE_TEXT_LIMIT) {
  if (!Array.isArray(nodes) || !nodes.length) return null;
  const byId = new Map(nodes.map((node) => [String(node.nodeId), node]));
  const root = nodes.find((node) => axRole(node) === "RootWebArea") || nodes[0];
  const lines = [];
  const seen = new Set();
  let bytes = 0;
  let truncated = false;

  const addLine = (line) => {
    const nextBytes = new TextEncoder().encode(`${line}\n`).length;
    if (bytes + nextBytes > maxBytes) {
      truncated = true;
      return false;
    }
    lines.push(line);
    bytes += nextBytes;
    return true;
  };

  const visit = (node, depth) => {
    if (!node || seen.has(node.nodeId) || truncated) return;
    seen.add(node.nodeId);
    const kept = keepAxNode(node);
    if (kept) {
      const role = axRole(node) || "node";
      const name = axName(node);
      const value = axValue(node.value);
      const states = [
        axProp(node, "checked") ? `checked=${axProp(node, "checked")}` : "",
        axProp(node, "selected") ? `selected=${axProp(node, "selected")}` : "",
        axProp(node, "expanded") ? `expanded=${axProp(node, "expanded")}` : "",
        axProp(node, "disabled") ? `disabled=${axProp(node, "disabled")}` : "",
      ].filter(Boolean).join(" ");
      const label = [
        `${"  ".repeat(Math.min(depth, 6))}- ${role}`,
        name ? `"${name.slice(0, 220)}"` : "",
        value ? `value="${value.slice(0, 160)}"` : "",
        states
      ].filter(Boolean).join(" ");
      if (!addLine(label)) return;
    }
    for (const childId of node.childIds || []) {
      visit(byId.get(String(childId)), kept ? depth + 1 : depth);
      if (truncated) break;
    }
  };

  visit(root, 0);
  return {
    source: "chrome_accessibility_tree",
    budget_bytes: maxBytes,
    truncated,
    node_count: nodes.length,
    retained_lines: lines.length,
    text: lines.join("\n")
  };
}

function summarizeAxSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "";
  const buckets = [
    ["heading", snapshot.headings],
    ["landmark", snapshot.landmarks],
    ["button", snapshot.buttons],
    ["link", snapshot.links],
    ["input", snapshot.inputs],
    ["dialog", snapshot.dialogs],
    ["row", snapshot.file_folder_rows],
    ["iframe", snapshot.iframes],
  ];
  const lines = [];
  for (const [kind, items] of buckets) {
    if (!Array.isArray(items)) continue;
    for (const item of items.slice(0, 80)) {
      const role = item.role || kind;
      const name = item.name || item.label || item.text || item.title || item.src || "";
      const ref = item.ref ? ` ref=${item.ref}` : "";
      const selector = item.selector ? ` selector=${item.selector}` : "";
      const hidden = item.cross_origin ? " cross_origin=true" : "";
      lines.push(`- ${role} "${String(name).slice(0, 220)}"${ref}${selector}${hidden}`);
      if (lines.join("\n").length > AX_TREE_TEXT_LIMIT) {
        lines.push("...");
        return lines.join("\n");
      }
    }
  }
  return lines.join("\n");
}

async function withChromeDebugger(tab, timings, fn) {
  if (!chrome.debugger?.attach || !tab?.id) throw new Error("chrome.debugger unavailable");
  const target = { tabId: tab.id };
  let attached = false;
  await timed(timings, "debugger_attach", () => chrome.debugger.attach(target, "1.3"));
  attached = true;
  const send = (method, params = {}) => timed(timings, `cdp_${method.split(".").pop()}`, () =>
    chrome.debugger.sendCommand(target, method, params)
  );
  try {
    return await fn(send);
  } finally {
    if (attached) {
      try { await chrome.debugger.detach(target); } catch (_err) {}
    }
  }
}

async function accessibilityTreeContext(tab, timings = {}) {
  try {
    const response = await timed(timings, "ax_snapshot", () => chrome.runtime.sendMessage({
      type: "SENSEI_BUILD_AX_SNAPSHOT",
      tabId: tab.id,
    }));
    if (response?.ok && response.snapshot) {
      return {
        tree: response.snapshot,
        semantic_tree: {
          source: "chrome_accessibility_tree",
          budget_bytes: PAGE_TREE_BYTE_LIMIT,
          snapshot: response.snapshot,
          text: summarizeAxSnapshot(response.snapshot),
          truncated: Boolean(response.snapshot?.truncation),
        },
        browser_read_source: "accessibility_tree_primary",
      };
    }
  } catch (_err) {
    // Older service-worker builds do not expose SENSEI_BUILD_AX_SNAPSHOT.
    // Fall through to a direct debugger read from the side panel.
  }

  try {
    return await withChromeDebugger(tab, timings, async (send) => {
      await send("Accessibility.enable");
      const result = await send("Accessibility.getFullAXTree");
      const semanticTree = compactAccessibilityTree(result?.nodes || []);
      if (!semanticTree) return null;
      return {
        semantic_tree: semanticTree,
        browser_read_source: "accessibility_tree_primary",
      };
    });
  } catch (err) {
    return {
      browser_read_source: "content_script_fallback",
      accessibility_error: String(err?.message || err).slice(0, 300),
    };
  }
}

async function contentScriptPageContext(tab, options, timings = {}) {
  await ensureContentScript(tab, timings);
  const response = await timed(timings, "context", () => chrome.tabs.sendMessage(tab.id, {
    type: "SENSEI_PAGE_CONTEXT",
    options
  }));
  return response?.page_context || {};
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
    const [domContext, axContext] = await Promise.all([
      contentScriptPageContext(tab, {
        includeVisibleText,
        includeInteractiveElements: true,
        visibleTextLimit: PAGE_CONTEXT_TEXT_LIMIT,
        waitForStableMs: PAGE_STABLE_WAIT_MS,
        maxWaitMs: 4500,
      }, timings).catch(() => fallback),
      accessibilityTreeContext(tab, timings),
    ]);
    const value = trimPageContextToBudget({ ...fallback, ...(domContext || {}), ...(axContext || {}) });
    state.contextCache = { key, tabId: tab.id, ts: performance.now(), value };
    return value;
  } catch (_err) {
    return fallback;
  }
}

async function freshPageContextForContinuation(timings = {}) {
  const tab = await timed(timings, "tab", activeTab);
  if (!tab?.id) return {};
  const fallback = { url: tab.url || "", title: tab.title || "" };
  if (!canInjectIntoTab(tab)) return fallback;

  try {
    await waitForTabSettled(tab.id, 6000);
    const current = await chrome.tabs.get(tab.id);
    const [domContext, axContext] = await Promise.all([
      contentScriptPageContext(current, {
        includeVisibleText: true,
        includeInteractiveElements: true,
        visibleTextLimit: PAGE_CONTEXT_TEXT_LIMIT,
        waitForStableMs: PAGE_STABLE_WAIT_MS,
        maxWaitMs: 4500,
      }, timings).catch(() => fallback),
      accessibilityTreeContext(current, timings),
    ]);
    return trimPageContextToBudget({ ...fallback, ...(domContext || {}), ...(axContext || {}) });
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

function parseFillTargetForBridge(action) {
  const raw = String(action?.target || "").trim();
  const extras = action?.extras || {};
  if (raw.startsWith("{")) {
    try {
      const parsed = JSON.parse(raw);
      return {
        selector: String(parsed.selector || parsed.target || "").trim(),
        value: String(parsed.value || parsed.text || "").trim(),
      };
    } catch (_err) {
      // Fall through to delimiter parsing.
    }
  }
  const match = raw.match(/^(.*?)\s*(?:=>|:=|::)\s*([\s\S]*)$/);
  if (match) return { selector: match[1].trim(), value: match[2].trim() };
  return {
    selector: raw,
    value: String(extras.value || extras.text || "").trim(),
  };
}

function localPathFromFillValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^file:\/\//i.test(raw)) {
    try {
      return decodeURIComponent(new URL(raw).pathname);
    } catch (_err) {
      return raw.replace(/^file:\/\//i, "");
    }
  }
  if ((raw.startsWith("~/") || raw.startsWith("/")) &&
      /\.(pdf|docx?|odt|rtf|txt|csv|jpe?g|png|webp|gif|zip)$/i.test(raw)) {
    return raw;
  }
  return "";
}

function basenameForPath(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "upload.bin";
}

function promptNeedsLocalFileHints(prompt) {
  return /\b(resume|résumé|cv|cover\s+letter|ai\s+query|transcript|certificate|certification|pdf|docx?|upload|application)\b/i
    .test(String(prompt || ""));
}

async function localFileHintsForPrompt(prompt) {
  if (!promptNeedsLocalFileHints(prompt)) return null;
  try {
    const preferred = [state.config.resumePath].filter(Boolean);
    const data = await backendFetch("/extension/resolve_local_file", {
      method: "POST",
      body: { query: prompt, preferred_paths: preferred },
      timeoutMs: 9000,
    });
    if (!data?.ok || !Array.isArray(data.candidates) || !data.candidates.length) return null;
    return {
      query: data.query || prompt,
      ambiguous: Boolean(data.ambiguous),
      candidates: data.candidates.slice(0, 5),
    };
  } catch (_err) {
    return null;
  }
}

async function attachLocalFilePayload(action) {
  const kind = String(action?.kind || "").toUpperCase();
  if (kind !== "BROWSER_FILL") return action;
  const parsed = parseFillTargetForBridge(action);
  const path = localPathFromFillValue(parsed.value);
  if (!path) return action;

  const file = await backendFetch("/extension/read_local_file", {
    method: "POST",
    body: { path },
    timeoutMs: 60000,
  });
  if (!file?.ok || !file?.base64) {
    throw new Error(file?.error || `local file read failed: ${path}`);
  }
  return {
    ...action,
    extras: {
      ...(action.extras || {}),
      fileUpload: {
        path: file.path || path,
        name: basenameForPath(file.path || path),
        mime: file.mime || "application/octet-stream",
        size: file.size || 0,
        base64: file.base64,
      },
    },
  };
}

async function tryDebuggerFileUpload(tab, action, timings = {}) {
  const kind = String(action?.kind || "").toUpperCase();
  if (kind !== "BROWSER_FILL") return null;
  const parsed = parseFillTargetForBridge(action);
  const requestedPath = localPathFromFillValue(parsed.value);
  if (!requestedPath || !parsed.selector) return null;

  const file = await backendFetch("/extension/read_local_file", {
    method: "POST",
    body: { path: requestedPath },
    timeoutMs: 60000,
  });
  if (!file?.ok) throw new Error(file?.error || `local file read failed: ${requestedPath}`);
  const path = file.path || requestedPath;

  try {
    const uploaded = await withChromeDebugger(tab, timings, async (send) => {
      await send("DOM.enable");
      const expression = `document.querySelector(${JSON.stringify(parsed.selector)})`;
      const evaluated = await send("Runtime.evaluate", {
        expression,
        objectGroup: "sensei-file-upload",
        includeCommandLineAPI: false,
      });
      const objectId = evaluated?.result?.objectId;
      if (!objectId) throw new Error("file input selector did not resolve in debugger");
      const node = await send("DOM.requestNode", { objectId });
      if (!node?.nodeId) throw new Error("debugger could not resolve file input node");
      await send("DOM.setFileInputFiles", {
        nodeId: node.nodeId,
        files: [path],
      });
      await send("Runtime.evaluate", {
        expression: `(() => { const el = document.querySelector(${JSON.stringify(parsed.selector)}); if (!el) return false; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`,
        includeCommandLineAPI: false,
        returnByValue: true,
      }).catch(() => {});
      await send("Runtime.releaseObject", { objectId }).catch(() => {});
      return {
        ok: true,
        filled: parsed.selector,
        file_upload: {
          method: "debugger.DOM.setFileInputFiles",
          path,
          file_name: basenameForPath(path),
          file_size: file.size || 0,
          mime: file.mime || "application/octet-stream",
        },
      };
    });
    return uploaded;
  } catch (err) {
    return {
      ok: false,
      debugger_file_upload_failed: true,
      error: String(err?.message || err),
      fallback_action: {
        ...action,
        extras: {
          ...(action.extras || {}),
          fileUpload: {
            path,
            name: basenameForPath(path),
            mime: file.mime || "application/octet-stream",
            size: file.size || 0,
            base64: file.base64,
          },
        },
      }
    };
  }
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

// Phase 1.1 domain-classifier wiring. The backend at /extension/classify_domain
// returns one of four categories per host; we cache the result per host with a
// TTL hint from the response. Categories 1/2 are blocked at classifyBrowserAction
// time; category 3 forces per-action confirm even on otherwise-safe kinds.
const DOMAIN_CLASS_CACHE_TTL_MS = 5 * 60 * 1000;

function hostFromOriginOrUrl(input) {
  const raw = String(input || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw.startsWith("http") ? raw : `https://${raw}`);
    return (url.hostname || "").toLowerCase();
  } catch (_err) {
    return raw.toLowerCase().split("/")[0].split(":")[0];
  }
}

async function classifyOrigin(originOrUrl) {
  const host = hostFromOriginOrUrl(originOrUrl);
  if (!host) return { category: 0, reason: "no host", matched: "", host: "" };
  const now = Date.now();
  const cached = state.domainClassCache.get(host);
  if (cached && (now - cached.ts) < DOMAIN_CLASS_CACHE_TTL_MS) return cached.result;
  try {
    const result = await backendFetch("/extension/classify_domain", {
      method: "POST",
      body: { domain: host },
      timeoutMs: 4000
    });
    if (result && typeof result.category === "number") {
      state.domainClassCache.set(host, { result, ts: now });
      return result;
    }
  } catch (_err) {
    // Fail open. Classifier unreachable means we don't add classifier-based
    // blocks; the local blockedOrigins list + category regex below still apply.
  }
  return { category: 0, reason: "classifier unreachable", matched: "", host };
}

async function ensureOriginsClassified(origins = []) {
  const hosts = [...new Set(origins.filter(Boolean).map(hostFromOriginOrUrl).filter(Boolean))];
  if (!hosts.length) return;
  await Promise.all(hosts.map((host) => classifyOrigin(host)));
}

function originDomainClass(originOrUrl) {
  const host = hostFromOriginOrUrl(originOrUrl);
  if (!host) return null;
  const cached = state.domainClassCache.get(host);
  if (!cached) return null;
  if ((Date.now() - cached.ts) > DOMAIN_CLASS_CACHE_TTL_MS) return null;
  return cached.result;
}

function originBlockedReason(originOrUrl = "") {
  const raw = String(originOrUrl || "");
  const origin = originForUrl(raw) || raw;
  // Phase 1.1 — classifier verdict wins over local-only signals when present.
  const verdict = originDomainClass(raw);
  if (verdict && verdict.category === 1) {
    return "domain_classifier:cat1_malicious";
  }
  if (verdict && verdict.category === 2) {
    return "domain_classifier:cat2_sensitive_auth";
  }
  const blocked = state.config.blockedOrigins || [];
  if (blocked.some((entry) => origin === entry || origin.endsWith(`.${String(entry).replace(/^https?:\/\//, "")}`))) {
    return "site_blocklist:user_blocked_site";
  }
  const host = (() => {
    try { return new URL(origin.startsWith("http") ? origin : `https://${origin}`).hostname; }
    catch (_err) { return raw; }
  })().toLowerCase();
  const categoryPatterns = [
    ["financial", /\b(bank|banking|paypal|stripe|venmo|cashapp|coinbase|robinhood|fidelity|vanguard|schwab|chase|wellsfargo|capitalone|amex|visa|mastercard)\b/i],
    ["adult", /\b(adult|porn|xxx|onlyfans)\b/i],
    ["piracy", /\b(torrent|pirate|crack|warez)\b/i],
  ];
  const matched = categoryPatterns.find(([, pattern]) => pattern.test(host));
  return matched ? `site_blocklist:high_risk_${matched[0]}` : "";
}

async function sendToContent(tab, action, timings = {}) {
  const ready = await ensureContentScript(tab, timings);
  if (!ready) throw new Error("cannot access this tab");
  const bridgedAction = await attachLocalFilePayload(action);
  return chrome.tabs.sendMessage(tab.id, { type: "SENSEI_EXECUTE_ACTION", action: bridgedAction });
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

function classifyBrowserAction(action, origin = "") {
  const kind = String(action?.kind || "").toUpperCase();
  const target = String(action?.target || "").toLowerCase();
  const checkUrl = kind === "BROWSER_NAV" ? target : origin;
  const blockedReason = originBlockedReason(checkUrl);
  if (blockedReason) {
    return {
      safe: false,
      requires_confirm: true,
      blocked: true,
      gated_by: blockedReason,
      reason: `Blocked by pilot safety policy: ${blockedReason.split(":").pop().replace(/_/g, " ")}`
    };
  }

  // Phase 1.1 — category 3 ("force confirm every action") wins over an
  // otherwise-safe verdict but does NOT block. Re-checked after the existing
  // heuristics so explicit purchase/delete/auth gating still surfaces its
  // own gated_by string.
  const verdict = originDomainClass(checkUrl);
  const cat3 = verdict && verdict.category === 3 ? verdict : null;
  const applyCat3 = (result) => {
    if (!cat3 || result.blocked || result.requires_confirm) return result;
    return {
      ...result,
      safe: false,
      requires_confirm: true,
      gated_by: result.gated_by || "domain_classifier:cat3_force_confirm",
      reason: result.reason || `High-friction domain — ${cat3.reason || cat3.matched}`
    };
  };

  const PURCHASE_RE = /\b(buy|purchase|pay|checkout|order|subscribe|add to cart)\b/i;
  const DELETE_RE = /\b(delete|remove|destroy|uninstall|erase|wipe|cancel.*(account|subscription))\b/i;
  const AUTH_RE = /\b(sign[-_\s]*up|sign[-_\s]*in|log[-_\s]*in|log[-_\s]*out|register|authorize|grant\s*access|oauth|api\s*key)\b/i;
  // Anthropic-spec hard-limit list (https://support.anthropic.com/en/collections/13228104-claude-for-chrome):
  // never enter passwords, SSNs, financial account numbers, passport numbers,
  // or medical data. Existing terms (password / ssn / credit card / etc.)
  // covered the first three; passport + medical-class terms + driver license
  // + date of birth close the documented gap.
  const SENSITIVE_RE = /\b(password|ssn|social.*security|credit.*card|cvv|cvc|api.*key|bank.*account|routing.*number|passport|passport.*number|medical(.*record)?|diagnosis|health.*insurance|patient.*id|driver.*license|driver.*licence|date.*of.*birth|dob)\b/i;
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
  if (READONLY_BROWSER_KINDS.has(kind)) {
    return applyCat3({ safe: true, requires_confirm: false, gated_by: null });
  }
  return applyCat3({ safe: true, requires_confirm: false, gated_by: null });
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

  // Auto-mode safe BROWSER_*: approved-origin auto-run, plus read-only
  // observation/navigation-assist actions that do not mutate page data.
  if (origin && state.config.approvedOrigins.includes(origin)) return true;
  if (READONLY_BROWSER_KINDS.has(kind)) return true;
  return false;
}

async function approveAction(action, row, permissionDecision = "allow_once") {
  const kind = String(action.kind || "").toUpperCase();
  const timings = {};
  let tab = null;
  setActionStatus(row, "Running");
  row.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });

  if (!kind.startsWith("BROWSER_")) {
    setActionStatus(row, "Backend-only — switch the mode dropdown to \"Act without asking\" to dispatch");
    reportAction(action, "accept", "blocked", { reason: "non-browser action; backend dispatches in auto mode" });
    recordLoopResult(action, "accept", "blocked", { reason: "non-browser action; backend dispatches in auto mode" });
    return;
  }

  try {
    tab = await activeTab();
    if (!tab?.id) throw new Error("no active tab");
    const origin = actionOrigin(action, tab);
    const blockedReason = originBlockedReason(kind === "BROWSER_NAV" ? action.target : origin);
    if (blockedReason) {
      throw new Error(`blocked by pilot safety policy: ${blockedReason}`);
    }
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
        dataUrl_preview: truncateDataUrlForAudit(capture.dataUrl),
        context_lifetime: "one_turn"
      };
    } else if (kind === "BROWSER_NAV") {
      const url = normalizeUrl(action.target);
      await chrome.tabs.update(tab.id, { url });
      await waitForTabSettled(tab.id, 8000);
      result = { ok: true, navigated: url };
      invalidatePageContext(tab.id);
    } else if (kind === "BROWSER_READ_PAGE" || kind === "BROWSER_OBSERVE") {
      result = {
        ok: true,
        page_context: await freshPageContextForContinuation(timings),
        text: "Page observed with semantic tree and current interactives."
      };
    } else if (kind === "BROWSER_DRIVE_INSPECT_FOLDER") {
      result = await sendToContent(tab, action, timings);
      invalidatePageContext(tab.id);
    } else if (kind === "BROWSER_FILL") {
      const uploadAttempt = await tryDebuggerFileUpload(tab, action, timings);
      if (uploadAttempt?.ok) {
        result = uploadAttempt;
      } else if (uploadAttempt?.fallback_action) {
        result = await sendToContent(tab, uploadAttempt.fallback_action, timings);
        if (!result?.ok) result = { ...result, debugger_fallback_error: uploadAttempt.error };
      } else {
        result = await sendToContent(tab, action, timings);
      }
      if (CONTEXT_SETTLING_BROWSER_KINDS.has(kind)) await waitForTabSettled(tab.id, 4000);
      invalidatePageContext(tab.id);
    } else {
      result = await sendToContent(tab, action, timings);
      if (CONTEXT_SETTLING_BROWSER_KINDS.has(kind)) await waitForTabSettled(tab.id, 4000);
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

function normalizeDriveTerm(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function parseDriveInspectTarget(action) {
  const raw = String(action?.target || "").trim();
  let parsed = {};
  if (raw.startsWith("{")) {
    try {
      parsed = JSON.parse(raw);
    } catch (_err) {
      parsed = {};
    }
  }
  const query = String(parsed.query || parsed.folder || raw || "resume").trim();
  const variants = Array.isArray(parsed.variants) ? parsed.variants : [];
  const terms = [query, ...variants].filter(Boolean).map(String);
  if (/\b(resume|cv|career)\b/i.test(normalizeDriveTerm(query)) || !terms.length) {
    terms.push("Resume", "resume", "résumé", "CV", "career");
  }
  const uniqueTerms = [];
  const seen = new Set();
  for (const term of terms) {
    const cleaned = String(term || "").trim();
    const key = normalizeDriveTerm(cleaned);
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    uniqueTerms.push(cleaned);
  }
  return {
    query: query || uniqueTerms[0] || "resume",
    variants: uniqueTerms.length ? uniqueTerms : ["resume"],
    folderOnly: parsed.folderOnly !== false,
    maxSearches: Math.max(1, Math.min(Number(parsed.maxSearches || 5), 8)),
  };
}

async function sleepMs(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForTabSettled(tabId, timeoutMs = 10000) {
  const start = performance.now();
  while (performance.now() - start < timeoutMs) {
    try {
      const current = await chrome.tabs.get(tabId);
      if (current?.status === "complete") break;
    } catch (_err) {
      break;
    }
    await sleepMs(250);
  }
  // Google Drive is an SPA; complete fires before the result grid finishes.
  await sleepMs(1600);
}

async function driveExtract(tab, action, phase, query) {
  const target = JSON.stringify({ phase, query });
  const result = await sendToContent(tab, {
    ...action,
    kind: "BROWSER_DRIVE_INSPECT_FOLDER",
    target,
  });
  return result?.drive_state || result?.list_state || result || {};
}

function scoreDriveItem(item, terms, folderOnly) {
  if (!item || typeof item !== "object") return 0;
  const name = normalizeDriveTerm(item.name || "");
  const haystack = normalizeDriveTerm([
    item.name,
    item.aria_label,
    item.text,
    item.kind
  ].filter(Boolean).join(" "));
  let score = item.selected ? 35 : 0;
  if (item.is_folder) score += 20;
  if (folderOnly && item.kind === "file") score -= 20;
  for (const term of terms) {
    const t = normalizeDriveTerm(term);
    if (!t) continue;
    if (name === t) score += 80;
    else if (name.includes(t)) score += 45;
    else if (haystack.includes(t)) score += 25;
  }
  return score;
}

function pickDriveItem(state, opts) {
  const items = Array.isArray(state?.items) ? state.items : [];
  const scored = items
    .map((item) => ({ item, score: scoreDriveItem(item, opts.variants, opts.folderOnly) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score);
  return scored[0]?.item || null;
}

function summarizeDriveState(state) {
  if (!state || typeof state !== "object") return "No Drive state returned.";
  if (state.empty) {
    return `Drive folder appears empty (${state.empty_reason || "empty-state text visible"}).`;
  }
  const items = Array.isArray(state.items) ? state.items : [];
  if (!items.length) return state.summary || "No visible Drive items were extracted.";
  const names = items.slice(0, 12).map((item) => {
    const suffix = item.kind && item.kind !== "unknown" ? ` (${item.kind})` : "";
    return `${item.name || item.aria_label || "unnamed"}${suffix}`;
  });
  const extra = items.length > names.length ? ` and ${items.length - names.length} more` : "";
  return `Drive items: ${names.join("; ")}${extra}.`;
}

async function openDriveItem(tab, item) {
  if (item?.href && /^https:\/\/drive\.google\.com\//i.test(item.href)) {
    await chrome.tabs.update(tab.id, { url: item.href });
    invalidatePageContext(tab.id);
    return { method: "href", href: item.href };
  }
  if (!item?.selector) throw new Error("matching Drive item has no selector");
  const result = await sendToContent(tab, {
    kind: "BROWSER_DOUBLE_CLICK",
    target: item.selector,
  });
  if (!result?.ok) throw new Error(result?.error || "Drive item open failed");
  invalidatePageContext(tab.id);
  return { method: "double_click", selector: item.selector };
}

async function inspectDriveFolderWorkflow(tab, action) {
  const opts = parseDriveInspectTarget(action);
  const searchStates = [];
  let lastUrl = tab?.url || "";

  for (const variant of opts.variants.slice(0, opts.maxSearches)) {
    const searchUrl = `https://drive.google.com/drive/search?q=${encodeURIComponent(variant)}`;
    await chrome.tabs.update(tab.id, { url: searchUrl });
    invalidatePageContext(tab.id);
    await waitForTabSettled(tab.id);
    tab = await chrome.tabs.get(tab.id);
    lastUrl = tab?.url || searchUrl;
    const searchState = await driveExtract(tab, action, "search", variant);
    searchStates.push({
      variant,
      url: searchState.url || lastUrl,
      summary: summarizeDriveState(searchState),
      empty: Boolean(searchState.empty),
      items: Array.isArray(searchState.items) ? searchState.items.slice(0, 20) : [],
    });
    const match = pickDriveItem(searchState, opts);
    if (!match) continue;

    const openResult = await openDriveItem(tab, match);
    await waitForTabSettled(tab.id);
    tab = await chrome.tabs.get(tab.id);
    const folderState = await driveExtract(tab, action, "folder", variant);
    const observedUrl = await readObservedTabUrl(tab);
    const summary = summarizeDriveState(folderState);
    return {
      ok: true,
      drive_workflow: "folder_inspected",
      query: opts.query,
      matched_variant: variant,
      found_item: match,
      open_result: openResult,
      observed_tab_url: observedUrl,
      search_states: searchStates,
      folder_state: folderState,
      text: summary,
    };
  }

  return {
    ok: true,
    drive_workflow: "no_matching_folder",
    query: opts.query,
    observed_tab_url: lastUrl,
    search_states: searchStates,
    text: `No matching Drive folder was extracted after searching: ${opts.variants.slice(0, opts.maxSearches).join(", ")}.`,
  };
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

  // Phase 1.1 — pre-warm the domain classifier for every origin we're about
  // to classify (active-tab origin + any BROWSER_NAV targets in this round).
  // Synchronous classifyBrowserAction below reads from state.domainClassCache;
  // failing to pre-warm just means classifier verdicts won't apply this round
  // (we still fall back to the local blockedOrigins + regex categories).
  try {
    const candidateOrigins = [];
    if (tab) candidateOrigins.push(actionOrigin({}, tab));
    for (const action of actions) {
      candidateOrigins.push(actionOrigin(action, tab));
      if (String(action?.kind || "").toUpperCase() === "BROWSER_NAV") {
        candidateOrigins.push(String(action?.target || ""));
      }
    }
    await ensureOriginsClassified(candidateOrigins);
  } catch (_err) {
    // Pre-warm is best-effort; never block the render.
  }

  const all = [
    ...actions.map((action) => {
      const origin = actionOrigin(action, tab);
      const classification = classifyBrowserAction(action, origin);
      return {
        ...action,
        blocked: Boolean(classification.blocked),
        reason: classification.reason || action.reason,
        classification,
        gated_by: classification.gated_by
      };
    }),
    ...blockedActions.map((action) => ({ ...action, blocked: true }))
  ];

  dock.hidden = all.length === 0;
  if (!all.length) return;

  // Mode-aware rendering. Plan mode = inert preview cards (no buttons,
  // "Plan only" footer). Review / Auto = current behavior, with backend
  // status taxonomy already honored by shouldAutoRunAction.
  const currentMode = ($("#modeSelect")?.value || state.config.mode || "review").toLowerCase();

  // Anthropic-spec "Ask before acting" UI: when the model emits 3+
  // pending browser actions in one round AND none of them auto-flow
  // yet (no Always-allow on the origin, none read-only), surface a
  // single "Approve All" header card at the top of the dock instead
  // of forcing the user to approve 11 cards one at a time. This
  // matches "Review Claude's approach once, then let it run" without
  // depending on whether the model emitted a literal <PLAN>…</PLAN>
  // block in its reply text (the cloud lane emits the block; the
  // local 7B doesn't reliably). The actions are the same data either
  // way — this is render, not a workaround.
  const tabOrigin = tab ? actionOrigin(all[0] || {}, tab) : "";
  const pendingActions = all.filter((action) => {
    if (action.blocked) return false;
    const isPlanned = String(action?.status || "").toLowerCase() === "planned";
    const isPlanInert = currentMode === "plan" && isPlanned;
    if (isPlanInert) return false;
    const o = actionOrigin(action, tab);
    if (shouldAutoRunAction(action, o)) return false;
    return true;
  });
  const showApproveAll = currentMode !== "plan" && pendingActions.length >= 3;

  // Row lookup map for the Approve-All click handler — keyed by the
  // action object identity, so we don't depend on stable action.id
  // being present on every dispatcher version.
  const _actionRows = new Map();

  if (showApproveAll) {
    const planCard = document.createElement("section");
    planCard.className = "action-item plan-card";
    const heading = document.createElement("div");
    heading.className = "action-main";
    const headLabel = document.createElement("span");
    headLabel.className = "kind";
    headLabel.textContent = "PLAN";
    const headSummary = document.createElement("span");
    headSummary.className = "target";
    headSummary.textContent =
      `${pendingActions.length} actions on ${tabOrigin || "this page"} — review and approve once`;
    heading.append(headLabel, headSummary);

    const stepsList = document.createElement("ol");
    stepsList.className = "plan-steps";
    pendingActions.forEach((action) => {
      const li = document.createElement("li");
      const k = String(action.kind || "").replace(/^BROWSER_/, "").toLowerCase();
      const t = String(action.target || "").slice(0, 100);
      li.textContent = `${k}: ${t}`;
      stepsList.appendChild(li);
    });

    const buttons = document.createElement("div");
    buttons.className = "action-buttons";
    const approveAll = document.createElement("button");
    approveAll.className = "primary";
    approveAll.type = "button";
    approveAll.textContent = "Approve all";
    approveAll.addEventListener("click", async () => {
      buttons.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
      // Remember the origin once so subsequent actions on this page
      // flow through auto-run on future rounds too (Phase 4 semantics).
      const origin = tabOrigin || actionOrigin(pendingActions[0], tab);
      if (origin) {
        await allowOrigin(origin, pendingActions[0]).catch(() => null);
      }
      for (const action of pendingActions) {
        const row = _actionRows.get(action);
        if (row) await approveAction(action, row, "always_allow_site");
      }
    });
    buttons.appendChild(approveAll);

    const declineAll = document.createElement("button");
    declineAll.className = "reject";
    declineAll.type = "button";
    declineAll.textContent = "Decline all";
    declineAll.addEventListener("click", () => {
      buttons.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
      pendingActions.forEach((action) => {
        const row = _actionRows.get(action);
        if (row) rejectAction(action, row);
      });
    });
    buttons.appendChild(declineAll);

    heading.appendChild(buttons);
    planCard.append(heading, stepsList);
    list.appendChild(planCard);
  }

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
    //
    // Button-order rule: in "Act without asking" mode (auto), make
    // "Always allow site" the PRIMARY (filled-accent) button so the
    // path to the spec's auto-flow UX is obvious — observed 2026-05-14:
    // Elijah set Auto, hit Google Drive, saw 11 "Action ready for
    // review" cards in a row because drive.google.com wasn't yet on
    // approvedOrigins. The button was always there but ranked
    // secondary, easy to miss. In Review/Plan modes "Allow once" stays
    // primary — those modes EXPECT per-action gating, so promoting
    // "Always allow site" would push users out of their chosen mode.
    if (!action.blocked && !autoRun && !isPlanInert) {
      const canAlways = origin && !action.classification?.requires_confirm;
      const promoteAlways = canAlways && currentMode === "auto";

      const approve = document.createElement("button");
      approve.className = promoteAlways ? "secondary" : "primary";
      approve.type = "button";
      approve.textContent = "Allow once";
      approve.addEventListener("click", () => approveAction(action, row, "allow_once"));

      let always = null;
      if (canAlways) {
        always = document.createElement("button");
        always.className = promoteAlways ? "primary" : "secondary";
        always.type = "button";
        always.textContent = promoteAlways
          ? `Always allow ${origin.replace(/^https?:\/\//, "")}`
          : "Always allow site";
        always.addEventListener("click", async () => {
          await allowOrigin(origin, action);
          approveAction(action, row, "always_allow_site");
        });
      }

      // Order: primary button first. In Auto, that's "Always allow…";
      // in Review/Plan, "Allow once".
      if (promoteAlways) {
        buttons.appendChild(always);
        buttons.appendChild(approve);
      } else {
        buttons.appendChild(approve);
        if (always) buttons.appendChild(always);
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
    _actionRows.set(action, row);

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
    const [ctx, localFileHints] = await Promise.all([
      pageContext(prompt, timings),
      localFileHintsForPrompt(prompt),
    ]);
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
    if (localFileHints) body.local_file_hints = localFileHints;
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
    const ctx = await freshPageContextForContinuation(timings);
    const body = {
      parent_turn_id: state.loop.turn_id,
      source: "chrome_extension",
      session_id: state.config.sessionId,
      action_results: state.loop.results,
      page_context: ctx,
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
