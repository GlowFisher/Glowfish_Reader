import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

const root = path.resolve(import.meta.dirname, "..");

async function loadPageSession() {
  const source = await readFile(path.join(root, "src", "page-session.js"), "utf8");
  const window = {};
  vm.runInNewContext(source, { window, Map, Set });
  return window.GlowfishPageSession;
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

for (const pageCount of [46, 100, 500, 2000]) {
  test(`page session remains bounded for ${pageCount} pages`, async () => {
    const PageSession = await loadPageSession();
    const saves = [];
    const descriptors = Array.from({ length: pageCount }, (_, index) => ({
      page_id: `page-${index + 1}`,
      width: 1200,
      height: 1800,
      revision: 0,
    }));
    const api = {
      documentMeta: async (batch) => ({ batch, revision: 0, pages: descriptors }),
      documentPage: async (_batch, pageId) => ({
        page: { page_id: pageId, lines: [{ id: `${pageId}-line`, text: `body ${pageId}` }], order: [`${pageId}-line`] },
        revision: 0,
      }),
      savePage: async (batch, pageId, page, revision) => {
        saves.push({ batch, pageId, page, revision });
        return { revision: revision + 1 };
      },
    };
    const session = new PageSession(api);

    await session.open("large document", 0);
    await settle();
    assert.equal(session.pageCache.size <= 3, true);
    assert.equal(JSON.stringify(session.documentMeta).includes("body page"), false);

    const indexes = [1, 2, Math.floor(pageCount / 2), pageCount - 2, pageCount - 1];
    for (const index of indexes) {
      await session.goto(index);
      await settle();
      assert.equal(session.pageCache.size <= 3, true);
    }
    assert.equal(saves.length, 0, "clean navigation must not save pages");

    const currentId = session.currentId();
    session.markDirty();
    await session.goto(Math.max(0, session.pageIdx - 1));
    await settle();
    assert.equal(saves.length, 1);
    assert.equal(saves[0].pageId, currentId);
    assert.equal(session.pageCache.size <= 3, true);
  });
}
