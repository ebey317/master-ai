# Hypnotix Negative Test — bridge unreachable, honest failure

End-to-end honest-failure test for phase 1 of the
[Reactive Waddling Papert plan](~/.claude/plans/reactive-waddling-papert.md).

Verifies that when the local backend is unreachable, the extension **refuses
to dispatch** with a structured "would have sent" message rather than
fake success, hallucinated completion, or a generic network-error stack
trace. This is the gate the external architecture review correctly flagged
as the test of whether failure reporting is honest.

The matching happy-path test is `hypnotix_positive.md`. Both must pass
honestly for phase 1 acceptance.

## Setup

1. Confirm `master-ai-ui.service` is currently active (we'll stop it
   for the test, then restart):

   ```bash
   systemctl --user is-active master-ai-ui.service
   ```

   Expected: `active`.

2. Reload the unpacked extension in `chrome://extensions` so the new
   heartbeat + bridge-gate code in `side_panel.js` is loaded.

3. Open the Sensei side panel and confirm the connection state reads
   `Backend ready` (heartbeat is succeeding). This is your baseline.

4. (Optional, recommended) In a second terminal, tail the audit log
   so you can confirm NO new row appears during this test:

   ```bash
   tail -f ~/.master_ai_audit_typed.jsonl
   ```

5. Pre-cleanup hypnotix so a stale process doesn't confuse the
   post-check:

   ```bash
   pkill -x hypnotix 2>/dev/null
   ```

## Take the bridge down

```bash
systemctl --user stop master-ai-ui.service
```

Wait ~10 seconds. The side panel heartbeat fires every 7s; the staleness
threshold is 20s. Within that window the connection state must transition
to a "Bridge unreachable" or similar error indicator.

Confirm the service is actually stopped:

```bash
systemctl --user is-active master-ai-ui.service
```

Expected: `inactive` or `failed`.

## Test prompt

Set mode to **Auto** in the side panel. Send exactly:

```
open hypnotix
```

## Expected behavior

### Side panel chat

A user message bubble showing your prompt, immediately followed by an
error message:

```
Bridge unreachable (<the heartbeat's last error, e.g. "Failed to fetch">).
Would have sent: "open hypnotix". Restart master-ai-ui.service to
reconnect, then try again.
```

The connection state shows `Bridge unreachable`.

### DevTools Network panel

**NO** `POST /chat` request fires. The extension refused at the bridge
gate before reaching the network call.

You may see `/health` probes appearing intermittently (every 7s) and
failing — that's the heartbeat doing its job. Those are expected.

### System process table

```bash
pgrep -af '(^|/)hypnotix([[:space:]]|$)'
```

Expected: no output. The launcher never fired because the request never
reached the backend.

### Audit log

The tail you started in setup step 4 should show **no new lines** during
this attempt. No turn_terminal row, no extension_action_result row. The
attempt never reached the backend, so the audit trail correctly has no
record of it.

## Pass criteria

All of these must be true:

- [ ] Side panel connection state shows `Bridge unreachable` within
      ~20 seconds of stopping the service
- [ ] Sending "open hypnotix" produces the literal `Bridge unreachable
      (...). Would have sent: "open hypnotix". Restart master-ai-ui.service
      to reconnect, then try again.` error message
- [ ] User's prompt is still echoed into the chat (so they know it was
      received by the side panel)
- [ ] DevTools Network shows NO `/chat` request fired during the attempt
- [ ] `pgrep -af hypnotix` returns nothing — no process spawned
- [ ] No new line appended to `~/.master_ai_audit_typed.jsonl`

The honest-failure principle: **the agent must not say it did something
it could not do, and must not fail silently**. Both halves matter — fake
success is the more famous failure mode but silent failure (the spinner
spins forever) is just as misleading.

## Recover

```bash
systemctl --user start master-ai-ui.service
sleep 3
systemctl --user is-active master-ai-ui.service
```

Within ~7 seconds of recovery, the side panel heartbeat should pick up
again and the connection state should return to `Backend ready`.

Try the positive prompt to confirm the system is back to normal:

```
open hypnotix
```

Expected: the happy path from `hypnotix_positive.md`.

## If the test fails to fail honestly

| Symptom | Read this | Likely break |
| --- | --- | --- |
| Side panel says `Backend ready` even after service is stopped | side_panel.js heartbeat | `startHeartbeat()` not running, interval too long, or `bridgeState()` staleness threshold mis-set |
| Sending the prompt fires a `/chat` request that fails with a connection error | side_panel.js sendPrompt | Bridge-state gate not wired; check `bridgeState().ok` is consulted before backendFetch |
| Reply says "Done" or "Opened Hypnotix" with no hypnotix process | this is the worst case — fake success | sendPrompt is calling /chat without bridge check, OR backendFetch is returning cached stale data, OR audit shape was hallucinated by the model and trusted |
| Audit log shows a new row | The request DID reach the backend (bridge wasn't actually down) | check `systemctl --user is-active master-ai-ui.service` after the test |
| Side panel hangs indefinitely with a spinner | the network call is in flight without a bridge check | sendPrompt's bridge gate is missing or short-circuited |

## Why this test matters

The matching positive test proves the system CAN do the thing. This test
proves the system can REFUSE to do the thing when it can't, *honestly*.
Most agentic systems get the positive case right and fail this test —
they silently retry, fake completion, or stall. Phase 1 of this plan
explicitly targets honest failure as a first-class capability.

## Related

- `hypnotix_positive.md` — the matching happy-path test
- `~/scripts/sensei_extension/side_panel.js` — heartbeat + bridge gate
- `~/.claude/plans/reactive-waddling-papert.md` — phase 1 plan with
  the "no fake completion" criterion
