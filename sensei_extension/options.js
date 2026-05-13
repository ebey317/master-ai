const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8080",
  token: "",
  mode: "review",
  sessionId: ""
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

async function load() {
  const stored = await chromeGet(Object.keys(DEFAULTS));
  const config = { ...DEFAULTS, ...stored };
  if (!config.sessionId) config.sessionId = `sensei-${crypto.randomUUID()}`;
  $("#backendUrl").value = config.backendUrl || DEFAULTS.backendUrl;
  $("#token").value = config.token || "";
  $("#mode").value = config.mode || "review";
  $("#sessionId").value = config.sessionId;
  await chromeSet({ sessionId: config.sessionId });
  setStatus("Loaded");
}

async function save() {
  const values = {
    backendUrl: $("#backendUrl").value.trim().replace(/\/+$/, "") || DEFAULTS.backendUrl,
    token: $("#token").value.trim(),
    mode: $("#mode").value,
    sessionId: $("#sessionId").value.trim() || `sensei-${crypto.randomUUID()}`
  };
  await chromeSet(values);
  setStatus("Saved");
}

async function testBackend() {
  const backendUrl = $("#backendUrl").value.trim().replace(/\/+$/, "") || DEFAULTS.backendUrl;
  const token = $("#token").value.trim();
  setStatus("Testing");
  try {
    const res = await fetch(`${backendUrl}/health`, {
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
});
