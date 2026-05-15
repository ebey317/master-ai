(() => {
  if (globalThis.__SENSEI_CONTENT_SCRIPT_LOADED__) return;
  globalThis.__SENSEI_CONTENT_SCRIPT_LOADED__ = true;

const ACTION_TARGETS =
  "button, a, input, textarea, select, [role='button'], [aria-label], [contenteditable='true']";

const DEFAULT_VISIBLE_TEXT_LIMIT = 1800;
const READ_TEXT_LIMIT = 5000;
const FOCUSED_TEXT_LIMIT = 1200;
const INTERACTIVE_LIMIT = 80;
const CONSOLE_LIMIT = 40;
const PAGE_STABLE_DEBOUNCE_MS = 650;
const PAGE_STABLE_MAX_WAIT_MS = 3500;
const SKIP_TEXT_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS"]);

globalThis.__SENSEI_PAGE_OBSERVER_STATE__ = globalThis.__SENSEI_PAGE_OBSERVER_STATE__ || {
  version: 0,
  last_change_ts: Date.now(),
  last_reason: "init",
  url: location.href,
  ready_state: document.readyState,
};

function bumpPageObservation(reason) {
  const obs = globalThis.__SENSEI_PAGE_OBSERVER_STATE__;
  obs.version += 1;
  obs.last_change_ts = Date.now();
  obs.last_reason = safePageText ? safePageText(reason, 80) : String(reason || "").slice(0, 80);
  obs.url = location.href;
  obs.ready_state = document.readyState;
}

function installPageObservationHooks() {
  if (globalThis.__SENSEI_PAGE_OBSERVER_INSTALLED__) return;
  globalThis.__SENSEI_PAGE_OBSERVER_INSTALLED__ = true;

  const wrapHistory = (name) => {
    const original = history[name];
    if (typeof original !== "function") return;
    history[name] = function senseiHistoryWrapper(...args) {
      const out = original.apply(this, args);
      bumpPageObservation(`history.${name}`);
      return out;
    };
  };
  wrapHistory("pushState");
  wrapHistory("replaceState");
  window.addEventListener("hashchange", () => bumpPageObservation("hashchange"), true);
  window.addEventListener("popstate", () => bumpPageObservation("popstate"), true);
  document.addEventListener("readystatechange", () => {
    if (document.readyState === "complete") bumpPageObservation("readyState.complete");
  }, true);

  let mutationTimer = 0;
  const scheduleMutationBump = () => {
    clearTimeout(mutationTimer);
    mutationTimer = setTimeout(() => bumpPageObservation("mutation.debounced"), PAGE_STABLE_DEBOUNCE_MS);
  };
  const root = document.querySelector("main,[role='main'],#main,[data-testid*='main'],[aria-label*='main' i]") || document.body || document.documentElement;
  if (root && MutationObserver) {
    const observer = new MutationObserver(scheduleMutationBump);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-label", "aria-selected", "aria-expanded", "role", "hidden", "style", "class"],
    });
    globalThis.__SENSEI_PAGE_OBSERVER__ = observer;
  }
}

globalThis.__SENSEI_CONSOLE_EVENTS__ = globalThis.__SENSEI_CONSOLE_EVENTS__ || [];
if (!globalThis.__SENSEI_CONSOLE_CAPTURE_INSTALLED__) {
  globalThis.__SENSEI_CONSOLE_CAPTURE_INSTALLED__ = true;
  const pushConsoleEvent = (level, args) => {
    try {
      const message = Array.from(args || []).map((arg) => {
        if (arg instanceof Error) return `${arg.name}: ${arg.message}`;
        if (typeof arg === "object") return JSON.stringify(arg).slice(0, 800);
        return String(arg);
      }).join(" ");
      globalThis.__SENSEI_CONSOLE_EVENTS__.push({
        level,
        message: safePageText ? safePageText(message, 800) : String(message).slice(0, 800),
        ts: new Date().toISOString()
      });
      globalThis.__SENSEI_CONSOLE_EVENTS__ = globalThis.__SENSEI_CONSOLE_EVENTS__.slice(-CONSOLE_LIMIT);
    } catch (_err) {
      // Console capture must never break the page.
    }
  };
  for (const level of ["error", "warn"]) {
    const original = console[level];
    console[level] = function senseiConsoleWrapper(...args) {
      pushConsoleEvent(level, args);
      return original.apply(this, args);
    };
  }
  window.addEventListener("error", (event) => {
    pushConsoleEvent("error", [`${event.message || "Script error"} at ${event.filename || "unknown"}:${event.lineno || 0}`]);
  });
  window.addEventListener("unhandledrejection", (event) => {
    pushConsoleEvent("error", [`Unhandled promise rejection: ${event.reason?.message || event.reason || "unknown"}`]);
  });
}

// ─── RANK 1 page_context sanitizer — client defense-in-depth.
// Mirrors stt_server.py contract bit-exact (same step order, same scrub
// targets, same replacement literal). Server re-runs all of this on receipt
// and Test #8 in the server suite pins that the server alone is sufficient,
// so any client divergence is caught. Spec lives in:
// ~/.claude/plans/auto-did-not-actually-stateful-wozniak.md.
const _BIDI_ZWSP_RE = /[​‌‍‎‏‪-‮⁦-⁩﻿]/g;
const _DIRECTIVE_VERBS = [
  // Order: longest-first so RUNTERM matches before RUN.
  "RUNTERM", "REMEMBER", "CREATE", "READ", "EDIT",
  "THINK", "DONE", "RUN", "ASK",
];
const _SCRUB_REPLACEMENT = "[scrubbed directive]";

function _escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function _verbRe(verb) {
  return new RegExp(`\\b${_escapeRegex(verb)}\\s*:`, "gi");
}
function _spacedVerbRe(verb) {
  const spaced = verb.split("").map(_escapeRegex).join("[ \\t]");
  return new RegExp(`\\b${spaced}\\s*:`, "gi");
}
const _VERB_PATTERNS = _DIRECTIVE_VERBS.map(_verbRe);
const _SPACED_VERB_PATTERNS = _DIRECTIVE_VERBS
  .filter((v) => v.length >= 2)
  .map(_spacedVerbRe);
const _BROWSER_RE = /\bBROWSER_[A-Z_]+\s*:/gi;
const _BLOCK_MARKER_RE = /<<<CONTENT|>>>CONTENT|<<<FIND|>>>FIND|<<<REPLACE|>>>REPLACE/gi;
// <PLAN READY> matched first so <PLAN> doesn't shadow it.
const _PLAN_MARKER_RE = /<PLAN READY>|<\/PLAN>|<PLAN>/gi;

function sanitizePageString(text) {
  if (!text) return text || "";
  let cleaned = String(text).replace(_BIDI_ZWSP_RE, "");
  for (const pattern of _VERB_PATTERNS) cleaned = cleaned.replace(pattern, _SCRUB_REPLACEMENT);
  for (const pattern of _SPACED_VERB_PATTERNS) cleaned = cleaned.replace(pattern, _SCRUB_REPLACEMENT);
  cleaned = cleaned.replace(_BROWSER_RE, _SCRUB_REPLACEMENT);
  cleaned = cleaned.replace(_BLOCK_MARKER_RE, _SCRUB_REPLACEMENT);
  cleaned = cleaned.replace(_PLAN_MARKER_RE, _SCRUB_REPLACEMENT);
  return cleaned;
}

function clipText(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!limit || text.length <= limit) return text;
  return `${text.slice(0, limit).trim()}...`;
}

function safePageText(value, limit) {
  return sanitizePageString(clipText(value, limit));
}

function shouldSkipTextNode(node) {
  let el = node.parentElement;
  while (el && el !== document.body) {
    if (SKIP_TEXT_TAGS.has(el.tagName) || el.hidden || el.getAttribute("aria-hidden") === "true") {
      return true;
    }
    el = el.parentElement;
  }
  return false;
}

function visibleText(limit = DEFAULT_VISIBLE_TEXT_LIMIT) {
  const body = document.body;
  if (!body) return "";

  const parts = [];
  let length = 0;
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (shouldSkipTextNode(node) || !String(node.nodeValue || "").trim()) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    }
  });

  while (walker.nextNode() && length < limit) {
    const text = String(walker.currentNode.nodeValue || "").replace(/\s+/g, " ").trim();
    if (!text) continue;
    const remaining = limit - length;
    parts.push(text.length > remaining ? text.slice(0, remaining).trim() : text);
    length += text.length + 1;
  }

  const output = parts.join(" ").trim();
  return sanitizePageString(length >= limit ? `${output.trim()}...` : output);
}

function selectionText() {
  return safePageText(String(window.getSelection?.() || ""), 1200);
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value || "").replace(/["\\]/g, "\\$&").replace(/[^\w-]/g, "\\$&");
}

function elementText(el, limit = READ_TEXT_LIMIT) {
  if (!el) return "";
  if (el === document.body || el === document.documentElement) return visibleText(limit);
  return safePageText(el.value || el.innerText || el.textContent || el.getAttribute("aria-label") || "", limit);
}

function elementRole(el) {
  const explicit = el.getAttribute("role");
  if (explicit) return explicit;
  const tag = el.tagName.toLowerCase();
  if (tag === "a") return "link";
  if (tag === "button") return "button";
  if (tag === "select") return "select";
  if (tag === "textarea") return "textbox";
  if (tag === "input") {
    const type = String(el.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (type === "submit" || type === "button") return "button";
    return "textbox";
  }
  return tag;
}

function elementName(el) {
  return safePageText([
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("placeholder"),
    el.value,
    el.textContent
  ].filter(Boolean).join(" "), 120);
}

function selectorFor(el) {
  const tag = el.tagName.toLowerCase();
  const id = el.getAttribute("id");
  if (id) return `#${cssEscape(id)}`;
  const name = el.getAttribute("name");
  if (name) return `${tag}[name="${cssEscape(name)}"]`;
  const aria = el.getAttribute("aria-label");
  if (aria) return `${tag}[aria-label="${cssEscape(aria)}"]`;
  const placeholder = el.getAttribute("placeholder");
  if (placeholder) return `${tag}[placeholder="${cssEscape(placeholder)}"]`;
  return tag;
}

function structuralSelectorFor(el) {
  const parts = [];
  let current = el;
  while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.documentElement) {
    const tag = current.tagName.toLowerCase();
    const id = current.getAttribute("id");
    if (id && sanitizePageString(id) === id) {
      parts.unshift(`${tag}#${cssEscape(id)}`);
      break;
    }

    let index = 1;
    let sibling = current.previousElementSibling;
    while (sibling) {
      if (sibling.tagName === current.tagName) index += 1;
      sibling = sibling.previousElementSibling;
    }
    parts.unshift(`${tag}:nth-of-type(${index})`);
    current = current.parentElement;
  }
  return parts.length ? parts.join(" > ") : el.tagName.toLowerCase();
}

function safeSelectorFor(el) {
  const selector = selectorFor(el);
  return sanitizePageString(selector) === selector ? selector : structuralSelectorFor(el);
}

function collectDeep(selector, limit = 1500) {
  const found = [];
  const seen = new Set();

  const add = (el) => {
    if (!el || seen.has(el) || found.length >= limit) return;
    seen.add(el);
    found.push(el);
  };

  const walkRoot = (root) => {
    if (!root || found.length >= limit) return;
    try {
      root.querySelectorAll(selector).forEach(add);
    } catch (_err) {
      return;
    }
    let all = [];
    try {
      all = Array.from(root.querySelectorAll("*"));
    } catch (_err) {
      all = [];
    }
    for (const el of all) {
      if (found.length >= limit) break;
      if (el.shadowRoot) walkRoot(el.shadowRoot);
      if (el.tagName === "IFRAME" || el.tagName === "FRAME") {
        try {
          if (!el.contentDocument) continue;
          walkRoot(el.contentDocument);
        } catch (_err) {
          // Cross-origin frames are summarized separately; content is not readable here.
        }
      }
    }
  };

  walkRoot(document);
  return found;
}

function elementBounds(el) {
  try {
    const rect = el.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  } catch (_err) {
    return null;
  }
}

function interactiveElements(limit = INTERACTIVE_LIMIT) {
  const candidates = collectDeep(ACTION_TARGETS, limit * 10)
    .filter(isVisible)
    .slice(0, limit);
  return candidates.map((el, index) => {
    const role = elementRole(el);
    const name = elementName(el) || "(unnamed)";
    const selector = safeSelectorFor(el);
    return `${index + 1}. ${role} "${name}" selector=${selector}`;
  }).join("\n");
}

function semanticFallbackElements(limit = 140) {
  const selectors = [
    "main", "[role='main']", "header", "[role='banner']", "nav", "[role='navigation']",
    "section", "article", "form", "[role='form']", "dialog", "[role='dialog']",
    "h1,h2,h3,[role='heading']", ACTION_TARGETS, "table,[role='table'],[role='grid']",
    "tr,[role='row']", "li,[role='listitem']"
  ].join(",");
  return collectDeep(selectors, limit * 12)
    .filter(isVisible)
    .slice(0, limit)
    .map((el) => ({
      role: elementRole(el),
      name: elementName(el) || elementText(el, 160),
      selector: safeSelectorFor(el),
      bounds: elementBounds(el),
      value_present: Boolean(currentElementValue(el).trim()),
      expanded: el.getAttribute("aria-expanded") || "",
      selected: el.getAttribute("aria-selected") || "",
      checked: el.getAttribute("aria-checked") || "",
    }))
    .filter((item) => item.name || item.role);
}

function iframeSummaries(limit = 30) {
  return Array.from(document.querySelectorAll("iframe,frame"))
    .filter(isVisible)
    .slice(0, limit)
    .map((frame, index) => {
      const base = {
        index,
        selector: safeSelectorFor(frame),
        src: safePageText(frame.getAttribute("src") || frame.src || "", 800),
        title: safePageText(frame.getAttribute("title") || "", 200),
        name: safePageText(frame.getAttribute("name") || "", 160),
        bounds: elementBounds(frame),
      };
      try {
        const doc = frame.contentDocument;
        if (!doc) throw new Error("contentDocument unavailable");
        const text = safePageText(doc.body?.innerText || doc.body?.textContent || "", 600);
        return {
          ...base,
          same_origin: true,
          title_observed: safePageText(doc.title || "", 200),
          summary_text: text,
          interactive_count: doc.querySelectorAll(ACTION_TARGETS).length,
        };
      } catch (err) {
        return {
          ...base,
          cross_origin: true,
          unobserved_reason: "cross-origin frame; content script records metadata only",
        };
      }
    });
}

function consoleState() {
  const events = Array.isArray(globalThis.__SENSEI_CONSOLE_EVENTS__)
    ? globalThis.__SENSEI_CONSOLE_EVENTS__.slice(-CONSOLE_LIMIT)
    : [];
  return events.map((event) => ({
    level: safePageText(event.level || "", 20),
    message: safePageText(event.message || "", 800),
    ts: safePageText(event.ts || "", 40)
  }));
}

function domState() {
  const forms = collectDeep("form", 80).filter(isVisible).slice(0, 20).map((form, index) => ({
    index,
    selector: safeSelectorFor(form),
    fields: Array.from(form.querySelectorAll("input, textarea, select")).filter(isVisible).slice(0, 40).map((field) => ({
      role: elementRole(field),
      name: renderedLabelFor(field) || elementName(field) || field.getAttribute("name") || "",
      selector: safeSelectorFor(field),
      type: safePageText(field.getAttribute("type") || field.tagName.toLowerCase(), 40),
      value_present: Boolean(currentElementValue(field).trim())
    }))
  }));
  const headings = collectDeep("h1,h2,h3,[role='heading']", 120)
    .filter(isVisible)
    .slice(0, 20)
    .map((el) => elementText(el, 160))
    .filter(Boolean);
  return {
    forms,
    headings,
    counts: {
      forms: document.forms?.length || 0,
      inputs: document.querySelectorAll("input, textarea, select").length,
      buttons: document.querySelectorAll("button,[role='button']").length,
      links: document.querySelectorAll("a[href]").length,
    }
  };
}

function pageContext(options = {}) {
  const includeVisibleText = options.includeVisibleText !== false;
  const includeInteractiveElements = options.includeInteractiveElements !== false;
  const visibleTextLimit = Number(options.visibleTextLimit || DEFAULT_VISIBLE_TEXT_LIMIT);
  const includeSemanticFallback = options.includeSemanticFallback !== false;
  const active = document.activeElement;
  const focused = active && active !== document.body && active !== document.documentElement
    ? elementText(active, FOCUSED_TEXT_LIMIT)
    : "";
  const context = {
    url: safePageText(location.href, 2000),
    title: safePageText(document.title || "", 300),
    selection: selectionText(),
    focused_text: focused
  };
  if (includeInteractiveElements) context.interactive_elements = interactiveElements();
  if (includeVisibleText) context.visible_text = visibleText(visibleTextLimit);
  if (includeSemanticFallback) context.semantic_fallback = semanticFallbackElements();
  context.iframes = iframeSummaries();
  context.dom_state = domState();
  context.console_state = consoleState();
  context.observe_state = {
    version: globalThis.__SENSEI_PAGE_OBSERVER_STATE__.version,
    last_reason: globalThis.__SENSEI_PAGE_OBSERVER_STATE__.last_reason,
    last_change_ms_ago: Math.max(0, Date.now() - globalThis.__SENSEI_PAGE_OBSERVER_STATE__.last_change_ts),
    url: safePageText(globalThis.__SENSEI_PAGE_OBSERVER_STATE__.url || location.href, 2000),
    ready_state: safePageText(document.readyState, 40),
    triggers: [
      "url",
      "hashchange",
      "history.pushState",
      "history.replaceState",
      "popstate",
      "readyState.complete",
      "main-content MutationObserver debounced"
    ]
  };
  return context;
}

async function waitForPageStable(minQuietMs = PAGE_STABLE_DEBOUNCE_MS, maxWaitMs = PAGE_STABLE_MAX_WAIT_MS) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const obs = globalThis.__SENSEI_PAGE_OBSERVER_STATE__;
    if (document.readyState === "complete" && Date.now() - obs.last_change_ts >= minQuietMs) {
      return { stable: true, waited_ms: Date.now() - start };
    }
    await sleep(80);
  }
  return { stable: false, waited_ms: Date.now() - start };
}

async function pageContextAsync(options = {}) {
  if (Number(options.waitForStableMs || 0) > 0) {
    await waitForPageStable(
      Math.max(100, Math.min(Number(options.waitForStableMs), 2000)),
      Math.max(500, Math.min(Number(options.maxWaitMs || PAGE_STABLE_MAX_WAIT_MS), 8000))
    );
  }
  return pageContext(options);
}

// Phase 9 — workflow recording. Captures actionable DOM events as both a
// lightweight rrweb-style event stream and directly replayable BROWSER_* steps.
globalThis.__SENSEI_WORKFLOW_RECORDING__ = globalThis.__SENSEI_WORKFLOW_RECORDING__ || {
  active: false,
  started_at: "",
  events: [],
  rrweb_events: [],
  steps: [],
  handlers: null,
  rrweb_stop: null,
};

function recordedLabelFor(el) {
  return safePageText(renderedLabelFor(el) || elementName(el) || elementText(el, 80), 120);
}

function pushWorkflowEvent(type, el, extra = {}) {
  const rec = globalThis.__SENSEI_WORKFLOW_RECORDING__;
  if (!rec.active) return;
  const selector = el ? safeSelectorFor(el) : "";
  const label = el ? recordedLabelFor(el) : "";
  const event = {
    type,
    ts: Date.now(),
    url: safePageText(location.href, 2000),
    title: safePageText(document.title || "", 300),
    selector,
    label,
    role: el ? elementRole(el) : "",
    ...extra,
  };
  rec.events.push(event);
  if (rec.events.length > 500) rec.events.shift();
  const step = eventToWorkflowStep(event);
  if (step) {
    const prev = rec.steps[rec.steps.length - 1];
    if (prev && prev.kind === step.kind && prev.target === step.target) {
      rec.steps[rec.steps.length - 1] = step;
    } else {
      rec.steps.push(step);
      if (rec.steps.length > 120) rec.steps.shift();
    }
  }
}

function eventToWorkflowStep(event) {
  if (!event || !event.selector) return null;
  if (event.type === "click") {
    return {
      kind: "BROWSER_CLICK",
      target: event.selector,
      label: event.label || event.selector,
    };
  }
  if (event.type === "dblclick") {
    return {
      kind: "BROWSER_DOUBLE_CLICK",
      target: event.selector,
      label: event.label || event.selector,
    };
  }
  if (event.type === "input" || event.type === "change") {
    return {
      kind: "BROWSER_FILL",
      target: event.selector,
      value: safePageText(event.value || "", 1000),
      label: event.label || event.selector,
    };
  }
  return null;
}

function startWorkflowRecording() {
  const rec = globalThis.__SENSEI_WORKFLOW_RECORDING__;
  if (rec.active) return { ok: true, already_recording: true };
  rec.active = true;
  rec.started_at = new Date().toISOString();
  rec.events = [{
    type: "navigation",
    ts: Date.now(),
    url: safePageText(location.href, 2000),
    title: safePageText(document.title || "", 300),
  }];
  rec.rrweb_events = [];
  rec.steps = [{
    kind: "BROWSER_NAV",
    target: location.href,
    label: document.title || location.href,
  }];
  if (globalThis.rrweb?.record) {
    try {
      rec.rrweb_stop = globalThis.rrweb.record({
        emit(event) {
          rec.rrweb_events.push(event);
          if (rec.rrweb_events.length > 500) rec.rrweb_events.shift();
        }
      });
    } catch (_err) {
      rec.rrweb_stop = null;
    }
  }
  const onClick = (event) => pushWorkflowEvent("click", event.target);
  const onDblClick = (event) => pushWorkflowEvent("dblclick", event.target);
  const onInput = (event) => pushWorkflowEvent("input", event.target, {
    value: currentElementValue(event.target),
  });
  const onChange = (event) => pushWorkflowEvent("change", event.target, {
    value: currentElementValue(event.target),
  });
  document.addEventListener("click", onClick, true);
  document.addEventListener("dblclick", onDblClick, true);
  document.addEventListener("input", onInput, true);
  document.addEventListener("change", onChange, true);
  rec.handlers = { onClick, onDblClick, onInput, onChange };
  return { ok: true, started_at: rec.started_at, url: location.href };
}

function stopWorkflowRecording() {
  const rec = globalThis.__SENSEI_WORKFLOW_RECORDING__;
  if (!rec.active) {
    return { ok: true, active: false, events: rec.events || [], steps: rec.steps || [] };
  }
  const h = rec.handlers || {};
  document.removeEventListener("click", h.onClick, true);
  document.removeEventListener("dblclick", h.onDblClick, true);
  document.removeEventListener("input", h.onInput, true);
  document.removeEventListener("change", h.onChange, true);
  if (rec.rrweb_stop) {
    try { rec.rrweb_stop(); } catch (_err) {}
  }
  rec.active = false;
  rec.handlers = null;
  rec.rrweb_stop = null;
  return {
    ok: true,
    active: false,
    started_at: rec.started_at,
    stopped_at: new Date().toISOString(),
    events: rec.events || [],
    rrweb_events: rec.rrweb_events || [],
    steps: rec.steps || [],
    url: location.href,
    title: document.title || "",
  };
}

installPageObservationHooks();

function isVisible(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
}

// Shadow-piercing walker — used by the DOM-fallback page-read path when the
// extension cannot attach the debugger (chrome:// pages, extension popups,
// or any tab where Accessibility.getFullAXTree is unavailable). Closed shadow
// roots stay unreachable through this walker; closed-shadow regions are only
// trusted via the AX tree. See plan §2.
function walkShadowPiercing(root, callback) {
  if (!root || typeof callback !== "function") return;
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    if (!node) continue;
    if (node.nodeType === Node.ELEMENT_NODE) {
      callback(node);
      if (node.shadowRoot && node.shadowRoot.mode === "open") {
        const kids = node.shadowRoot.querySelectorAll("*");
        for (let i = kids.length - 1; i >= 0; i -= 1) stack.push(kids[i]);
      }
    }
    if (node.children && node.children.length) {
      for (let i = node.children.length - 1; i >= 0; i -= 1) stack.push(node.children[i]);
    }
  }
}

function trySelector(target) {
  try {
    return document.querySelector(target);
  } catch (_err) {
    return null;
  }
}

function normalizedText(el) {
  return [
    el.value,
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("placeholder"),
    clipText(el.textContent, 800)
  ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim().toLowerCase();
}

function findElement(target) {
  const raw = String(target || "").trim();
  if (!raw) return null;
  const bySelector = trySelector(raw);
  if (bySelector && isVisible(bySelector)) return bySelector;

  const needle = raw.toLowerCase();
  const candidates = collectDeep(ACTION_TARGETS, 2000).filter(isVisible);
  return candidates.find((el) => normalizedText(el) === needle)
    || candidates.find((el) => normalizedText(el).includes(needle))
    || null;
}

function parseFillTarget(action) {
  const raw = String(action?.target || "").trim();
  const extras = action?.extras || {};
  if (raw.startsWith("{")) {
    try {
      const parsed = JSON.parse(raw);
      return {
        selector: parsed.selector || parsed.target || "",
        value: parsed.value || parsed.text || "",
        overwrite: Boolean(parsed.overwrite || parsed.force)
      };
    } catch (_err) {
      // Fall through to delimiter parsing.
    }
  }
  const match = raw.match(/^(.*?)\s*(?:=>|:=|::)\s*([\s\S]*)$/);
  if (match) return { selector: match[1].trim(), value: match[2].trim(), overwrite: Boolean(extras.overwrite || extras.force) };
  return { selector: raw, value: extras.value || extras.text || "", overwrite: Boolean(extras.overwrite || extras.force) };
}

function currentElementValue(el) {
  if (!el) return "";
  if (String(el.getAttribute("type") || "").toLowerCase() === "file") {
    return Array.from(el.files || []).map((file) => file.name).join(", ");
  }
  if (el.isContentEditable) return String(el.textContent || "");
  if ("value" in el) return String(el.value || "");
  return "";
}

function fillValuesDiffer(current, requested) {
  return String(current || "").trim() !== String(requested || "").trim();
}

function renderedLabelFor(el) {
  if (!el) return "";
  const id = el.getAttribute("id");
  const explicitLabel = id ? document.querySelector(`label[for="${cssEscape(id)}"]`) : null;
  const wrappingLabel = el.closest?.("label");
  return safePageText([
    explicitLabel?.innerText,
    wrappingLabel?.innerText,
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("placeholder"),
    el.getAttribute("name")
  ].filter(Boolean).join(" "), 300);
}

function base64ToBytes(base64) {
  const binary = atob(String(base64 || ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function isFileUploadAction(action, parsed) {
  if (action?.extras?.fileUpload?.base64) return true;
  const value = String(parsed?.value || "").trim();
  return /^file:\/\//i.test(value) ||
    ((value.startsWith("/") || value.startsWith("~/")) &&
      /\.(pdf|docx?|odt|rtf|txt|csv|jpe?g|png|webp|gif|zip)$/i.test(value));
}

function findFillElement(parsed, allowHidden = false) {
  const bySelector = trySelector(parsed.selector);
  if (bySelector && (allowHidden || isVisible(bySelector))) return bySelector;
  return findElement(parsed.selector);
}

function setFileInputValue(el, fileUpload) {
  if (!el || String(el.getAttribute("type") || "").toLowerCase() !== "file") {
    return { ok: false, error: "target is not a file input" };
  }
  if (!fileUpload?.base64) return { ok: false, error: "missing file payload" };
  const bytes = base64ToBytes(fileUpload.base64);
  const file = new File([bytes], fileUpload.name || "upload.bin", {
    type: fileUpload.mime || "application/octet-stream",
  });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  el.files = transfer.files;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return {
    ok: true,
    file_name: file.name,
    file_size: file.size,
    mime: file.type || "",
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseJsonTarget(action) {
  const raw = String(action?.target || "").trim();
  if (!raw.startsWith("{")) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_err) {
    return {};
  }
}

function parseWaitMs(target, fallback = 1000, max = 10000) {
  const raw = String(target || "").trim();
  const match = raw.match(/\d+/);
  const parsed = match ? Number(match[0]) : fallback;
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(parsed, max));
}

function normalizeSearchText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function cleanDriveName(value) {
  return safePageText(
    String(value || "")
      .replace(/\bMore actions\b.*$/i, "")
      .replace(/\bShared folder\b/ig, "folder")
      .replace(/\s+/g, " ")
      .trim(),
    180
  );
}

function firstUsefulLine(value) {
  const lines = String(value || "")
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return lines[0] || "";
}

function driveItemKind(raw) {
  const text = normalizeSearchText(raw);
  if (/\bfolder\b/.test(text)) return "folder";
  if (/\b(pdf|document|spreadsheet|presentation|image|jpeg|jpg|png|docx|xlsx|zip)\b/.test(text)) return "file";
  return "unknown";
}

function driveItemCandidates(limit = 80) {
  const seen = new Map();
  const ariaRows = collectDeep("[role='row'][aria-label]", limit * 4).filter(isVisible);
  const fallbackSelectors = [
    "[role='gridcell'][aria-label]",
    "[role='listitem'][aria-label]",
    "[data-target='doc'][aria-label]"
  ].join(",");
  const candidates = (ariaRows.length ? ariaRows : collectDeep(fallbackSelectors, limit * 4)).filter(isVisible);

  for (const el of candidates) {
    const aria = el.getAttribute("aria-label") || "";
    const text = el.innerText || el.textContent || "";
    const raw = [aria, firstUsefulLine(text)].filter(Boolean).join(" ");
    const name = cleanDriveName(aria || firstUsefulLine(text));
    const normalized = normalizeSearchText(name || raw);
    if (!normalized || normalized.length < 2) continue;
    if (/^(new|search|settings|help|support|google apps|account|list view|grid view)$/.test(normalized)) continue;

    const selector = safeSelectorFor(el);
    const selected = el.getAttribute("aria-selected") === "true"
      || el.getAttribute("aria-current") === "true";
    const kind = driveItemKind(raw);
    const rec = {
      name: name || safePageText(firstUsefulLine(text) || aria, 180),
      kind,
      is_folder: kind === "folder",
      selected,
      role: el.getAttribute("role") || elementRole(el),
      selector,
      aria_label: safePageText(aria, 260),
      text: safePageText(text, 500),
      href: el.href || el.querySelector?.("a[href]")?.href || ""
    };
    const key = `${normalized}|${rec.kind}|${rec.selector}`;
    if (!seen.has(key)) seen.set(key, rec);
    if (seen.size >= limit) break;
  }

  return Array.from(seen.values());
}

function driveEmptyReason(text) {
  const haystack = String(text || "");
  const patterns = [
    /Drop files here/i,
    /use the ['"]?New['"]? button/i,
    /This folder is empty/i,
    /No files or folders/i,
    /No items/i,
    /No results/i
  ];
  const match = patterns.find((pattern) => pattern.test(haystack));
  return match ? match.source.replace(/\\/g, "") : "";
}

function driveState() {
  const text = visibleText(9000);
  const items = driveItemCandidates();
  const selected = items.filter((item) => item.selected);
  const emptyReason = driveEmptyReason(text);
  const isDrive = /(^|\.)drive\.google\.com$/i.test(location.hostname);
  const summary = emptyReason
    ? `Drive page appears empty: ${emptyReason}.`
    : `Drive page has ${items.length} visible item candidate${items.length === 1 ? "" : "s"}.`;
  return {
    is_drive: isDrive,
    url: safePageText(location.href, 2000),
    title: safePageText(document.title || "", 300),
    empty: Boolean(emptyReason),
    empty_reason: emptyReason,
    summary,
    items,
    selected_items: selected,
    visible_text: text
  };
}

function genericListState() {
  const selectors = [
    "li",
    "[role='row']",
    "[role='listitem']",
    "[role='gridcell']",
    "tr",
    "article"
  ].join(",");
  const items = Array.from(document.querySelectorAll(selectors))
    .filter(isVisible)
    .slice(0, 80)
    .map((el) => ({
      text: elementText(el, 500),
      selector: safeSelectorFor(el),
      role: el.getAttribute("role") || elementRole(el)
    }))
    .filter((item) => item.text);
  return {
    url: safePageText(location.href, 2000),
    title: safePageText(document.title || "", 300),
    summary: `Page has ${items.length} visible list item candidate${items.length === 1 ? "" : "s"}.`,
    items
  };
}

function findTextOnPage(target) {
  const needle = normalizeSearchText(target);
  const matches = [];
  if (!needle) return matches;
  const candidates = collectDeep("*", 1800)
    .filter(isVisible)
    .slice(0, 1200);
  for (const el of candidates) {
    const text = elementText(el, 500);
    if (!text || !normalizeSearchText(text).includes(needle)) continue;
    matches.push({
      text,
      selector: safeSelectorFor(el),
      role: el.getAttribute("role") || elementRole(el)
    });
    if (matches.length >= 30) break;
  }
  return matches;
}

function parseScrollTarget(target) {
  const raw = String(target || "down").trim().toLowerCase();
  const amountMatch = raw.match(/-?\d+/);
  const amount = amountMatch ? Number(amountMatch[0]) : Math.round(window.innerHeight * 0.85);
  if (raw.includes("top")) return { top: 0, left: window.scrollX, behavior: "smooth" };
  if (raw.includes("bottom")) return { top: document.documentElement.scrollHeight, left: window.scrollX, behavior: "smooth" };
  if (raw.includes("up")) return { top: window.scrollY - Math.abs(amount), left: window.scrollX, behavior: "smooth" };
  if (raw.includes("left")) return { top: window.scrollY, left: window.scrollX - Math.abs(amount), behavior: "smooth" };
  if (raw.includes("right")) return { top: window.scrollY, left: window.scrollX + Math.abs(amount), behavior: "smooth" };
  return { top: window.scrollY + Math.abs(amount), left: window.scrollX, behavior: "smooth" };
}

function nativeValueSetterFor(el) {
  const prototypes = [];
  if (el instanceof HTMLInputElement) prototypes.push(HTMLInputElement.prototype);
  if (el instanceof HTMLTextAreaElement) prototypes.push(HTMLTextAreaElement.prototype);
  if (el instanceof HTMLSelectElement) prototypes.push(HTMLSelectElement.prototype);
  prototypes.push(Object.getPrototypeOf(el));
  for (const proto of prototypes) {
    const descriptor = proto && Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor?.set) return descriptor.set;
  }
  return null;
}

function dispatchFormEvents(el, value) {
  try {
    el.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      inputType: "insertReplacementText",
      data: String(value || "")
    }));
  } catch (_err) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function setElementValue(el, value) {
  if (!el) return;
  el.focus();
  if (el.isContentEditable) {
    el.textContent = value;
    dispatchFormEvents(el, value);
    return;
  }
  if (el instanceof HTMLSelectElement) {
    const requested = String(value || "");
    const option = Array.from(el.options || []).find((opt) =>
      opt.value === requested || normalizeSearchText(opt.textContent) === normalizeSearchText(requested)
    );
    if (option) el.value = option.value;
    else el.value = requested;
    dispatchFormEvents(el, value);
    return;
  }
  if ("value" in el) {
    const setter = nativeValueSetterFor(el);
    if (setter) setter.call(el, value);
    else el.value = value;
  } else {
    el.textContent = value;
  }
  dispatchFormEvents(el, value);
}

async function executeBrowserAction(action) {
  const kind = String(action?.kind || "").toUpperCase();
  if (kind === "BROWSER_WAIT") {
    const ms = parseWaitMs(action?.target, 1000, 15000);
    await sleep(ms);
    return {
      ok: true,
      waited_ms: ms,
      page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: true, waitForStableMs: 150 })
    };
  }

  if (kind === "BROWSER_SCROLL") {
    const target = parseScrollTarget(action?.target);
    window.scrollTo(target);
    await sleep(250);
    await waitForPageStable(250, 1200);
    return {
      ok: true,
      scroll: { x: window.scrollX, y: window.scrollY },
      page_context: await pageContextAsync({ includeVisibleText: true, visibleTextLimit: 2200, waitForStableMs: 150 })
    };
  }

  if (kind === "BROWSER_READ_PAGE" || kind === "BROWSER_OBSERVE") {
    const ctx = await pageContextAsync({
      includeVisibleText: true,
      includeInteractiveElements: true,
      visibleTextLimit: READ_TEXT_LIMIT,
      waitForStableMs: PAGE_STABLE_DEBOUNCE_MS,
    });
    return {
      ok: true,
      page_context: ctx,
      text: ctx.visible_text || ctx.title || "page observed"
    };
  }

  if (kind === "BROWSER_READ") {
    const target = String(action?.target || "").trim();
    const el = target ? findElement(target) : null;
    return {
      ok: true,
      text: el ? elementText(el, READ_TEXT_LIMIT) : visibleText(READ_TEXT_LIMIT),
      page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 })
    };
  }

  if (kind === "BROWSER_CLICK") {
    const el = findElement(action.target);
    if (!el) return { ok: false, error: "target not found" };
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    el.click();
    await waitForPageStable(350, 1400);
    return { ok: true, clicked: action.target, page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 }) };
  }

  if (kind === "BROWSER_DOUBLE_CLICK") {
    const el = findElement(action.target);
    if (!el) return { ok: false, error: "target not found" };
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, view: window }));
    await waitForPageStable(350, 1400);
    return { ok: true, double_clicked: action.target, page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 }) };
  }

  if (kind === "BROWSER_FILL") {
    const parsed = parseFillTarget(action);
    const fileUpload = action?.extras?.fileUpload || null;
    const wantsFileUpload = isFileUploadAction(action, parsed);
    const el = findFillElement(parsed, wantsFileUpload);
    if (!el) return { ok: false, error: "target not found" };
    if (wantsFileUpload || fileUpload) {
      const upload = setFileInputValue(el, fileUpload);
      if (!upload.ok) return upload;
      return {
        ok: true,
        filled: parsed.selector,
        file_upload: upload,
        page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 })
      };
    }
    const current = currentElementValue(el);
    const requested = String(parsed.value || "");
    const overwrite = Boolean(parsed.overwrite || action?.overwrite || action?.extras?.overwrite || action?.extras?.force);
    if (current.trim() && fillValuesDiffer(current, requested) && !overwrite) {
      return {
        ok: false,
        conflict: true,
        error: "field already has a different value",
        target: parsed.selector,
        rendered_label: renderedLabelFor(el),
        existing_value: safePageText(current, 500),
        requested_value: safePageText(requested, 500),
        page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 })
      };
    }
    if (current.trim() && !fillValuesDiffer(current, requested)) {
      return {
        ok: true,
        filled: parsed.selector,
        preserved_existing_value: true,
        page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 })
      };
    }
    setElementValue(el, parsed.value);
    await waitForPageStable(250, 1000);
    return { ok: true, filled: parsed.selector, page_context: await pageContextAsync({ includeVisibleText: false, includeInteractiveElements: false, waitForStableMs: 150 }) };
  }

  if (kind === "BROWSER_NAV") {
    const url = String(action?.target || "").trim();
    if (!url) return { ok: false, error: "missing url" };
    location.assign(url);
    return { ok: true, navigated: url };
  }

  if (kind === "BROWSER_FIND") {
    const matches = findTextOnPage(action?.target);
    return {
      ok: true,
      query: safePageText(action?.target || "", 200),
      count: matches.length,
      matches,
      text: matches.length ? matches.map((m) => m.text).join("\n").slice(0, READ_TEXT_LIMIT) : ""
    };
  }

  if (kind === "BROWSER_EXTRACT_LIST") {
    const opts = parseJsonTarget(action);
    const mode = normalizeSearchText(opts.mode || action?.target || "");
    const state = mode.includes("drive") || /(^|\.)drive\.google\.com$/i.test(location.hostname)
      ? driveState()
      : genericListState();
    return { ok: true, list_state: state, text: state.summary };
  }

  if (kind === "BROWSER_DRIVE_INSPECT_FOLDER") {
    const state = driveState();
    return { ok: true, drive_state: state, text: state.summary };
  }

  return { ok: false, error: `unsupported browser action: ${kind}` };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SENSEI_PING") {
    sendResponse({ ok: true });
    return false;
  }

  if (message?.type === "SENSEI_PAGE_CONTEXT") {
    pageContextAsync(message.options || {})
      .then((ctx) => sendResponse({ ok: true, page_context: ctx }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err), page_context: pageContext({ includeVisibleText: false }) }));
    return true;
  }

  if (message?.type === "SENSEI_EXECUTE_ACTION") {
    executeBrowserAction(message.action)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }

  // Phase 5.2 — return the console-event ring buffer the page has been
  // accumulating since load. The buffer caps itself at CONSOLE_LIMIT so the
  // response stays bounded.
  if (message?.type === "SENSEI_READ_CONSOLE_EVENTS") {
    const filter = String(message.filter || "all").toLowerCase();
    const all = Array.isArray(globalThis.__SENSEI_CONSOLE_EVENTS__)
      ? globalThis.__SENSEI_CONSOLE_EVENTS__.slice(-CONSOLE_LIMIT)
      : [];
    const filtered = (filter === "all" || !filter)
      ? all
      : all.filter((e) => String(e?.level || "").toLowerCase() === filter);
    sendResponse(filtered);
    return false;
  }

  if (message?.type === "SENSEI_RECORD_START") {
    sendResponse(startWorkflowRecording());
    return false;
  }

  if (message?.type === "SENSEI_RECORD_STOP") {
    sendResponse(stopWorkflowRecording());
    return false;
  }

  return false;
});
})();
