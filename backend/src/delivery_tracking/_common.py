# -*- coding: utf-8 -*-
"""两家承运公司查询共用的 HTTP 与 HTML 小工具。

**为什么是正则而不是 HTML 解析库**：本仓库没有 bs4 / lxml（``requirements.txt`` 只有
``requests``），为两个页面引一个解析依赖不划算。两家的结果区都是结构固定的表格 / 列表，
按标签切片够用；真变了也会变到正则匹配不到，那时返回的是「解析不出履历」而不是错数据。
"""

from __future__ import annotations

import html as _html
import re
import ssl
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter

#: 两家页面上的时刻都是日本时间，且日本不实行夏令时，固定 +09:00 即可（无需 zoneinfo）。
JST = timezone(timedelta(hours=9))

#: 不带 UA 时两家都可能返回精简页；用普通桌面 UA 保持与人工查询同一份 HTML。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: 连接 / 读取超时。这条链路挂在用户点击的阻塞请求上，不能让它久等。
TIMEOUT = (8, 20)


class _LegacyCipherAdapter(HTTPAdapter):
    """把 OpenSSL 的安全级别降到 1 的适配器——**只挂给需要它的那个域名**。

    ヤマト 的 ``toi.kuronekoyamato.co.jp`` 只提供 ``AES128-GCM-SHA256``（静态 RSA 密钥交换，
    无前向保密）。OpenSSL 3.x 默认 ``SECLEVEL=2`` 直接拒绝这类套件，握手在
    ClientHello 之后就被服务器回了 ``handshake failure``——症状看着像网络故障，
    其实是本地挑的密码套件里没有对方认的那个（curl 的默认级别更松，所以 curl 能通）。

    降的是**套件准入**，不是校验：证书链与主机名验证照旧
    （``create_default_context`` 的 ``verify_mode`` / ``check_hostname`` 不动）。
    这条链路只发一个运单号、只读回一页公开履历，可以接受没有前向保密。
    """

    def init_poolmanager(self, *args, **kwargs):  # noqa: D102
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_session: Optional[requests.Session] = None
_session_lock = threading.Lock()

#: 需要挂 :class:`_LegacyCipherAdapter` 的前缀。别放宽到全局：其余出站请求
#: （图床 / DeepSeek / 汇率）没有理由陪着降级。
_LEGACY_TLS_PREFIXES = ("https://toi.kuronekoyamato.co.jp",)


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                for prefix in _LEGACY_TLS_PREFIXES:
                    s.mount(prefix, _LegacyCipherAdapter())
                _session = s
    return _session


def _read(resp: requests.Response) -> str:
    resp.raise_for_status()
    # 两家都声明 UTF-8；显式指定免得 requests 从 ISO-8859-1 猜错，把日文全变成乱码。
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def http_get(url: str) -> str:
    return _read(_get_session().get(url, headers={"User-Agent": _UA}, timeout=TIMEOUT))


def http_post(url: str, data: dict) -> str:
    return _read(
        _get_session().post(url, data=data, headers={"User-Agent": _UA}, timeout=TIMEOUT)
    )


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s　]+")


def text_of(fragment: str) -> str:
    """一段 HTML → 归一化后的纯文本（去标签、解实体、压空白，含全角空格）。"""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


def digits(raw: Optional[str]) -> str:
    """运单号归一化：两家页面都会把号码显示成 ``0000-0000-0000``，查询要纯数字。"""
    return re.sub(r"\D", "", str(raw or ""))


def to_epoch(dt: datetime) -> int:
    return int(dt.replace(tzinfo=JST).timestamp())


def parse_md_hm(text: str) -> Optional[int]:
    """``09月23日 11:08`` → epoch 秒。**年份靠推**——ヤマト 的履历不给年。

    取当前日本年份；若算出来比现在还晚一天以上，说明是跨年的旧件，退一年。
    （履历只保留数月，不会出现需要退两年的情况。）
    """
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:\s*(\d{1,2})\s*[:：]\s*(\d{2}))?", text or "")
    if not m:
        return None
    now = datetime.now(JST)
    month, day = int(m.group(1)), int(m.group(2))
    hour = int(m.group(3) or 0)
    minute = int(m.group(4) or 0)
    for year in (now.year, now.year - 1):
        try:
            dt = datetime(year, month, day, hour, minute, tzinfo=JST)
        except ValueError:  # 2/29 之类：换一年再试
            continue
        if dt <= now + timedelta(days=1):
            return int(dt.timestamp())
    return None


def parse_ymd_hm(text: str) -> Optional[int]:
    """``2026/09/20 20:14`` → epoch 秒（日本郵便 的履历带完整年份）。"""
    m = re.search(
        r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})日?(?:\s*(\d{1,2})[:：](\d{2}))?", text or ""
    )
    if not m:
        return None
    try:
        return int(
            datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4) or 0), int(m.group(5) or 0), tzinfo=JST,
            ).timestamp()
        )
    except ValueError:
        return None


def cells(row_html: str, tag: str) -> List[str]:
    """一行 HTML 里所有 ``<td>`` / ``<th>`` 的文本。"""
    return [
        text_of(m.group(1))
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", row_html, re.S | re.I)
    ]
