import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("background exports remain cancellable and download only completed results", async () => {
  const app = await readFile(path.join(root, "src", "app.js"), "utf8");
  assert.match(app, /response\.status !== 202/);
  assert.match(app, /gfWatchDocumentTask\(task\.job_id/);
  assert.match(app, /cancelTask\(task\.job_id\)/);
  assert.match(app, /taskResultUrl\(task\.job_id\)/);
  assert.match(app, /status\.state === "cancelled"/);
  assert.match(app, /status\.state !== "done"/);
});
