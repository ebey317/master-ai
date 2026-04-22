# Master AI — Sudo Map

**What this is:** the complete list of password-gated (sudo) commands Master AI ever asks you to run. Every entry is documented so you know exactly what's being changed on your computer and why. You run these in a separate terminal. Claude never runs them.

**The rule:** Claude never runs sudo, never auto-confirms, never types a password. If a change needs root, it comes here first, you read what it does, you paste it yourself.

**Format of each entry:**
- **What this opens up** — what becomes possible after you run it
- **Why it matters** — the real-world problem it solves
- **What it changes on your computer** — exact files, services, or settings touched
- **Paste this** — one short command you copy into a separate terminal
- **Check it worked** — a no-password command to verify

---

## [S01] Tell Ollama: only keep one AI brain awake at a time ✅ APPLIED 2026-04-19

**What this opens up:** the reasoning loop can run without freezing your computer.

**Why it matters:** your computer has a set amount of fast memory (RAM). Each AI brain takes up a big chunk. If more than one brain is awake at the same time, fast memory fills up and your computer starts using slow memory instead. Slow memory is SO slow the whole machine locks up. That's what happened 2026-04-19. This tells Ollama: "no matter what, only one brain awake."

**What it changes on your computer:**
- Adds `Environment="OLLAMA_MAX_LOADED_MODELS=1"` to `/etc/systemd/system/ollama.service.d/keep-alive.conf`
- Reloads systemd so it reads the new rule
- Restarts Ollama so the rule takes effect

**Paste this** (one line, short enough not to wrap):
```
sudo bash ~/scripts/apply_ollama_cap.sh
```

**Check it worked** (no password needed):
```
systemctl show ollama -p Environment
```
You should see `OLLAMA_MAX_LOADED_MODELS=1` in the output.

---

## [S02] Keep Sensei + Pupil running after you log out

**What this opens up:** your 24/7 always-on rule. Sensei stays alive in tmux, Pupil (`:8080`) stays reachable, TTS (`:5050`) keeps answering — even after you close your session or log out.

**Why it matters:** by default, Linux kills your user's background services the moment you log out. That means Sensei would shut down every time you walked away. The fix is called "user lingering" — telling systemd "keep this user's services running even with no one logged in."

**What it changes on your computer:**
- Flips one bit in systemd's user database: `elijah` goes from "services die on logout" to "services persist."
- Does not start anything new. Does not change any config. Only changes the rule about what happens when you log out.

**Paste this** (one line):
```
sudo bash ~/scripts/apply_user_linger.sh
```

**Check it worked** (no password):
```
loginctl show-user elijah | grep Linger
```
You should see `Linger=yes`.

---

## [S03] Open LAN ports for Pupil + TTS + Mesh (only if ufw is on)

**What this opens up:** other devices on your local network can reach Pupil in a browser (`:8080`), hear the TTS voice (`:5050`), and talk to the mesh (`/node_info`). Your phone, other PCs on Tailscale, anyone you trust on your network.

**Why it matters:** most Linux boxes ship with a firewall turned off, but some have `ufw` (uncomplicated firewall) on. If ufw is blocking these ports, you can reach Pupil from THIS machine but not from your phone. This opens three specific ports — nothing else.

**BEFORE you run S03, check if you even need it** (no password):
```
sudo ufw status
```
- If it says **"Status: inactive"** → skip S03 entirely. Your firewall isn't blocking anything.
- If it says **"Status: active"** → S03 is useful. Continue below.

**What it changes on your computer:**
- Adds three ufw rules: port 8080/tcp (Pupil), port 5050/tcp (TTS), port 11434/tcp (Ollama — LAN only, don't use this on public networks).
- Does NOT turn the firewall on or off. Only adds rules to the existing one.

**Paste this** (one line):
```
sudo bash ~/scripts/apply_ufw_ports.sh
```

**Check it worked** (no password):
```
sudo ufw status numbered
```
You should see rules allowing 8080, 5050, and 11434.

---

## [S04] Install earlyoom + tune swappiness — stop the hard freezes

**What this opens up:** your computer stops hard-locking when memory pressure spikes. One process dies instead of the whole machine.

**Why it matters:** S01 stopped Ollama from stacking multiple brains, but it didn't stop OTHER memory pressure — RustDesk streaming video + Jellyfin + vite + Pupil + browser tabs + one Ollama model = enough to saturate 15 GB. When that happens with no userland OOM-killer watching, the kernel thrashes swap so hard that it locks up before its OWN killer fires. That's what happened 2026-04-20 — freeze at ~06:40, dead until power button at home. `earlyoom` is a tiny daemon that watches RAM+swap and kills the biggest offender BEFORE the kernel hits thrash state.

**What it changes on your computer:**
- Installs the `earlyoom` package from Ubuntu's `universe/admin` repo
- Writes `/etc/default/earlyoom` with thresholds: kill biggest process when RAM AND swap both below 10%
- Adds an "avoid" list (systemd, Xorg, sshd, tailscaled, cinnamon) and a "prefer" list (ollama, python, chrome, firefox, node) so the killer picks the right target
- Writes `/etc/sysctl.d/99-master-ai-swappiness.conf` setting `vm.swappiness=10` (was 60) — kernel prefers RAM over swap
- Enables + starts the `earlyoom` systemd service

**Paste this** (one line):
```
sudo bash ~/scripts/apply_earlyoom.sh
```

**Check it worked** (no password):
```
systemctl is-active earlyoom && cat /proc/sys/vm/swappiness
```
Should print `active` and `10`.

**See what it killed** (if it fires):
```
journalctl -u earlyoom --since today
```

---

## Why each sudo is NEEDED (big picture)

- **S01** — prevents Ollama-caused freeze. Required before you trust the reasoning loop (`think:` / `think fast:` / `think deep:`).
- **S02** — required for the "always-on" product experience you're selling. Without it, buyers have to manually relaunch Sensei every time they reboot or log out.
- **S03** — required for multi-device access (phone, Tailscale). Without it, Master AI is a single-machine product. With it, it becomes the "every entry point" wedge.
- **S04** — prevents general-memory-pressure freeze. S01 only covers Ollama; S04 covers everything else (RustDesk, browser, Jellyfin, vite) that can eat RAM. Together they turn the 15 GB machine from "might hard-freeze under load" into "kills the biggest process and keeps running." Becomes less critical after the 32 GB RAM upgrade but should stay installed anyway.

## [S05] Stop the silent-hang freezes on Skylake graphics ⏳ PENDING PASTE + REBOOT

**What this opens up:** the computer stops locking up silently when Sensei + RustDesk + browser all run together.

**Why it matters:** the freezes 2026-04-19 and 2026-04-20 were NOT memory problems — earlyoom logs prove the box had 12+ GB free when it died. The real cause is the Intel HD Graphics 530 driver (i915) on kernel 5.15 with two power-saving features that have known hang bugs: **Panel Self-Refresh (PSR)** and **Frame Buffer Compression (FBC)**. RustDesk continuously captures the screen; that workload triggers the bug, the graphics chip hard-locks, the whole kernel follows, and the box can't even log why before it dies. That's why every freeze is silent — not a software overrun, a known driver bug. `last reboot` shows 5 of these crashes in 7 days, getting more frequent as the workload grew.

**What it changes on your computer:**
- Backs up `/etc/default/grub` to `/etc/default/grub.backup.<timestamp>` so you can revert
- Appends `i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0` to `GRUB_CMDLINE_LINUX_DEFAULT`
- Runs `update-grub` so the new boot line takes effect next reboot
- Does NOT touch anything else — idempotent (re-running is harmless)

**Paste this** (one line, in a separate terminal):
```
sudo bash ~/scripts/apply_i915_safety.sh
```

**Then reboot.** The fix only activates after reboot.

**Check it worked** (no password needed, after reboot):
```
cat /proc/cmdline | tr ' ' '\n' | grep i915
```
You should see all three `i915.enable_*=0` lines.

**If something goes wrong:** the script prints a one-line revert command that restores the backup.

---

## Why there aren't more

Everything else Master AI does runs as your normal user:
- Installing scripts → `~/scripts/`
- Writing memory → `~/.claude/projects/.../memory/`
- Chat history → `~/.master_ai_chats/`
- Running Sensei → user process
- Running Pupil → systemd USER service (no root)
- Running TTS → systemd USER service (no root)
- Pulling Ollama models → Ollama handles its own install dir
- Config files → `~/.master_ai_*`

The sudo list is finite on purpose. Everything above lives here. If Claude ever asks for sudo for something NOT on this list, that's a product bug — flag it immediately.
