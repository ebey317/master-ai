#!/usr/bin/env node
// Phase 3.1 — node-based unit tests for _parseCdpMouseTarget in side_panel.js.
// Verifies JSON-form parsing, shorthand parsing, and edge cases. Does NOT
// exercise dispatchCdpMouse against a real tab (that needs the Chrome
// headless harness — same shape as test_chrome_headless_e2e.py).

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sidePanelPath = path.resolve(__dirname, "..", "side_panel.js");
const src = fs.readFileSync(sidePanelPath, "utf8");
const start = src.indexOf("const _CDP_BUTTON_NAMES");
const end = src.indexOf("async function dispatchCdpMouse");
if (start < 0 || end < 0 || end <= start) {
  console.error("FAIL: could not locate CDP mouse helper block in side_panel.js");
  process.exit(1);
}
const chunk = src.slice(start, end) + "\nthis.PARSE = _parseCdpMouseTarget;\n";

const ctx = {};
vm.createContext(ctx);
vm.runInContext(chunk, ctx);
const parse = ctx.PARSE;

let failures = 0;
function check(label, fn) {
  try {
    fn();
    console.log(`ok ${label}`);
  } catch (err) {
    console.error(`FAIL ${label} — ${err.message}`);
    failures += 1;
  }
}
function eq(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`expected ${JSON.stringify(expected)} got ${JSON.stringify(actual)} [${label}]`);
  }
}

check("JSON click", () => {
  const out = parse('{"action":"click","x":300,"y":400}');
  eq(out.action, "click", "action"); eq(out.x, 300, "x"); eq(out.y, 400, "y");
});

check("JSON wheel with delta", () => {
  const out = parse('{"action":"wheel","x":0,"y":0,"deltaX":50,"deltaY":-100}');
  eq(out.action, "wheel", "action"); eq(out.deltaX, 50, "deltaX"); eq(out.deltaY, -100, "deltaY");
});

check("JSON right click with modifiers", () => {
  const out = parse('{"action":"click","x":50,"y":50,"button":"right","modifiers":4}');
  eq(out.button, "right", "button"); eq(out.modifiers, 4, "modifiers");
});

check("shorthand click", () => {
  const out = parse("click 300 400");
  eq(out.action, "click", "action"); eq(out.x, 300, "x"); eq(out.y, 400, "y");
});

check("shorthand click with button", () => {
  const out = parse("click 300 400 right");
  eq(out.button, "right", "button");
});

check("shorthand click with count and modifiers", () => {
  const out = parse("click 10 20 left 2 8");
  eq(out.button, "left", "button"); eq(out.clickCount, 2, "count"); eq(out.modifiers, 8, "modifiers");
});

check("shorthand wheel", () => {
  const out = parse("wheel 100 200 50 -75");
  eq(out.action, "wheel", "action"); eq(out.x, 100, "x"); eq(out.y, 200, "y");
  eq(out.deltaX, 50, "deltaX"); eq(out.deltaY, -75, "deltaY");
});

check("shorthand move", () => {
  const out = parse("move 50 60");
  eq(out.action, "move", "action"); eq(out.x, 50, "x"); eq(out.y, 60, "y");
});

check("empty target → null", () => {
  if (parse("") !== null) throw new Error("expected null");
  if (parse(null) !== null) throw new Error("expected null on null");
});

check("non-numeric x/y → null", () => {
  if (parse("click abc def") !== null) throw new Error("expected null for non-numeric");
});

check("too few parts → null", () => {
  if (parse("click 100") !== null) throw new Error("expected null for missing y");
});

check("invalid button name ignored", () => {
  const out = parse("click 1 2 not-a-button 1 0");
  // button stays undefined; positional parser only sets it when name matches.
  eq(out.button, undefined, "button");
});

check("malformed JSON falls through to positional", () => {
  const out = parse("{action:click}"); // not valid JSON
  // No three positional parts → null.
  if (out !== null) throw new Error("expected null");
});

check("JSON with stray fields preserved", () => {
  const out = parse('{"action":"press","x":10,"y":20,"custom":"x"}');
  eq(out.action, "press", "action"); eq(out.custom, "x", "custom passthrough");
});

// Phase 3.3 — drag composite parsing.
check("shorthand drag", () => {
  const out = parse("drag 10 20 100 200");
  eq(out.action, "drag", "action");
  eq(out.x, 10, "x"); eq(out.y, 20, "y");
  eq(out.toX, 100, "toX"); eq(out.toY, 200, "toY");
});

check("shorthand drag with button + modifiers", () => {
  const out = parse("drag 0 0 50 50 right 8");
  eq(out.button, "right", "button");
  eq(out.modifiers, 8, "modifiers");
});

check("shorthand drag missing toX/toY → null", () => {
  if (parse("drag 10 20 abc def") !== null) throw new Error("expected null for non-numeric toX/toY");
  if (parse("drag 10 20") !== null) throw new Error("expected null for missing toX/toY");
});

check("JSON drag", () => {
  const out = parse('{"action":"drag","x":0,"y":0,"toX":100,"toY":50}');
  eq(out.action, "drag", "action"); eq(out.toX, 100, "toX"); eq(out.toY, 50, "toY");
});

if (failures) {
  console.error(`---\n${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("---\nall CDP mouse parser assertions PASS");
