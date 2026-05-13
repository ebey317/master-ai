const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8080",
  mode: "review",
  token: "",
  sessionId: ""
};

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
  if (message?.type !== "SENSEI_ACTIVE_TAB") return false;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    sendResponse({ tab: tabs?.[0] || null });
  });
  return true;
});
