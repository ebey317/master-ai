const ACTION_TARGETS =
  "button, a, input, textarea, select, [role='button'], [aria-label], [contenteditable='true']";

const DEFAULT_VISIBLE_TEXT_LIMIT = 1800;
const READ_TEXT_LIMIT = 5000;
const FOCUSED_TEXT_LIMIT = 1200;
const INTERACTIVE_LIMIT = 80;
const SKIP_TEXT_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS"]);

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
  return length >= limit ? `${output.trim()}...` : output;
}

function selectionText() {
  return clipText(String(window.getSelection?.() || ""), 1200);
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value || "").replace(/["\\]/g, "\\$&").replace(/[^\w-]/g, "\\$&");
}

function elementText(el, limit = READ_TEXT_LIMIT) {
  if (!el) return "";
  if (el === document.body || el === document.documentElement) return visibleText(limit);
  return clipText(el.value || el.innerText || el.textContent || el.getAttribute("aria-label") || "", limit);
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
  const raw = clipText([
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("placeholder"),
    el.value,
    el.textContent
  ].filter(Boolean).join(" "), 120);
  // Defense-in-depth: scrub directive-shaped tokens before the value leaves
  // the page. Server re-runs the same sanitizer on receipt.
  return sanitizePageString(raw);
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

function interactiveElements(limit = INTERACTIVE_LIMIT) {
  const candidates = Array.from(document.querySelectorAll(ACTION_TARGETS))
    .filter(isVisible)
    .slice(0, limit);
  return candidates.map((el, index) => {
    const role = elementRole(el);
    const name = elementName(el) || "(unnamed)";
    const selector = selectorFor(el);
    return `${index + 1}. ${role} "${name}" selector=${selector}`;
  }).join("\n");
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
    url: location.href,
    title: document.title || "",
    selection: selectionText(),
    focused_text: focused
  };
  if (includeInteractiveElements) context.interactive_elements = interactiveElements();
  if (includeVisibleText) context.visible_text = visibleText(visibleTextLimit);
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
        value: parsed.value || parsed.text || ""
      };
    } catch (_err) {
      // Fall through to delimiter parsing.
    }
  }
  const match = raw.match(/^(.*?)\s*(?:=>|:=|::)\s*([\s\S]*)$/);
  if (match) return { selector: match[1].trim(), value: match[2].trim() };
  return { selector: raw, value: extras.value || extras.text || "" };
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

  if (kind === "BROWSER_FILL") {
    const parsed = parseFillTarget(action);
    const el = findElement(parsed.selector);
    if (!el) return { ok: false, error: "target not found" };
    setElementValue(el, parsed.value);
    return { ok: true, filled: parsed.selector, page_context: pageContext({ includeVisibleText: false, includeInteractiveElements: false }) };
  }

  if (kind === "BROWSER_NAV") {
    const url = String(action?.target || "").trim();
    if (!url) return { ok: false, error: "missing url" };
    location.assign(url);
    return { ok: true, navigated: url };
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
