# -*- coding: utf-8 -*-
"""Glowfish Reader 史料阅读器 —— 应用装配 + 跨平台启动入口。

本机单用户模式：无登录，史料工作区固定落 _work/users/local/。
后端按职责拆分：content_api(上传·导入·识别·编辑·出图) /
export_api(导出下载) / library_api(设置·笔记本·删改)。识别外包 paddleocr env 子进程。
素材只走本机回环、落本机磁盘，不外呼（自动断句使用本地古文标点 ONNX）。

启动（host/port/引擎/是否开浏览器由 appconfig 决定，SHUPAI_* 环境变量可覆盖）：
  python server.py        # 手动起服务（桌面 App 入口走 desktop_app.py）
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import appconfig
import content_api
import export_api
import library_api
import me_api
import capabilities_api
import ui_assets
import subprocess_env

# 数据根目录由 appconfig 决定（开发态 _work/，打包态 %APPDATA%）；单机用户落 users/local/。
(appconfig.data_root() / "users").mkdir(parents=True, exist_ok=True)
OCR_CACHE = subprocess_env.prepare_ocr_environment(cleanup_legacy=True)

app = FastAPI(title="Glowfish Reader 史料阅读器")


@app.on_event("shutdown")
def shutdown_ocr_processes():
    content_api.shutdown_ocr()


@app.get("/health")
def health():
    return {"ok": True}


# API/出图路由须在静态 catch-all 之前注册，才能优先于 "/" 挂载点命中。
# 账号/授权/升级/公告功能已归档（见 archived/），本机单用户模式直接放行，无授权门。
app.include_router(me_api.router)
app.include_router(capabilities_api.router)
app.include_router(content_api.router)
app.include_router(export_api.router)
app.include_router(library_api.router)

# 静态前端：本机单用户，无需登录页/登录闸。
app.mount("/", StaticFiles(directory=str(ui_assets.ui_dist()), html=True), name="static")


if __name__ == "__main__":
    from launcher import serve
    serve(app, appconfig)
