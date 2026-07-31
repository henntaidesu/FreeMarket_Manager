# -*- coding: utf-8 -*-
"""煤炉账号 MITM 抓取端点：打开出品一覧页截获 items/get_items 并解析 seller_id。"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException

from ....auth import require_auth
from ....ssl_mitm_proxy.capture_config import read_capture_file
from ....ssl_mitm_proxy.runner import (
    default_mitm_proxy_url,
    mitm_status,
    start_mitm_proxy,
)
from ....web_drive import get_web_drive_manager
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import automation_headless_enabled
from .mercari_accounts_helpers import (
    _item_api_dict,
    _norm_seller_id,
)
from .mercari_accounts_models import (
    FetchSellerIdViaMitmBody,
    MERCARI_LISTINGS_URL,
)

log = logging.getLogger(__name__)


async def _wait_capture_with_progress(
    *,
    since_ms: int,
    capture_type: str,
    wait_seconds: int,
    seller_id: Optional[str] = None,
    dpop_field: Optional[str] = None,
    acquired_fields: Optional[List[str]] = None,
    step_name: str = "",
    url_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """等待捕获并每 3 秒打印一次进度（CLI 可见）。"""
    acquired_fields = acquired_fields or []
    deadline = time.monotonic() + wait_seconds
    next_log_at = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_log_at:
            got = "、".join(acquired_fields) if acquired_fields else "无"
            left = max(0, int(deadline - now))
            msg = (
                f"[MITM][进度] 当前步骤: {step_name or capture_type} | "
                f"已获取字段: {got} | 剩余约 {left}s"
            )
            log.info(msg)
            print(msg, flush=True)
            next_log_at = now + 3.0
        # 直接读该 capture_type 专属文件，不受其他类型请求覆盖干扰
        data = read_capture_file(capture_type)
        if data and int(data.get("ts") or 0) >= since_ms:
            if seller_id:
                sid = str(data.get("seller_id") or "").strip()
                if sid and sid != seller_id:
                    await asyncio.sleep(0.9)
                    continue
            if dpop_field:
                df = str(data.get("dpop_field") or "").strip()
                if df != dpop_field:
                    await asyncio.sleep(0.9)
                    continue
            if url_contains:
                u = str(data.get("url") or "")
                if url_contains not in u:
                    await asyncio.sleep(0.9)
                    continue
            return data
        await asyncio.sleep(0.9)
    return None


def _avatar_ext_from(url: str, content_type: str) -> str:
    """依据 Content-Type 或 URL 后缀推断头像文件扩展名。"""
    ct = (content_type or "").lower()
    if "webp" in ct:
        return "webp"
    if "png" in ct:
        return "png"
    if "gif" in ct:
        return "gif"
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    tail = (url or "").split("?", 1)[0].rsplit(".", 1)
    ext = tail[-1].lower() if len(tail) == 2 else ""
    if ext in {"webp", "png", "gif"}:
        return ext
    return "jpg"


async def _download_avatar_local(
    page: Any, url: str, *, prefix: str = "mercari_avatar"
) -> Optional[str]:
    """经浏览器上下文下载头像并存入 backend/imges，返回 ``/imges/xxx.ext``；失败返回 None。"""
    u = (url or "").strip()
    if not u:
        return None
    try:
        from ...image_storage import save_image_bytes

        resp = await page.request.get(u, timeout=15000)
        if not resp.ok:
            log.info("[MITM] 下载头像失败 status=%s url=%s", resp.status, u)
            return None
        body = await resp.body()
        if not body:
            return None
        ext = _avatar_ext_from(u, resp.headers.get("content-type", ""))
        return save_image_bytes(body, ext=ext, prefix=prefix)
    except Exception as exc:
        log.info("[MITM] 下载头像异常（忽略）：%s", exc)
        return None


async def _read_seller_profile_from_dom(
    mgr: Any, session_key: str, *, timeout_ms: int = 8000
) -> Dict[str, str]:
    """从出品一覧页顶部账号按钮读取卖家头像与用户名（用户名同步为账号名称）。

    对应 DOM：``[data-testid="account-button"]`` 内的 ``<img>``（头像，alt="XXXの画像"）
    与 ``<p>``（用户名）。头像会经浏览器下载并存入本地 ``/imges``；读取失败时返回空字典
    （不影响 seller_id 主流程）。
    """
    out: Dict[str, str] = {}
    try:
        page = await mgr.active_tab_page(session_key)
        locator = page.locator('[data-testid="account-button"]').first
        try:
            await locator.wait_for(state="attached", timeout=timeout_ms)
        except Exception:
            pass
        try:
            avatar = await locator.locator("img").first.get_attribute("src")
            avatar = (avatar or "").strip()
            if avatar:
                # 只存本地图片路径：下载成功才写入 avatar（供保存时覆盖旧头像）；
                # 下载失败则不同步本次头像，保留账号原有本地头像，绝不落远程 URL。
                local = await _download_avatar_local(page, avatar)
                if local:
                    out["avatar"] = local
                else:
                    log.info("[MITM] 头像本地下载失败，跳过本次头像同步：%s", avatar)
        except Exception:
            pass
        try:
            name = await locator.locator("p").first.text_content()
            name = (name or "").strip()
            if not name:
                alt = await locator.locator("img").first.get_attribute("alt")
                alt = (alt or "").strip()
                # 头像 alt 形如「Williamc2の画像」：去掉尾部「の画像」得到用户名
                name = alt[:-3].strip() if alt.endswith("の画像") else alt
            if name:
                out["account_name"] = name
        except Exception:
            pass
    except Exception as exc:
        log.info("[MITM] 读取卖家头像/用户名失败（忽略）：%s", exc)
    return out


async def fetch_seller_id_via_mitm(
    body: FetchSellerIdViaMitmBody = Body(default_factory=FetchSellerIdViaMitmBody),
    user: dict = Depends(require_auth),
):
    """
    启动 MITM，用指定 WebDrive 会话（如 mercari_prepare / mercari_{id}）经代理打开
    jp.mercari.com/mypage/listings，截获
    GET api.mercari.jp/items/get_items?status=on_sale,stop&... 并从查询参数读取 seller_id。

    会话隔离（与「打开浏览器」的有头主 profile ``mercari_{id}`` 互不冲突）：
    - 已有账号：用同步专用无头 profile ``mercari_{id}__sync`` + 克隆主 profile 登录态；
    - 新增账号预登录：用 ``mercari_prepare_{user_id}`` 按用户隔离的 profile
      （自带登录态），关闭后带 MITM 代理重开。

    全流程通过 ``run_mercari_serial_async`` 进入账号队列；队列空闲后由队列层
    自动关闭浏览器（``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 秒延迟）。
    """
    from ....web_drive.core.paths import (
        MERCARI_PREPARE_ALIAS,
        mercari_id_from_account_key,
        resolve_prepare_alias,
    )

    # 预登录会话按用户隔离：mercari_prepare → mercari_prepare_{user_id}
    account_key = resolve_prepare_alias(
        (body.account_key or MERCARI_PREPARE_ALIAS).strip(), user.get("sub")
    )
    aid = mercari_id_from_account_key(account_key)

    async def _do_fetch():
        r = start_mitm_proxy()
        if r.get("error"):
            raise HTTPException(status_code=500, detail=r["error"])

        t0 = int(time.time() * 1000)
        mgr = get_web_drive_manager()
        headless = bool(body.headless) or automation_headless_enabled()

        if aid is not None:
            # 已有账号：同步专用无头 profile + 克隆主 profile 登录态（只读，不触碰有头主浏览器）
            from ....web_drive.core.mitm_session import clone_main_profile_cookies
            from ....web_drive.core.paths import mercari_automation_key

            auto_key = mercari_automation_key(aid)
            session_key = auto_key
            await mgr.close_session(auto_key, force=True)
            await mgr.open_session(
                auto_key,
                headless=headless,
                proxy_server=default_mitm_proxy_url(),
                interactive=not headless,
                start_minimized=True,
            )
            await clone_main_profile_cookies(mgr, aid, auto_key)
            await mgr.reload_active_tab(auto_key, MERCARI_LISTINGS_URL)
        else:
            session_key = account_key
            # 新增账号预登录：prepare 专用 profile 自带登录态，关闭后带 MITM 代理重开以截获请求
            await mgr.close_session(account_key, force=True)
            await mgr.open_session(
                account_key,
                headless=headless,
                start_url=MERCARI_LISTINGS_URL,
                proxy_server=default_mitm_proxy_url(),
                interactive=not headless,
                start_minimized=True,
            )

        cap = await _wait_capture_with_progress(
            since_ms=t0,
            capture_type="items_get_items",
            wait_seconds=body.wait_seconds,
            dpop_field="dpop_on_sale_list",
            step_name="在售列表 seller_id",
        )
        if not cap:
            raise HTTPException(
                status_code=408,
                detail=(
                    "超时：未截获 GET /items/get_items（status 含 on_sale/stop）。"
                    "请确认 MITM 已启动、Edge 已登录煤炉且出品一覧可正常加载。"
                ),
            )

        sid = _norm_seller_id(str(cap.get("seller_id") or "").strip())
        if not sid:
            raise HTTPException(status_code=500, detail="截获请求中未解析到有效 seller_id")

        # 顺带从出品一覧页顶部账号按钮读取卖家头像与用户名（用户名同步账号名称）
        profile = await _read_seller_profile_from_dom(mgr, session_key)

        log.info(
            "[MITM] 已解析 seller_id=%s account_name=%s avatar=%s account_key=%s url=%s",
            sid,
            profile.get("account_name") or "",
            profile.get("avatar") or "",
            account_key,
            cap.get("url") or "",
        )
        return {
            "success": True,
            "data": {
                "seller_id": sid,
                "avatar": profile.get("avatar") or "",
                "account_name": profile.get("account_name") or "",
                "url": cap.get("url"),
                "ts": cap.get("ts"),
                "account_key": account_key,
            },
            "mitm": mitm_status(),
        }

    if aid is not None:
        queue_key = queue_key_for_mercari_account(aid)
    elif account_key.startswith(MERCARI_PREPARE_ALIAS):
        # 所有用户的 prepare 抓取共用一个全局串行队列：MITM capture 文件全局共享，
        # profile 虽已按用户隔离，抓取本身仍须串行以防并发互抢捕获结果
        queue_key = MERCARI_PREPARE_ALIAS
    else:
        queue_key = account_key
    return await run_mercari_serial_async(queue_key, _do_fetch)
