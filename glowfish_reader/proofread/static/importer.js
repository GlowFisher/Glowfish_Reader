"use strict";
/* ============================================================================
 * 选择导入素材弹窗（浏览器版：multipart 上传替原生选择器）。
 * 流程：点【导入】→ 选文件/选文件夹 → 上传 → 选择目标文件夹、排序 → 确认导入。
 * 功能：缩略图列表、快捷排序、拖拽与 Ctrl 多选、PDF 展开分页、单条删除。
 * ========================================================================== */

let impItems = [];     // [{uid, rel, name, mtime, type:'image'|'pdf'|'pdfpage', page?, pages?, selected}]
let impUidSeq = 0;
let impToken = null;   // 本批上传令牌（/api/upload 返回；/api/thumb、/api/open 据此定位上传区）
let impDragUids = null, impMarker = null;
let impTargetNotebookId = null;
const impEsc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function thumbUrl(it) {
  const pg = it.type === "pdfpage" ? it.page : 0;
  return `/api/thumb?token=${encodeURIComponent(impToken)}&rel=${encodeURIComponent(it.rel)}&page=${pg}`;
}

function impFolderOptionsFromTree(tree) {
  const notebooks = (tree && Array.isArray(tree.notebooks)) ? tree.notebooks : [];
  const byParent = new Map();
  notebooks.forEach((nb) => {
    if (!nb || nb.archived) return;
    const parentId = nb.parentId || null;
    if (!byParent.has(parentId)) byParent.set(parentId, []);
    byParent.get(parentId).push(nb);
  });
  byParent.forEach((list) => list.sort((a, b) =>
    (a.archived ? 1 : 0) - (b.archived ? 1 : 0) || (a.order || 0) - (b.order || 0) || String(a.name || "").localeCompare(String(b.name || ""))));
  const out = [], seen = new Set();
  const walk = (parentId, depth, prefix) => {
    (byParent.get(parentId || null) || []).forEach((nb) => {
      if (!nb.id || seen.has(nb.id)) return;
      seen.add(nb.id);
      const name = nb.name || "未命名文件夹";
      const path = prefix ? prefix + " / " + name : name;
      out.push({ id: nb.id, name, depth, path });
      walk(nb.id, depth + 1, path);
    });
  };
  walk(null, 0, "");
  notebooks.forEach((nb) => {
    if (nb && !nb.archived && nb.id && !seen.has(nb.id)) {
      const name = nb.name || "未命名文件夹";
      seen.add(nb.id);
      out.push({ id: nb.id, name, depth: 0, path: name });
    }
  });
  return out;
}
async function impFetchFolderOptions() {
  try {
    const disk = await api("/api/notebooks");
    const options = impFolderOptionsFromTree(disk);
    if (options.length) return options;
  } catch (e) {}
  return [];
}
function impGetFolderOptions() {
  try {
    if (typeof nbImportFolderOptions === "function") {
      const options = nbImportFolderOptions();
      if (options && options.length) return options;
    }
  } catch (e) {}
  return [];
}
function impResolveTargetFolder(options) {
  options = options || impGetFolderOptions();
  if (impTargetNotebookId && options.some((nb) => nb.id === impTargetNotebookId)) return impTargetNotebookId;
  if (typeof nbImportDefaultFolderId === "function") {
    try {
      const id = nbImportDefaultFolderId();
      if (id && options.some((nb) => nb.id === id)) return id;
    } catch (e) {}
  }
  return (options[0] && options[0].id) || null;
}
function impApplyTargetFolders(options) {
  const sel = $("#impTargetSelect");
  if (!sel) return;
  options = options || [];
  const previous = impTargetNotebookId || sel.value || null;
  const fallback = impResolveTargetFolder(options);
  const target = (previous && options.some((nb) => nb.id === previous)) ? previous : fallback;
  sel.innerHTML = "";
  options.forEach((nb) => {
    const opt = document.createElement("option");
    opt.value = nb.id;
    opt.textContent = "　".repeat(nb.depth || 0) + nb.name;
    opt.title = nb.path || nb.name;
    sel.appendChild(opt);
  });
  if (target && options.some((nb) => nb.id === target)) sel.value = target;
  impTargetNotebookId = sel.value || target || null;
  sel.disabled = !options.length;
}
async function impRenderTargetFolders() {
  let options = impGetFolderOptions();
  if (!options.length) options = await impFetchFolderOptions();
  impApplyTargetFolders(options);
}
async function impOpenModal() {
  $("#importModal").classList.remove("hidden");
  await impRenderTargetFolders();
}

function startImport() {
  if (typeof closeBarMenus === "function") closeBarMenus();
  const input = $("#impFilesInput");
  if (!input) return toast("导入控件未初始化");
  input.value = "";
  input.click();
}
const closeImporter = () => $("#importModal").classList.add("hidden");

function uploadProgress(txt) {
  const box = $("#importProgress");
  if (txt == null) { box.classList.add("hidden"); box.textContent = ""; return; }
  box.textContent = txt; box.classList.remove("hidden");
}

function uploadFiles(fileList) {
  const files = [...fileList].filter((f) => /\.(jpe?g|png|pdf)$/i.test(f.name));
  if (!files.length) return toast("未选择 JPG/PNG/PDF 文件");
  const fd = new FormData();
  const mtimes = [];
  for (const f of files) {
    fd.append("files", f, f.webkitRelativePath || f.name);
    mtimes.push(f.lastModified || 0);
  }
  fd.append("mtimes", JSON.stringify(mtimes));
  uploadProgress("正在导入素材：上传 0%");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) uploadProgress(`正在导入素材：上传 ${Math.round(e.loaded / e.total * 100)}%`);
  };
  xhr.onload = () => {
    uploadProgress(null);
    if (xhr.status === 401) { location.href = "/login.html"; return; }
    if (xhr.status < 200 || xhr.status >= 300) {
      let detail = xhr.statusText;
      try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (_) {}
      return toast("上传失败：" + detail);
    }
    let res;
    try { res = JSON.parse(xhr.responseText); } catch (_) { return toast("上传响应解析失败"); }
    impToken = res.token;
    const its = res.items || [];
    if (!its.length) return toast("未发现可识别的图片或 PDF");
    impItems = its.map((m) => ({ uid: "u" + (impUidSeq++), selected: false,
      rel: m.rel, name: m.name, mtime: m.mtime || 0, type: m.type, pages: m.pages || 1 }));
    impSort("nameAsc");
    impOpenModal();
  };
  xhr.onerror = () => { uploadProgress(null); toast("上传失败：网络错误"); };
  xhr.send(fd);
}

function impSort(kind) {
  const by = (cmp, dir) => impItems.sort((a, b) => dir * cmp(a, b));
  const nm = (a, b) => String(a.name).localeCompare(String(b.name), undefined, { numeric: true, sensitivity: "base" });
  const mt = (a, b) => (a.mtime - b.mtime);
  if (kind === "nameAsc") by(nm, 1);
  else if (kind === "nameDesc") by(nm, -1);
  else if (kind === "mtimeAsc") by(mt, 1);
  else if (kind === "mtimeDesc") by(mt, -1);
  else if (kind === "reverse") impItems.reverse();
  renderImporter();
}

function renderImporter() {
  const list = $("#impList");
  list.innerHTML = ""; impMarker = null;
  impItems.forEach((it) => {
    const row = document.createElement("div");
    row.className = "imp-row" + (it.selected ? " sel" : "");
    row.dataset.uid = it.uid; row.draggable = true;
    const tag = it.type === "pdf" ? `<span class="imp-tag">PDF · ${it.pages}页</span>`
      : it.type === "pdfpage" ? `<span class="imp-tag">PDF 第${it.page}页</span>` : "";
    const expand = it.type === "pdf"
      ? `<button class="btn btn-micro imp-expand" data-uid="${it.uid}" title="按页拆分该 PDF，可与图片混排">展开分页</button>` : "";
    row.innerHTML = `
      <img class="imp-thumb" src="${thumbUrl(it)}" alt="" loading="lazy" draggable="false">
      <input class="imp-name-input" data-uid="${it.uid}" value="${impEsc(it.name)}" title="${impEsc(it.name)}" autocomplete="off" spellcheck="false">
      ${tag}<span class="imp-spacer"></span>${expand}
      <button class="btn btn-micro imp-del" data-uid="${it.uid}" title="移除此素材">删除</button>`;
    list.appendChild(row);
  });
  $("#impCount").textContent = `共 ${impItems.length} 项`;
}

function expandPdf(uid) {
  const i = impItems.findIndex((x) => x.uid === uid);
  if (i < 0 || impItems[i].type !== "pdf") return;
  const src = impItems[i], pages = [];
  for (let p = 1; p <= (src.pages || 1); p++)
    pages.push({ uid: "u" + (impUidSeq++), selected: false, rel: src.rel,
      name: src.name + `（第${p}页）`, mtime: src.mtime, type: "pdfpage", page: p, pages: src.pages });
  impItems.splice(i, 1, ...pages);
  renderImporter();
}
function delItem(uid) { impItems = impItems.filter((x) => x.uid !== uid); renderImporter(); }
function commitImportItemName(input, restoreOnEmpty) {
  const it = impItems.find((x) => x.uid === input.dataset.uid);
  if (!it) return;
  const oldName = input.dataset.oldName || it.name || "";
  if (!restoreOnEmpty) {
    it.name = input.value;
    input.title = input.value;
    return;
  }
  const name = input.value.trim();
  if (!name) {
    it.name = oldName;
    input.value = oldName;
    input.title = oldName;
    toast("请输入素材名称");
    return;
  }
  it.name = name;
  input.value = name;
  input.title = name;
  input.dataset.oldName = name;
}


function impRowMousedown(e, uid) {
  if (e.target.closest("button,input,textarea,select")) return;
  const it = impItems.find((x) => x.uid === uid);
  if (e.ctrlKey || e.metaKey) { it.selected = !it.selected; }
  else if (!it.selected) { impItems.forEach((x) => x.selected = false); it.selected = true; }
  renderImporter();
}
function impDropIndex(clientY) {
  const rows = [...$("#impList").querySelectorAll(".imp-row")];
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return i;
  }
  return rows.length;
}
function showMarker(index) {
  const list = $("#impList"), rows = [...list.querySelectorAll(".imp-row")];
  if (!impMarker) { impMarker = document.createElement("div"); impMarker.className = "imp-drop-line"; }
  if (index >= rows.length) list.appendChild(impMarker); else list.insertBefore(impMarker, rows[index]);
}

function initImporter() {
  const list = $("#impList");
  $("#impFilesInput").onchange = (e) => { if (e.target.files.length) uploadFiles(e.target.files); };
  const target = $("#impTargetSelect");
  if (target) target.onchange = (e) => { impTargetNotebookId = e.target.value || null; };
  document.querySelectorAll("#importModal [data-sort]").forEach((b) => b.onclick = () => impSort(b.dataset.sort));
  list.addEventListener("mousedown", (e) => {
    const row = e.target.closest(".imp-row"); if (row) impRowMousedown(e, row.dataset.uid);
  });
  list.addEventListener("click", (e) => {
    const ex = e.target.closest(".imp-expand"); if (ex) return expandPdf(ex.dataset.uid);
    const dl = e.target.closest(".imp-del"); if (dl) return delItem(dl.dataset.uid);
  });
  list.addEventListener("focusin", (e) => {
    const input = e.target.closest(".imp-name-input");
    if (input) input.dataset.oldName = input.value;
  });
  list.addEventListener("input", (e) => {
    const input = e.target.closest(".imp-name-input");
    if (input) commitImportItemName(input, false);
  });
  list.addEventListener("change", (e) => {
    const input = e.target.closest(".imp-name-input");
    if (input) commitImportItemName(input, true);
  });
  list.addEventListener("keydown", (e) => {
    const input = e.target.closest(".imp-name-input");
    if (!input) return;
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); commitImportItemName(input, true); input.blur(); }
    else if (e.key === "Escape") {
      const it = impItems.find((x) => x.uid === input.dataset.uid);
      if (it) { it.name = input.dataset.oldName || it.name || ""; input.value = it.name || ""; input.title = it.name || ""; }
      input.blur();
    }
  });
  list.addEventListener("dragstart", (e) => {
    const row = e.target.closest(".imp-row"); if (!row) return;
    const uid = row.dataset.uid, it = impItems.find((x) => x.uid === uid);
    if (!it.selected) { impItems.forEach((x) => x.selected = false); it.selected = true; renderImporter(); }
    impDragUids = impItems.filter((x) => x.selected).map((x) => x.uid);
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", uid); } catch (_) {}
    document.body.classList.add("imp-dragging");
  });
  list.addEventListener("dragover", (e) => { if (!impDragUids) return; e.preventDefault(); showMarker(impDropIndex(e.clientY)); });
  list.addEventListener("drop", (e) => {
    if (!impDragUids) return;
    e.preventDefault();
    const rowsUids = [...list.querySelectorAll(".imp-row")].map((r) => r.dataset.uid);
    let idx = impDropIndex(e.clientY);
    while (idx < rowsUids.length && impDragUids.includes(rowsUids[idx])) idx++;
    const refUid = rowsUids[idx];
    const moving = impDragUids.map((u) => impItems.find((x) => x.uid === u));
    const rest = impItems.filter((x) => !impDragUids.includes(x.uid));
    let pos = refUid ? rest.findIndex((x) => x.uid === refUid) : rest.length;
    if (pos < 0) pos = rest.length;
    impItems = [...rest.slice(0, pos), ...moving, ...rest.slice(pos)];
    impDragUids = null; renderImporter();
  });
  list.addEventListener("dragend", () => {
    impDragUids = null; document.body.classList.remove("imp-dragging");
    if (impMarker && impMarker.parentNode) impMarker.remove(); impMarker = null;
  });
  $("#impReselect").onclick = () => { closeImporter(); const i = $("#impFilesInput"); i.value = ""; i.click(); };
  $("#impCancel").onclick = closeImporter;
  $("#impConfirm").onclick = confirmImport;
}

async function confirmImport() {
  if (!impItems.length) return toast("没有可导入的素材");
  if (!impToken) return toast("上传令牌缺失，请重新选择素材");
  await impRenderTargetFolders();
  const targetNotebookId = impTargetNotebookId || impResolveTargetFolder();
  if (!targetNotebookId) return toast("请选择导入到哪个文件夹");
  const stem = (n) => String(n || "导入").replace(/\.[^.]+$/, "");
  const groups = [];
  const pdfIdx = {};
  for (const it of impItems) {
    if (it.type === "image") {
      groups.push({ name: stem(it.name), items: [{ rel: it.rel, type: "image" }] });
    } else {
      if (pdfIdx[it.rel] == null) { pdfIdx[it.rel] = groups.length; groups.push({ name: stem(it.name), items: [] }); }
      groups[pdfIdx[it.rel]].items.push(it.type === "pdfpage"
        ? { rel: it.rel, type: "pdfpage", page: it.page } : { rel: it.rel, type: "pdf" });
    }
  }
  closeImporter();
  startImportProgress();
  let fail = 0;
  const keepCurrentOpen = (typeof proof !== "undefined" && !!proof);
  try {
    for (let gi = 0; gi < groups.length; gi++) {
      const g = groups[gi];
      if (typeof gfSetBatchImportProgress === "function") gfSetBatchImportProgress(gi, groups.length, g.name);
      try {
        const data = await api("/api/open", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: impToken, items: g.items, name: g.name,
            punct_backend: (settings && settings.punct_backend) || "local" }) });
        if (keepCurrentOpen && typeof nbRegisterProofDoc === "function") nbRegisterProofDoc(data.proof, false, targetNotebookId);
        else {
          applyLoaded(data);
          if (typeof nbRegisterProofDoc === "function") nbRegisterProofDoc(data.proof, true, targetNotebookId);
        }
      } catch (e) { fail++; toast("导入失败：" + g.name + "：" + e.message); }
    }
  } finally { if (typeof gfClearBatchImportProgress === "function") gfClearBatchImportProgress(); stopImportProgress(); }
  if (groups.length > 1 && !fail) toast(`已导入 ${groups.length} 条史料`);
}

