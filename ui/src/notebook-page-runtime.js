"use strict";
/* Open notebook documents through metadata + current page, never /api/load. */
async function nbOpenDocOnce(id, gotoLast) {
  try {
    await gfOpenPagedDocument(id, gotoLast ? Number.MAX_SAFE_INTEGER : 0);
  } catch (error) {
    toast("打开失败：" + error.message);
  }
}
/* Notebook page pickers only need descriptors. Never revive a full proof cache. */
nbEnsureExportPages = async function (docId) {
  if (nbExportPageCache[docId]) return nbExportPageCache[docId];
  if (nbExportLoadingDocs[docId]) return nbExportLoadingDocs[docId];
  const task = GlowfishApi.reader.documentMeta(docId).then((meta) => {
    const pages = (meta.pages || []).map((pg, index) => ({
      page_id: pg.page_id,
      label: nbExportPageLabel(pg, index)
    }));
    nbExportPageCache[docId] = pages;
    return pages;
  }).finally(() => { delete nbExportLoadingDocs[docId]; });
  nbExportLoadingDocs[docId] = task;
  return task;
};

/* Copy responses are metadata-only; opening the copy fetches its active page later. */
nbDuplicate = async function (nb) {
  toast("Copying notebook...");
  const copy = { id: nbId(), name: nb.name + " copy", tags: (nb.tags || []).slice(), archived: false,
    created: Date.now(), updated: Date.now(), order: nbMaxNbOrder() + 1, documentIds: [] };
  nbTree.notebooks.push(copy);
  let order = 0;
  for (const docId of nb.documentIds) {
    try {
      const result = await api("/api/copy_batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch: docId }) });
      const source = nbTree.documents[docId] || {};
      const meta = result.document_meta || { pages: [] };
      nbTree.documents[result.batch] = { notebookId: copy.id, displayName: source.displayName || result.batch, order: order++,
        pageCount: result.page_count || meta.pages.length, firstPage: meta.pages[0] && meta.pages[0].page_id, createdAt: Date.now() };
      copy.documentIds.push(result.batch);
    } catch (error) { toast("Copy failed: " + error.message); }
  }
  nbOpenState[copy.id] = true;
  nbSaveTree(); renderTree(); toast("Copy complete");
};
