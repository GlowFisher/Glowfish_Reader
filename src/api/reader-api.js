(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.reader = Object.freeze({
    open: (body) => http.post("/api/open", body),
    save: (body) => http.post("/api/save", body),
    documentMeta: (batch) => http.json(`/api/document_meta?batch=${encodeURIComponent(batch)}`),
    documentPage: (batch, pageId) => http.json(`/api/document_page?batch=${encodeURIComponent(batch)}&page_id=${encodeURIComponent(pageId)}`),
    savePage: (batch, pageId, page, baseRevision) => http.post("/api/save_page", { batch, page_id: pageId, page, base_revision: baseRevision }),
    saveDocumentMeta: (batch, changes, baseRevision) => http.post("/api/save_document_meta", { batch, changes, base_revision: baseRevision }),
    checkpoint: (batch) => http.post("/api/document_checkpoint", { batch }),
    load: (batch) => http.json(`/api/load?batch=${encodeURIComponent(batch)}`),
    notebooks: () => http.json("/api/notebooks"),
    searchRaw: (options) => http.raw("/api/document_search", options),
    noticesRaw: () => http.raw("/api/notices", { cache: "no-store" }),
    raw: http.raw
  });
})(window);
