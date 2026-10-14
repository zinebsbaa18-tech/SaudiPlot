// Compare an ESLint JSON report against the approved frozen-frontend
// baseline. The frozen UI may not be modified, so its 13 known errors are
// accepted; any NEW error (new rule, new file, or higher count) fails.
//
// Usage: node check-lint-baseline.mjs <eslint-report.json> <baseline.json>
import { readFileSync } from "node:fs";
import { relative, sep } from "node:path";

const [reportPath, baselinePath] = process.argv.slice(2);
if (!reportPath || !baselinePath) {
  console.error("usage: node check-lint-baseline.mjs <eslint-report.json> <baseline.json>");
  process.exit(2);
}

const report = JSON.parse(readFileSync(reportPath, "utf8"));
const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));

// Key errors by frontend-relative path + rule id, count occurrences.
const counts = new Map();
for (const result of report) {
  const rel = relative(process.cwd(), result.filePath).split(sep).join("/");
  for (const message of result.messages) {
    if (message.severity !== 2) continue;
    const key = `${rel}|${message.ruleId ?? "parse-error"}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
}

let failed = false;
for (const [key, count] of counts) {
  const allowed = baseline[key] ?? 0;
  if (count > allowed) {
    failed = true;
    console.error(`NEW lint error(s): ${key} — ${count} found, baseline allows ${allowed}`);
  }
}
for (const [key, allowed] of Object.entries(baseline)) {
  if ((counts.get(key) ?? 0) < allowed) {
    console.log(`note: baseline entry no longer fully present (can be tightened): ${key}`);
  }
}

if (failed) {
  console.error("\nLint failed: errors beyond the approved frozen-frontend baseline.");
  process.exit(1);
}
console.log(`Lint OK: ${[...counts.values()].reduce((a, b) => a + b, 0)} error(s), all within the approved baseline.`);
