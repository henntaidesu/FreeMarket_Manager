# -*- coding: utf-8 -*-
"""出品端点：post_to_market + 进度 + 分类坐标"""

import logging
import re
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel, Field
from .....web_drive import get_web_drive_manager

log = logging.getLogger(__name__)


# 出品进度轮询 job_id：仅允许安全字符（前端 crypto.randomUUID() 等）
_LISTING_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

# ──────────────────────── 出品自动化 ──────────────────────── #

class PostToMarketBody(PydanticModel):
    """出品自动化请求体（全字段）。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = ""
    description: str = ""
    image_urls: List[str] = []
    # 是否为图片添加水印（出品账号名 + 日期）后再上传
    watermark: bool = False
    # 商品类型：mapping_id 用于从 DB 查出各级 position
    category_mapping_id: Optional[str] = None
    # 商品状態
    status: str = ""
    # 快递費負担：seller / buyer
    shipping_payer: str = "seller"
    # 配送方法：undecided / rakuraku / yuuyu / tanome / regular_mail
    shipping_method: str = "undecided"
    # 販売タイプ + 价格
    sale_type: str = "instant_buy"   # "instant_buy" | "auction"
    auction_duration: str = "normal"  # "normal" | "3hours"（仅 auction 时生效）
    price: int = 0
    # 发货
    shipping_days: str = "2_3_days"  # "1_2_days" | "2_3_days" | "4_7_days"
    shipping_from_area_id: str = ""  # Mercari area id，如 "13"
    # 代理
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    # 可选：与 GET /listing/post-progress/{job_id} 配合展示当前步骤
    progress_job_id: Optional[str] = Field(default=None, max_length=128)

def _get_category_positions(mapping_id: Optional[str]) -> dict:
    """根据 mapping_id 查询类别各级 position，找不到时返回全 None。"""
    if not mapping_id:
        return {}
    try:
        from .....db_manage.models.system.product_type_category_mapping import (
            ProductTypeCategoryMappingModel,
        )
        rows = ProductTypeCategoryMappingModel.find_all(
            where="mapping_id = ?",
            params=(str(mapping_id),),
            limit=1,
        )
        if not rows:
            return {}
        row = rows[0].to_dict()
        return {
            "category_level1_pos": row.get("category_level1_position"),
            "category_level2_pos": row.get("category_level2_position"),
            "category_level3_pos": row.get("category_level3_position"),
            "product_type_pos":    row.get("product_type_position"),
        }
    except Exception as exc:
        log.warning("查询 category positions 失败: %s", exc)
        return {}

def listing_post_progress(job_id: str):
    """出品自动化执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    from .....web_drive.listing.units.listing_progress import get_listing_progress

    jid = (job_id or "").strip()
    if not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_listing_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}

async def post_to_market(
    body: PostToMarketBody,
    *,
    background_caller: bool = False,
    wait_for_lock: Optional[bool] = None,
):
    """
    在出品专用**独立无头** profile（``mercari_{id}__listing``）经 SSL 中间人代理打开
    https://jp.mercari.com/sell/create，并自动完成全部表单步骤：
      · Switch 检查 → 图片上传 → 商品名/说明填写
      · 商品类型选择 → 販売タイプ+价格 → 发货天数 → 发货地址
    登录态进入时从主 profile 克隆 Cookie，不占用 ``mercari_{id}``——与自动同步、
    /#/mercari-accounts「打开浏览器」互不冲突；流程结束后无头会话立即关闭。

    全局出品锁：同一时刻只允许一个出品在执行（跨账号、跨用户）。
    - HTTP 手动出品（默认）：锁被占用时直接 409，前端提示稍候再试；
    - ``background_caller=True``（自动补挂等后台任务）：排队等待锁，不丢任务，
      且**不再进账号串行队列**（调用方已在队列槽内，再入队会自我死锁）。
    - ``wait_for_lock``：单独控制「等锁 / 冲突即 409」，默认跟随 ``background_caller``。
      任务队列 worker 传 ``background_caller=False, wait_for_lock=True``——
      既要进账号串行队列（与同账号同步/待办互斥），又要排队等锁而不是失败。
    """
    from .....web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .....web_drive.core.paths import mercari_id_from_account_key
    from .....web_drive.listing.units.listing_lock import (
        ListingBusyError,
        hold_listing_lock,
    )
    from .....web_drive.listing.units.listing_progress import clear_listing_progress
    from .....web_drive.listing.units.post_to_macket import post_to_market as _do_post
    from .....ssl_mitm_proxy.runner import default_mitm_proxy_url

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

        # 从 DB 查询 category position 字段
        cat_pos = _get_category_positions(body.category_mapping_id)

        mgr = get_web_drive_manager()

        async def _run() -> Dict[str, Any]:
            return await _do_post(
                mgr,
                body.account_key,
                name=body.name,
                description=body.description,
                image_urls=body.image_urls,
                watermark=body.watermark,
                category_level1_pos=cat_pos.get("category_level1_pos"),
                category_level2_pos=cat_pos.get("category_level2_pos"),
                category_level3_pos=cat_pos.get("category_level3_pos"),
                product_type_pos=cat_pos.get("product_type_pos"),
                status=body.status,
                shipping_payer=body.shipping_payer,
                shipping_method=body.shipping_method,
                sale_type=body.sale_type,
                auction_duration=body.auction_duration,
                price=body.price,
                shipping_days=body.shipping_days,
                shipping_from_area_id=body.shipping_from_area_id,
                proxy_server=proxy,
                progress_job_id=jid,
            )

        # 全局出品锁：手动入口冲突即 409；后台补挂 / 任务队列排队等待
        label = "自动出品（售出补挂）进行中" if background_caller else "其他用户正在出品"
        wait = background_caller if wait_for_lock is None else bool(wait_for_lock)

        async def _locked_run() -> Dict[str, Any]:
            async with hold_listing_lock(label, wait=wait):
                return await _run()

        if background_caller:
            # 自动补挂已在该账号同步队列槽内（auto_relist 内联调用），不可再入队（自我死锁）；
            # 锁序为「账号队列 → 出品锁」，由外层同步任务持有队列。
            data = await _locked_run()
        else:
            # 手动出品：先进该账号串行队列，再取全局出品锁——锁序与 auto_relist 一致
            #（账号队列 → 出品锁），既与同账号同步/待办互斥（避免共享 MITM 截获串扰），又不会死锁。
            data = await run_mercari_serial_async(
                queue_key_for_mercari_account(account_id),
                _locked_run,
            )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except ListingBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("post_to_market 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_listing_progress(jid)
