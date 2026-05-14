# Hypnotix Positive Test — desktop.launch_app happy path

End-to-end vertical-slice acceptance test for phase 1 of the
[Reactive Waddling Papert plan](~/.claude/plans/reactive-waddling-papert.md).

Verifies that **extension → kernel → capability registry → executor →
verifier → audit-shaped reply** works honestly, with the launched process
visible in the system process table and the audit row carrying full
evidence (capability name + full VerifyResult shape + git short).

## Setup

1. `master-ai-ui.service` must be active:

   ```bash
   systemctl --user is-active master-ai-ui.service
   ```

   Expected: `active`.

2. Reload the unpacked extension in `chrome://extensions` so any changes
   to `side_panel.js` are loaded.

3. Ensure Hypnotix is not already running so the test starts from a clean
   process table:

   ```bash
   pkill -x hypnotix 2>/dev/null
   sleep 1
   pgrep -af '(^|/)hypnotix([[:space:]]|$)'
   ```

   Expected: no output (no hypnotix process).

4. Open the Sensei side panel.

5. Confirm the connection state reads `Backend ready` (heartbeat just
   pinged `/health` successfully).

6. (Optional, recommended on a debugging run) In a second terminal:

   ```bash
   tail -f ~/.master_ai_audit_typed.jsonl
   ```

   And:

   ```bash
   journalctl --user -u master-ai-ui.service -f
   ```

## Test prompt

Set mode to **Auto** in the side panel. Send exactly:

```
open hypnotix
```

## Expected behavior

### Side panel chat

Almost immediate (around 200 ms total) response:

```
Launching hypnotix via the registered desktop.launch_app capability.
RUN: hypnotix &

— server-dispatched output —
$ hypnotix &
[desktop.launch_app] verified: <PID> hypnotix (<elapsed>ms)
```

The PID is the live Linux PID of the new Hypnotix process. The elapsed_ms
is how long the verifier took to find it (typically 10-50 ms).

### Reply metadata (DevTools Network → /chat → Response tab)

```json
{
  "route": "desktop_launch",
  "model": "master-ai",
  "latency_ms": <≤500>,
  "actions": [],
  "blocked_actions": [],
  "done": true,
  "terminal_reason": "no_actions"
}
```

### System process table

```bash
pgrep -af '(^|/)hypnotix([[:space:]]|$)'
```

Expected: at least one line with the PID reported in the reply.

### Audit row

The latest line of `~/.master_ai_audit_typed.jsonl` should contain:

```json
{
  "kind": "turn_terminal",
  "route": "desktop_launch",
  "capabilities_fired": ["desktop.launch_app"],
  "verification_results": [
    {
      "ok": true,
      "observed": "<PID> hypnotix",
      "elapsed_ms": <small>,
      "reason": "process 'hypnotix' found"
    }
  ],
  "git_commit_short": "<10-char>",
  ...
}
```

`prompt_version` may read `"unstamped"` for this route — that's expected;
short-circuit routes don't reach the CLOUD_SYSTEM assembly site where
stamping happens. `git_commit_short` is always populated.

## Pass criteria

All of these must be true:

- [ ] Side panel reply contains `[desktop.launch_app] verified: <PID> hypnotix`
      (not "done", not a generic confirmation — proof with a real PID)
- [ ] `route: desktop_launch` and `model: master-ai` in the response JSON
- [ ] `latency_ms` under 500 (typical: 150-250)
- [ ] `actions: []` and `done: true` (no orphan action cards)
- [ ] `pgrep -af '(^|/)hypnotix([[:space:]]|$)'` shows the PID after the call
- [ ] Audit row has `capabilities_fired: ["desktop.launch_app"]`
- [ ] Audit row's `verification_results[0].ok` is `true`
- [ ] Audit row's `verification_results[0].observed` matches the PID from the reply
- [ ] `git_commit_short` is populated

If any line fails, the vertical slice is not honestly verified.

## If it stalls or fails

| Symptom | Read this | Likely break |
| --- | --- | --- |
| No /chat fires in DevTools Network | side_panel.js bridge gate | `bridgeState().ok` is false — heartbeat says bridge unhealthy |
| `route: cloud_fast` instead of `desktop_launch` | master_ai.py `_desktop_launch_short_circuit` | API wrapper changed, regex anchor lost, or "hypnotix" removed from allowlist |
| Reply has `RUN: hypnotix &` but no verified line | stt_server.py registry dispatch block | Registry didn't match — check `_caps.get_registry().lookup("RUN", "hypnotix &")` |
| Reply has `[desktop.launch_app] not verified` | verifiers.py `verify_process_running` | Hypnotix didn't appear in process table within 5s. Try launching `hypnotix` manually from a terminal first; if that also fails, the issue is upstream (Hypnotix install, display server) |
| Audit row missing `capabilities_fired` | stt_server.py `_write_turn_audit` | `_registry_handled` list not populated — check the dispatch loop append |
| Audit row missing `git_commit_short` | prompt_versions.py `_git_commit_short` | `~/scripts` not a git repo, or `git` not on PATH inside the service environment |

## Cleanup

```bash
pkill -x hypnotix 2>/dev/null
```

If `pkill` is ignored (Hypnotix sometimes refuses signals), close its
window manually or `kill -9 <PID>` from your own terminal.

## Related

- `hypnotix_negative.md` — the matching honest-failure test (bridge unreachable)
- `loop_smoke.html` + `LOOP_CHECKLIST.md` — broader extension-loop smoke test
- `~/scripts/capabilities.py` — registry source of truth, REGISTRY_VERSION
- `~/scripts/verifiers.py` — verifier framework, anchored pgrep regex
- `~/.master_ai_audit_typed.jsonl` — audit log this test reads from
