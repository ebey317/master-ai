const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8080",
  mode: "review",
  token: "",
  sessionId: ""
};

// ─── AX-tree snapshot (Claude-Chrome-style page read).
// Plan: ~/.claude/plans/https-www-claudechrome-com-blog-how-clau-hidden-bentley.md
// Primary source is the Chrome accessibility tree via CDP, which pierces both
// open and closed Shadow DOM. content_script's DOM-fallback walker covers the
// chrome:// / extension-popup case where the debugger cannot attach.

const PAGE_TREE_BYTE_CAP = 24576;
const AX_DEBUGGER_VERSION = "1.3";
const CROSS_ORIGIN_IFRAME_STRATEGY = "src_title_only";  // future: "debugger_attach_per_frame"

const _attachedTabs = new Set();
const _snapshotRefMaps = new Map();  // tabId → { ref: {backendNodeId, selector} }

async function _ensureDebuggerAttached(tabId) {
  if (_attachedTabs.has(tabId)) return;
  await new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, AX_DEBUGGER_VERSION, () => {
      const err = chrome.runtime.lastError;
      if (err) {
        // "Another debugger is already attached" is fine if it's us; surface otherwise.
        if (String(err.message || "").includes("already attached")) {
          _attachedTabs.add(tabId);
          resolve();
          return;
        }
        reject(new Error(err.message || String(err)));
        return;
      }
      _attachedTabs.add(tabId);
      resolve();
    });
  });
}

function _cdpSend(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params || {}, (result) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(`${method}: ${err.message || String(err)}`));
        return;
      }
      resolve(result || {});
    });
  });
}

chrome.debugger.onDetach.addListener((source, reason) => {
  if (source?.tabId !== undefined) {
    _attachedTabs.delete(source.tabId);
    _snapshotRefMaps.delete(source.tabId);
    _networkBuffers.delete(source.tabId);
    _networkEnabledTabs.delete(source.tabId);
  }
  // reason is "target_closed" / "canceled_by_user" — both fine, nothing to do.
});

// Phase 5.3 — Network ring buffer per tab. Filled by chrome.debugger.onEvent
// when Network.* events fire. Bounded at NETWORK_BUFFER_LIMIT so a noisy page
// can't blow extension memory. Authorization / Cookie / Set-Cookie / Proxy-
// Authorization headers are redacted before storage.
const NETWORK_BUFFER_LIMIT = 50;
const _networkBuffers = new Map();          // tabId -> Array<event>
const _networkEnabledTabs = new Set();      // tabId set
const _NETWORK_REDACT_HEADERS = new Set([
  "authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key",
]);

function _redactHeaders(headers) {
  if (!headers || typeof headers !== "object") return {};
  const out = {};
  for (const [name, value] of Object.entries(headers)) {
    const lower = String(name || "").toLowerCase();
    out[name] = _NETWORK_REDACT_HEADERS.has(lower) ? "[REDACTED]" : String(value || "").slice(0, 600);
  }
  return out;
}

function _appendNetworkEvent(tabId, event) {
  if (!Number.isFinite(tabId)) return;
  let buf = _networkBuffers.get(tabId);
  if (!buf) { buf = []; _networkBuffers.set(tabId, buf); }
  buf.push(event);
  if (buf.length > NETWORK_BUFFER_LIMIT) buf.splice(0, buf.length - NETWORK_BUFFER_LIMIT);
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source?.tabId;
  if (!Number.isFinite(tabId)) return;
  if (method === "Network.requestWillBeSent") {
    const req = params?.request || {};
    _appendNetworkEvent(tabId, {
      phase: "request",
      request_id: params.requestId,
      method: req.method || "",
      url: String(req.url || "").slice(0, 800),
      ts: Date.now(),
      headers: _redactHeaders(req.headers || {}),
      resource_type: params.type || "",
    });
  } else if (method === "Network.responseReceived") {
    const resp = params?.response || {};
    _appendNetworkEvent(tabId, {
      phase: "response",
      request_id: params.requestId,
      url: String(resp.url || "").slice(0, 800),
      ts: Date.now(),
      status: resp.status,
      status_text: resp.statusText,
      mime_type: resp.mimeType,
      headers: _redactHeaders(resp.headers || {}),
    });
  }
});

async function _ensureNetworkEnabled(tabId) {
  if (_networkEnabledTabs.has(tabId)) return true;
  try {
    await _ensureDebuggerAttached(tabId);
    await _cdpSend(tabId, "Network.enable", {});
    _networkEnabledTabs.add(tabId);
    return true;
  } catch (_err) {
    return false;
  }
}

chrome.tabs.onRemoved.addListener((tabId) => {
  _attachedTabs.delete(tabId);
  _networkBuffers.delete(tabId);
  _networkEnabledTabs.delete(tabId);
  _snapshotRefMaps.delete(tabId);
});

function _truncateNodeName(name, limit = 120) {
  if (!name) return "";
  const collapsed = String(name).replace(/\s+/g, " ").trim();
  return collapsed.length > limit ? `${collapsed.slice(0, limit - 1)}…` : collapsed;
}

function _axNodeRole(node) {
  return node?.role?.value || "";
}

function _axNodeName(node) {
  return _truncateNodeName(node?.name?.value || "");
}

function _axNodeValue(node) {
  const v = node?.value?.value;
  return v === undefined || v === null ? "" : _truncateNodeName(String(v), 240);
}

function _axNodeState(node) {
  const state = {};
  const props = Array.isArray(node?.properties) ? node.properties : [];
  for (const p of props) {
    if (!p || !p.name) continue;
    const v = p.value?.value;
    switch (p.name) {
      case "disabled":
      case "checked":
      case "expanded":
      case "selected":
      case "focused":
      case "invalid":
      case "required":
        if (v === true || v === "true" || v === "mixed") state[p.name] = v === "mixed" ? "mixed" : true;
        break;
      case "current":
        if (v && v !== "false") state.current = String(v);
        break;
      default:
        break;
    }
  }
  return state;
}

async function _resolveBackendToSelector(tabId, backendNodeId) {
  if (!backendNodeId) return "";
  try {
    const res = await _cdpSend(tabId, "DOM.describeNode", { backendNodeId, depth: 0 });
    const n = res?.node || {};
    const attrs = {};
    const list = Array.isArray(n.attributes) ? n.attributes : [];
    for (let i = 0; i + 1 < list.length; i += 2) attrs[list[i]] = list[i + 1];
    const tag = String(n.localName || n.nodeName || "").toLowerCase();
    if (!tag) return "";
    if (attrs["data-testid"]) return `${tag}[data-testid="${_cssEscape(attrs["data-testid"])}"]`;
    if (attrs["data-test"]) return `${tag}[data-test="${_cssEscape(attrs["data-test"])}"]`;
    if (attrs.id) return `#${_cssEscape(attrs.id)}`;
    if (attrs.name) return `${tag}[name="${_cssEscape(attrs.name)}"]`;
    if (attrs["aria-label"]) return `${tag}[aria-label="${_cssEscape(attrs["aria-label"])}"]`;
    return tag;
  } catch (_err) {
    return "";
  }
}

function _cssEscape(value) {
  return String(value || "").replace(/["\\]/g, "\\$&");
}

function _bucketForRole(role) {
  if (role === "heading") return "headings";
  if (role === "link") return "links";
  if (role === "button") return "buttons";
  if (["textbox", "combobox", "checkbox", "radio", "searchbox", "spinbutton", "slider", "switch"].includes(role)) return "inputs";
  if (["navigation", "main", "complementary", "banner", "contentinfo", "search", "region", "form"].includes(role)) return "landmarks";
  if (role === "dialog" || role === "alertdialog") return "dialogs";
  if (role === "list" || role === "grid" || role === "tree" || role === "table") return "lists";
  if (role === "row" || role === "gridcell" || role === "treeitem" || role === "listitem") return "rows";
  return "other";
}

async function _walkAxNodes(tabId, nodes, refMap, refSeq, page, byteBudget) {
  const byId = new Map();
  for (const n of nodes) byId.set(n.nodeId, n);

  const result = {
    headings: [],
    landmarks: [],
    buttons: [],
    links: [],
    inputs: [],
    dialogs: [],
    lists: [],
    file_folder_rows: [],
    iframes: [],
    truncation: { dropped_nodes: 0, reason: null }
  };

  // Iframes — record only metadata (cross-origin default per CROSS_ORIGIN_IFRAME_STRATEGY).
  // Same-origin walk is Phase 1.5; we still record the node so the model knows the frame exists.
  const ROLES_OF_INTEREST = new Set([
    "heading", "link", "button", "textbox", "combobox", "checkbox", "radio",
    "searchbox", "spinbutton", "slider", "switch",
    "navigation", "main", "complementary", "banner", "contentinfo", "search", "region", "form",
    "dialog", "alertdialog", "list", "grid", "tree", "table",
    "row", "gridcell", "treeitem", "listitem"
  ]);

  for (const n of nodes) {
    const role = _axNodeRole(n);
    if (!ROLES_OF_INTEREST.has(role)) continue;
    if (n.ignored) continue;
    const name = _axNodeName(n);
    if (!name && !["textbox", "combobox", "checkbox", "radio", "searchbox"].includes(role)) continue;

    refSeq.value += 1;
    const ref = `r-${refSeq.value}`;
    const backendNodeId = n.backendDOMNodeId || 0;
    const selector = await _resolveBackendToSelector(tabId, backendNodeId);
    refMap[ref] = { backendNodeId, selector };

    const node = { role, name, ref };
    const state = _axNodeState(n);
    if (Object.keys(state).length) node.state = state;
    const value = _axNodeValue(n);
    if (value) node.value = value;
    if (selector) node.selector = selector;
    if (role === "heading") {
      const levelProp = (n.properties || []).find((p) => p?.name === "level");
      const lvl = levelProp?.value?.value;
      if (lvl) node.level = Number(lvl);
    }

    const bucket = _bucketForRole(role);
    if (bucket === "headings") result.headings.push(node);
    else if (bucket === "landmarks") result.landmarks.push(node);
    else if (bucket === "buttons") result.buttons.push(node);
    else if (bucket === "links") result.links.push(node);
    else if (bucket === "inputs") result.inputs.push(node);
    else if (bucket === "dialogs") result.dialogs.push(node);
    else if (bucket === "lists") result.lists.push(node);
    else if (bucket === "rows") {
      // Drive-style file/folder rows surface here when they carry role=row + aria-label.
      const kind = /folder/i.test(name) ? "folder" : "file";
      result.file_folder_rows.push({ ref, kind, name, selector, role, state });
    }
  }

  return result;
}

function _serializedBytes(obj) {
  try {
    return new TextEncoder().encode(JSON.stringify(obj)).byteLength;
  } catch (_err) {
    return 0;
  }
}

function _enforceByteCap(snapshot) {
  // Truncation order: drop list rows past 50 → buttons/links past 60 each →
  // landmarks past 12 → headings past 30. Tree-shape preservation is more
  // important than completeness; the model can BROWSER_OBSERVE again with
  // narrower scope if it needs more.
  const before = _serializedBytes(snapshot);
  if (before <= PAGE_TREE_BYTE_CAP) {
    snapshot.truncation = { ...(snapshot.truncation || {}), bytes_before: before, bytes_after: before };
    return snapshot;
  }
  let dropped = 0;
  const trim = (arr, max) => {
    if (Array.isArray(arr) && arr.length > max) {
      dropped += arr.length - max;
      arr.length = max;
    }
  };
  trim(snapshot.file_folder_rows, 50);
  trim(snapshot.lists, 20);
  trim(snapshot.buttons, 60);
  trim(snapshot.links, 60);
  trim(snapshot.inputs, 60);
  trim(snapshot.landmarks, 12);
  trim(snapshot.headings, 30);
  const after = _serializedBytes(snapshot);
  snapshot.truncation = {
    ...(snapshot.truncation || {}),
    reason: "byte_cap",
    dropped_nodes: dropped,
    bytes_before: before,
    bytes_after: after
  };
  return snapshot;
}

async function buildAxSnapshot(tabId) {
  await _ensureDebuggerAttached(tabId);
  await _cdpSend(tabId, "DOM.enable", {});
  await _cdpSend(tabId, "Accessibility.enable", {});
  const axResult = await _cdpSend(tabId, "Accessibility.getFullAXTree", {});
  const nodes = Array.isArray(axResult?.nodes) ? axResult.nodes : [];

  const refMap = {};
  const refSeq = { value: 0 };
  const buckets = await _walkAxNodes(tabId, nodes, refMap, refSeq, null, PAGE_TREE_BYTE_CAP);

  let url = "";
  let title = "";
  try {
    const tab = await new Promise((resolve) => chrome.tabs.get(tabId, (t) => resolve(t || null)));
    url = tab?.url || "";
    title = tab?.title || "";
  } catch (_err) { /* tabId may have closed */ }

  const snapshot = {
    url,
    title,
    source: "ax_tree",
    headings: buckets.headings,
    landmarks: buckets.landmarks,
    buttons: buckets.buttons,
    links: buckets.links,
    inputs: buckets.inputs,
    dialogs: buckets.dialogs,
    lists: buckets.lists,
    file_folder_rows: buckets.file_folder_rows,
    iframes: buckets.iframes,
    truncation: buckets.truncation
  };

  _enforceByteCap(snapshot);
  _snapshotRefMaps.set(tabId, refMap);
  return { snapshot, refMap };
}

chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const next = {};
  for (const [key, value] of Object.entries(DEFAULTS)) {
    if (stored[key] === undefined) next[key] = value;
  }
  if (!stored.sessionId) next.sessionId = `sensei-${crypto.randomUUID()}`;
  if (Object.keys(next).length) await chrome.storage.local.set(next);

  if (chrome.sidePanel?.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!chrome.sidePanel?.open || !tab?.id) return;
  try {
    await chrome.sidePanel.open({ tabId: tab.id });
  } catch (_err) {
    await chrome.sidePanel.open({ windowId: tab.windowId });
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SENSEI_ACTIVE_TAB") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      sendResponse({ tab: tabs?.[0] || null });
    });
    return true;
  }

  if (message?.type === "SENSEI_BUILD_AX_SNAPSHOT") {
    const requestedTabId = Number.isInteger(message.tabId) ? message.tabId : null;
    const resolveTab = requestedTabId !== null
      ? Promise.resolve(requestedTabId)
      : new Promise((resolve) => chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs?.[0]?.id ?? null)));
    resolveTab
      .then((tabId) => {
        if (!Number.isInteger(tabId)) {
          sendResponse({ ok: false, error: "no active tab to snapshot" });
          return;
        }
        return buildAxSnapshot(tabId).then((result) => {
          sendResponse({ ok: true, ...result });
        });
      })
      .catch((err) => {
        sendResponse({ ok: false, error: String(err?.message || err) });
      });
    return true;
  }

  if (message?.type === "SENSEI_RESOLVE_REF") {
    const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
    const ref = String(message.ref || "");
    if (tabId === null || !ref) {
      sendResponse({ ok: false, error: "tabId and ref required" });
      return false;
    }
    const map = _snapshotRefMaps.get(tabId) || {};
    const hit = map[ref];
    sendResponse(hit ? { ok: true, ...hit } : { ok: false, error: `unknown ref ${ref}` });
    return false;
  }

  // Phase 5.3 — return the captured Network ring buffer for a tab. Filter is
  // "all" (default), "xhr" / "fetch", or "subresource" (everything else).
  if (message?.type === "SENSEI_READ_NETWORK_EVENTS") {
    const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
    if (tabId === null) {
      sendResponse({ ok: false, error: "tabId required" });
      return false;
    }
    _ensureNetworkEnabled(tabId)
      .then((enabled) => {
        if (!enabled) {
          sendResponse({ ok: false, error: "Network domain could not be enabled (debugger may be in use)" });
          return;
        }
        const filter = String(message.filter || "all").toLowerCase();
        const all = _networkBuffers.get(tabId) || [];
        let events = all;
        if (filter && filter !== "all") {
          events = all.filter((e) => {
            const rt = String(e?.resource_type || "").toLowerCase();
            if (filter === "xhr") return rt === "xhr";
            if (filter === "fetch") return rt === "fetch";
            if (filter === "subresource") return !["xhr", "fetch", "document"].includes(rt);
            return true;
          });
        }
        sendResponse({ ok: true, count: events.length, events });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }

  if (message?.type === "SENSEI_CAPTURE_VISIBLE_TAB") {
    const capture = (windowId) => chrome.tabs.captureVisibleTab(windowId, { format: "png" }, (dataUrl) => {
      const err = chrome.runtime.lastError;
      if (err) {
        sendResponse({ ok: false, error: err.message || String(err) });
        return;
      }
      sendResponse({ ok: true, dataUrl });
    });

    if (Number.isInteger(message.windowId)) {
      capture(message.windowId);
      return true;
    }

    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs?.[0] || null;
      if (!Number.isInteger(tab?.windowId)) {
        sendResponse({ ok: false, error: "no active browser window available for screenshot" });
        return;
      }
      capture(tab.windowId);
    });
    return true;
  }

  return false;
});
