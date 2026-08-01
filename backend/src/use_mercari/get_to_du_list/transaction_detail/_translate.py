# -*- coding: utf-8 -*-
"""消息日中翻译：抓取交易详情时，把买家消息译为中文存入 transaction_messages.text_zh。

走谷歌免费非官方端点（translate.googleapis.com/translate_a/single，无需密钥），
仅翻译买家（is_buyer）消息；失败/超时单条静默跳过（text_zh 留空 → 前端只显示原文）。

幂等：同一订单刷新重抓时，按 (msg_id, 原文) 复用上次已存的 text_zh，避免重复请求
被限流的免费端点。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 8.0  # seconds，单条
_TARGET = "zh-CN"
# 同一会话内并发翻译的上限（买家消息通常很少，给个保守上限即可）
_CONCURRENCY = 4
#: 查询串编码后的最大长度。留言走 GET query，超过这个长度就不发请求（见 _translate_one）。
#: 1800 是为了让「基址 + 参数」整体稳在 2000 字符以内——各类中间环节的通用安全线。
_MAX_QUERY_LEN = 1800


def _translate_one(text: str) -> Optional[str]:
    """调用免费端点把 text 译为中文。失败返回 None。"""
    q = (text or "").strip()
    if not q:
        return None
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": _TARGET, "dt": "t", "q": q}
    )
    # 整条消息是塞进 **GET 查询串** 的，没有上限就会撞 URL 长度限制：日文 URL 编码后约 9 字节/字，
    # 一条上千字的留言轻松过万字节。运气好是 414/400（本函数返回 None，前端回落显示原文，没问题），
    # 运气不好是中间环节把 URL 截断 —— 那样会把**残缺的译文当完整结果**存进 text_zh，
    # 比不翻译更糟。所以宁可放弃翻译，也不发一个可能被截断的请求。
    if len(params) > _MAX_QUERY_LEN:
        log.info(
            "[txmsg] 留言过长（编码后 %d 字节 > %d），跳过翻译，前端显示原文",
            len(params), _MAX_QUERY_LEN,
        )
        return None
    req = urllib.request.Request(
        f"{_ENDPOINT}?{params}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
        # 结构：[[["译文片段","原文片段",...], ...], ...]，拼接全部译文片段
        segs = data[0] if isinstance(data, list) and data else None
        if not isinstance(segs, list):
            return None
        out = "".join(
            seg[0] for seg in segs if isinstance(seg, list) and seg and isinstance(seg[0], str)
        )
        out = out.strip()
        return out or None
    except Exception as exc:  # noqa: BLE001 翻译失败不影响主流程
        log.debug("[txmsg] 翻译失败: %s", exc)
        return None


def translate_text(text: str) -> Optional[str]:
    """同步翻译单段文本为中文（按需翻译端点用）。失败返回 None。"""
    return _translate_one(text)


async def translate_buyer_messages(
    messages: List[Dict[str, Any]],
    old_messages: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """原地给买家消息补 ``text_zh``：优先复用旧译文，其余调用谷歌端点。

    ``messages``：``_parse_messages`` 产出的展示态消息（含 is_buyer / text / id）。
    ``old_messages``：该订单上次已存的消息（用于按 msg_id+原文 复用 text_zh）。
    """
    if not messages:
        return
    # 旧译文索引：msg_id -> (原文, 译文)
    reuse: Dict[str, tuple] = {}
    for m in old_messages or []:
        mid = str(m.get("id") or "").strip()
        zh = (m.get("text_zh") or "").strip()
        if mid and zh:
            reuse[mid] = (str(m.get("text") or ""), zh)

    pending: List[Dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        m.setdefault("text_zh", None)
        if not m.get("is_buyer"):
            continue
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        mid = str(m.get("id") or "").strip()
        old = reuse.get(mid)
        if old and old[0] == str(m.get("text") or ""):
            m["text_zh"] = old[1]
            continue
        pending.append(m)

    if not pending:
        return

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _run(msg: Dict[str, Any]) -> None:
        async with sem:
            zh = await asyncio.to_thread(_translate_one, str(msg.get("text") or ""))
            if zh:
                msg["text_zh"] = zh

    await asyncio.gather(*(_run(m) for m in pending))
