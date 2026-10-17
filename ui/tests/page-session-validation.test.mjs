import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

const root = path.resolve(import.meta.dirname, "..");

async function PageSession() {
  const source = await readFile(path.join(root, "src", "page-session.js"), "utf8");
  const window = {};
  vm.runInNewContext(source, { window, Map, Set });
  return window.GlowfishPageSession;
}

function apiWith(pageFactory) {
  return {
    documentMeta: async () => ({
      batch: "book",
      pages: [{ page_id: "page-1" }, { page_id: "page-2" }],
    }),
    documentPage: async (_batch, pageId) => ({
      page: pageFactory(pageId),
      revision: 0,
    }),
    savePage: async () => ({ revision: 1 }),
  };
}

test("valid text and valid blank pages both load", async () => {
  const Session = await PageSession();
  const session = new Session(apiWith((pageId) => pageId === "page-1"
    ? { page_id: pageId, lines: [{ id: "line-1", text: "body" }], order: ["line-1"] }
    : { page_id: pageId, lines: [], order: [] }));

  const first = await session.open("book", 0);
  const blank = await session.goto(1);
  assert.equal(first.page.lines[0].text, "body");
  assert.deepEqual(blank.page.lines, []);
  assert.deepEqual(blank.page.order, []);
});

for (const [name, factory, message] of [
  ["missing page", () => undefined, /缺少 page 对象/],
  ["mismatched page id", () => ({ page_id: "other", lines: [], order: [] }), /页面标识不匹配/],
  ["missing lines", (pageId) => ({ page_id: pageId, order: [] }), /缺少 lines 数组/],
  ["missing order", (pageId) => ({ page_id: pageId, lines: [] }), /缺少 order 数组/],
]) {
  test(`${name} is rejected before caching`, async () => {
    const Session = await PageSession();
    const session = new Session(apiWith(factory));
    await assert.rejects(session.open("book", 0), message);
    assert.equal(session.pageCache.size, 0);
  });
}

test("invalid next page rolls back and can be retried", async () => {
  const Session = await PageSession();
  let invalid = true;
  const session = new Session(apiWith((pageId) => {
    if (pageId === "page-2" && invalid) return { page_id: pageId, lines: [] };
    return { page_id: pageId, lines: [], order: [] };
  }));

  await session.open("book", 0);
  await assert.rejects(session.goto(1), /缺少 order 数组/);
  assert.equal(session.pageIdx, 0);
  assert.equal(session.currentId(), "page-1");
  assert.equal(session.pageCache.has("page-2"), false);

  invalid = false;
  const recovered = await session.goto(1);
  assert.equal(recovered.page.page_id, "page-2");
  assert.equal(session.pageIdx, 1);
});
