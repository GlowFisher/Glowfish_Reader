/* Bounded client-side document session. Page bodies never exceed three cached entries. */
(function (global) {
  "use strict";

  class PageSession {
    constructor(api) {
      this.api = api;
      this.documentMeta = null;
      this.activeBatch = null;
      this.pageIdx = 0;
      this.pageCache = new Map();
      this.dirtyPages = new Set();
    }

    async open(batch, pageIdx = 0) {
      const meta = await this.api.documentMeta(batch);
      this.activeBatch = batch;
      this.documentMeta = meta;
      this.pageIdx = Math.max(0, Math.min(pageIdx, Math.max(0, meta.pages.length - 1)));
      this.pageCache.clear();
      this.dirtyPages.clear();
      return this.goto(this.pageIdx);
    }

    currentId() {
      return this.documentMeta && this.documentMeta.pages[this.pageIdx] && this.documentMeta.pages[this.pageIdx].page_id;
    }

    _validatedPageItem(loaded, pageId) {
      const fail = (detail) => {
        throw new Error(`页面数据结构不完整：${pageId} ${detail}`);
      };
      if (!loaded || typeof loaded !== "object" || !loaded.page || typeof loaded.page !== "object")
        fail("缺少 page 对象");
      if (String(loaded.page.page_id || "") !== String(pageId))
        fail("页面标识不匹配");
      if (!Array.isArray(loaded.page.lines))
        fail("缺少 lines 数组");
      if (!Array.isArray(loaded.page.order))
        fail("缺少 order 数组");
      return { page: loaded.page, revision: loaded.revision };
    }

    async page(pageId) {
      if (this.pageCache.has(pageId)) return this.pageCache.get(pageId);
      const loaded = await this.api.documentPage(this.activeBatch, pageId);
      const item = this._validatedPageItem(loaded, pageId);
      this.pageCache.set(pageId, item);
      this._evict();
      return item;
    }

    async goto(index) {
      await this.flushCurrent();
      const previousIndex = this.pageIdx;
      this.pageIdx = Math.max(0, Math.min(index, this.documentMeta.pages.length - 1));
      let current;
      try {
        current = await this.page(this.currentId());
      } catch (error) {
        this.pageIdx = previousIndex;
        throw error;
      }
      this._prefetchAdjacent();
      return current;
    }

    markDirty(pageId = this.currentId()) { if (pageId) this.dirtyPages.add(pageId); }

    async flushCurrent() {
      const pageId = this.currentId();
      if (pageId) await this.flush(pageId);
    }

    async flush(pageId) {
      if (!this.dirtyPages.has(pageId)) return;
      const item = this.pageCache.get(pageId);
      if (!item) return;
      const saved = await this.api.savePage(this.activeBatch, pageId, item.page, item.revision);
      item.revision = saved.revision;
      this.dirtyPages.delete(pageId);
    }

    async flushAll() { for (const pageId of [...this.dirtyPages]) await this.flush(pageId); }

    _prefetchAdjacent() {
      for (const index of [this.pageIdx - 1, this.pageIdx + 1]) {
        const descriptor = this.documentMeta.pages[index];
        if (descriptor && !this.pageCache.has(descriptor.page_id)) this.page(descriptor.page_id).catch(() => {});
      }
    }

    _evict() {
      const keep = new Set([this.pageIdx - 1, this.pageIdx, this.pageIdx + 1]
        .map(i => this.documentMeta.pages[i]).filter(Boolean).map(p => p.page_id));
      for (const pageId of this.pageCache.keys()) {
        if (this.pageCache.size <= 3) break;
        if (!keep.has(pageId) && !this.dirtyPages.has(pageId)) this.pageCache.delete(pageId);
      }
    }
  }

  global.GlowfishPageSession = PageSession;
})(window);
