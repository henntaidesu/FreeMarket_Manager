# -*- coding: utf-8 -*-
"""在售商品端点：删除 / 改价 / 重新上架 / 下架"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel, Field
from .....web_drive import get_web_drive_manager
from .listing import _LISTING_JOB_ID_RE, _account_platform

log = logging.getLogger(__name__)

#: 煤炉「発送までの日数」option value → 雅虎 post_to_yahoo 的发货天数键
_YAHOO_SHIPPING_DAYS_BY_DURATION = {
    "1": "1_2_days",
    "2": "2_3_days",
    "3": "4_7_days",
}


# ──────────────────────── 在售商品删除 ──────────────────────── #

class DeleteMercariItemBody(PydanticModel):
    """通过 WebDrive 在煤炉编辑页删除在售商品。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    item_id: str = Field(..., min_length=1, max_length=64)
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    progress_job_id: Optional[str] = None

async def delete_on_sale_item(body: DeleteMercariItemBody):
    """
    账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页删除商品，跳转出品一覧后同步本地列表；
    经 ``run_mercari_serial_async`` 串行，浏览器在队列空闲超时后由队列自动关闭。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 共用通用
    sync_progress 内存存储，前端可复用同一个轮询接口展示步骤。
    """
    from .....web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .....web_drive.core.paths import mercari_id_from_account_key
    from .....web_drive.delete.units.delete_order import delete_mercari_item as _do_delete
    from .....ssl_mitm_proxy.runner import default_mitm_proxy_url
    from .....use_mercari.sync.sync_progress import clear_sync_progress

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    jid = (body.progress_job_id or "").strip() or None
    if jid and not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    account_id = mercari_id_from_account_key(body.account_key)
    if account_id is None:
        raise HTTPException(status_code=400, detail="无效的 account_key")

    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        mgr = get_web_drive_manager()

        if _account_platform(account_id) == "yahoo":
            from .....web_drive.yahoo_item import delete_yahoo_item

            async def _run() -> Dict[str, Any]:
                return await delete_yahoo_item(account_id, item_id=item_id)
        else:
            async def _run() -> Dict[str, Any]:
                return await _do_delete(
                    mgr,
                    body.account_key,
                    item_id=item_id,
                    proxy_server=proxy,
                    progress_job_id=jid,
                )

        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(account_id),
            _run,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("delete_on_sale_item 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)

# ──────────────────────── 在售商品修改 ──────────────────────── #

#: 修改时允许回传的图片来源：本系统图库 / 煤炉原图。其余一律 400——
#: ``_resolve_image_to_local`` 本身会接受服务器上的任意绝对路径与任意 URL，
#: 放行就等于让前端把服务器上的文件传上煤炉、或让服务器替人去请求任意地址。
_REVISE_IMAGE_PREFIXES = ("/imges/", "https://static.mercdn.net/")
#: 煤炉编辑页的六档商品状态 / 配送方法取值（与 revise_fields 的映射同集合）
_REVISE_CONDITIONS = {"new_unused", "almost_unused", "good", "fair", "used", "bad"}
_REVISE_SHIPPING_METHODS = {"undecided", "rakuraku", "yuuyu", "tanome", "regular_mail"}


class ReviseMercariItemBody(PydanticModel):
    """通过 WebDrive 在煤炉编辑页修改在售商品（全部字段均可选，None = 不改）。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    item_id: str = Field(..., min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, max_length=80)
    price: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=4000)
    # 配送について（传入煤炉 <option> value）：配送料の負担 2/1、発送までの日数 1/2/3、発送元の地域 1~47/99
    shipping_payer: Optional[str] = Field(default=None, max_length=8)
    shipping_duration: Optional[str] = Field(default=None, max_length=8)
    shipping_from_area_id: Optional[str] = Field(default=None, max_length=8)
    # 以下四项目前只有煤炉实现：图片（完整的新列表，整组替换）/ 商品类型映射 id / 商品状态 / 配送方法
    image_urls: Optional[List[str]] = Field(default=None, max_length=20)
    product_type_id: Optional[str] = Field(default=None, max_length=32)
    condition: Optional[str] = Field(default=None, max_length=16)
    shipping_method: Optional[str] = Field(default=None, max_length=16)
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    progress_job_id: Optional[str] = None


def _validate_revise_rich_fields(body: ReviseMercariItemBody) -> Optional[List[int]]:
    """校验四项新字段并把商品类型解析成类别位置数组；非法值抛 ValueError（→ 400）。"""
    if body.image_urls is not None:
        if not body.image_urls:
            raise ValueError("图片列表为空：煤炉商品至少需要 1 张图片")
        for u in body.image_urls:
            if not str(u or "").startswith(_REVISE_IMAGE_PREFIXES):
                raise ValueError(f"不支持的图片来源：{str(u)[:80]}")
    if body.condition is not None and body.condition not in _REVISE_CONDITIONS:
        raise ValueError(f"未知的商品状态：{body.condition}")
    if body.shipping_method is not None and body.shipping_method not in _REVISE_SHIPPING_METHODS:
        raise ValueError(f"未知的配送方法：{body.shipping_method}")
    if not (body.product_type_id or "").strip():
        return None
    from .....db_manage.models.system.product_type_category_mapping import (
        ProductTypeCategoryMappingModel,
    )

    positions = ProductTypeCategoryMappingModel.positions_for(body.product_type_id, "mercari")
    if not positions:
        # 出品侧煤炉缺位置会静默跳过选类别；修改是用户明确要改类别，静默跳过就成了「改了但没改」
        raise ValueError("该商品类型未配置煤炉类别位置，请先在「商品类型映射」中配置")
    return positions

async def revise_on_sale_item(body: ReviseMercariItemBody):
    """
    账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页填写并点击「変更する」提交，
    随后打开出品一覧同步本地列表；经 ``run_mercari_serial_async`` 串行，浏览器在队列空闲超时后自动关闭。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 共用通用
    sync_progress 内存存储，前端可复用同一个轮询接口展示步骤。
    """
    from .....web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .....web_drive.core.paths import mercari_id_from_account_key
    from .....web_drive.revise.units.revise_order import revise_mercari_item as _do_revise
    from .....ssl_mitm_proxy.runner import default_mitm_proxy_url
    from .....use_mercari.sync.sync_progress import clear_sync_progress

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    jid = (body.progress_job_id or "").strip() or None
    if jid and not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    account_id = mercari_id_from_account_key(body.account_key)
    if account_id is None:
        raise HTTPException(status_code=400, detail="无效的 account_key")

    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        mgr = get_web_drive_manager()
        is_yahoo = _account_platform(account_id) == "yahoo"
        if is_yahoo and (
            body.image_urls is not None
            or body.product_type_id
            or body.condition is not None
            or body.shipping_method is not None
        ):
            raise ValueError("雅虎在售商品暂不支持修改图片 / 类别 / 商品状态 / 配送方法")
        category_positions = None if is_yahoo else _validate_revise_rich_fields(body)

        if is_yahoo:
            from .....web_drive.yahoo_item import revise_yahoo_item

            async def _run() -> Dict[str, Any]:
                # 雅虎没有「送料負担」（恒出品者負担），该字段忽略
                return await revise_yahoo_item(
                    account_id,
                    item_id=item_id,
                    name=body.name,
                    price=body.price,
                    description=body.description,
                    shipping_days=_YAHOO_SHIPPING_DAYS_BY_DURATION.get(
                        str(body.shipping_duration or "").strip()
                    ),
                    shipping_from_area_id=body.shipping_from_area_id,
                )
        else:
            async def _run() -> Dict[str, Any]:
                return await _do_revise(
                    mgr,
                    body.account_key,
                    item_id=item_id,
                    name=body.name,
                    price=body.price,
                    description=body.description,
                    shipping_payer=body.shipping_payer,
                    shipping_duration=body.shipping_duration,
                    shipping_from_area_id=body.shipping_from_area_id,
                    image_urls=body.image_urls,
                    category_positions=category_positions,
                    condition=body.condition,
                    shipping_method=body.shipping_method,
                    proxy_server=proxy,
                    progress_job_id=jid,
                )

        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(account_id),
            _run,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("revise_on_sale_item 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)

# ──────────────────────── 在售商品恢复出售 ──────────────────────── #

class ResumeMercariItemBody(PydanticModel):
    """通过 WebDrive 在煤炉编辑页点击「出品を再開する」恢复出售（仅暂停出售状态适用）。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    item_id: str = Field(..., min_length=1, max_length=64)
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    progress_job_id: Optional[str] = None

async def resume_on_sale_item(body: ResumeMercariItemBody):
    """
    账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页点击「出品を再開する」恢复出售，
    随后直接更新本地 on_sale_items 状态为 on_sale；经 ``run_mercari_serial_async`` 串行，
    浏览器在队列空闲超时后自动关闭。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 共用通用
    sync_progress 内存存储，前端可复用同一个轮询接口展示步骤。
    """
    from .....web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .....web_drive.core.paths import mercari_id_from_account_key
    from .....web_drive.resume.units.resume_order import resume_mercari_item as _do_resume
    from .....ssl_mitm_proxy.runner import default_mitm_proxy_url
    from .....use_mercari.sync.sync_progress import clear_sync_progress

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    jid = (body.progress_job_id or "").strip() or None
    if jid and not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    account_id = mercari_id_from_account_key(body.account_key)
    if account_id is None:
        raise HTTPException(status_code=400, detail="无效的 account_key")

    # 新计数模型下，恢复出售（stop → on_sale）不消耗库存（暂停期间该件仍占用「在售」名额），
    # 故不再做「绑定库存数量是否充足」的前置校验。
    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        mgr = get_web_drive_manager()

        if _account_platform(account_id) == "yahoo":
            from .....web_drive.yahoo_item import resume_yahoo_item

            async def _run() -> Dict[str, Any]:
                return await resume_yahoo_item(account_id, item_id=item_id)
        else:
            async def _run() -> Dict[str, Any]:
                return await _do_resume(
                    mgr,
                    body.account_key,
                    item_id=item_id,
                    proxy_server=proxy,
                    progress_job_id=jid,
                )

        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(account_id),
            _run,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("resume_on_sale_item 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)

# ──────────────────────── 在售商品暂停出售 ──────────────────────── #

class SuspendMercariItemBody(PydanticModel):
    """通过 WebDrive 在煤炉编辑页点击「出品を一時停止する」暂停出售（仅出售中状态适用）。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    item_id: str = Field(..., min_length=1, max_length=64)
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    progress_job_id: Optional[str] = None

async def suspend_on_sale_item(body: SuspendMercariItemBody):
    """
    账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页点击「出品を一時停止する」暂停出售，
    随后直接更新本地 on_sale_items 状态为 stop；经 ``run_mercari_serial_async`` 串行，
    浏览器在队列空闲超时后自动关闭。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 共用通用
    sync_progress 内存存储，前端可复用同一个轮询接口展示步骤。
    """
    from .....web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .....web_drive.core.paths import mercari_id_from_account_key
    from .....web_drive.suspend.units.suspend_order import suspend_mercari_item as _do_suspend
    from .....ssl_mitm_proxy.runner import default_mitm_proxy_url
    from .....use_mercari.sync.sync_progress import clear_sync_progress

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    jid = (body.progress_job_id or "").strip() or None
    if jid and not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    account_id = mercari_id_from_account_key(body.account_key)
    if account_id is None:
        raise HTTPException(status_code=400, detail="无效的 account_key")

    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        mgr = get_web_drive_manager()

        if _account_platform(account_id) == "yahoo":
            from .....web_drive.yahoo_item import suspend_yahoo_item

            async def _run() -> Dict[str, Any]:
                return await suspend_yahoo_item(account_id, item_id=item_id)
        else:
            async def _run() -> Dict[str, Any]:
                return await _do_suspend(
                    mgr,
                    body.account_key,
                    item_id=item_id,
                    proxy_server=proxy,
                    progress_job_id=jid,
                )

        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(account_id),
            _run,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("suspend_on_sale_item 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)
