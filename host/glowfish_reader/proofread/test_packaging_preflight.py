# -*- coding: utf-8 -*-
from pathlib import Path

import packaging_preflight


SPEC = Path(__file__).with_name("glowfish_reader.spec")


def test_preflight_accepts_current_ocr_core_environment():
    summary, failures = packaging_preflight.check_preflight()

    assert summary
    assert failures == []


def test_spec_copies_metadata_into_datas_not_analysis_kwargs():
    text = SPEC.read_text(encoding="utf-8")

    assert "copy_metadata" in text
    assert "datas += copy_metadata(_dist_name)" in text
    assert "copy_metadata=" not in text
    assert "BUNDLE_METADATA_DISTRIBUTIONS" in text


def test_spec_bundles_real_ocr_smoke_fixture():
    text = SPEC.read_text(encoding="utf-8")

    assert "vertical_cht_clean.png" in text
    assert 'os.path.join("assets", "selftest")' in text
