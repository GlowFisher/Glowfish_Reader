# -*- coding: utf-8 -*-
"""极简 /api/me 桩：账号系统归档后，保留给自检与潜在探测使用。

single: False 表示「无需登录、直接放行」——本机单用户，无登录/授权门。
"""
from fastapi import APIRouter

from userctx import LOCAL_USER

router = APIRouter()


@router.get("/api/me")
def me():
    return {**LOCAL_USER, "single": False}
