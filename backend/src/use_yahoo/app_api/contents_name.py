# -*- coding: utf-8 -*-
"""雅虎发货的「品名」（``contentsGroupName``）：校验与默认值。

品名是印在配送单上给配送公司看的，雅虎要求必填、≤17 字，且只能用 EUC-JP 编得出的字符。
校验与 App 一字不差（APK ``nb/a.java`` 的 ``a()``）：NFKC 规范化 → 去掉 ``〜`` ``−`` →
去掉格式控制符（Unicode Cf）与异体字选择符 U+FE00–FE0F → 能否无损往返 EUC-JP。

**组合购买（まとめ買い）的交易页品名框是空的**（实测 z708827142），回落用的商品标题形如
``＜まとめ買い＞ 鳴潮 ユーノ ポストカード 9点 計2点``——那是出品文案，不是品名，截到 17 字
还会把真正的商品名截掉一半。``suggest_contents_name`` 把这类标签剥掉再按词截断，
只是一个默认值，用户在发货向导里仍可改。
"""
from __future__ import annotations

import re
import unicodedata

#: 品名上限，与网页端发货表单的 maxlength、App 的 ``contents_group_name_max`` 一致
CONTENTS_NAME_MAX_LEN = 17

_APP_STRIP_RE = re.compile("[〜−]")
#: 出品文案常用的括号标签（【送料無料】＜まとめ買い＞[匿名配送] …），整段剥掉
_TAG_RE = re.compile(r"[【＜<\[［《〈][^】＞>\]］》〉]*[】＞>\]］》〉]")
_SPACE_RE = re.compile(r"\s+")


def _is_legal_char(ch: str) -> bool:
    if unicodedata.category(ch) == "Cf" or "︀" <= ch < "︐":
        return True  # App 校验前就丢掉的字符，不算非法
    try:
        ch.encode("euc_jp")
        return True
    except UnicodeEncodeError:
        return False


def has_illegal_chars(name: str) -> bool:
    """与 App 同口径：是否含雅虎不收的字符（emoji、EUC-JP 以外的汉字等）。"""
    text = _APP_STRIP_RE.sub("", unicodedata.normalize("NFKC", name or ""))
    return not all(_is_legal_char(ch) for ch in text)


def validate_contents_name(name: str) -> str:
    """提交前的品名：去空白、截到上限后校验，不合格抛 ``ValueError``（在任何对外请求之前）。"""
    text = _SPACE_RE.sub(" ", (name or "").strip())[:CONTENTS_NAME_MAX_LEN].strip()
    if not text:
        raise ValueError("品名不能为空（雅虎必填），请在发货向导里填写具体的品名")
    if has_illegal_chars(text):
        bad = "".join(
            ch for ch in unicodedata.normalize("NFKC", text) if not _is_legal_char(ch)
        )
        raise ValueError(f"品名「{text}」含雅虎不能使用的字符：{bad}")
    return text


def suggest_contents_name(title: str) -> str:
    """从商品标题推一个默认品名：剥括号标签、丢非法字符、超长时按词截断。"""
    text = _TAG_RE.sub(" ", title or "")
    text = "".join(ch for ch in text if _is_legal_char(ch))
    words = _SPACE_RE.sub(" ", text).strip().split(" ")
    while len(words) > 1 and len(" ".join(words)) > CONTENTS_NAME_MAX_LEN:
        words.pop()
    return " ".join(words)[:CONTENTS_NAME_MAX_LEN].strip()
