# -*- coding: utf-8 -*-
"""每用户设置读写（content_api 导入/导出取默认值、library_api 设置面板共用）。

设置随登录用户走，落 _work/users/<uid>/settings.json。
"""
import json

# 全量设置（底图区 / 点校区 / 底部通用）——与旧单人版默认一致，逐键白名单
DEFAULT_SETTINGS = {
    # 底图区
    "show_zoom_ctl": True, "canvas_bg": "black", "canvas_bg_image": "", "show_boxes": False,
    "pan_bound": True, "img_quality": "balanced",
    "lowconf_red": True,
    # 点校区
    "default_script": "s", "punct_pos": "caret", "confirm_delete": True,
    "text_layout": "horizontal", "text_font": "songti", "text_size": 16,
    "drag_anim": True, "show_row_ops": True, "punct_backend": "local", "proof_mode": "page",
    "engine_pref": "",              # 识别引擎偏好：""=满血版 / "ppocrv6_onnx"=轻量版
    "ocr_acceleration": "cpu",     # CPU default; GPU can opt in only after runtime self-test
    # 底部通用
    "export_format": "docx", "export_with_image": False, "export_page_marks": False,
    "export_last_dir": "",          # 记忆上次导出保存目录（桌面端原生保存对话框默认打开此处）
    "autosave": 0,
}


def _normalize_settings(s):
    if s.get("punct_backend") not in {"local", "off"}:
        s["punct_backend"] = "local"
    if s.get("engine_pref") == "onnx":
        s["engine_pref"] = "ppocrv6_onnx"
    if s.get("ocr_acceleration") not in {"cpu", "auto"}:
        s["ocr_acceleration"] = "cpu"
    return s


def load_settings(ctx):
    s = dict(DEFAULT_SETTINGS)
    p = ctx.settings_path
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return _normalize_settings(s)


def save_settings(ctx, s):
    ctx.settings_path.write_text(
        json.dumps(_normalize_settings(s), ensure_ascii=False, indent=2), encoding="utf-8")
