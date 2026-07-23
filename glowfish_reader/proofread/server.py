# -*- coding: utf-8 -*-
"""Glowfish Reader 史料阅读器 多用户网页版 —— 应用装配 + 跨平台启动入口。

单机/内网多用户：注册/登录后各自隔离的史料工作区（_work/users/<uid>/，互不可见）。
后端按职责拆分：auth_api(认证) / content_api(上传·导入·识别·编辑·出图) /
export_api(导出下载) / library_api(设置·笔记本·删改)。识别外包 paddleocr env 子进程。
素材只走本机回环、落本机磁盘，不外呼（自动断句使用本地古文标点 ONNX）。

启动（host/port/引擎/是否开浏览器由 appconfig 决定，SHUPAI_* 环境变量可覆盖）：
  python server.py        # 多用户网页版手动起服务（桌面 App 入口走 desktop_app.py）
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import appconfig
import auth_api
import content_api
import export_api
import library_api
import update_api
import notice_api
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
# 授权码门禁已移除：业务路由（content/export/library）不再挂授权门，直接放行。
# 账号系统（手机号/短信登录，auth_api）与升级/公告（update/notice）保留。
app.include_router(auth_api.router)
app.include_router(update_api.router)
app.include_router(notice_api.router)
app.include_router(capabilities_api.router)
app.include_router(content_api.router)
app.include_router(export_api.router)
app.include_router(library_api.router)

# 静态前端：login.html 无需鉴权；index.html 由 auth-guard.js 处理登录态
# （单机模式自动豁免登录），业务 /api/* 不再有授权门。
app.mount("/", StaticFiles(directory=str(ui_assets.ui_dist()), html=True), name="static")


if __name__ == "__main__":
    from launcher import serve
    serve(app, appconfig)
