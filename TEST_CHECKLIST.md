# Master AI — Live Test Checklist (post-freeze)

Three tests you run when you're at the terminal. Each one verifies work that's already landed on disk. Results go into the session log so the next "where were we" can confirm what's green.

**Context:** the 2026-04-19 freeze was fixed by S01 (Ollama RAM cap) plus code patches (MODE default, `_safe_input` TTY refusal, reasoning loop directive quarantine). These tests confirm all of that actually works end-to-end.

---

## Test 1 — Reasoning Loop (think:) works without freezing

**Why this test:** S01 caps Ollama at one brain in RAM, which SHOULD let the 4-stage reasoning loop run without OOM. This is the first thing you were running when the machine froze. Verifying now is the highest-confidence way to know the fix took.

**How to run:**
1. Open Sensei (master.sh → option 4 → dojo gate → enter)
2. Type (safe starter query, nothing heavy):
   ```
   think fast: why does bash set -e not trigger on a failed command inside a pipeline?
   ```
3. Watch the status line. You should see:
   - `🧠 [1/3] PLANNER (qwen2.5:7b)...`
   - `🧠 [2/3] SOLVER (qwen2.5:7b)...`
   - `🧠 [3/3] FINALIZER (qwen2.5:3b)...`
4. Final answer shows as AI reply. No freeze. No multiple-model-load OOM.

**What to report back:**
- Did all 3 stages complete? ✅ / ❌
- Wall-clock time from send to final answer (should be 60–120s in fast mode)
- System RAM behavior — if you can `free -h` in another terminal during the run, note the peak. Should stay well under the ceiling.

**If it freezes again:**
- It's a DIFFERENT cause than today's. Power-off is safe — S01 didn't fix it.
- Before retrying: `systemctl show ollama -p Environment | tr ' ' '\n'` — confirm `OLLAMA_MAX_LOADED_MODELS=1` is still there.
- Check `~/.master_ai_audit.log` — new file. If empty, the reasoning loop didn't touch confirm_run (expected). If populated with `DENY-NO-TTY`, that's the safeguard firing.

---

## Test 2 — Multi-User Isolation

**Why this test:** multi-user plumbing (profile-aware `/sessions`, `/keys`, dojo gate) landed earlier today. `multiuser_test.sh` passes 18/18, but that's a scripted check. This is the live, interactive end-to-end.

**How to run:**
1. `bash ~/scripts/master.sh` → option 15 (Add User)
2. Pick a test profile name like `testuser`
3. When prompted, confirm the profile is created (you'll see confirmation)
4. Switch into it: option 17 (Switch User) → pick `testuser`
5. Banner at the top of Sensei should show `👤 testuser` (non-default indicator)
6. Say something to Sensei: `hi`. It answers.
7. Type `save session` — should save to `testuser`'s chat dir
8. Open Pupil at `http://localhost:8080` in a browser on the same machine. Confirm the "Projects ▾" dropdown and the chat area are EMPTY for testuser (localStorage is namespaced `testuser::`)
9. Switch back: option 17 → default
10. Confirm your original chat history and project board are intact

**What to report back:**
- Profile creation succeeded? ✅ / ❌
- Banner showed active profile? ✅ / ❌
- Pupil showed empty state for new profile? ✅ / ❌
- No leakage of your data into testuser's view? ✅ / ❌
- After switching back, your default profile is unchanged? ✅ / ❌

**Cleanup when done:**
- `ls ~/.master_ai_profiles/` — see all profiles
- To delete `testuser`: `rm -rf ~/.master_ai_profiles/testuser` (no sudo needed — your own dir)

---

## Test 3 — Phone access via Tailscale

**Why this test:** the whole "every entry point" wedge depends on the phone actually reaching Pupil. This verifies the Tailscale path works and the firewall (off on this box — see SUDO_MAP S03) isn't a factor.

**Prereqs** (check before starting):
- Tailscale is running on this machine: `tailscale status | head -5` should show `logged in`
- Tailscale is installed on your phone with the same account
- Your phone is on ANY network (cellular, wifi, doesn't matter — Tailscale bridges them)

**How to run:**
1. Get this machine's Tailscale IP: `tailscale ip -4`
2. On your phone, open a browser and go to: `http://<tailscale-ip>:8080`
3. Pupil should load with the martial-arts belt theme and the "Projects ▾" dropdown
4. Tap a project card — chat opens
5. Type something — AI responds. Voice-to-text input should work if your phone browser supports it (Chrome on Android works best).
6. Try the paperwork briefing — tap a project, see the AI 5-bullet summary appear

**What to report back:**
- Pupil loaded on phone? ✅ / ❌
- RAM bar in header shows data? ✅ / ❌
- Chat round-trip works? ✅ / ❌
- Voice-to-text input works? ✅ / ❌

**If phone can't reach :8080:**
- On this machine: `ss -tlnp | grep 8080` — confirm stt_server is listening on `0.0.0.0:8080` (not `127.0.0.1:8080`)
- If it's bound to 127.0.0.1, the server won't accept remote connections. Needs a config fix.
- Check Tailscale: `tailscale status` on both ends. Both should be "active."

---

## What to do with this doc

- Keep it as the "post-freeze acceptance test" — run all three any time a new sudo or code change lands in the permission layer
- Results of each test go into today's state memory under the appropriate section ("what was verified")
- If all three pass, the recovery arc from today is complete and v1.8 is a legitimate candidate for "pack it up for sale"
