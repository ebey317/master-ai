#!/usr/bin/env node
// Phase 3.2 — node-based unit tests for _parseCdpKeyTarget and _keyToCode
// in side_panel.js. Covers shorthand and JSON parsing plus the key-to-code
// fallback.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sidePanelPath = path.resolve(__dirname, "..", "side_panel.js");
const src = fs.readFileSync(sidePanelPath, "utf8");
const start = src.indexOf("function _keyToCode");
const end = src.indexOf("async function dispatchCdpKey");
if (start < 0 || end < 0 || end <= start) {
  console.error("FAIL: could not locate CDP key helper block in side_panel.js");
  process.exit(1);
}
const chunk = src.slice(start, end) + "\nthis.PARSE = _parseCdpKeyTarget;\nthis.K2C = _keyToCode;\n";
const ctx = {};
vm.createContext(ctx);
vm.runInContext(chunk, ctx);
const parse = ctx.PARSE;
const k2c = ctx.K2C;

let failures = 0;
function check(label, fn) {
  try { fn(); console.log(`ok ${label}`); }
  catch (err) { console.error(`FAIL ${label} — ${err.message}`); failures += 1; }
}
function eq(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`expected ${JSON.stringify(expected)} got ${JSON.stringify(actual)} [${label}]`);
  }
}

// _keyToCode
check("k2c letter", () => eq(k2c("a"), "KeyA"));
check("k2c letter upper", () => eq(k2c("A"), "KeyA"));
check("k2c digit", () => eq(k2c("5"), "Digit5"));
check("k2c Enter", () => eq(k2c("Enter"), "Enter"));
check("k2c Tab", () => eq(k2c("Tab"), "Tab"));
check("k2c ArrowUp", () => eq(k2c("ArrowUp"), "ArrowUp"));
check("k2c F5", () => eq(k2c("F5"), "F5"));
check("k2c space char", () => eq(k2c(" "), "Space"));
check("k2c Space word", () => eq(k2c("Space"), "Space"));
check("k2c passes through unknown", () => eq(k2c("OemPlus"), "OemPlus"));

// _parseCdpKeyTarget — shorthand
check("type shorthand single word", () => {
  const out = parse("type hello");
  eq(out.action, "type", "action"); eq(out.text, "hello", "text");
});

check("type shorthand multi-word with spaces preserved", () => {
  const out = parse("type hello world  with   spaces");
  eq(out.text, "hello world  with   spaces", "text preserves internal whitespace");
});

check("press Enter", () => {
  const out = parse("press Enter");
  eq(out.action, "press", "action"); eq(out.key, "Enter", "key"); eq(out.modifiers, 0, "modifiers default");
});

check("press with modifiers", () => {
  const out = parse("press s 2");
  eq(out.key, "s", "key"); eq(out.modifiers, 2, "modifiers ctrl");
});

check("down shorthand", () => {
  const out = parse("down Shift 0");
  eq(out.action, "down", "action"); eq(out.key, "Shift", "key");
});

check("up shorthand", () => {
  const out = parse("up Shift 0");
  eq(out.action, "up", "action");
});

// _parseCdpKeyTarget — JSON
check("JSON press", () => {
  const out = parse('{"action":"press","key":"Enter","modifiers":4}');
  eq(out.action, "press", "action"); eq(out.key, "Enter", "key"); eq(out.modifiers, 4, "modifiers");
});

check("JSON type", () => {
  const out = parse('{"action":"type","text":"hello"}');
  eq(out.action, "type", "action"); eq(out.text, "hello", "text");
});

check("JSON with code override", () => {
  const out = parse('{"action":"press","key":"Enter","code":"NumpadEnter"}');
  eq(out.code, "NumpadEnter", "code passthrough");
});

// edge cases
check("empty target → null", () => {
  if (parse("") !== null) throw new Error("expected null");
});

check("single word → null", () => {
  if (parse("press") !== null) throw new Error("expected null for press with no key");
});

check("malformed JSON falls through", () => {
  const out = parse("{action:bad}"); // not valid JSON
  // No "<verb> <rest>" pattern matches → null.
  if (out !== null) throw new Error("expected null");
});

if (failures) {
  console.error(`---\n${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("---\nall CDP key parser assertions PASS");
