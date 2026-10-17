import assert from "node:assert/strict";
import { readFile, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("build manifest is deterministic and contains API clients", async () => {
  const outA = path.join(root, "dist-test-a");
  const outB = path.join(root, "dist-test-b");
  try {
    for (const output of [outA, outB]) {
      const run = spawnSync(process.execPath, [path.join(root, "scripts", "build.mjs"), "--out", output], { encoding: "utf8" });
      assert.equal(run.status, 0, run.stderr);
    }
    const manifestA = await readFile(path.join(outA, "manifest.json"), "utf8");
    const manifestB = await readFile(path.join(outB, "manifest.json"), "utf8");
    assert.equal(manifestA, manifestB);
    const paths = JSON.parse(manifestA).files.map((item) => item.path);
    for (const expected of ["api/http.js", "api/reader-api.js", "api/ocr-api.js", "api/export-api.js"]) {
      assert(paths.includes(expected));
    }
  } finally {
    await rm(outA, { recursive: true, force: true });
    await rm(outB, { recursive: true, force: true });
  }
});
