#!/usr/bin/env node
// Phase 1.2 — node-based unit tests for the PermissionManager taxonomy in
// side_panel.js. Extracts the PermissionManager block from the source, runs
// it in a sandbox with a minimal state stub, and asserts the 8-type +
// 2-duration mapping for each BROWSER_* kind we care about.
//
// Run: node sensei_extension/test/test_permission_manager.js
// Exit: 0 = all green, 1 = at least one assertion failed.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sidePanelPath = path.resolve(__dirname, "..", "side_panel.js");
const src = fs.readFileSync(sidePanelPath, "utf8");
const start = src.indexOf("const PermissionType = Object.freeze");
const end = src.indexOf("async function rememberPermission");
if (start < 0 || end < 0 || end <= start) {
  console.error("FAIL: could not locate PermissionManager block in side_panel.js");
  process.exit(1);
}
const chunk = src.slice(start, end) +
  "\nthis.PM = PermissionManager;\nthis.PT = PermissionType;\nthis.PD = PermissionDuration;\n";

const ctx = {
  state: { config: { approvedOrigins: ["https://github.com"] } },
  URL,
};
vm.createContext(ctx);
vm.runInContext(chunk, ctx);
const PM = ctx.PM, PT = ctx.PT, PD = ctx.PD;

let failures = 0;
function eq(actual, expected, label) {
  if (actual !== expected) {
    console.error(`FAIL ${label} — expected ${JSON.stringify(expected)} got ${JSON.stringify(actual)}`);
    failures += 1;
    return;
  }
  console.log(`ok ${label}`);
}

// typeFor: each BROWSER_* kind maps to the expected permission type.
eq(PM.typeFor({kind:"BROWSER_NAV", target:"https://example.com"}, "https://example.com"), PT.NAVIGATE, "NAV same-origin → NAVIGATE");
eq(PM.typeFor({kind:"BROWSER_NAV", target:"https://other.com"}, "https://example.com"), PT.DOMAIN_TRANSITION, "NAV cross-origin → DOMAIN_TRANSITION");
eq(PM.typeFor({kind:"BROWSER_NAV", target:"bareword"}, "https://example.com"), PT.NAVIGATE, "NAV bareword target → NAVIGATE");
eq(PM.typeFor({kind:"BROWSER_TAB_CREATE", target:"https://example.com"}, "https://example.com"), PT.NAVIGATE, "TAB_CREATE same-origin → NAVIGATE");
eq(PM.typeFor({kind:"BROWSER_TAB_CREATE", target:"https://other.com"}, "https://example.com"), PT.DOMAIN_TRANSITION, "TAB_CREATE cross-origin → DOMAIN_TRANSITION");
eq(PM.typeFor({kind:"BROWSER_READ_PAGE"}, ""), PT.READ_PAGE_CONTENT, "READ_PAGE → READ_PAGE_CONTENT");
eq(PM.typeFor({kind:"BROWSER_OBSERVE"}, ""), PT.READ_PAGE_CONTENT, "OBSERVE → READ_PAGE_CONTENT");
eq(PM.typeFor({kind:"BROWSER_READ", target:"#main"}, ""), PT.READ_PAGE_CONTENT, "READ region → READ_PAGE_CONTENT");
eq(PM.typeFor({kind:"BROWSER_CLICK", target:"#submit"}, ""), PT.CLICK, "CLICK → CLICK");
eq(PM.typeFor({kind:"BROWSER_DOUBLE_CLICK", target:".row"}, ""), PT.CLICK, "DOUBLE_CLICK → CLICK");
eq(PM.typeFor({kind:"BROWSER_SCROLL", target:"down"}, ""), PT.CLICK, "SCROLL → CLICK");
eq(PM.typeFor({kind:"BROWSER_DRIVE_INSPECT_FOLDER"}, ""), PT.CLICK, "DRIVE_INSPECT → CLICK");
eq(PM.typeFor({kind:"BROWSER_CDP_MOUSE", target:"click 300 400"}, ""), PT.CLICK, "CDP_MOUSE → CLICK");
eq(PM.typeFor({kind:"BROWSER_CDP_KEY", target:"press Enter"}, ""), PT.TYPE, "CDP_KEY → TYPE");
eq(PM.typeFor({kind:"BROWSER_FILL", target:"#name :: Elijah"}, ""), PT.TYPE, "FILL text → TYPE");
eq(PM.typeFor({kind:"BROWSER_FILL", target:"#r :: file:///home/x.pdf"}, ""), PT.UPLOAD_IMAGE, "FILL file:// → UPLOAD_IMAGE");
eq(PM.typeFor({kind:"BROWSER_FILL", target:"#r", file_payload:{}}, ""), PT.UPLOAD_IMAGE, "FILL with payload → UPLOAD_IMAGE");
eq(PM.typeFor({kind:"BROWSER_SCREENSHOT"}, ""), PT.READ_PAGE_CONTENT, "SCREENSHOT → READ_PAGE_CONTENT");
eq(PM.typeFor({kind:"NON_BROWSER_THING"}, ""), null, "non-browser action → null");

// durationFor: existing string decisions map onto once|always.
eq(PM.durationFor("always_allow_site"), PD.ALWAYS, "decision always_allow_site → always");
eq(PM.durationFor("allow_once"), PD.ONCE, "decision allow_once → once");
eq(PM.durationFor("auto"), PD.ONCE, "decision auto → once");
eq(PM.durationFor("unknown"), PD.ONCE, "decision unknown → once (safe default)");

// isGranted: reflects state.config.approvedOrigins membership.
eq(PM.isGranted({kind:"BROWSER_CLICK"}, "https://github.com"), true, "approved origin → granted");
eq(PM.isGranted({kind:"BROWSER_CLICK"}, "https://other.com"), false, "non-approved origin → not granted");
eq(PM.isGranted({kind:"BROWSER_CLICK"}, ""), false, "empty origin → not granted");

// envelopeFor: full audit shape.
const env = PM.envelopeFor({kind:"BROWSER_CLICK", target:"#x"}, "https://github.com", "allow_once");
eq(env.permission_type, PT.CLICK, "envelope.permission_type");
eq(env.permission_duration, PD.ONCE, "envelope.permission_duration");
eq(env.permission_decision, "allow_once", "envelope.permission_decision");
eq(env.origin, "https://github.com", "envelope.origin");

if (failures) {
  console.error(`---\n${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("---\nall PermissionManager assertions PASS");
