# -*- coding: utf-8 -*-
"""Post-OCR character confusion correction for historical Chinese documents.

Corrects common OCR errors caused by visually-similar characters (形近字).
Operates as a pure text post-processing step — no model inference, no external
data, no corpus needed.  The confusion table is a manually-curated list of
well-known OCR error pairs; compound words provide contextual disambiguation.

Correction rules (conservative — only correct when context provides evidence):
  1. If replacing a confused char with a candidate produces a known compound
     word in the surrounding text → correct.
  2. Date/number patterns (×年×月×曰 → ×年×月×日).
  3. Otherwise keep original — never guess.

Usage:
    import ocr_confusion
    text = ocr_confusion.correct_ocr_text(text)
"""

# ── Confusion map ────────────────────────────────────────────────────────────
# Key: OCR output character (commonly wrong).
# Value: list of characters it might actually be.
# Sorted by visual similarity category.

CONFUSION_MAP = {
    # --- Stroke count / closure -------------------------------------------------
    "已": ["己", "巳"],
    "己": ["已", "巳"],
    "巳": ["已", "己"],

    # --- Horizontal stroke presence ---------------------------------------------
    "末": ["未"],
    "未": ["末"],

    # --- Box closure (日/曰) ----------------------------------------------------
    "日": ["曰"],
    "曰": ["日"],

    # --- Leg variants (人/入/八) ------------------------------------------------
    "人": ["入", "八"],
    "入": ["人", "八"],
    "八": ["人", "入"],

    # --- Vertical stroke (千/干/于) ---------------------------------------------
    "千": ["干", "于"],
    "干": ["千", "于"],
    "于": ["千", "干"],

    # --- Horizontal stroke count (土/士, 王/玉, 大/太) -------------------------
    "土": ["士"],
    "士": ["土"],
    "王": ["玉"],
    "玉": ["王"],
    "大": ["太"],
    "太": ["大"],

    # --- Dot presence (午/牛, 貝/見, 問/間) ----------------------------------------
    "午": ["牛"],
    "牛": ["午"],
    "貝": ["見"],
    "見": ["貝"],
    "問": ["間"],
    "間": ["問"],

    # --- Radical variants -------------------------------------------------------
    "辯": ["辨"],
    "辨": ["辯"],
    "閒": ["閑", "間"],
    "閑": ["閒", "間"],
    "藉": ["籍"],
    "籍": ["藉"],
    "覆": ["復"],
    "復": ["覆"],

    # --- Similar right-side components ------------------------------------------
    "博": ["搏"],
    "搏": ["博"],
    "狠": ["狼"],
    "狼": ["狠"],
    "晴": ["睛"],
    "睛": ["晴"],
    "涼": ["晾"],
    "晾": ["涼"],

    # --- Historical document common ---------------------------------------------
    "貸": ["貨"],
    "貨": ["貸"],
    "栗": ["粟"],
    "粟": ["栗"],
    "崇": ["祟"],
    "祟": ["崇"],
    "侯": ["候"],
    "候": ["侯"],
    "折": ["拆"],
    "拆": ["折"],
    "烏": ["鳥"],
    "鳥": ["烏"],
    "鳴": ["嗚"],
    "嗚": ["鳴"],

    # --- Single-stroke difference -----------------------------------------------
    "刀": ["刁"],
    "刁": ["刀"],
    "萬": ["万"],
    "万": ["萬"],
    "几": ["凡"],
    "凡": ["几"],

    # --- Dot/water variants -----------------------------------------------------
    "准": ["淮", "準"],
    "淮": ["准"],
    "治": ["冶"],
    "冶": ["治"],
    "泠": ["冷"],
    "冷": ["泠"],

    # --- Additional historical common -------------------------------------------
    "令": ["今"],
    "今": ["令"],
    "甲": ["申", "由"],
    "申": ["甲", "由"],
    "由": ["甲", "申"],
    "風": ["鳳"],
    "鳳": ["風"],
    "曆": ["歷"],
    "歷": ["曆"],
    "鹹": ["減"],
    "減": ["鹹"],

    # --- Radical/semantic variants ----------------------------------------------
    "諸": ["緒"],
    "緒": ["諸"],
    "陸": ["隆"],
    "隆": ["陸"],
    "綉": ["繡"],
    "繡": ["綉"],
    "線": ["綠"],
    "綠": ["線"],
    "綿": ["錦"],
    "錦": ["綿"],
    "澤": ["擇"],
    "擇": ["澤"],
    "響": ["嚮"],
    "嚮": ["響"],
}

# ── Known compound words ──────────────────────────────────────────────────────
# Multi-character strings that are correct in historical Chinese documents.
# When a confused character, if replaced with a candidate, forms one of these
# compounds in the surrounding context, the correction is applied.

KNOWN_COMPOUNDS = {
    # Administrative / legal
    "辨理", "契約", "永遠", "永遠爲照", "永賣", "承租", "承買", "出賣",
    "出賃", "立契", "立約", "憑照", "印契", "契尾", "田契", "房契",
    "雍正", "乾隆", "嘉慶", "道光", "咸豐", "同治", "光緒", "宣統",
    "崇禎", "順治", "康熙", "萬曆", "永樂", "洪武",
    "年月日", "年月",

    # Common historical document terms
    "文契", "買主", "賣主", "中人", "代筆", "知見", "在場",
    "永遠管業", "任憑", "不得", "異言", "恐口", "無憑",
    "立永賣契", "立賣契", "永賣契", "杜賣契",
    "錢粮", "糧銀", "正項", "雜項",
    "此照", "爲照", "存照", "執照",

    # Financial / measurement
    "紋銀", "制錢", "銅錢", "銀兩",
    "升斗", "石斗", "畝分", "頃畝",

    # Common classical terms
    "是以", "於是", "然而", "雖然", "況且",
    "所有", "所謂", "可以", "何以",
    "皆因", "因爲", "倘若",

    # Title / honorific
    "大人", "老爺", "太爺", "太夫人", "孺人",
    "先生", "大爺", "兄台", "仁兄",

    # Time terms
    "今日", "明日", "昨日", "次日",
    "正月", "臘月", "冬月", "閏月",
    "初一日", "十五日", "三十日",
}

# ── Internals ─────────────────────────────────────────────────────────────────

_DIGIT_CHARS = "一二三四五六七八九十廿卅初"


def _is_digit_char(ch: str) -> bool:
    return ch.isdigit() or ch in _DIGIT_CHARS


def _forms_compound(chars, i, text) -> bool:
    """text 中位置 i 的字是否落在某个已知复合词内。"""
    n = len(chars)
    for win_len in (2, 3, 4):
        start = max(0, i - win_len + 1)
        end = min(i + 1, n - win_len + 1)
        for s in range(start, end):
            if text[s:s + win_len] in KNOWN_COMPOUNDS:
                return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def correct_ocr_text(text: str) -> str:
    """Apply confusion dictionary correction to OCR output text.

    Scans each character; if it's a known confusion candidate, checks whether
    replacing it with a possible correction produces a known compound word in
    the surrounding context.  Also handles date/number patterns.

    Conservative: only corrects when context provides positive evidence.
    Returns corrected text (may be identical to input if no corrections apply).
    """
    if not text:
        return text

    chars = list(text)
    n = len(chars)

    for i, ch in enumerate(chars):
        candidates = CONFUSION_MAP.get(ch)
        if not candidates:
            continue

        # 原字本来就成词就别动。词表里「大爺」「太爺」并存，而 CONFUSION_MAP 是双向的，
        # 少了这道闸，正确的「太爺」会被改成「大爺」，反之亦然——纯抛硬币。
        if _forms_compound(chars, i, "".join(chars)):
            continue

        corrected = None

        for candidate in candidates:
            # Build test string with replacement at position i
            test = "".join(chars[:i] + [candidate] + chars[i + 1:])

            # Rule 1: 替换后能凑出已知复合词 → 采纳
            if _forms_compound(chars, i, test):
                corrected = candidate
                break

            # Rule 2: 日期格式 —— 「年/月」或数字后面的「曰」应是「日」
            if ch == "曰" and candidate == "日" and i >= 1:
                if chars[i - 1] in "年月":
                    corrected = candidate
                    break
                # ⚠ 数字后的「曰」不一定是日期：文言列举「一曰…五曰…」正是单字数字＋曰
                # （退想斋日记真值「國之民五曰宗」）。日期的数字是两位以上：二十曰 / 廿八曰 /
                # 三月十五曰。故要么前文近处有「年/月」，要么「曰」前是连续两个以上数字字。
                if _is_digit_char(chars[i - 1]) and (
                        any(c in "年月" for c in chars[max(0, i - 6):i])
                        or (i >= 2 and _is_digit_char(chars[i - 2]))):
                    corrected = candidate
                    break

            # Rule 3: Number followed by date unit
            if ch == "曰" and candidate == "日":
                if i + 1 < n and chars[i + 1] in "年月時":  # unlikely but harmless
                    corrected = candidate
                    break

        if corrected:
            chars[i] = corrected

    return "".join(chars)


def correct_ocr_lines(lines):
    """Apply confusion correction to a list of OCR line dicts.

    Modifies lines in-place: updates each line's 'text' field.
    Returns the lines list (same objects, mutated).
    """
    for line in (lines or []):
        if isinstance(line, dict) and "text" in line:
            line["text"] = correct_ocr_text(line["text"])
    return lines
