import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

const root = path.resolve(import.meta.dirname, "..");

test("failed page load preserves the previously active page", async () => {
  const source = await readFile(path.join(root, "src", "page-session.js"), "utf8");
  const window = {};
  vm.runInNewContext(source, { window, Map, Set });
  const PageSession = window.GlowfishPageSession;
  const api = {
    documentMeta: async () => ({
      batch: "book",
      pages: [{ page_id: "page-1" }, { page_id: "page-2" }],
    }),
    documentPage: async (_batch, pageId) => {
      if (pageId === "page-2") throw new Error("page unavailable");
      return { page: { page_id: pageId, lines: [], order: [] }, revision: 0 };
    },
    savePage: async () => ({ revision: 1 }),
  };
  const session = new PageSession(api);

  await session.open("book", 0);
  await assert.rejects(session.goto(1), /page unavailable/);
  assert.equal(session.pageIdx, 0);
  assert.equal(session.currentId(), "page-1");
});
