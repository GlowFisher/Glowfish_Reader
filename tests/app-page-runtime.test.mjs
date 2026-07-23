import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

const root = path.resolve(import.meta.dirname, "..");
const settle = () => new Promise((resolve) => setImmediate(resolve));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function loadRuntime(hooks = {}) {
  const source = await readFile(path.join(root, "src", "app-page-runtime.js"), "utf8");
  const controls = new Map();
  const bindings = new Map();
  for (const id of ["prevPage", "nextPage", "scriptBtn", "saveBtn", "canvasNav", "layoutBtn", "hist", "statPage", "statDelta"]) {
    controls.set(id, { disabled: false, classList: { remove() {} } });
  }
  const context = {
    console,
    Date,
    Set,
    GlowfishApi: { reader: {} },
    settings: {},
    lowConf: 0,
    proof: null,
    pageIdx: 0,
    batch: null,
    imgVer: 0,
    undoStack: [],
    redoStack: [],
    currentLayout: "horizontal",
    proofMode: "page",
    renderCount: 0,
    document: {
      body: { classList: { toggle() {} } },
      querySelector(selector) { return controls.get(selector.slice(1)) || null; },
    },
    $() { return { textContent: "" }; },
    updateHist() {},
    updateScriptBtn() {},
    syncLayoutButtons() {},
    syncProofModeButtons() {},
    render() { context.renderCount++; },
    toast() {},
    bindClick(id, handler) { bindings.set(id, handler); return controls.get(id); },
  };
  context.GlowfishPageSession = class {
    constructor() {
      this.activeBatch = null;
      this.pageIdx = 0;
      this.documentMeta = null;
    }
    async open(batchName, requestedPage) {
      this.activeBatch = batchName;
      this.pageIdx = requestedPage;
      this.documentMeta = {
        batch: batchName,
        pages: [{ page_id: `${batchName}-1` }, { page_id: `${batchName}-2` }],
      };
      if (hooks.open) return hooks.open(this, batchName, requestedPage);
      const pageId = `${batchName}-${requestedPage + 1}`;
      return { page: { page_id: pageId, lines: [{ id: `${pageId}-line`, text: pageId }], order: [`${pageId}-line`] } };
    }
    async goto(index) {
      if (hooks.goto) return hooks.goto(this, index);
      this.pageIdx = index;
      const pageId = `${this.activeBatch}-${index + 1}`;
      return { page: { page_id: pageId, lines: [{ id: `${pageId}-line`, text: pageId }], order: [`${pageId}-line`] } };
    }
    markDirty() {}
    async flushAll() {}
  };
  vm.createContext(context);
  vm.runInContext(
    `${source}\nglobalThis.__runtime = { gfOpenPagedDocument, applyLoaded, _gfMovePage, pageNext, pagePrev, toggleScript, session: () => gfPageSession };`,
    context,
  );
  return { context, controls, bindings, runtime: context.__runtime };
}

test("document open stays busy until the first page is activated and rendered", async () => {
  const firstPage = deferred();
  const { context, controls, runtime } = await loadRuntime({
    open: () => firstPage.promise,
  });

  const opening = runtime.applyLoaded({ batch: "new-document" });
  assert.equal(controls.get("nextPage").disabled, true);
  assert.equal(context.renderCount, 0);

  firstPage.resolve({ page: { page_id: "new-document-1" } });
  assert.equal(await opening, true);
  assert.equal(context.renderCount, 1);
  assert.equal(context.batch, "new-document");
  assert.equal(controls.get("nextPage").disabled, false);
});

test("repeated navigation is ignored while one page request is active", async () => {
  const move = deferred();
  let gotoCalls = 0;
  const { context, controls, runtime } = await loadRuntime({
    goto: (session, index) => {
      gotoCalls++;
      return move.promise.then((item) => {
        session.pageIdx = index;
        return item;
      });
    },
  });
  await runtime.gfOpenPagedDocument("book");

  const first = runtime._gfMovePage(1);
  const repeated = runtime._gfMovePage(1);
  assert.equal(await repeated, false);
  assert.equal(gotoCalls, 1);
  assert.equal(controls.get("nextPage").disabled, true);

  move.resolve({ page: { page_id: "book-2" } });
  assert.equal(await first, true);
  assert.equal(context.pageIdx, 1);
  assert.equal(context.renderCount, 2);
  assert.equal(controls.get("nextPage").disabled, false);
});

test("an old page response cannot overwrite a newly opened document", async () => {
  const oldMove = deferred();
  const { context, runtime } = await loadRuntime({
    goto: (session, index) => oldMove.promise.then((item) => {
      session.pageIdx = index;
      return item;
    }),
  });
  await runtime.gfOpenPagedDocument("old");
  const moving = runtime._gfMovePage(1);
  await settle();

  assert.equal(await runtime.gfOpenPagedDocument("new"), true);
  oldMove.resolve({ page: { page_id: "old-2" } });
  assert.equal(await moving, false);
  assert.equal(context.batch, "new");
  assert.equal(context.proof.pages[0].page_id, "new-1");
  assert.equal(context.renderCount, 2);
});


test("runtime owns the paging and script button handlers", async () => {
  let gotoCalls = 0;
  const { bindings, context, runtime } = await loadRuntime({
    goto: (session, index) => {
      gotoCalls++;
      session.pageIdx = index;
      const pageId = `${session.activeBatch}-${index + 1}`;
      return { page: { page_id: pageId, lines: [{ id: `${pageId}-line`, text: "loaded body" }], order: [`${pageId}-line`] } };
    },
  });

  assert.equal(bindings.get("prevPage"), runtime.pagePrev);
  assert.equal(bindings.get("nextPage"), runtime.pageNext);
  assert.equal(bindings.get("scriptBtn"), runtime.toggleScript);

  await runtime.gfOpenPagedDocument("book");
  assert.equal(await bindings.get("nextPage")(), true);
  assert.equal(gotoCalls, 1);
  assert.equal(context.pageIdx, 1);
  assert.deepEqual(context.proof.pages[1].order, ["book-2-line"]);
  assert.equal(context.proof.pages[1].lines[0].text, "loaded body");
});
