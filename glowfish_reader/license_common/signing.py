# -*- coding: utf-8 -*-
"""Shared signing-envelope canonicalization."""
import json


def canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
