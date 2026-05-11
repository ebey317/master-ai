# Pupil HTTP API contract

Status: **P0.1 contract — locked**. Pupil HTML (P0.2) and any future Pupil
mobile client must build against the shapes below. Implementation lives in
`~/scripts/stt_server.py` (port 8080). Smoke tests live in
`~/scripts/test_pupil_api.py`.

## Scope

This contract covers the **Pupil browser surface only** — same-machine
localhost calls from the Pupil UI to the Master AI backend. It is NOT the
inter-node mesh protocol (`POST /ask`, which is mesh-token-gated and
intentionally kept separate). Pupil endpoints are bound to `localhost`/`127.0.0.1`
binding semantics of stt_server and do not require an auth token; if you need
to expose them off-box, do that with an explicit reverse proxy and your own
auth layer.

## Versioning

This is `v1`. Backward-compatible changes (new optional fields, new endpoints)
won't bump the version. Breaking changes do bump it, in which case the new
endpoints live under `/v2/...` and the old endpoints stay working for one
release cycle.

## Conventions

- Content type: `application/json` for all request and response bodies.
- Timestamps: ISO-8601 strings (`2026-05-11T14:30:00-04:00`).
- Booleans: `true` / `false` (not `0` / `1`).
- Errors: HTTP status >= 400 with body `{"error": "<short reason>"}`.
- Optional fields: documented with `?` after the field name; servers omit when
  unset, clients must tolerate missing.

## Endpoints

### GET /health

Liveness + Ollama reachability check. Cheap, intended for poll loops.

**Response (200):**
```
{
  "ok": true,                           // false only if internal error
  "ollama": "active" | "down",          // Ollama daemon reachable on 11434
  "model": "master-ai",                 // currently configured local model name
  "ts": "2026-05-11T14:30:00-04:00"
}
```

### GET /status

Current Sensei state. More expensive than `/health` because it reads metrics
and Ollama `/api/ps`. Use it for the status card; don't hammer it from a poll
loop.

**Response (200):**
```
{
  "mode": "plan" | "review" | "auto",   // from ~/.master_ai_mode
  "model": "master-ai",                 // active local model
  "memory_facts": 243,                  // line count of ~/.master_ai_memory
  "last_route": "local" | "cloud_fast" | "cloud_deep" | "vision" | "system_query" | "weather" | "...",
  "queue_depth": 0,                     // future use; always 0 until queue lands
  "loaded_models": [                    // Ollama models resident in RAM right now
    {"name": "master-ai:latest", "size_mb": 4700}
  ],
  "mem": {                              // free at this moment (MB)
    "total_mb": 15868,
    "used_mb": 8762,
    "available_mb": 7106,
    "swap_used_mb": 0
  },
  "ts": "2026-05-11T14:30:00-04:00"
}
```

### POST /chat

The Pupil chat endpoint. **MVP behavior** in P0.1: direct call into the local
model via Ollama `/api/generate`, returning a structured shape. **P0.3 hookup**
moves this to call `master_ai.handle()` so Pupil gets the full Sensei brain
(routing, blocked-feedback, harvest). The response shape stays the same — only
the engine behind it changes.

**Request:**
```
{
  "prompt": "what's 2+2?",              // required, non-empty
  "mode": "plan" | "review" | "auto",   // optional; default = current ~/.master_ai_mode
  "model": "master-ai"                  // optional; default = master-ai
}
```

**Response (200):**
```
{
  "reply": "2 + 2 equals 4.",           // the assistant's text reply
  "route": "local",                     // which lane handled the prompt
  "model": "master-ai",                 // model that produced the reply
  "latency_ms": 7104,                   // wall-clock from request to response
  "blocked_actions": [],                // list of {kind, target, reason} if any
                                        //   directives were blocked during this turn
  "ts": "2026-05-11T14:30:00-04:00"
}
```

**Errors:**
- 400 — `{"error": "missing prompt"}` if `prompt` is empty/missing.
- 503 — `{"error": "ollama unreachable"}` if Ollama daemon is down.
- 500 — `{"error": "<exception>"}` for everything else.

### GET /events

Server-Sent Events stream. Pupil opens this once and listens for live events
(typed-action lifecycle from P0.4, mode changes, hook fires from P1.4).

**Response:** `text/event-stream`, never closes. Each event:
```
event: <name>
data: <json-payload>

```

**Events emitted in P0.1 (heartbeat only — typed-action events land in P0.4):**
- `event: hello\ndata: {"ts": "..."}` — sent once on connect.
- `event: heartbeat\ndata: {"ts": "..."}` — every 15 seconds.

**Events reserved for P0.4 (will appear once typed actions land):**
- `action_started`, `action_finished`, `action_blocked`, `mode_changed`,
  `hook_fired`, `route_decided`.

Clients must tolerate unknown event names (ignore + continue listening).

### POST /mode

Change the current Sensei mode. Persists to `~/.master_ai_mode`.

**Request:**
```
{ "mode": "plan" | "review" | "auto" }
```

**Response (200):**
```
{ "ok": true, "mode": "auto" }
```

**Errors:**
- 400 — `{"error": "invalid mode"}` if not one of plan/review/auto.

Side effects: a `mode_changed` event fires on the `/events` SSE stream (in P0.4
once typed actions wire it up — P0.1 ships the persistence only).

### POST /voice

Toggle Pupil's voice (TTS) output preference. Stored at
`~/.master_ai_voice_enabled`.

**Request:**
```
{
  "enabled": true | false,              // required
  "engine": "piper"                     // optional; reserved for multi-engine future
}
```

**Response (200):**
```
{
  "ok": true,
  "voice_state": {
    "enabled": true,
    "engine": "piper"
  }
}
```

## Acceptance (P0.1 done when)

- `python3 ~/scripts/test_pupil_api.py` passes with exit code 0.
- Each endpoint above returns its documented shape under the test harness.
- Existing `POST /ask` (mesh-gated) and `GET /sys` continue to work
  unchanged — this contract adds endpoints, it does not replace any.
- `bash ~/scripts/sensei_selftest.sh` does not regress (109 PASS · 0 WARN ·
  1 FAIL → still 109 PASS · 0 WARN · 1 FAIL, where the 1 FAIL is still the
  `pupil.html` placeholder until P0.2 lands).
