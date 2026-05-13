const DEFAULT_CONFIG = {
  backendUrl: "http://127.0.0.1:8080",
  token: "",
  mode: "review",
  sessionId: ""
};

const state = {
  config: { ...DEFAULT_CONFIG },
  mediaRecorder: null,
  mediaStream: null,
  chunks: []
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

async function backendFetch(path, options = {}) {
  let body = options.body;
  const headers = backendHeaders(options.headers || {});

  if (body !== undefined && !(body instanceof Blob) && typeof body !== "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  } else if (body instanceof Blob) {
    headers["Content-Type"] = body.type || "application/octet-stream";
  }

  const res = await fetch(`${state.config.backendUrl}${path}`, {
    method: options.method || (body === undefined ? "GET" : "POST"),
    headers,
    body
  });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_err) {
    data = { raw: text };
  }
  if (!res.ok) {
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
    return !/^\s*(RUNTERM|RUN|READ|CREATE|EDIT|REMEMBER|BROWSER_CLICK|BROWSER_FILL|BROWSER_READ|BROWSER_NAV):/i.test(line)
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

async function activeTab() {
  const result = await chrome.runtime.sendMessage({ type: "SENSEI_ACTIVE_TAB" });
  return result?.tab || null;
}

async function pageContext() {
  const tab = await activeTab();
  if (!tab?.id) return {};
  const fallback = { url: tab.url || "", title: tab.title || "" };
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "SENSEI_PAGE_CONTEXT" });
    return response?.page_context || fallback;
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

async function sendToContent(tabId, action) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "SENSEI_EXECUTE_ACTION", action });
  } catch (_firstErr) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content_script.js"] });
    return chrome.tabs.sendMessage(tabId, { type: "SENSEI_EXECUTE_ACTION", action });
  }
}

async function reportAction(action, verdict, result, finalState = {}) {
  try {
    await backendFetch("/extension/action_result", {
      method: "POST",
      body: {
        action_id: action.id,
        action,
        verdict,
        result,
        final_state: finalState
      }
    });
  } catch (err) {
    appendError(`Action audit failed: ${err.message}`);
  }
}

function setActionStatus(row, text) {
  const status = row.querySelector(".status");
  if (status) status.textContent = text;
}

async function approveAction(action, row) {
  const kind = String(action.kind || "").toUpperCase();
  setActionStatus(row, "Running");
  row.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });

  if (!kind.startsWith("BROWSER_")) {
    setActionStatus(row, "Not executable in the browser");
    await reportAction(action, "accept", "blocked", { reason: "unsupported by extension" });
    return;
  }

  try {
    const tab = await activeTab();
    if (!tab?.id) throw new Error("no active tab");

    let result;
    if (kind === "BROWSER_NAV") {
      const url = normalizeUrl(action.target);
      await chrome.tabs.update(tab.id, { url });
      result = { ok: true, navigated: url };
    } else {
      result = await sendToContent(tab.id, action);
    }

    const ok = Boolean(result?.ok);
    setActionStatus(row, ok ? "Done" : (result?.error || "Failed"));
    await reportAction(action, "accept", ok ? "success" : "failure", result || {});
  } catch (err) {
    setActionStatus(row, err.message);
    await reportAction(action, "accept", "failure", { error: err.message });
  }
}

async function rejectAction(action, row) {
  row.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
  setActionStatus(row, "Rejected");
  await reportAction(action, "reject", "blocked", {});
}

function renderActions(actions = [], blockedActions = []) {
  const dock = $("#actionDock");
  const list = $("#actionList");
  list.textContent = "";

  const all = [
    ...actions.map((action) => ({ ...action, blocked: false })),
    ...blockedActions.map((action) => ({ ...action, blocked: true }))
  ];

  dock.hidden = all.length === 0;
  if (!all.length) return;

  for (const action of all) {
    const row = document.createElement("section");
    row.className = "action-item";

    const main = document.createElement("div");
    main.className = "action-main";

    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = action.kind || "ACTION";

    const buttons = document.createElement("div");
    buttons.className = "action-buttons";

    if (!action.blocked) {
      const approve = document.createElement("button");
      approve.className = "primary";
      approve.type = "button";
      approve.textContent = "Approve";
      approve.addEventListener("click", () => approveAction(action, row));
      buttons.appendChild(approve);

      const reject = document.createElement("button");
      reject.className = "reject";
      reject.type = "button";
      reject.textContent = "Reject";
      reject.addEventListener("click", () => rejectAction(action, row));
      buttons.appendChild(reject);
    }

    main.append(kind, buttons);

    const target = document.createElement("div");
    target.className = "target";
    target.textContent = action.target || action.reason || "";

    const status = document.createElement("div");
    status.className = "status";
    status.textContent = action.blocked ? (action.reason || "Blocked") : "Pending";

    row.append(main, target, status);
    list.appendChild(row);
  }
}

async function sendPrompt() {
  const input = $("#promptInput");
  const prompt = input.value.trim();
  if (!prompt) return;

  input.value = "";
  appendMessage("user", prompt);
  $("#sendButton").disabled = true;
  $("#micButton").disabled = true;
  setConnection("Thinking");

  try {
    const ctx = await pageContext();
    const body = {
      prompt,
      mode: $("#modeSelect").value,
      source: "chrome_extension",
      session_id: state.config.sessionId,
      page_context: ctx
    };
    const data = await backendFetch("/chat", { method: "POST", body });
    const meta = [data.route, data.model, `${data.latency_ms || 0} ms`].filter(Boolean).join(" | ");
    appendMessage("assistant", cleanReply(data.reply), meta);
    $("#routeMeta").textContent = meta;
    renderActions(data.actions || [], data.blocked_actions || []);
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

async function healthCheck() {
  try {
    const data = await backendFetch("/health");
    setConnection(data.ok ? "Backend ready" : "Backend degraded");
  } catch (err) {
    setConnection(`Backend offline: ${err.message}`, "error");
  }
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

async function init() {
  await loadConfig();
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
  await healthCheck();
  appendMessage("assistant", "Ready.");
}

init().catch((err) => appendError(err.message));
