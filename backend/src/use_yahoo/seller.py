# -*- coding: utf-8 -*-
"""雅虎账号的卖家 ID（``p########``）解析与落库。

雅虎不像煤炉那样在 API 里给 seller_id：登录后 ``/my`` 页面头部有一条指向自己主页的
``/user/{seller_id}`` 链接，从那里取。取到后写回 ``mercari_accounts.seller_id``——
在售表按 seller_id 关联账号显示卖家名、按卖家筛选，这一步不做的话雅虎行就没有卖家名。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from ..web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser

log = logging.getLogger(__name__)

MY_PAGE_URL = f"{YAHOO_BASE_URL}/my"

_USER_LINK_RE = re.compile(r"/user/(p\w+)")

#: 未设置头像时页面用的占位图，不能当成用户头像同步下来
_DEFAULT_AVATAR_MARK = "prof_default"

#: ``/my`` 页头部那条指向自己主页的链接，一条链接同时给出卖家 ID 与昵称：
#: ``href`` 是 ``/user/p########``，文本首行是昵称（次行起是评价数/认证徽章）。
#:
#: 头像**不是 ``<img>``**，而是圆形 div 的 CSS ``background-image``
#: （``displayname-pctr.c.yimg.jp/d/display-name/{hash}``），只扫 img 会一无所获。
#: 页面上有大小两个（导航栏 36px / 资料块 44px），URL 相同，取最大的那个。
_PROFILE_JS = """
() => {
  const a = [...document.querySelectorAll('a[href]')].find(
    (x) => /\\/user\\/p\\w+/.test(x.getAttribute('href') || '')
  );
  const m = a ? (a.getAttribute('href') || '').match(/\\/user\\/(p\\w+)/) : null;
  const nick = a ? (a.innerText || '').trim().split('\\n')[0].trim() : '';

  let avatar = null, best = 0;
  document.querySelectorAll('div, span').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 20 || Math.abs(r.width - r.height) > 4) return;
    const cs = getComputedStyle(el);
    if (!/50%|9999px/.test(cs.borderRadius || '')) return;
    const bg = cs.backgroundImage || '';
    const hit = bg.match(/url\\(["']?(.*?)["']?\\)/);
    if (!hit || !hit[1]) return;
    if (r.width > best) { best = r.width; avatar = hit[1]; }
  });

  return {seller_id: m ? m[1] : null, nickname: nick || null, avatar: avatar};
}
"""


def yahoo_account_seller_id(account_id: int) -> Optional[str]:
    """读账号已存的卖家 ID（没有返回 None）。"""
    from ..db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

    acc = MercariAccountModel.find_by_id(id=int(account_id))
    if acc is None:
        return None
    return str(getattr(acc, "seller_id", "") or "").strip() or None


def _persist_seller_id(account_id: int, seller_id: str) -> None:
    from ..db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

    acc = MercariAccountModel.find_by_id(id=int(account_id))
    if acc is None:
        return
    acc.seller_id = seller_id
    acc.save()
    log.info("[yahoo] 账号#%s 卖家ID已记录：%s", account_id, seller_id)


async def _read_my_page_profile(page: Any) -> Dict[str, str]:
    """在已导航到 ``/my`` 的页面上读卖家 ID / 昵称 / 头像。"""
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    data = await page.evaluate(_PROFILE_JS) or {}
    sid = str(data.get("seller_id") or "").strip()
    if not sid:
        raise RuntimeError(
            "未能在雅虎「マイページ」上解析出卖家ID，请确认该浏览器已登录 Yahoo!フリマ"
        )
    out = {
        "seller_id": sid,
        "account_name": str(data.get("nickname") or "").strip(),
        "avatar": "",
    }
    avatar_url = str(data.get("avatar") or "").strip()
    if avatar_url and _DEFAULT_AVATAR_MARK not in avatar_url:
        # 只写本地路径：下载成功才回填，失败就不同步本次头像（保留账号原有的），绝不落远程 URL
        from ..use_web.mercari_accounts.units.mercari_accounts_mitm import (
            _download_avatar_local,
        )

        local = await _download_avatar_local(page, avatar_url, prefix="yahoo_avatar")
        if local:
            out["avatar"] = local
        else:
            log.info("[yahoo] 头像下载失败，跳过本次头像同步：%s", avatar_url)
    return out


async def fetch_yahoo_basic_info(account_key: str) -> Dict[str, str]:
    """打开 ``/my`` 读回「卖家ID + 账号名称」（账号编辑弹窗的「获取基础信息」）。

    只读不落库——与煤炉那个按钮一致，值填回表单由用户确认后保存。

    两种会话：
    - 已有账号（``mercari_{id}``）：走自动化无头会话（从主 profile 克隆登录态），
      不打扰用户手动打开的浏览器；
    - 新增账号（``yahoo_prepare[_uid]``）：复用用户刚登录的那个预登录浏览器并导航到 ``/my``
      —— 此时账号还没入库，没有可克隆登录态的主 profile。

    雅虎不需要 MITM：卖家 ID 直接在页面 DOM 里（煤炉得从 ``items/get_items`` 的查询参数截获）。
    """
    from ..web_drive.core.manager import get_web_drive_manager
    from ..web_drive.core.paths import mercari_id_from_account_key

    key = str(account_key or "").strip()
    aid = mercari_id_from_account_key(key)
    if aid is not None:
        async with yahoo_automation_browser(aid, start_url=MY_PAGE_URL) as (mgr, skey):
            return await _read_my_page_profile(await mgr.active_tab_page(skey))

    mgr = get_web_drive_manager()
    # 预登录会话是用户可见且已登录的：复用它并就地导航，不能 close 重开（会丢登录态）
    await mgr.open_session(
        key, headless=False, interactive=True, restore_tabs=False, start_url=MY_PAGE_URL
    )
    return await _read_my_page_profile(await mgr.active_tab_page(key))


async def resolve_yahoo_seller_id(account_id: int) -> str:
    """返回该雅虎账号的卖家 ID；账号上没有就打开 ``/my`` 抓一次并写回。"""
    aid = int(account_id)
    existing = yahoo_account_seller_id(aid)
    if existing:
        return existing

    async with yahoo_automation_browser(aid, start_url=MY_PAGE_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)
        hrefs = await page.evaluate(
            "() => [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href') || '')"
        )
    for href in hrefs or []:
        m = _USER_LINK_RE.search(str(href))
        if m:
            sid = m.group(1)
            _persist_seller_id(aid, sid)
            return sid

    raise RuntimeError(
        "未能在雅虎「マイページ」上解析出卖家ID，请确认该账号浏览器仍处于登录状态"
    )
