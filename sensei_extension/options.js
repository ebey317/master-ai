const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8080",
  token: "",
  mode: "review",
  sessionId: "",
  actionPermissionMode: "ask",
  approvedOrigins: [],
  permissionHistory: []
};

const $ = (selector) => document.querySelector(selector);

function chromeGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function chromeSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

function setStatus(text) {
  $("#status").textContent = text;
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/[+/=]/g, "").slice(0, 32);
}

function normalizeConfig(config) {
  const next = { ...DEFAULTS, ...config };
  if (!["ask", "act"].includes(next.actionPermissionMode)) next.actionPermissionMode = "ask";
  if (!Array.isArray(next.approvedOrigins)) next.approvedOrigins = [];
  if (!Array.isArray(next.permissionHistory)) next.permissionHistory = [];
  return next;
}

function renderApprovedSites(origins = []) {
  const list = $("#approvedSites");
  list.textContent = "";
  if (!origins.length) {
    const item = document.createElement("li");
    item.textContent = "No approved sites";
    list.appendChild(item);
    return;
  }
  for (const origin of origins) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = origin;
    const revoke = document.createElement("button");
    revoke.type = "button";
    revoke.textContent = "Revoke";
    revoke.addEventListener("click", async () => {
      const stored = normalizeConfig(await chromeGet(Object.keys(DEFAULTS)));
      stored.approvedOrigins = stored.approvedOrigins.filter((value) => value !== origin);
      await chromeSet({ approvedOrigins: stored.approvedOrigins });
      renderApprovedSites(stored.approvedOrigins);
      setStatus("Permission revoked");
    });
    item.append(label, revoke);
    list.appendChild(item);
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 3500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err?.name === "AbortError") throw new Error("health check timed out");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function load() {
  const stored = await chromeGet(Object.keys(DEFAULTS));
  const config = normalizeConfig(stored);
  if (!config.sessionId) config.sessionId = `sensei-${crypto.randomUUID()}`;
  $("#backendUrl").value = config.backendUrl || DEFAULTS.backendUrl;
  $("#token").value = config.token || "";
  $("#mode").value = config.mode || "review";
  $("#sessionId").value = config.sessionId;
  $("#actionPermissionMode").value = config.actionPermissionMode;
  renderApprovedSites(config.approvedOrigins);
  await chromeSet({ sessionId: config.sessionId });
  setStatus("Loaded");
}

async function save() {
  const values = {
    backendUrl: $("#backendUrl").value.trim().replace(/\/+$/, "") || DEFAULTS.backendUrl,
    token: $("#token").value.trim(),
    mode: $("#mode").value,
    sessionId: $("#sessionId").value.trim() || `sensei-${crypto.randomUUID()}`,
    actionPermissionMode: $("#actionPermissionMode").value
  };
  await chromeSet(values);
  setStatus("Saved");
}

async function testBackend() {
  const backendUrl = $("#backendUrl").value.trim().replace(/\/+$/, "") || DEFAULTS.backendUrl;
  const token = $("#token").value.trim();
  setStatus("Testing");
  try {
    const res = await fetchWithTimeout(`${backendUrl}/health`, {
      headers: { "X-Master-AI-Token": token }
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    setStatus(data.ok ? "Backend ready" : "Backend degraded");
  } catch (err) {
    setStatus(`Test failed: ${err.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("#optionsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    save();
  });
  $("#testBackend").addEventListener("click", testBackend);
  $("#generateToken").addEventListener("click", () => {
    $("#token").value = randomToken();
    setStatus("Token generated");
  });
  $("#clearApprovedSites").addEventListener("click", async () => {
    await chromeSet({ approvedOrigins: [] });
    renderApprovedSites([]);
    setStatus("Approved sites cleared");
  });
});
