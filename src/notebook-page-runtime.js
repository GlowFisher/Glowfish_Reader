"use strict";
/* Open notebook documents through metadata + current page, never /api/load. */
async function nbOpenDocOnce(id, gotoLast) {
  try {
    await gfOpenPagedDocument(id, gotoLast ? Number.MAX_SAFE_INTEGER : 0);
  } catch (error) {
    toast("打开失败：" + error.message);
  }
}
