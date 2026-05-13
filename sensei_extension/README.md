# Sensei Browser Bridge

Chrome Manifest V3 extension scaffold for the local Master AI backend.

## Files

- `manifest.json` - MV3 manifest, service worker, side panel, content script, options page.
- `service_worker.js` - side panel behavior and active tab lookup.
- `side_panel.html`, `side_panel.css`, `side_panel.js` - chat, action approval, and local Whisper `/stt`.
- `content_script.js` - page context collection and `BROWSER_*` action dispatch.
- `options.html`, `options.css`, `options.js` - backend URL, token, mode, and session settings.

## Local Setup

1. Put the shared token in `~/.master_ai_extension_token`.
2. Open `chrome://extensions`, enable Developer mode, and load this directory unpacked.
3. Open the extension options and set the same token.

Every backend request includes `X-Master-AI-Token`; `/chat` sends `source`, `session_id`, and `page_context`.
