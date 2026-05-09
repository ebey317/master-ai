# Pending Sudo / Password Review

Anything that needs your password or sudo approval queues here. You review
remotely during the day, paste when you have a separate terminal open,
check off as you go.

Rule from `.sensei_behavior.md` (hard): Sensei NEVER accepts passwords,
NEVER pipes a password to sudo, NEVER asks "what's your password." Every
sudo-requiring action lands HERE for you to run yourself.

## How to use this file

1. A Sensei or Claude agent adds an entry with: what, why, where, exact command.
2. You read remotely (from phone / work / elsewhere).
3. When you're at a separate terminal on Madam-Mary, run the command.
4. Check the `[x]` box, add a one-line result.

## Current pending items

_(none — queue is empty as of 2026-04-19 evening)_

### Template for new entries

```
### [ ] <short title>
- **Who:** <agent name / session id>
- **What:** <one-line summary of the change>
- **Where:** <file path or system area affected>
- **Why:** <user-facing reason>
- **Exact command to run in a separate terminal:**
      sudo <the exact line>
- **Verify after running:**
      <a one-line check that confirms it worked>
- **Added:** <YYYY-MM-DD HH:MM>
- **Approved by:** <fill in your initials when you run it>
- **Result:** <fill in after running>
```

## Historical entries (resolved)

- **2026-04-19** — `sudo bash ~/scripts/apply_ollama_cap.sh` — added
  `OLLAMA_MAX_LOADED_MODELS=2` to the systemd drop-in (the box later
  moved from the original 1-model cap to the current 2-model residency).
  Applied same day.
- **2026-04-19** — `sudo bash ~/scripts/apply_user_linger.sh` — already on
  from an earlier session. Idempotent, verified.
- **2026-04-19** — `sudo bash ~/scripts/apply_ufw_ports.sh` — ufw inactive
  on this box, dormant rules queued in ufw db. No action required.
