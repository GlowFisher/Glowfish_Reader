# -*- coding: utf-8 -*-
import recognize_ppocrv6_onnx as ocr


def test_inference_budget_caps_extra_predictions():
    budget = ocr.InferenceBudget(max_extra_predicts=3, soft_time_limit_seconds=999)
    assert [budget.allow() for _ in range(3)] == [True, True, True]
    assert budget.allow() is False
    assert budget.extra_predicts == 3
    assert budget.exhausted is True


def test_inference_budget_honors_soft_deadline(monkeypatch):
    budget = ocr.InferenceBudget(soft_time_limit_seconds=10, started_at=100)
    monkeypatch.setattr(ocr.time, "monotonic", lambda: 111)
    assert budget.allow() is False
    assert budget.exhausted is True
