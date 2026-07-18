"use strict";
/* Glowfish Reader 史料阅读编辑器 —— 编排层：全局状态、API、工具栏、撤销、加载/保存/导出。
 * 右栏渲染与横竖交互见 editor.js；左栏底图见 viewer.js；拖拽排序见 dnd.js；设置见 settings.js。 */
let proof = null, pageIdx = 0, lowConf = 0.85, batch = null;
let pureMode = true;             // 纯净校对恒为默认（视觉再设计 v2 去开关钮）：隐藏每行工具栏，全键盘点校常开
let imgVer = 0;                  // 底图缓存键：仅在 (重新)加载文档时翻新，翻页可命中浏览器缓存
const UNDO_LIMIT = 80;          // 撤销栈上限（每条=整份 proof 深拷贝）
const TEXT_UNDO_MERGE_MS = 800; // 连续文本输入在短暂停顿内合并为一步撤销
const IMPORT_POLL_MS = 350;     // 导入进度轮询间隔

const $ = (s) => document.querySelector(s);
// toast(m) 纯文本；toast(m,{label,fn,ms}) 带操作按钮（如导出后「打开所在文件夹」），停留更久。
const toast = (m, opts) => {
  const t = $("#toast");
  if (opts && opts.label) {
    t.innerHTML = ""; t.appendChild(document.createTextNode(m + "  "));
    const b = document.createElement("button");
    b.className = "btn btn-micro"; b.textContent = opts.label;
    b.onclick = () => { try { opts.fn && opts.fn(); } catch (_) {} t.classList.remove("show"); };
    t.appendChild(b);
  } else { t.textContent = m; }
  t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), (opts && opts.ms) || 1800);
};

const page = () => proof.pages[pageIdx];
const lineById = (id) => { for (const l of page().lines) if (l.id === id) return l; return null; };

// ---- 撤销/恢复：整份 proof 快照栈 ----
let undoStack = [], redoStack = [];
let textUndoMerge = { scope: null, ts: 0 };
const snapshot = () => JSON.parse(JSON.stringify(page()));
function resetTextUndoMerge() {
  textUndoMerge = { scope: null, ts: 0 };
}
function pushUndo(snap) {
  resetTextUndoMerge();
  undoStack.push(snap || snapshot());
  if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  redoStack = []; updateHist();
  if (typeof gfMarkCurrentPageDirty === "function") gfMarkCurrentPageDirty();
  if (typeof gfScheduleSave === "function") gfScheduleSave();
}
function pushTextUndo(scopeKey) {
  const now = Date.now();
  if (!textUndoMerge.scope || textUndoMerge.scope !== scopeKey || now - textUndoMerge.ts > TEXT_UNDO_MERGE_MS) {
    pushUndo();
    textUndoMerge = { scope: scopeKey, ts: now };
    return;
  }
  textUndoMerge.ts = now;
}
function undo() {
  if (!undoStack.length) return;
  resetTextUndoMerge();
  redoStack.push(snapshot()); proof.pages[pageIdx] = undoStack.pop();
  render(); updateHist();
}
function redo() {
  if (!redoStack.length) return;
  resetTextUndoMerge();
  undoStack.push(snapshot()); proof.pages[pageIdx] = redoStack.pop();
  render(); updateHist();
}
function updateHist() {
  const u = $("#undoBtn"), r = $("#redoBtn");
  if (u) u.disabled = !undoStack.length;
  if (r) r.disabled = !redoStack.length;
}

function applyLoaded(data) {
  proof = data.proof; batch = proof.batch; lowConf = data.low_conf;   // lowConf 仍用于标红阈值（控件已移除，固定默认）
  pageIdx = 0;
  imgVer = Date.now();   // 本次加载的底图缓存键（重新导入同名 batch 时也会变→强制刷新底图）
  undoStack = []; redoStack = []; updateHist();
  updateScriptBtn();
  currentLayout = settings.text_layout || "horizontal";   // 持久默认排版来自设置
  proofMode = settings.proof_mode || "page";              // 持久默认校读模式（默认整页，v2）
  syncLayoutButtons();
  if (typeof syncProofModeButtons === "function") syncProofModeButtons();
  for (const id of ["canvasNav", "layoutBtn", "scriptBtn", "hist", "statPage", "statDelta"])
    $("#" + id).classList.remove("hidden");   // mainBtns(保存/导入/导出)永久固定显示，不在此列
  render();
  if (typeof gfCacheProof === "function") gfCacheProof();   // 加载后写本地缓存（瞬时恢复用）
  if (typeof nbOnDocLoaded === "function") nbOnDocLoaded();  // notebook.js：登记/激活当前文档
  toast("已加载 " + proof.pages.length + " 页");
}

// 新增①：导入进度——轮询 /api/import_progress；逐页进度 + 引擎名 + 滑动平均剩余估时；失败小字旁注
let importTimer = null;
let importSawOcr = false;
let impSamples = [];                                      // [{t, done}] 估时采样（每次 done 前进时记录）
const ENGINE_LABEL = { ppocrv6: "PP-OCRv6", onnx: "快速", paddle: "Paddle" };

function gfEta(total) {
  // 滑动窗口（最近 ≤6 个页完成事件）估算剩余时间；样本不足返回 ""
  if (impSamples.length < 2) return "";
  const win = impSamples.slice(-6);
  const pages = win[win.length - 1].done - win[0].done;
  const secs = (win[win.length - 1].t - win[0].t) / 1000;
  if (pages <= 0 || secs <= 0) return "";
  const remain = Math.round((total - win[win.length - 1].done) * (secs / pages));
  if (remain <= 0) return "";
  return remain >= 90 ? `，预计还需 ${Math.ceil(remain / 60)} 分钟` : `，预计还需 ${remain} 秒`;
}

// 回退横幅：高精引擎失败自动降级快速引擎时持久提示（可手动关闭），替代静默降级
function gfShowFallbackBanner(fb) {
  if ($("#fallbackBanner")) return;
  const b = document.createElement("div");
  b.id = "fallbackBanner";
  b.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:8900;display:flex;align-items:center;" +
    "gap:12px;padding:8px 16px;background:#7a4a12;color:#fff;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.25)";
  const frm = ENGINE_LABEL[fb.from] || fb.from, to = ENGINE_LABEL[fb.to] || fb.to;
  b.innerHTML = `<span style="flex:1">本次识别已从「${frm}」引擎自动回退到「${to}」引擎（原因：${
    (fb.reason || "启动失败").slice(0, 120)}）。识别仍全程本地完成；可在设置中改用快速引擎，或检查高精引擎组件后重新导入。</span>
    <button class="btn btn-sec" id="fbDismiss">知道了</button>`;
  document.body.appendChild(b);
  $("#fbDismiss").onclick = () => b.remove();
}

// 资产缺件横幅：模型/词表没随包时持久提示。历史上这类缺失是静默的——功能没了，程序照跑。
async function gfCheckCapabilitiesOnce() {
  try {
    const r = await api("/api/capabilities");
    if (r.ok || $("#capBanner")) return;
    const missing = Object.values(r.capabilities).filter((c) => !c.ok).map((c) => c.label);
    const b = document.createElement("div");
    b.id = "capBanner";
    b.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:8900;display:flex;align-items:center;" +
      "gap:12px;padding:8px 16px;background:#7a1f1f;color:#fff;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.25)";
    b.innerHTML = `<span style="flex:1">以下功能未启用（组件缺失）：${missing.join("、")}。
      识别仍可进行，但这些增强层不会生效。请重新安装完整版安装包。</span>
      <button class="btn btn-sec" id="capDismiss">知道了</button>`;
    document.body.appendChild(b);
    $("#capDismiss").onclick = () => b.remove();
  } catch (e) {}
}

function startImportProgress() {
  const box = $("#importProgress"), fail = $("#importFail");
  box.textContent = "正在导入素材：准备中…"; box.classList.remove("hidden");
  fail.classList.add("hidden"); fail.textContent = "";
  impSamples = [];
  importSawOcr = false;
  if (importTimer) clearInterval(importTimer);
  importTimer = setInterval(async () => {
    try {
      const p = await api("/api/import_progress");
      const engTag = p.engine && ENGINE_LABEL[p.engine] ? `（${ENGINE_LABEL[p.engine]}引擎）` : "";
      if (p.phase === "ocr" && p.total) {
        importSawOcr = true;
        const last = impSamples[impSamples.length - 1];
        if (!last || p.done > last.done) impSamples.push({ t: Date.now(), done: p.done });
        const pct = Math.round(p.done / p.total * 100);
        box.textContent = (p.total > 1)
          ? `正在识别文字 ${p.done}/${p.total}${engTag}，进度 ${pct}%${gfEta(p.total)}`
          : `正在识别文字${engTag}：${pct}%`;
      } else if (p.phase === "load") { importSawOcr = true; box.textContent = `正在识别文字：加载模型${engTag}`; }
      else if (p.phase === "import" && p.total) box.textContent = `正在导入素材 ${p.done}/${p.total}`;
      else if (p.phase === "done") box.textContent = "导入与识别完成：100%";
      else box.textContent = "正在导入素材：准备中…";
      if (p.fallback) gfShowFallbackBanner(p.fallback);
      if (p.failed && p.failed.length) {                  // 失败文件不阻断，仅小字提示
        fail.textContent = "⚠ " + p.failed.map((f) => `第${f.idx}页 ${f.name} 导入失败`).join("；");
        fail.classList.remove("hidden");
      }
    } catch (e) {}
  }, IMPORT_POLL_MS);
}
async function gfCheckFallbackOnce() {
  try { const p = await api("/api/import_progress"); if (p.fallback) gfShowFallbackBanner(p.fallback); }
  catch (e) {}
}
function stopImportProgress() {
  if (importTimer) { clearInterval(importTimer); importTimer = null; }
  const box = $("#importProgress");
  box.classList.remove("hidden");
  if (!importSawOcr) {
    box.textContent = "正在识别文字 1/1，进度 100%";
    setTimeout(() => { box.textContent = "导入与识别完成：100%"; }, 550);
    setTimeout(() => box.classList.add("hidden"), 1300);
  } else {
    box.textContent = "导入与识别完成：100%";
    setTimeout(() => box.classList.add("hidden"), 800);
  }
  gfCheckFallbackOnce();                                  // 收尾再查一次：回退多在末段写入，别错过
  setTimeout(() => $("#importFail").classList.add("hidden"), 6000);   // 失败提示再留几秒供查看
}

// 新增二：删除当前页（受「删除行二次确认」开关控制；可撤销）
function delCurrentPage() {
  if (!proof || !proof.pages.length) return;
  if (settings.confirm_delete) $("#pageDelModal").classList.remove("hidden");
  else doDelPage();
}
function doDelPage() {
  $("#pageDelModal").classList.add("hidden");
  if (!proof || !proof.pages.length) return;
  pushUndo();
  proof.pages.splice(pageIdx, 1);                          // 清空当前页：原图引用+文本+识别行
  if (pageIdx >= proof.pages.length) pageIdx = Math.max(0, proof.pages.length - 1);
  render();
}

// 空白态：无 proof 或无页 → body.gf-blank（显示「底图区/点校区」竖排楷书占位）
function gfUpdateBlank() {
  document.body.classList.toggle("gf-blank", !proof || !proof.pages || !proof.pages.length);
}

function render() {
  gfUpdateBlank();
  if (!proof) return;                         // 无文档：gfUpdateBlank 已切空白态，余下渲染跳过
  if (!proof.pages.length) {                  // 删空后：清左右双栏视图
    $("#pageLabel").textContent = "0/0";
    $("#editorBody").innerHTML = "";
    $("#pageImg").removeAttribute("src");
    $("#boxes").innerHTML = "";
    refreshStats();
    if (typeof annRefresh === "function") annRefresh();
    return;
  }
  const pg = page();
  $("#pageLabel").textContent = `${pageIdx + 1} / ${proof.pages.length}`;   // 仅页码，不显文件名
  const img = $("#pageImg");
  img.onload = layoutImage;   // viewer.js：按基准摆放识别框 + 应用平移缩放
  img.onerror = () => toast("原图加载失败：请确认本机数据目录仍保留该史料图片");
  img.src = `/img/${encodeURIComponent(batch)}/${encodeURIComponent(pg.page_id)}?t=${imgVer}`;
  renderEditor();             // editor.js：按当前排版重绘右栏
  refreshStats();
  if (typeof annRefresh === "function") annRefresh();   // 顶层批注面板随页刷新
}

// 翻页：跨史料连贯——本史料内翻页；到边界则跳到笔记本内上/下一条史料（按左侧排序）。
function nbDocIds() {
  const nb = (typeof nbCur === "function") ? nbCur() : null;
  return nb ? nb.documentIds.slice() : [];
}
function pageNext() {
  if (!proof) return;
  if (pageIdx < proof.pages.length - 1) { pageIdx++; render(); return; }
  const ids = nbDocIds(), i = ids.indexOf(proof.batch);
  if (i >= 0 && i < ids.length - 1 && typeof nbOpenDoc === "function") nbOpenDoc(ids[i + 1]);
}
function pagePrev() {
  if (!proof) return;
  if (pageIdx > 0) { pageIdx--; render(); return; }
  const ids = nbDocIds(), i = ids.indexOf(proof.batch);
  if (i > 0 && typeof nbOpenDoc === "function") nbOpenDoc(ids[i - 1], true);   // 跳上一条史料末页
}

// 从底图识别框点选 → 高亮并定位右栏对应条目
function activateRow(id) {
  markActiveRow(id); highlightBox(id);
  const row = document.querySelector(`[data-id="${cssEsc(id)}"]`);
  if (row) row.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  focusLine(id, 0);
}
function highlightBox(id) {
  document.querySelectorAll(".box").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
}

// 简繁在位切换（默认简体；点一次转繁体，右侧文本随之变）
function updateScriptBtn() {
  const b = $("#scriptBtn");
  if (b && proof) b.textContent = proof.script === "t" ? "繁體" : "简体";
}
async function toggleScript() {
  const to = proof.script === "s" ? "t" : "s";
  toast(to === "t" ? "转繁体中…" : "转简体中…");
  try {
    pushUndo();
    const r = await api("/api/convert", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proof, to }) });
    proof = r.proof; updateScriptBtn(); renderEditor();
  } catch (e) { toast("切换失败：" + e.message); }
}

async function save() {
  try { await api("/api/save", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proof }) });
    refreshStats();
    if (typeof gfCacheProof === "function") gfCacheProof();   // 磁盘落盘同时并行写本地缓存
    toast("已保存"); } catch (e) { toast("保存失败：" + e.message); }
}
// ===== 顶栏下拉菜单（导出）：锚定按钮下方，点外部 / Esc 关闭 =====
function positionBarMenu(menu, btn) {
  const r = btn.getBoundingClientRect();
  menu.style.position = "fixed";
  menu.style.top = (r.bottom + 6) + "px";
  menu.style.left = r.left + "px";
  menu.style.right = "auto";
}
function openBarMenu(menu, btn) {
  if (!menu) return;
  if (!menu.classList.contains("hidden")) {
    closeBarMenus();
    return;
  }
  closeBarMenus();
  positionBarMenu(menu, btn);
  menu.classList.remove("hidden");
  setTimeout(() => document.addEventListener("mousedown", barMenuOutside, true), 0);
}
function closeBarMenus() {
  const em = $("#exportMenu");
  if (em) em.classList.add("hidden");
  document.removeEventListener("mousedown", barMenuOutside, true);
}
function barMenuOutside(e) {
  if (e.target.closest("#exportMenu, #exportBtn")) return;
  closeBarMenus();
}

// 导出：下拉选范围(本页 / 整个笔记本) + 是否带批注 → 浏览器直接下载（文件流 + RFC5987 中文名）
function openExportMenu() {
  const cb = $("#expWithAnnot");
  if (cb) cb.checked = (typeof gfReadExportAnnot === "function") ? gfReadExportAnnot() : !!settings.export_with_annot;
  const cbi = $("#expWithImage");
  if (cbi) cbi.checked = !!settings.export_with_image;
  const cbp = $("#expPageMarks");
  if (cbp) cbp.checked = !!settings.export_page_marks;      // 默认随设置；本次导出可临时改
  openBarMenu($("#exportMenu"), $("#exportBtn"));
}
function parseFilename(cd) {
  if (!cd) return null;
  let m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (m) { try { return decodeURIComponent(m[1]); } catch (_) { return m[1]; } }
  m = /filename="?([^";]+)"?/i.exec(cd);
  return m ? m[1] : null;
}

// pywebview 原生桥探测（桌面壳才有；返回方法引用或 null，避免到处重写 window.pywebview&&...&&api[x] 长链）
const gfBridge = (m) => (window.pywebview && window.pywebview.api && window.pywebview.api[m]) || null;
function blobToB64(blob) {                                // Blob → base64（传给原生桥写盘）
  return new Promise((res, rej) => { const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(",")[1]); fr.onerror = rej; fr.readAsDataURL(blob); });
}
function saveExportDir(dir) {                             // 记忆上次导出目录（落后端 settings.json，下次默认打开）；仅在目录变化时写盘
  if (!dir || (typeof settings !== "undefined" && settings.export_last_dir === dir)) return;
  try { if (typeof settings !== "undefined") settings.export_last_dir = dir; } catch (_) {}
  api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ export_last_dir: dir }) }).catch(() => {});
}

const EXPORT_SAVE_TYPES = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".csv": "text/csv",
  ".zip": "application/zip",
};
function exportSaveType(fname, blob) {
  const lower = (fname || "").toLowerCase();
  const ext = Object.keys(EXPORT_SAVE_TYPES).find((x) => lower.endsWith(x)) || ".docx";
  const mime = EXPORT_SAVE_TYPES[ext] || blob.type || "application/octet-stream";
  return { ext, mime };
}
async function browserSaveExport(fname, blob) {
  if (!window.showSaveFilePicker) return null;
  const { ext, mime } = exportSaveType(fname, blob);
  try {
    const handle = await window.showSaveFilePicker({
      suggestedName: fname,
      types: [{ description: "Glowfish Reader export", accept: { [mime]: [ext] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return { ok: true, path: fname };
  } catch (e) {
    if (e && e.name === "AbortError") return { canceled: true };
    throw e;
  }
}

async function downloadExport(body) {                    // 单次导出：POST /api/export → 桌面原生保存；浏览器保存选择；最后降级 Downloads
  const r = await GlowfishApi.export.download(body);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  const blob = await r.blob();
  const fname = parseFilename(r.headers.get("Content-Disposition")) || "导出";
  const n = r.headers.get("X-Doc-Paragraphs");
  const saveExport = gfBridge("save_export");
  if (saveExport) {                                      // 桌面壳：系统原生保存对话框 + 记忆目录
    toast("\u8bf7\u9009\u62e9\u5bfc\u51fa\u6587\u4ef6\u7684\u4fdd\u5b58\u4f4d\u7f6e");
    const b64 = await blobToB64(blob);
    const startDir = (typeof settings !== "undefined" && settings.export_last_dir) || "";
    const res = await saveExport(fname, b64, startDir);
    if (res && res.canceled) return { fname, n, canceled: true };
    if (!res || !res.ok) throw new Error((res && res.error) || "保存失败");
    if (res.dir) saveExportDir(res.dir);
    return { fname, n, path: res.path };
  }
  const picked = await browserSaveExport(fname, blob);     // 现代浏览器：弹保存文件选择框
  if (picked && picked.canceled) return { fname, n, canceled: true };
  if (picked && picked.ok) return { fname, n, path: picked.path };
  const url = URL.createObjectURL(blob);                  // 旧浏览器降级：a 标签落 Downloads
  const a = document.createElement("a");
  a.href = url; a.download = fname; document.body.appendChild(a); a.click();
  a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
  return { fname, n };
}
async function selectedPagesExportBody(selected, pageMarks) {
  const nb = (typeof nbCur === "function") ? nbCur() : null;
  return {
    scope: "selected_pages",
    selected,
    name: (nb && nb.name) || "选中页面",
    page_marks: pageMarks,
  };
}

async function doExport(scope) {
  closeBarMenus();
  const withAnnot = !!($("#expWithAnnot") && $("#expWithAnnot").checked);
  const imgOpt = $("#expWithImage");
  const withImage = imgOpt ? !!imgOpt.checked : !!settings.export_with_image;
  const pageMarksOpt = $("#expPageMarks");
  const pageMarks = pageMarksOpt ? !!pageMarksOpt.checked : !!settings.export_page_marks;
  let main, finishSelected = false;
  if (scope === "page") {                                 // 本页
    if (!proof) return toast("未打开史料");
    main = { scope: "page", batch: proof.batch, page_id: page().page_id, page_marks: pageMarks };
  } else if (scope === "selected_pages") {
    if (typeof nbExportSelectedPayload !== "function") return toast("选择页面功能未初始化");
    const selected = nbExportSelectedPayload();
    if (!selected.length) return toast("未选择页面");
    main = await selectedPagesExportBody(selected, pageMarks);
    if (!main) return toast("未选择页面");
    finishSelected = true;
  } else {                                                // 整个笔记本（合并辑录）
    const nb = (typeof nbCur === "function") ? nbCur() : null;
    if (!nb || !nb.documentIds.length) return toast("当前笔记本无史料");
    main = { scope: "notebook", batches: nb.documentIds.slice(), name: nb.name, page_marks: pageMarks };
  }
  Object.assign(main, { with_annot: withAnnot, with_image: withImage });
  try {
    if (typeof gfAwaitSave === "function") {
      await gfAwaitSave();
    }
    const m = await downloadExport(main);
    if (m.canceled) return;                              // 用户在原生保存对话框点了取消
    if (finishSelected && typeof nbFinishExportPageSelect === "function") nbFinishExportPageSelect();
    const native = !!m.path, verb = native ? "已保存" : "已下载";
    const shownName = native && m.path ? m.path : m.fname;
    const msg = withAnnot ? `${verb} ${shownName}（正文与批注合一）`
      : (m.n ? `${verb} ${shownName}（${m.n} 段）` : `${verb} ${shownName}`);
    const openFolder = gfBridge("open_folder");
    if (native && openFolder) toast(msg, { label: "打开所在文件夹", fn: () => openFolder(m.path), ms: 6000 });
    else toast(msg);
    refreshStats();
  } catch (e) { toast("导出失败：" + e.message); }
}
// 改造段三：右上角字数客户端实时计算（无需保存即更新）。
// 当前页字数=当前页非删除条目定稿字符数（含标点）；改动字数=相对最初页(text_draft)的净字数增减，标点不计入、正负号即「符号」。
const PUNCT_RE = /[\s，。、；：！？「」『』（）()《》〈〉【】〖〗…—·,.;:!?"'`~@#$%^&*\-_=+\[\]{}|\\/<>·•　]/;
function countChars(s, excludePunct) {
  let n = 0;
  for (const ch of (s || "")) { if (excludePunct && PUNCT_RE.test(ch)) continue; n++; }
  return n;
}
function pageStats() {
  const pg = page();
  let pageChars = 0, finalNoP = 0, draftNoP = 0;
  for (const l of pg.lines) {
    draftNoP += countChars(l.text_draft, true);     // 最初页基数（含已删原文 → 删字记为减少）
    if (l.deleted) continue;
    pageChars += countChars(l.text, false);
    finalNoP += countChars(l.text, true);
  }
  return { pageChars, delta: finalNoP - draftNoP };
}
function refreshStats() {
  if (!proof) return;
  if (!proof.pages.length) {                  // 空页：字数清零
    $("#statPage").textContent = "本页共 0 字"; $("#statDelta").textContent = "改动 0"; return;
  }
  const { pageChars, delta } = pageStats();
  $("#statPage").textContent = `本页共 ${pageChars} 字`;
  $("#statDelta").textContent = `改动 ${delta > 0 ? "+" + delta : (delta < 0 ? String(delta) : "0")}`;
}

// ===== 工具栏与弹窗事件 =====
function bindClick(id, fn, required = true) {
  const el = $("#" + id);
  if (!el) {
    if (required && window.console && console.warn) console.warn("Missing UI element #" + id);
    return null;
  }
  el.onclick = fn;
  return el;
}

bindClick("importBtn", startImport);           // 唯一导入入口：直接打开文件/文件夹选择
bindClick("prevPage", pagePrev);
bindClick("nextPage", pageNext);
bindClick("pdConfirm", doDelPage);             // 删页确认弹窗保留（按钮已移除，仅留兜底接线）
bindClick("pdCancel", () => $("#pageDelModal").classList.add("hidden"));
bindClick("saveBtn", () => (typeof gfSnapshotSave === "function" ? gfSnapshotSave() : save()));
bindClick("scriptBtn", toggleScript);
bindClick("exportBtn", openExportMenu);        // 导出下拉菜单（选择页面 / 整个笔记本 + 是否带批注）
bindClick("expSelect", () => {
  closeBarMenus();
  if (typeof nbStartExportPageSelect === "function") nbStartExportPageSelect();
  else toast("选择页面功能未初始化");
});
bindClick("expNb", () => doExport("notebook"));
bindClick("undoBtn", undo);
bindClick("redoBtn", redo);
// 删除二次确认弹窗（开关由 editor.js delRow 判断；此处只接确认/取消）
bindClick("cdConfirm", () => { const id = pendingDelId; pendingDelId = null; $("#confirmModal").classList.add("hidden"); if (id) doDelete(id); });
bindClick("cdCancel", () => { pendingDelId = null; $("#confirmModal").classList.add("hidden"); });

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeBarMenus(); $("#settingsModal").classList.add("hidden"); $("#confirmModal").classList.add("hidden"); $("#pageDelModal").classList.add("hidden"); $("#importModal").classList.add("hidden"); }
  if (!proof) return;
  const k = e.key.toLowerCase();
  if (e.ctrlKey && k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
  else if (e.ctrlKey && (k === "y" || (e.shiftKey && k === "z"))) { e.preventDefault(); redo(); }
});

// ===== iter-001 新增：深浅主题切换 + 快捷键 + 帮助浮层（纯前端，localStorage 持久；独立监听器，不改既有逻辑） =====
function gfIsEditing() {
  const a = document.activeElement;
  if (!a) return false;
  return a.isContentEditable || a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT";
}
function gfToggleTheme() {
  const dark = !document.body.classList.contains("gf-dark");
  if (typeof applyThemeMode === "function") {
    applyThemeMode(dark ? "dark" : "light", true);
    if (typeof updateSegBtns === "function") updateSegBtns();
  } else {
    document.body.classList.toggle("gf-dark", dark);
    try { localStorage.setItem("gf-theme", dark ? "dark" : "light"); } catch (e) {}
    toast(dark ? "已切换深色主题" : "已切换浅色主题");
  }
}
// 纯净校对恒开（v2 去开关钮）：hide-rowops 常驻，editor.js keydown 路由全键盘点校常开
document.body.classList.add("pure-mode");
const gfHelp = () => $("#shortcutModal");
if ($("#themeBtn")) $("#themeBtn").onclick = gfToggleTheme;
if ($("#scClose")) $("#scClose").onclick = () => gfHelp().classList.add("hidden");

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {                                   // 补充：关帮助浮层 + 搜索面板（既有 Esc 监听处理其余弹窗）
    gfHelp().classList.add("hidden");
    const sp = $("#searchPanel"); if (sp) sp.classList.add("hidden");
    return;
  }
  if (e.ctrlKey && e.shiftKey && !e.altKey && e.key.toLowerCase() === "l") {  // iter-002：主题切换（全局，编辑态也生效）
    e.preventDefault(); gfToggleTheme(); return;
  }
  if (e.ctrlKey && !e.altKey && !e.shiftKey) {                // Ctrl 组合（编辑态也生效，preventDefault 覆盖浏览器默认）
    const k = e.key.toLowerCase();
    if (k === "s") { e.preventDefault(); $("#saveBtn").click(); return; }
    if (k === "f") { e.preventDefault(); $("#searchBtn").click(); return; }
    if (e.key === "=" || e.key === "+") { e.preventDefault(); $("#zoomIn") && $("#zoomIn").click(); return; }
    if (e.key === "-") { e.preventDefault(); $("#zoomOut") && $("#zoomOut").click(); return; }
    if (e.key === "0") { e.preventDefault(); $("#zoomReset") && $("#zoomReset").click(); return; }
    return;                                                   // 其余 Ctrl 组合（Ctrl+Z/Y 等）交回原监听器
  }
  if (gfIsEditing()) return;                                  // 编辑文本时，字符/翻页/方向键正常输入，不拦截
  if (e.key === "PageUp" || e.key === "[" || e.key === "ArrowLeft") { e.preventDefault(); if (typeof pagePrev === "function") pagePrev(); }
  else if (e.key === "PageDown" || e.key === "]" || e.key === "ArrowRight") { e.preventDefault(); if (typeof pageNext === "function") pageNext(); }
  else if (e.key === "?") { e.preventDefault(); gfHelp().classList.toggle("hidden"); }
});

initEditor();     // editor.js：排版面板 + 右栏滚轮缩放接线
initImporter();   // importer.js：导入素材排序弹窗接线
initSettings();   // settings.js：渲染设置面板 + 拉取配置 + 实时生效
gfCheckCapabilitiesOnce();                                  // 缺件即挂横幅，不静默降级
gfUpdateBlank();                                            // 启动即按当前(空)状态显示占位
if (typeof gfRestoreLast === "function") setTimeout(() => gfRestoreLast(), 0);
