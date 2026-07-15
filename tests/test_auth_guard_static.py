# -*- coding: utf-8 -*-
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_static(name):
    return (ROOT / "src" / name).read_text(encoding="utf-8")


def test_auth_guard_does_not_suppress_login_for_single_mode():
    auth_guard = read_static("auth-guard.js")

    assert "let singleMode = false;" not in auth_guard
    assert "if (singleMode) return;" not in auth_guard
    assert "window.GlowfishLoginModal.open(" in auth_guard


def test_expired_notice_flows_from_me_to_login_modal():
    """到期通知链路：/api/me 的 notice → toLogin → GlowfishLoginModal.open({notice}) → setMsg。"""
    auth_guard = read_static("auth-guard.js")
    modal = read_static("login-modal.js")

    assert "me.notice" in auth_guard                     # single 分支须把 notice 传给登录闸
    assert "notice" in auth_guard.split("const toLogin", 1)[1].split("};", 1)[0]
    assert "opts" in modal.split("open(", 1)[1].split(")", 1)[0]     # open 接收参数
    assert "opts.notice" in modal                        # 弹窗打开时展示通知文案


def test_logout_always_posts_logout_and_returns_to_login_flow():
    auth_guard = read_static("auth-guard.js")
    logout_block = auth_guard.split("if (out) out.onclick = async () => {", 1)[1].split("};", 1)[0]

    assert "if (me.single)" not in logout_block
    assert 'await _fetch("/api/logout", { method: "POST" });' in logout_block
    assert 'localStorage.removeItem("gf_user")' in logout_block
    assert "location.reload();" in logout_block
