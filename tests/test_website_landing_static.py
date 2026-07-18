# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "glowfish_reader" / "website"
INDEX = WEBSITE / "index.html"


def read_index():
    return INDEX.read_text(encoding="utf-8")


class WebsiteLandingStaticTests(unittest.TestCase):
    def test_landing_page_uses_the_confirmed_trial_copy(self):
        html = read_index()

        self.assertEqual(html.count("注册账号即免费试用"), 2)
        self.assertNotIn("注册账号享 14 天免费试用", html)

    def test_core_capabilities_expose_the_confirmed_tabs(self):
        html = read_index()

        expected_labels = ["精准识别", "图文对照", "校对批注", "一键导出", "个性设置", "数据隐私"]
        for label in expected_labels:
            self.assertIn(f">{label}</button>", html)

        self.assertIn('aria-controls="feature-panel-export" data-slide-target="3">一键导出</button>', html)
        self.assertIn('aria-controls="feature-panel-personalization" data-slide-target="4">个性设置</button>', html)
        self.assertIn('id="feature-panel-export"', html)
        self.assertIn('id="feature-panel-personalization"', html)

    def test_each_recognition_scene_uses_its_corresponding_sample_image(self):
        html = read_index()
        expected_scenes = {
            "contract": "契约示例.png",
            "genealogy": "族谱示例.png",
            "diary": "日记示例.png",
            "newspaper": "报纸示例.png",
            "journal": "期刊示例.png",
            "gazetteer": "方志示例.png",
        }

        for scene, filename in expected_scenes.items():
            panel = html.split(f'id="scene-panel-{scene}"', 1)[1].split("</article>", 1)[0]
            self.assertIn(f'src="assets/img/scenes/{filename}"', panel)
            self.assertTrue((WEBSITE / "assets" / "img" / "scenes" / filename).is_file())
