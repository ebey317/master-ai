#!/usr/bin/env node
// Phase 6 — node unit tests for the Quick Mode single-letter parser
// (parseQuickCommand) in side_panel.js. The loop + executor side-effects
// (dispatchQuickCommand, runQuickModeLoop) need a real Chrome runtime
// and are out of scope here.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sidePanelPath = path.resolve(__dirname, "..", "side_panel.js");
const src = fs.readFileSync(sidePanelPath, "utf8");
const start = src.indexOf("const QUICK_MODE_MAX_ROUNDS");
const end = src.indexOf("async function dispatchQuickCommand");
if (start < 0 || end < 0 || end <= start) {
  console.error("FAIL: could not locate Quick Mode parser block");
  process.exit(1);
}
const chunk = src.slice(start, end) + "\nthis.PARSE = parseQuickCommand;\nthis.CAP = QUICK_MODE_MAX_ROUNDS;\n";
const ctx = {};
vm.createContext(ctx);
vm.runInContext(chunk, ctx);
const parse = ctx.PARSE;

let failures = 0;
function check(label, fn) {
  try { fn(); console.log(`ok ${label}`); }
  catch (err) { console.error(`FAIL ${label} — ${err.message}`); failures += 1; }
}
function eq(a, b, label) {
  if (a !== b) throw new Error(`expected ${JSON.stringify(b)} got ${JSON.stringify(a)} [${label}]`);
}

// C click
check("click C 300 400", () => {
  const cmd = parse("C 300 400\n<<END>>");
  eq(cmd.op, "click"); eq(cmd.x, 300); eq(cmd.y, 400);
});

check("click case-insensitive", () => {
  const cmd = parse("c 1 2\n<<END>>");
  eq(cmd.op, "click"); eq(cmd.x, 1); eq(cmd.y, 2);
});

check("click missing coordinates → null", () => {
  if (parse("C abc def\n<<END>>") !== null) throw new Error("expected null");
});

// T type
check("type text", () => {
  const cmd = parse("T hello world\n<<END>>");
  eq(cmd.op, "type"); eq(cmd.text, "hello world");
});

// K key
check("key press Enter", () => {
  const cmd = parse("K Enter\n<<END>>");
  eq(cmd.op, "key"); eq(cmd.key, "Enter");
});

// N nav
check("nav URL", () => {
  const cmd = parse("N https://example.com\n<<END>>");
  eq(cmd.op, "nav"); eq(cmd.url, "https://example.com");
});

// J js
check("js expression", () => {
  const cmd = parse("J document.title\n<<END>>");
  eq(cmd.op, "js"); eq(cmd.source, "document.title");
});

// W wait
check("wait ms", () => {
  const cmd = parse("W 500\n<<END>>");
  eq(cmd.op, "wait"); eq(cmd.ms, 500);
});

check("wait clamps to 10000 max", () => {
  const cmd = parse("W 99999\n<<END>>");
  eq(cmd.ms, 10000);
});

// ST switch tab
check("switch tab", () => {
  const cmd = parse("ST 42\n<<END>>");
  eq(cmd.op, "switch_tab"); eq(cmd.tabId, 42);
});

check("switch tab non-numeric → null", () => {
  if (parse("ST abc\n<<END>>") !== null) throw new Error("expected null");
});

// DONE
check("DONE terminator", () => {
  const cmd = parse("DONE: filled the form\n<<END>>");
  eq(cmd.op, "done"); eq(cmd.summary, "filled the form");
});

// Edge cases
check("empty reply → null", () => {
  if (parse("") !== null) throw new Error("expected null on empty");
  if (parse(null) !== null) throw new Error("expected null on null");
});

check("unknown command → null", () => {
  if (parse("XYZ unsupported\n<<END>>") !== null) throw new Error("expected null");
});

check("strips after <<END>>", () => {
  const cmd = parse("C 10 20\n<<END>>\nC 999 999\n<<END>>");
  eq(cmd.x, 10); eq(cmd.y, 20);
});

check("ignores blank lines before command", () => {
  const cmd = parse("\n\nT hello\n<<END>>");
  eq(cmd.op, "type"); eq(cmd.text, "hello");
});

if (failures) {
  console.error(`---\n${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("---\nall Quick Mode parser assertions PASS");
