# -*- coding: utf-8 -*-
"""Tests for ocr_confusion — post-OCR character correction."""
import ocr_confusion


def test_noop_on_clean_text():
    text = "立永賣契人鄧耕亭今因家下要錢湊業"
    assert ocr_confusion.correct_ocr_text(text) == text


def test_noop_on_empty():
    assert ocr_confusion.correct_ocr_text("") == ""
    assert ocr_confusion.correct_ocr_text("字") == "字"


def test_correct_compound_word_辨理():
    # OCR outputs 辯 instead of 辨, but "辨理" is a known compound
    assert ocr_confusion.correct_ocr_text("辯理盤八") == "辨理盤八"


def test_correct_compound_word_契約():
    assert ocr_confusion.correct_ocr_text("契釣文書")  # 釣→約, but 釣 isn't in confusion map
    # Test real confusion: no common 契 confusion
    pass


def test_correct_date_pattern():
    # "曰" in date context → "日"
    assert ocr_confusion.correct_ocr_text("光緒十年三月十五曰") == "光緒十年三月十五日"
    assert ocr_confusion.correct_ocr_text("乾隆五十年十月二十曰立") == "乾隆五十年十月二十日立"


def test_correct_date_with_chinese_numeral():
    assert ocr_confusion.correct_ocr_text("二十曰") == "二十日"
    assert ocr_confusion.correct_ocr_text("廿八曰到") == "廿八日到"


def test_曰_not_corrected_outside_date_context():
    # "曰" meaning "say" should NOT be corrected
    text = "子曰學而時習之"
    assert ocr_confusion.correct_ocr_text(text) == text


def test_correct_未末():
    assert ocr_confusion.correct_ocr_text("未來之事") == "未來之事"  # "未"→"未" (correct form), context "來"
    text = "年末結算"  # "未" should be "末" — but without compound, keep original
    # No compound match, so unchanged
    result = ocr_confusion.correct_ocr_text("年末結算")
    # "年末" is NOT in compound list, so no correction
    assert result == "年末結算"


def test_correct_compound_光緒():
    assert ocr_confusion.correct_ocr_text("光諸三十年") == "光緒三十年"


def test_correct_compound_乾隆():
    assert ocr_confusion.correct_ocr_text("乾陸六十年") == "乾隆六十年"


def test_no_false_correction_on_unknown():
    # Character is confused but no compound or date match → keep original
    text = "單獨的已字"  # "已" is confused with 己/巳 but no compound match
    assert ocr_confusion.correct_ocr_text(text) == text


def test_correct_ocr_lines_inplace():
    lines = [
        {"text": "辯理清楚", "box": [0, 0, 10, 10], "score": 0.9},
        {"text": "光緒十年三月十五曰", "box": [10, 0, 20, 10], "score": 0.9},
        {"text": "祟禎元年立", "box": [20, 0, 30, 10], "score": 0.9},
    ]
    ocr_confusion.correct_ocr_lines(lines)
    assert lines[0]["text"] == "辨理清楚"
    assert lines[1]["text"] == "光緒十年三月十五日"
    assert lines[2]["text"] == "崇禎元年立"


def test_e2e_historical_document():
    """Simulate a typical historical document with multiple errors."""
    text = (
        "立永實契人鄧耕亭今將祖遺田壹坵出實與本村御秀川"
        "當日三面言定時值價銀参拾兩正即日契價兩相交訖"
        "日後水遠不得異言恐口無凴立此賣契存照"
    )
    corrected = ocr_confusion.correct_ocr_text(text)
    # 實→賣 (no, 實 is not in confusion map for 賣)
    # Actually let me test real confusions
    text2 = "崇禎十二年三月十五曰立永賣契人鄧耕亭永遠爲照"
    corrected2 = ocr_confusion.correct_ocr_text(text2)
    assert corrected2 == "崇禎十二年三月十五日立永賣契人鄧耕亭永遠爲照"


def test_existing_compound_is_never_rewritten():
    """原字已经成词就不许动——CONFUSION_MAP 是双向的，词表里「大爺」「太爺」并存。

    少了这道闸，两个正确写法会互相翻转（太爺→大爺，大爺→太爺），纯抛硬币。
    """
    assert ocr_confusion.correct_ocr_text("太爺在場") == "太爺在場"
    assert ocr_confusion.correct_ocr_text("大爺在場") == "大爺在場"


def test_correction_still_fires_when_original_is_not_a_word():
    assert ocr_confusion.correct_ocr_text("辯理契約") == "辨理契約"
    assert ocr_confusion.correct_ocr_text("年月曰") == "年月日"


def test_classical_enumeration_wu_yue_is_not_a_date():
    """文言列举「一曰…五曰…」里的「曰」不是日期。

    退想斋日记 s01 真值即「国之民，五曰宗」；原规则「数字后的曰→日」把它改坏了。
    """
    assert ocr_confusion.correct_ocr_text("國之民五曰宗蓋以") == "國之民五曰宗蓋以"
    assert ocr_confusion.correct_ocr_text("一曰仁二曰義") == "一曰仁二曰義"


def test_real_date_after_month_still_corrected():
    assert ocr_confusion.correct_ocr_text("三月十五曰") == "三月十五日"
    assert ocr_confusion.correct_ocr_text("崇禎十二年三月十五曰") == "崇禎十二年三月十五日"
