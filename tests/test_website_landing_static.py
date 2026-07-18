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

    def test_faq_omits_the_expired_trial_question(self):
        self.assertNotIn("试用期结束后怎么办？", read_index())

    def test_core_capabilities_expose_the_confirmed_tabs(self):
        html = read_index()

        expected_labels = ["精准识别", "图文对照", "校对批注", "一键导出", "个性设置", "数据隐私"]
        for label in expected_labels:
            self.assertIn(f">{label}</button>", html)

        self.assertIn('aria-controls="feature-panel-export" data-slide-target="3">一键导出</button>', html)
        self.assertIn('aria-controls="feature-panel-personalization" data-slide-target="4">个性设置</button>', html)
        self.assertIn('id="feature-panel-export"', html)
        self.assertIn('id="feature-panel-personalization"', html)

    def test_core_capability_panels_use_the_confirmed_example_images(self):
        html = read_index()
        expected_panels = {
            "intro": "识别示例.png",
            "compare": "图文对照示例.png",
            "annotation": "批注示例.png",
            "export": "导出示例.png",
            "personalization": "个性设置新版.jpg",
        }

        for panel_id, filename in expected_panels.items():
            panel = html.split(f'id="feature-panel-{panel_id}"', 1)[1].split("</article>", 1)[0]
            self.assertIn(f'src="assets/img/features/{filename}"', panel)
            self.assertTrue((WEBSITE / "assets" / "img" / "features" / filename).is_file())

        self.assertIn("感谢百度PaddleOCR模型的开源共享", html)
        self.assertIn('assets/css/base.css?v=20260718a', html)

    def test_landing_page_uses_the_confirmed_capability_and_trial_copy(self):
        html = read_index()

        expected_copy = [
            "高精度史料识别、图文对照、支持校对批注、自动标点、一键导出、个性化设置、数据永不上云。",
            "手机号注册即免费试用，到期后续期即可继续使用。",
            "原图、文本、注释一键导出史料长编",
            "一键导出原图、识别文本与注释，完整生成可编辑、打印的史料长编 DOCX 文档，也可导出 Markdown 格式，方便 Obsidian 等软件识读。",
            "按自己的习惯安排工作台",
            "自由度极高的点校",
            "点击底图区的“识”直接进入框识模式，可以重新框选，模型自动重新识别一次并加入到对应位置，也可以擦除掉不需要识别的区域。识读区支持整页点校与逐行点校两种模式。",
            "批注随文，随看随批",
            "划选文字即可落批注，鼠标移动到文字上方自动浮现。",
            "设置区分为通用、底图区、点区设置三块，支持深浅色主题切换、画布切换、模型切换、繁简体转换、横竖排转换、自动标点、自动断句、字体切换等功能。",
        ]
        for text in expected_copy:
            self.assertIn(text, html)

    def test_follow_section_uses_the_replacement_wechat_qr_code(self):
        html = read_index()

        self.assertIn('src="assets/img/qr-wechat-contact.png"', html)
        self.assertTrue((WEBSITE / "assets" / "img" / "qr-wechat-contact.png").is_file())

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
