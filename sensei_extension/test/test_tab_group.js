#!/usr/bin/env node
// Phase 4.1 — node-based unit tests for the TabGroupManager helpers in
// side_panel.js. Covers tabGroupColorForMode mapping and the
// SESSION_TAB_GROUP_TITLE constant. The async network-y helpers
// (restoreSessionTabGroup / addTabToSessionGroup) are integration-tested
// when a real Chrome runtime is available — out of scope here.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sidePanelPath = path.resolve(__dirname, "..", "side_panel.js");
const src = fs.readFileSync(sidePanelPath, "utf8");
const start = src.indexOf("const SESSION_TAB_GROUP_TITLE");
const end = src.indexOf("async function restoreSessionTabGroup");
if (start < 0 || end < 0 || end <= start) {
  console.error("FAIL: could not locate TabGroupManager helper block");
  process.exit(1);
}
const chunk = src.slice(start, end) +
  "\nthis.TITLE = SESSION_TAB_GROUP_TITLE;\nthis.COLOR_FOR_MODE = tabGroupColorForMode;\n";
const ctx = {};
vm.createContext(ctx);
vm.runInContext(chunk, ctx);
const colorForMode = ctx.COLOR_FOR_MODE;
const title = ctx.TITLE;

let failures = 0;
function check(label, fn) {
  try { fn(); console.log(`ok ${label}`); }
  catch (err) { console.error(`FAIL ${label} — ${err.message}`); failures += 1; }
}
function eq(a, b, label) {
  if (a !== b) throw new Error(`expected ${JSON.stringify(b)} got ${JSON.stringify(a)} [${label}]`);
}

// Tab-group color mapping matches the stoplight per feedback_mode_stoplight_colors.md.
check("plan → red", () => eq(colorForMode("plan"), "red"));
check("review → orange", () => eq(colorForMode("review"), "orange"));
check("auto → green", () => eq(colorForMode("auto"), "green"));
check("case-insensitive", () => {
  eq(colorForMode("PLAN"), "red");
  eq(colorForMode("Review"), "orange");
  eq(colorForMode("Auto"), "green");
});
check("unknown mode → blue fallback", () => {
  eq(colorForMode("safe"), "blue");  // SAFE was retired but exercising the fallback
  eq(colorForMode(""), "blue");
  eq(colorForMode(null), "blue");
  eq(colorForMode(undefined), "blue");
});

// The title is the stable label so users recognize Sensei's group.
check("title is 'Sensei'", () => eq(title, "Sensei"));

if (failures) {
  console.error(`---\n${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("---\nall TabGroupManager assertions PASS");
