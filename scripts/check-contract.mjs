import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const expected = readFileSync("contracts.lock", "utf8").trim();
const line = execFileSync("git", ["ls-files", "--stage", "components/contracts"], { encoding: "utf8" }).trim();
const actual = line.split(/\s+/)[1];
if (!/^[0-9a-f]{40}$/.test(expected) || actual !== expected) {
  throw new Error(`contracts gitlink mismatch: expected ${expected}, got ${actual}`);
}
console.log(`contracts pinned at ${actual}`);
