# -*- coding: utf-8 -*-
"""授权缓存并发安全：模拟导入大批文件时大量受门请求并发读改写 license.json，
凭据不得被并发覆写丢失、文件始终是合法 JSON（修 14+ 文件"未授权"根因）。"""
import json
import threading
from pathlib import Path

from licensing import store


def test_concurrent_save_never_corrupts(tmp_path):
    p = str(tmp_path / "license.json")
    store.save(p, {"account_cred": "CRED-OK"})   # 先写入凭据
    errors = []

    def worker(i):
        try:
            for _ in range(40):
                store.save(p, {"max_seen_ts": i})       # 模拟心跳并发写
                d = store.load(p)
                assert d["account_cred"] == "CRED-OK"  # 凭据不得被并发写丢
        except Exception as e:
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    json.loads(Path(p).read_text(encoding="utf-8"))     # 文件始终合法 JSON
    assert store.load(p)["account_cred"] == "CRED-OK"
