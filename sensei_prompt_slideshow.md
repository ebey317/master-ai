# Sensei Prompts — Slideshow App

Two prompts here. Use V1 first to get the basic app working. Then V2 to add face sorting once V1 is solid.

For both: switch Sensei to **Plan mode** before pasting (the grounded Plan mode shipped 2026-04-24 pulls Wikipedia + web + filesystem + memory before drafting). Sensei plans, emits `<PLAN READY>`, then shows the 4-button row. Press 1 to approve + execute.

---

## V1 — basic slideshow + uninstall (recommended start)

```
i want a slideshow app for my pictures. pulls from a folder, default that to pictures slash slideshow in my home folder. show each picture full screen, give me an option from three to thirty seconds per picture with different transition effects between slides like fade shadow ripple stuff like that.

if i want to add a picture i just drop it in the folder. if i want to delete one i just delete it from the folder. app re-reads the folder each time it starts.

i need two uninstall options. one that removes just the app and leaves my pictures alone. one that wipes everything app and pictures both. both ask me before doing anything destructive.

keep it simple. python with tkinter for the window or generate an html file my browser can open whichever is shorter and more reliable. save the script to scripts slash slideshow dot py. save the uninstall to scripts slash slideshow underscore uninstall dot py. must work without internet no cdn libraries.

when the plan is ready emit the literal line plan ready.
```

---

## V2 — add face sorting (run AFTER V1 works)

```
Upgrade the slideshow app to sort pictures by face.

When the app first opens a folder, scan every picture for faces using a local Python face recognition library. Save the face data in a small index file inside the folder so it does not have to rescan next time.

Let me filter the slideshow to show pictures of only one face at a time, or all faces mixed.

If the face recognition library is not installed, ask me to install it before continuing. Do not silently skip face sorting.

All face data stays on my machine. Never sent anywhere.

When the plan is ready, emit the literal line PLAN READY.
```

---

## Notes for using these

- Prompts are voice-friendly — no special characters that voice-to-text mangles
- "Pictures slash Slideshow" reads cleanly aloud as `Pictures/Slideshow`
- "Scripts slash slideshow dot py" reads cleanly as `scripts/slideshow.py`
- If Sensei's plan misses something, press 4 (keep talking) to refine — that's the training mechanism per `user_training_sensei_via_option_4.md`
- The flour/template insight applies — same prompt skeleton works for any small app: `Plan [thing] for me. It should [behavior]. Default [config]. Save the script to [path]. Local first, no internet needed. When the plan is ready, emit PLAN READY.`
