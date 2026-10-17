"use strict";
/* 点校句子/竖条拖拽排序 —— 已按产品要求停用（2026-06 重设计）。
 * 用户要求：点校区所有框不可点击拖动调整顺序。
 * 保留空入口 initRowDrag(rowEl, id) 供 editor.js 调用（不绑定任何拖拽事件），
 * 既不报错也不改 editor.js。面板宽度拖拽(#divider/#nbResize)与导入素材排序
 * (importer.js 的 .imp-row) 不在本文件，照常工作、不受影响。 */
function initRowDrag(rowEl, id) { /* no-op：点校拖拽排序已停用 */ }
