"use strict";
/* 完整双分区设置面板：数据驱动渲染 + 配置读写 + 实时生效（settings 为全局单一数据源）。
 * SET_SCHEMA 描述分区/配置项；二元项=分段单选按钮，字号=横向旋钮（改造段⑥）。 */
let settings = {
  // 底图区
  show_zoom_ctl: true, canvas_bg: "black", show_boxes: false, pan_bound: true, img_quality: "balanced",
  lowconf_red: true, lowconf_red_vertical: true,
  // 点校区（confirm_delete 锁定为 true：删除一律二次确认，设置面板不再暴露开关）
  default_script: "s", punct_pos: "caret", confirm_delete: true, text_layout: "horizontal",
  text_font: "songti", text_size: 16, drag_anim: true, show_row_ops: true, punct_backend: "local", proof_mode: "page",
  engine_pref: "",
  // 底部通用（export_with_annot 为前端新增项，仅 localStorage 持久，不入后端 settings.json）
  export_format: "docx", export_with_image: false, export_with_annot: false,
  export_page_marks: false, autosave: 0, auto_check_update: true,
};

const SET_SCHEMA = [
  { title: "通用设置", collapsible: true, items: [
    { key: "theme_mode", label: "主题模式", opts: [["light", "浅色"], ["dark", "深色"]], note: "切换应用整体明暗主题。" },
    { key: "export_format", label: "默认导出格式", opts: [["docx", ".docx"], ["md", ".md"], ["txt", ".txt"]], note: "导出时默认生成此格式。" },
    { key: "export_with_image", label: "导出默认附带原图", opts: [[true, "开启"], [false, "关闭"]], note: "开启后导出下拉的「附带原图」默认勾选；导出时仍可临时改变本次勾选。" },
    { key: "export_with_annot", label: "导出默认带批注笔记", opts: [[true, "开启"], [false, "关闭"]], note: "开启后导出下拉的「是否带批注笔记」默认勾选；导出时仍可临时改变本次勾选。" },
    { key: "export_page_marks", label: "导出默认标注页码", opts: [[true, "开启"], [false, "关闭"]], note: "开启后导出每页正文前自动插入「【第N页】」（页号取 PDF 源页或顺序号）；导出下拉可临时改变本次勾选。" },
    { key: "autosave", label: "自动保存", opts: [[0, "关闭"], [60, "1分钟"], [180, "3分钟"]], note: "按间隔自动保存修订草稿，防意外丢失。" },
    { key: "auto_check_update", label: "自动检查更新", opts: [[true, "开启"], [false, "关闭"]], note: "启动后后台向官方服务器自动检查新版本（仅传版本号，不上传任何史料）。" },
  ] },
  { title: "底图区设置", collapsible: true, items: [
    { key: "show_zoom_ctl", label: "缩放按钮", opts: [[true, "显示"], [false, "隐藏"]], note: "原图栏支持滚轮缩放、按住拖拽平移；隐藏按钮后缩放/拖拽不受影响。" },
    { key: "canvas_bg", label: "画布背景", opts: [["black", "纯黑"], ["gray", "深灰"], ["cream", "米白"], ["custom", "自定义"]], note: "切换原图阅览画布，适配长时间校对护眼。" },
    { key: "lowconf_red", label: "低置信识别文字标红", opts: [[true, "开启"], [false, "关闭"]], note: "开启后底图区横竖排低置信识别文字统一标红，直观区分识别误差。" },
  ] },
  { title: "点校区设置", collapsible: true, items: [
    { key: "engine_pref", label: "识别引擎", opts: [["", "满血版"], ["ppocrv6_onnx", "快速版"]], note: "满血版质量优先，处理可能较慢；快速版速度优先，更适合低配机器。" },
    { key: "default_script", label: "默认输出文字", opts: [["s", "简体"], ["t", "繁体"]], note: "导入新史料时自动生效；顶部简繁按钮仅临时预览，不改文件存储文字。" },
    { key: "punct_pos", label: "标点添加位置", opts: [["caret", "光标处"], ["end", "末尾"]], note: "逗号、句号按所选规则插入；光标处=输入框插入点，末尾=文本尾部追加。" },
    { key: "text_layout", label: "默认排版格式", opts: [["horizontal", "横排"], ["vertical", "竖排"]], note: "永久默认排版；顶部排版按钮为临时视图切换，不改此项。" },
    { key: "proof_mode", label: "默认校读格式", opts: [["page", "整页点校"], ["row", "逐行点校"]], note: "整页=整页连排版面，可划选文字加批注（默认）；逐行=按识别行分条点校。校读栏顶部可临时切换，此项为永久默认。" },
    { key: "punct_backend", label: "自动断句标点", opts: [["local", "开启"], ["off", "关闭"]], note: "导入识别后自动加现代标点（不增删汉字）；关闭后保留无标点原貌。" },
    { key: "text_size", label: "文本字号", type: "knob", min: 10, max: 24, note: "拖动滑块或点 ± 微调（10~24px）；字号变化自动适配输入框，文字不溢出。" },
    { key: "text_font", label: "文本字体", opts: [["songti", "宋体"], ["kaiti", "楷体"], ["siyuan", "思源黑体"], ["pmingliu", "新细明体"]], note: "自定义校勘文字字体（横竖排同步）。" },
  ] },
];

// 前端新增项 export_with_annot 走 localStorage（后端 /api/settings 只认白名单键，不持久未知键）
const EWA_KEY = "gf-export-with-annot";
const gfReadExportAnnot = () => { try { return localStorage.getItem(EWA_KEY) === "1"; } catch (e) { return false; } };
const gfWriteExportAnnot = (v) => { try { localStorage.setItem(EWA_KEY, v ? "1" : "0"); } catch (e) {} };

function renderSettingsPanel() {
  const body = $("#setBody");
  body.innerHTML = "";
  for (const sec of SET_SCHEMA) {
    const d = document.createElement("div"); d.className = "set-sec";
    const collapsible = !!sec.collapsible;            // 设置分区可折叠并默认收起
    if (collapsible) d.classList.add("set-collapsible", "collapsed");
    const arrow = collapsible
      ? '<svg class="set-arrow" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>'
      : "";
    d.innerHTML = `<div class="set-sec-h">${sec.title}${arrow}</div>`;
    const wrap = document.createElement("div"); wrap.className = "set-sec-body";
    for (const it of sec.items) {
      const row = document.createElement("div"); row.className = "set-row";
      if (it.type === "knob") {                       // 改造段⑥：字号旋钮（滑块 + ± 微调）
        row.innerHTML = `<span class="set-label">${it.label}</span>
          <span class="knob">
            <button class="btn btn-micro" data-knob="${it.key}" data-d="-1">−</button>
            <input type="range" aria-label="${it.label}" min="${it.min}" max="${it.max}" step="1" data-range="${it.key}">
            <button class="btn btn-micro" data-knob="${it.key}" data-d="1">＋</button>
            <span class="knob-val" data-kval="${it.key}"></span>
          </span>`;
      } else {
        const seg = it.opts.map(([v, lab]) =>
          `<button class="btn btn-seg" data-key="${it.key}" data-val='${JSON.stringify(v)}'>${lab}</button>`).join("");
        row.innerHTML = `<span class="set-label">${it.label}</span><span class="seg">${seg}</span>`;
      }
      wrap.appendChild(row);
      const note = document.createElement("div"); note.className = "set-note"; note.textContent = it.note;
      wrap.appendChild(note);
    }
    d.appendChild(wrap);
    body.appendChild(d);
  }
  // 可折叠分区：点标题/箭头展开收起
  body.querySelectorAll(".set-collapsible .set-sec-h").forEach((h) =>
    h.onclick = () => h.parentElement.classList.toggle("collapsed"));
  // 二元分段单选
  body.querySelectorAll(".btn-seg").forEach((b) => b.onclick = () => {
    const v = JSON.parse(b.dataset.val);
    if (b.dataset.key === "engine_pref") return setEnginePreference(v);
    settings[b.dataset.key] = v;
    if (b.dataset.key === "canvas_bg") {
      if (v === "custom") $("#bgImgInput").click();
      else { customBgUrl = null; applyCanvasBg(); }   // 选纯色=切回纯色模式
    }
    if (b.dataset.key === "theme_mode") applyThemeMode(v, true);
    if (b.dataset.key === "export_with_annot") gfWriteExportAnnot(v);             // 前端项即时落 localStorage
    if (b.dataset.key === "text_font") {                 // 文本字体：即时预览，无需先点保存
      const host = $("#editorBody");
      if (host) host.dataset.font = v;
    }
    updateSegBtns();
  });
  // 字号旋钮：滑块拖动 + ± 微调（即时映射 --txt-size，文字自适应输入框）
  body.querySelectorAll("input[data-range]").forEach((r) => r.oninput = () => {
    settings[r.dataset.range] = parseInt(r.value, 10); updateKnobs(); liveTextSize();
  });
  body.querySelectorAll("button[data-knob]").forEach((b) => b.onclick = () => {
    const it = findItem(b.dataset.knob);
    const v = Math.max(it.min, Math.min(it.max, (settings[b.dataset.knob] | 0) + parseInt(b.dataset.d, 10)));
    settings[b.dataset.knob] = v; updateKnobs(); liveTextSize();
  });
}
function findItem(key) { for (const s of SET_SCHEMA) for (const it of s.items) if (it.key === key) return it; }

function updateSegBtns() {
  $("#setBody").querySelectorAll(".btn-seg").forEach((b) =>
    b.classList.toggle("on", JSON.stringify(settings[b.dataset.key]) === b.dataset.val));
  updateKnobs();
}
function updateKnobs() {
  $("#setBody").querySelectorAll("input[data-range]").forEach((r) => { r.value = settings[r.dataset.range]; });
  $("#setBody").querySelectorAll(".knob-val").forEach((s) => { s.textContent = settings[s.dataset.kval] + "px"; });
}
function liveTextSize() {
  const host = $("#editorBody"); if (host) host.style.setProperty("--txt-size", (settings.text_size || 16) + "px");
}

// 新增⑥：画布背景应用——自定义图覆盖纯色；无自定义图则回退纯黑/深灰/米白
let customBgUrl = null;
function applyCanvasBg() {
  const left = $("#left");
  const bg = settings.canvas_bg === "custom" && !customBgUrl ? "black" : settings.canvas_bg;
  left.className = "bg-" + bg;
  if (customBgUrl) {
    left.style.backgroundImage = `url("${customBgUrl}")`;
    left.style.backgroundSize = "cover";
    left.style.backgroundPosition = "center";
  } else {
    left.style.backgroundImage = "";
  }
}

// hide-rowops 单一信源：纯净模式 或 设置关闭行工具栏 → 隐藏（togglePure 与 applyAllSettings 共用，避免两处公式漂移）
function applyRowOpsVisibility() {
  document.body.classList.toggle("hide-rowops", (typeof pureMode !== "undefined" && pureMode) || !settings.show_row_ops);
}
function applyAllSettings() {   // 把配置实时映射到界面
  $("#zoomCtl").style.display = settings.show_zoom_ctl ? "" : "none";
  applyCanvasBg();
  document.body.classList.toggle("hide-boxes", !settings.show_boxes);
  if (typeof syncBoxToggle === "function") syncBoxToggle();
  // 低置信标红统一开关：单一 lowconf_red 同时控制底图红框 + 横排 + 竖排点校文字标红
  document.body.classList.toggle("no-lowred", !settings.lowconf_red);
  document.body.classList.toggle("no-lowred-v", !settings.lowconf_red);
  document.body.classList.toggle("img-hd", settings.img_quality === "hd");
  document.body.classList.toggle("img-lite", settings.img_quality === "lite");
  applyRowOpsVisibility();
  document.body.classList.toggle("no-drag-anim", !settings.drag_anim);
  const host = $("#editorBody");
  if (host) { host.dataset.font = settings.text_font; host.style.setProperty("--txt-size", (settings.text_size || 16) + "px"); }
  if (typeof proof !== "undefined" && proof) {       // 应用持久默认排版/校读模式并重绘右栏
    currentLayout = settings.text_layout || "horizontal";
    proofMode = settings.proof_mode || "page";
    syncLayoutButtons(); syncProofModeButtons(); renderEditor();
    if (typeof layoutImage === "function") layoutImage();
  }
  setupAutosave();
}

function applyThemeMode(mode, announce) {
  const dark = mode === "dark";
  document.body.classList.toggle("gf-dark", dark);
  settings.theme_mode = dark ? "dark" : "light";
  try { localStorage.setItem("gf-theme", settings.theme_mode); } catch (e) {}
  if (announce && typeof toast === "function") toast(dark ? "已切换深色主题" : "已切换浅色主题");
}

function persistEnginePreference() {
  api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engine_pref: settings.engine_pref || "" }) }).catch(() => {});
}

function syncImportEngineSwitch() {
  const importModal = document.querySelector("#importModal");
  if (!importModal) return;
  importModal.querySelectorAll("[data-engine]").forEach((button) =>
    button.classList.toggle("on", button.dataset.engine === (settings.engine_pref || "")));
}
function setEnginePreference(value) {
  settings.engine_pref = value || "";
  persistEnginePreference();
  updateSegBtns();
  syncImportEngineSwitch();
}

let autosaveTimer = null;
function setupAutosave() {
  if (autosaveTimer) { clearInterval(autosaveTimer); autosaveTimer = null; }
  const sec = settings.autosave | 0;
  if (sec > 0) autosaveTimer = setInterval(() => { if (proof) save(); }, sec * 1000);
}

async function initSettings() {
  renderSettingsPanel();
  let fetched = false;
  try { Object.assign(settings, await api("/api/settings")); fetched = true; } catch (e) {}
  // v2 一次性迁移：默认校读改为整页——存量配置若还是逐行，翻一次为整页（用户仍可在设置改回，之后不再动）。
  // 仅在设置真正拉取成功后打标志：未登录/离线的加载不消耗迁移机会。
  try {
    if (fetched && !localStorage.getItem("gf-proofmode-v2")) {
      localStorage.setItem("gf-proofmode-v2", "1");
      if (settings.proof_mode === "row") {
        settings.proof_mode = "page";
        api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proof_mode: "page" }) }).catch(() => {});
      }
    }
  } catch (e) {}
  try {
    if (fetched && !localStorage.getItem("gf-boxes-hidden-v3")) {
      localStorage.setItem("gf-boxes-hidden-v3", "1");
      settings.show_boxes = false;
      api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ show_boxes: false }) }).catch(() => {});
    }
  } catch (e) {}
  if (settings.engine_pref === "onnx") settings.engine_pref = "ppocrv6_onnx";
  if (!["local", "off"].includes(settings.punct_backend)) settings.punct_backend = "local";
  try { settings.theme_mode = localStorage.getItem("gf-theme") === "dark" ? "dark" : "light"; } catch (e) { settings.theme_mode = "light"; }
  settings.confirm_delete = true;                       // 锁定：删除一律二次确认（开关已从面板移除）
  settings.export_with_annot = gfReadExportAnnot();     // 前端项从 localStorage 恢复
  updateSegBtns(); syncImportEngineSwitch(); applyAllSettings();
  $("#settingsBtn").onclick = () => { updateSegBtns(); $("#settingsModal").classList.remove("hidden"); };
  $("#setSave").onclick = saveSettings;
  $("#setCancel").onclick = () => $("#settingsModal").classList.add("hidden");
  $("#setReset").onclick = resetSettings;
  // 新增⑥：选中本地图片→objectURL 即时作为画布背景（不上传、不入 settings.json）
  const importModal = document.querySelector("#importModal");
  if (importModal) {
    importModal.querySelectorAll("[data-engine]").forEach((button) => {
      button.onclick = () => setEnginePreference(button.dataset.engine);
    });
  }
  $("#bgImgInput").onchange = (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (customBgUrl) URL.revokeObjectURL(customBgUrl);
    customBgUrl = URL.createObjectURL(f);
    settings.canvas_bg = "custom";
    applyCanvasBg();
    updateSegBtns();
    e.target.value = "";                       // 允许重复选同一文件
    toast("已应用自定义背景图");
  };
}
async function saveSettings() {
  try {
    const r = await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
    const themeMode = settings.theme_mode;
    Object.assign(settings, r.settings); settings.theme_mode = themeMode; applyAllSettings();
    $("#settingsModal").classList.add("hidden"); toast("设置已保存");
  } catch (e) { toast("保存失败：" + e.message); }
}
async function resetSettings() {
  try {
    const r = await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reset: true }) });
    settings = r.settings;
    settings.confirm_delete = true;                      // 重置后仍锁定二次确认
    settings.export_with_annot = false; gfWriteExportAnnot(false);   // 前端项一并重置
    try { settings.theme_mode = localStorage.getItem("gf-theme") === "dark" ? "dark" : "light"; } catch (e) { settings.theme_mode = "light"; }
    if (customBgUrl) { URL.revokeObjectURL(customBgUrl); customBgUrl = null; }   // 重置=清自定义背景图
    updateSegBtns(); syncImportEngineSwitch(); applyAllSettings(); toast("已恢复默认设置");
  } catch (e) { toast("重置失败：" + e.message); }
}
