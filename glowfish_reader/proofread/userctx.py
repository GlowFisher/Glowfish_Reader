# -*- coding: utf-8 -*-
"""本机单用户运行上下文：数据落 _work/users/local/。

current_user：FastAPI 依赖，本机单用户模式恒返回本机用户（无登录/授权门）。
Ctx：当前用户的工作目录与各路径；reg(batch) 直接从磁盘 proof.json 派生（消除全局可变态）。
"""
import json
from pathlib import Path

from fastapi import Cookie, Depends

import appconfig

WORK = appconfig.data_root()
USERS_ROOT = WORK / "users"

COOKIE = "sid"

# 本机单用户模式固定用户：数据落 _work/users/local/。
LOCAL_USER = {"id": "local", "username": "local", "display": "本机用户"}


def current_user(sid: str = Cookie(default=None)):
    """本机单用户模式直接返回本机用户（无登录）。"""
    return dict(LOCAL_USER)


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

def ctx_dep(user=Depends(current_user), sid: str = Cookie(default=None)):
    """FastAPI 依赖：本机单用户模式直接构造当前用户 Ctx，无登录/授权校验。"""
    return Ctx(user)
