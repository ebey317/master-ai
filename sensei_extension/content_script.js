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
const SKIP_TEXT_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS"]);

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

function interactiveElements(limit = INTERACTIVE_LIMIT) {
  const candidates = Array.from(document.querySelectorAll(ACTION_TARGETS))
    .filter(isVisible)
    .slice(0, limit);
  return candidates.map((el, index) => {
    const role = elementRole(el);
    const name = elementName(el) || "(unnamed)";
    const selector = safeSelectorFor(el);
    return `${index + 1}. ${role} "${name}" selector=${selector}`;
  }).join("\n");
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
  const forms = Array.from(document.forms || []).filter(isVisible).slice(0, 20).map((form, index) => ({
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
  const headings = Array.from(document.querySelectorAll("h1,h2,h3,[role='heading']"))
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
  context.dom_state = domState();
  context.console_state = consoleState();
  return context;
}

function isVisible(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
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
  const candidates = Array.from(document.querySelectorAll(ACTION_TARGETS)).filter(isVisible);
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
  const selectors = [
    "[role='row']",
    "[role='gridcell']",
    "[role='listitem']",
    "[data-target='doc']",
    "[aria-label]"
  ].join(",");
  const seen = new Map();
  const candidates = Array.from(document.querySelectorAll(selectors)).filter(isVisible);

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
      || el.getAttribute("aria-current") === "true"
      || /\bselected\b/i.test(el.className || "");
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
  const candidates = Array.from(document.querySelectorAll("body *"))
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

function setElementValue(el, value) {
  if (!el) return;
  el.focus();
  if (el.isContentEditable) {
    el.textContent = value;
  } else {
    const proto = Object.getPrototypeOf(el);
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor?.set) descriptor.set.call(el, value);
    else el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

async function executeBrowserAction(action) {
  const kind = String(action?.kind || "").toUpperCase();
  if (kind === "BROWSER_WAIT") {
    const ms = parseWaitMs(action?.target, 1000, 15000);
    await sleep(ms);
    return {
      ok: true,
      waited_ms: ms,
      page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: true })
    };
  }

  if (kind === "BROWSER_SCROLL") {
    const target = parseScrollTarget(action?.target);
    window.scrollTo(target);
    await sleep(250);
    return {
      ok: true,
      scroll: { x: window.scrollX, y: window.scrollY },
      page_context: pageContext({ includeVisibleText: true, visibleTextLimit: 2200 })
    };
  }

  if (kind === "BROWSER_READ") {
    const target = String(action?.target || "").trim();
    const el = target ? findElement(target) : null;
    return {
      ok: true,
      text: el ? elementText(el, READ_TEXT_LIMIT) : visibleText(READ_TEXT_LIMIT),
      page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false })
    };
  }

  if (kind === "BROWSER_CLICK") {
    const el = findElement(action.target);
    if (!el) return { ok: false, error: "target not found" };
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    el.click();
    return { ok: true, clicked: action.target, page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false }) };
  }

  if (kind === "BROWSER_DOUBLE_CLICK") {
    const el = findElement(action.target);
    if (!el) return { ok: false, error: "target not found" };
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, view: window }));
    return { ok: true, double_clicked: action.target, page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false }) };
  }

  if (kind === "BROWSER_FILL") {
    const parsed = parseFillTarget(action);
    const el = findElement(parsed.selector);
    if (!el) return { ok: false, error: "target not found" };
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
        page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false })
      };
    }
    if (current.trim() && !fillValuesDiffer(current, requested)) {
      return {
        ok: true,
        filled: parsed.selector,
        preserved_existing_value: true,
        page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false })
      };
    }
    setElementValue(el, parsed.value);
    return { ok: true, filled: parsed.selector, page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false }) };
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
    sendResponse({ ok: true, page_context: pageContext(message.options || {}) });
    return false;
  }

  if (message?.type === "SENSEI_EXECUTE_ACTION") {
    executeBrowserAction(message.action)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }

  return false;
});
})();
