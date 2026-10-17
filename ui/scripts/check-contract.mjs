import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const expected = readFileSync("contracts.lock", "utf8").trim();
if (!/^[0-9a-f]{40}$/.test(expected)) {
  throw new Error(`invalid contracts lock: ${expected}`);
}

const contractsRoot = process.env.GLOWFISH_CONTRACTS_ROOT;
if (contractsRoot) {
  const actual = execFileSync("git", ["-C", contractsRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  if (actual !== expected) {
    throw new Error(`contracts worktree mismatch: expected ${expected}, got ${actual}`);
  }
}
console.log(`contracts compatibility pinned at ${expected}`);
