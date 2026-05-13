const ACTION_TARGETS =
  "button, a, input, textarea, select, [role='button'], [aria-label], [contenteditable='true']";

function visibleText(limit = 5000) {
  const text = (document.body?.innerText || "").replace(/\s+\n/g, "\n").trim();
  return text.length > limit ? `${text.slice(0, limit).trim()}...` : text;
}

function selectionText() {
  return String(window.getSelection?.() || "").trim();
}

function pageContext() {
  const active = document.activeElement;
  return {
    url: location.href,
    title: document.title || "",
    selection: selectionText(),
    focused_text: active ? (active.value || active.innerText || active.getAttribute("aria-label") || "") : "",
    visible_text: visibleText()
  };
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
    el.innerText,
    el.textContent,
    el.value,
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("placeholder")
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
      text: el ? (el.innerText || el.value || el.textContent || "") : visibleText(),
      page_context: pageContext()
    };
  }

  if (kind === "BROWSER_CLICK") {
    const el = findElement(action.target);
    if (!el) return { ok: false, error: "target not found" };
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    el.click();
    return { ok: true, clicked: action.target, page_context: pageContext() };
  }

  if (kind === "BROWSER_FILL") {
    const parsed = parseFillTarget(action);
    const el = findElement(parsed.selector);
    if (!el) return { ok: false, error: "target not found" };
    setElementValue(el, parsed.value);
    return { ok: true, filled: parsed.selector, page_context: pageContext() };
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
  if (message?.type === "SENSEI_PAGE_CONTEXT") {
    sendResponse({ ok: true, page_context: pageContext() });
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
