# Master AI Interaction Standards

Status: P0 contract for controls. This file separates the two product
surfaces so controls are not invented from scratch.

## Product Surfaces

- Sensei is a terminal/TUI product. It should feel like an established
  terminal application running inside tmux and prompt_toolkit.
- Pupil is a browser/web-app product. It should feel like a normal HTML app,
  not a terminal simulation.

The common rule is not "make both terminal." The common rule is: use the
standard control grammar for the surface the user is actually in.

## Sensei Terminal Controls

Sensei must preserve terminal expectations:

- Tab completes commands or moves through command choices when a menu is open.
- Shift+Tab moves backward through command choices when a completion menu is
  open; when the input is empty, it opens the settings/mode command bucket.
- PageUp and PageDown scroll the output by a full visible page.
- Home and End jump to top and bottom of output.
- Up and Down stay command-history keys in the input.
- Mouse wheel scrolls inside Sensei only when `mouse remote` is enabled.
- `mouse local` keeps terminal drag-select/right-click copy behavior intact.
- Ctrl+Shift+C and Ctrl+Shift+V belong to the terminal emulator for copy/paste.
- Shift+Insert remains a paste fallback where the terminal supports it.
- Escape backs out of menus or dialogs; Enter activates or submits.

Sensei must not steal right-click/copy/paste by default. Local terminal copy is
more important than custom mouse capture unless the user explicitly chooses
remote/phone mouse mode.

## Pupil Browser Controls

Pupil must preserve browser expectations:

- Tab and Shift+Tab follow normal browser focus order.
- Ctrl+C, Ctrl+V, right-click, long-press selection, and touch scrolling stay
  native.
- Buttons, textareas, dialogs, and forms use normal HTML behavior.
- Focus states must be visible.
- Escape closes browser dialogs.
- Ctrl+Enter may submit chat, but Enter inside the textarea remains a newline.

Pupil must not imitate terminal copy mode, tmux scrollback, or terminal command
capture. It is a web app.

## Documentation Requirement

Whenever controls change, update all of these in the same change:

- `controls` / `shortcuts` command in Sensei
- `help` and `tips`
- Pupil Shortcuts panel
- This file

## Manual Acceptance

- Sensei: PageUp/PageDown scroll by a page; Home/End jump; Shift+Tab does not
  break input; terminal copy/paste still works in `mouse local`.
- Pupil: right-click, copy, paste, Tab, Shift+Tab, touch scroll, and browser
  focus all behave natively.
