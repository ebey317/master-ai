# Master AI Store Readiness Gate

Last updated: 2026-04-25

This file defines the minimum bar before a buyer bundle is uploaded or sold.

## Required Passes

- [ ] `git status --short` is empty.
- [ ] `python3 -m py_compile ~/scripts/master_ai.py ~/scripts/harvest.py` passes.
- [ ] `python3 ~/scripts/test_master_ai_parser.py` passes.
- [ ] `bash ~/scripts/sensei_selftest.sh` passes from a normal terminal, not a sandbox.
- [ ] `bash ~/scripts/pack_for_sale.sh /tmp/master-ai-sale-test` completes.
- [ ] Install test passes on a clean Linux or WSL user account.
- [ ] `doctor` shows Pupil, Ollama, required models, voice file, and TTS state clearly.
- [ ] `router` shows feedback stats without crashing.
- [ ] `harvest` shows cache stats without crashing.

## Store Assets

- [ ] Product title
- [ ] Short description
- [ ] Long description
- [ ] Privacy policy: `PRIVACY.md`
- [ ] Support page: `SUPPORT.md`
- [ ] Screenshots of Sensei, Pupil, Dojo, doctor, and install flow
- [ ] Version number and changelog
- [ ] Refund/support process for the sales platform

## Runtime Safety Gates

- [x] Auto mode stops after the first failed `RUN:`. Verified on disk 2026-04-27.
- [x] Pipelines fail correctly through `bash -o pipefail`. Verified on disk 2026-04-27.
- [x] Interactive commands such as `less`, `vim`, `top`, and `htop` are blocked from `RUN:` and must use `RUNTERM:`. Verified on disk 2026-04-27.
- [x] Missing top-level commands are blocked in Auto mode. Verified on disk 2026-04-27.
- [x] `sudo` and passwords are print-only handoffs. Verified on disk 2026-04-27.
- [x] Generated mail/spam automation scripts are not present in the bundle. Verified on disk 2026-04-27.

## Not Ready If

- Any untracked generated script is present in `~/scripts`.
- Any test only passes inside Elijah's current machine state.
- A demo requires private keys, personal memory, or local-only paths.
- The model can continue a command chain after a failed setup command.
