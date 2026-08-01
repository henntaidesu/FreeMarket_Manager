# -*- coding: utf-8 -*-
"""SQLite 风格 SQL → MySQL 语法翻译（仅供 MySQL 方言在执行时调用；SQLite 走原生
sqlite3，不经过此模块）。

上层统一以 SQLite 风格书写 SQL：
  · 参数占位符使用 ``?``
  · 标识符引用使用 ``[名称]`` 方括号
  · 类型转换沿用 SQLite 关键字：``CAST(x AS INTEGER)`` / ``CAST(x AS TEXT)``

翻译为 MySQL/PyMySQL 语法：
  · ``[名称]``        → `` `名称` ``（反引号）
  · ``?``            → ``%s``
  · ``AS INTEGER``   → ``AS SIGNED``；``AS TEXT`` → ``AS CHAR``；``AS REAL`` → ``AS DECIMAL``
  · 带参数执行时，PyMySQL 会对整条 SQL 做一次 ``%`` 格式化，故所有字面量 ``%``
    （含字符串内部）必须转义为 ``%%``。

替换必须区分「字符串字面量内部」与「SQL 语法部分」：``[]``/``?``/``CAST`` 仅在语法
部分改写，避免误伤字符串里的方括号、问号或关键字。字符串字面量以单引号界定，
``''`` 表示转义的单引号。
"""

from __future__ import annotations

import re

_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_CAST_TYPE_RE = re.compile(r"\bAS\s+INTEGER\b|\bAS\s+TEXT\b|\bAS\s+REAL\b",
                           re.IGNORECASE)
_CAST_MAP = {"INTEGER": "SIGNED", "TEXT": "CHAR", "REAL": "DECIMAL"}

# SQLite UPSERT → MySQL：
#   ``ON CONFLICT(冲突列) DO UPDATE SET 赋值`` → ``ON DUPLICATE KEY UPDATE 赋值``
#     （MySQL 依已有唯一键/主键判定冲突，不显式列出冲突列，故整段目标丢弃）
#   ``excluded.列`` → ``VALUES(列)``（引用「本应插入的新值」；MySQL 8.0 仍支持，
#     虽在 8.0.20+ 标记弃用但仍可用）。DO UPDATE 中对本表列的引用（如
#     ``table.col``）在 MySQL 里天然指向「已存在的旧值」，与 SQLite 语义一致，无需改写。
_ON_CONFLICT_RE = re.compile(
    r"ON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET", re.IGNORECASE)
_EXCLUDED_RE = re.compile(r"\bexcluded\.(`[^`]+`|\w+)", re.IGNORECASE)


def _split_string_literals(sql: str):
    """把 SQL 切成 (语法段 / 字符串段 / 注释段) 的序列。

    注释也必须切出来，和字符串字面量一样**不参与改写**：注释里出现一个 ``?`` 会被换成
    ``%s``，PyMySQL 就会多吃一个参数；出现一个 ``'`` 更糟——它会被当成字符串起始，把后面
    整段 SQL 都吞进「字面量」里，真正的 ``?`` 一个都换不成。仓库里已经有带 ``--`` 注释的
    多行 SQL（见 outbound_sync.py），只是碰巧没写到问号和撇号。

    识别两种注释：``--`` 行注释（按 MySQL 规则要求其后是空白或行尾，避免误伤 ``a--b``
    这种「减负号」写法）与 ``/* */`` 块注释。``#`` 行注释不处理——调用方一律写
    SQLite 风格 SQL，不会用它。
    """
    segs = []
    i = 0
    n = len(sql)
    start = 0
    while i < n:
        ch = sql[i]
        if ch == "'":
            segs.append(("code", sql[start:i]))
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            segs.append(("str", sql[i:j + 1]))
            i = j + 1
            start = i
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-" and (
            i + 2 >= n or sql[i + 2].isspace()
        ):
            segs.append(("code", sql[start:i]))
            j = sql.find("\n", i)
            j = n if j < 0 else j          # 注释到行尾；换行本身留给下一段
            segs.append(("comment", sql[i:j]))
            i = j
            start = i
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            segs.append(("code", sql[start:i]))
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2      # 未闭合就吃到结尾
            segs.append(("comment", sql[i:j]))
            i = j
            start = i
        else:
            i += 1
    segs.append(("code", sql[start:]))
    return segs


def _rewrite_code(seg: str, has_params: bool) -> str:
    # 顺序要点：先对原始字面量 % 转义，再把 ? 换成 %s，
    # 否则会把刚生成的 %s 误转义成 %%s。
    if has_params and "%" in seg:
        seg = seg.replace("%", "%%")
    seg = _BRACKET_RE.sub(lambda m: "`" + m.group(1) + "`", seg)
    seg = _CAST_TYPE_RE.sub(
        lambda m: "AS " + _CAST_MAP[m.group(0).split()[-1].upper()], seg)
    seg = _ON_CONFLICT_RE.sub("ON DUPLICATE KEY UPDATE", seg)
    seg = _EXCLUDED_RE.sub(lambda m: "VALUES(" + m.group(1) + ")", seg)
    seg = seg.replace("?", "%s")
    return seg


def translate(sql: str, has_params: bool) -> str:
    """把 SQLite 风格 SQL 翻译为 MySQL 语法。

    ``has_params`` 为 True（execute/executemany 带参数）时，PyMySQL 会对整条 SQL
    执行 ``query % args``，故需把所有字面量 ``%`` 转义为 ``%%``（含字符串内部）。
    """
    out = []
    for kind, seg in _split_string_literals(sql):
        if kind == "code":
            seg = _rewrite_code(seg, has_params)
        elif has_params and "%" in seg:
            # 字符串字面量与注释：都不改写语法，但 % 仍要转义
            #（PyMySQL 对整条 SQL 做一次 % 格式化，注释里的 % 同样会被吃掉）
            seg = seg.replace("%", "%%")
        out.append(seg)
    return "".join(out)
