# -*- coding: utf-8 -*-
"""每用户运行上下文：把单一 _work 切成 _work/users/<uid>/，实现多用户数据隔离。

current_user：FastAPI 依赖，从 sid cookie 解析登录用户，未登录抛 401。
Ctx：当前用户的工作目录与各路径；reg(batch) 直接从磁盘 proof.json 派生（消除全局可变态，
天然多用户安全——每个请求只触碰自己 uid 目录下的数据）。
"""
import json
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException

import appconfig
import auth
import license_api

WORK = appconfig.data_root()
USERS_ROOT = WORK / "users"

COOKIE = "sid"

# 单机模式的固定本机用户：数据落 _work/users/local/，与多用户路径结构一致（uid="local"）。
LOCAL_USER = {"id": "local", "username": "local", "display": "本机用户"}


def current_user(sid: str = Cookie(default=None)):
    """登录闸。single 模式直接给本机用户（无登录）；multi 模式 sid cookie → 用户，未登录抛 401。"""
    if appconfig.is_single():
        return dict(LOCAL_USER)
    u = auth.get_session_user(sid)
    if not u:
        raise HTTPException(401, "未登录")
    return u


class Ctx:
    """当前登录用户的工作上下文。所有路径均落在 _work/users/<uid>/ 内。"""

    def __init__(self, user):
        self.user = user
        self.uid = str(user["id"])
        self.work = USERS_ROOT / self.uid
        self.work.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.work / "settings.json"
        self.notebooks_path = self.work / "notebooks.json"
        self.progress_path = self.work / "_import_progress.json"
        self.uploads = self.work / "_uploads"

    def write_progress(self, d):
        try:
            self.progress_path.write_text(json.dumps(d), encoding="utf-8")
        except Exception:
            pass

    def read_progress(self):
        if self.progress_path.exists():
            try:
                return json.loads(self.progress_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"phase": "idle"}

    def reg(self, batch):
        """从磁盘 proof.json 派生批次路径登记（取代旧全局 REG）。找不到返回 None。

        batch 须为已规范化的名字（调用方过 safefs.safe_batch / coerce_batch）。"""
        if not batch:
            return None
        bdir = self.work / batch
        proof_path = bdir / "proof.json"
        meta_path = bdir / "document.json"
        if not proof_path.exists() and not meta_path.exists():
            return None
        try:
            source_path = proof_path if proof_path.exists() else meta_path
            proof = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception:
            proof = {}
        image_dir = proof.get("image_dir") or str(bdir / "_src")
        return {"image_dir": image_dir, "proof_path": str(proof_path),
                "recog_path": str(bdir / "_recog.json"),
                "engine": proof.get("engine", "paddle")}

def _single_mode_authorized(sid):
    """single 模式下，是否有权访问正文/数据接口——与 /api/me 汇报给前端的口径保持一致。

    ⚠此前 current_user() 在 single 模式下无条件放行 LOCAL_USER，account_gate() 只在
    /api/me 里跑，只影响"要不要弹登录窗"这个 UI 判断，从未拦过 content_api/export_api/
    library_api 等真正读写数据的接口——curl 直打这些接口可绕开登录/试用到期完全免验证。
    这里补上同一套裁决（云账号 account_gate 或本机 sid 会话二选一），未过闸直接拒绝。

    云封禁即时生效：如果本机曾经有过云账号凭据且被服务器拒绝（disabled/expired），
    则不回退到本地 sid 兜底——确保管理员后台封禁后用户无法通过本地会话继续使用。"""
    account, _ = license_api.account_gate()
    if account:
        return True
    # 云账号被服务器明确拒绝（封禁/到期/登出）：不放行本地 sid 兜底。
    d = license_api.store.load(license_api._path())
    if d.get("account_block_reason"):
        return False
    if d.get("account_cred") and not d.get("account"):
        return False
    return bool(auth.get_session_user(sid))


def ctx_dep(user=Depends(current_user), sid: str = Cookie(default=None)):
    """FastAPI 依赖：登录/授权校验 + 构造当前用户 Ctx。

    single 模式下 uid 仍固定为 LOCAL_USER（"local"），不随登录账号切换——避免同一台机器
    的既有数据因账号身份变化而"搬家"；这里只做放行与否的裁决，不改变数据落盘路径。"""
    if appconfig.is_single() and not _single_mode_authorized(sid):
        raise HTTPException(401, "未登录")
    return Ctx(user)
