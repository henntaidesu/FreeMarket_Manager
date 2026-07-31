# -*- coding: utf-8 -*-
"""订单信息刷新与进度查询"""

import re
from fastapi import HTTPException
from .....db_manage.models.orders.order import OrderModel
from .....use_mercari.get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from .....use_mercari.sync.sync_data import resolve_account_id_by_seller_id
from .....use_mercari.sync.sync_progress import clear_sync_progress, get_sync_progress
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from ..orders_models import RefreshOrderInfoBody


_REFRESH_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

def _is_yahoo_account(account_id: int) -> bool:
    try:
        from .....db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return False
        return (str(getattr(acc, "platform", "") or "").strip() or "mercari") == "yahoo"
    except Exception:
        return False


async def refresh_order_info(data: RefreshOrderInfoBody):
    """WebDriver 打开 jp.mercari.com/transaction/m{订单号}，MITM 截获 transaction_evidences/get 后更新状态、金额等字段。

    ``progress_job_id`` 配合 GET /use_web/orders/refresh-progress/{job_id} 让前端轮询展示步骤。
    """
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    du = (data.data_user or "").strip()
    if not du:
        raise HTTPException(status_code=400, detail="卖家ID（data_user）不能为空")

    jid = (data.progress_job_id or "").strip() or None
    if jid and not _REFRESH_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    aid = resolve_account_id_by_seller_id(du)
    if aid is None:
        raise HTTPException(
            status_code=400,
            detail="未找到与该卖家ID绑定的 active 煤炉账号，请在账号管理中配置 seller_id",
        )

    if _is_yahoo_account(aid):
        # 雅虎没有 transaction_evidences 这类接口，改为重读卖家交易页
        from .....use_yahoo.orders import refresh_yahoo_order

        try:
            data_out = await refresh_yahoo_order(int(aid), order_no)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"刷新失败: {exc}") from exc
        return {"success": True, "data": data_out}

    async def _do_refresh() -> dict:
        err = await apply_item_info_to_order(
            order_no,
            account_id=aid,
            expected_seller_id=du,
            progress_job_id=jid,
        )
        if err == "order_not_found":
            raise HTTPException(status_code=404, detail="本地不存在该订单号")
        if err == "seller_mismatch":
            raise HTTPException(
                status_code=400,
                detail="接口返回的商品不属于该卖家，请检查订单号与卖家ID是否匹配",
            )
        if err and err.startswith("api:"):
            raise HTTPException(status_code=502, detail=err[4:])
        if err and err.startswith("request:"):
            raise HTTPException(status_code=502, detail=err[8:])
        if err == "save_failed":
            raise HTTPException(status_code=500, detail="写入数据库失败")
        if err:
            raise HTTPException(status_code=400, detail=err)

        rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="订单不存在")
        return rows[0].to_dict()

    try:
        return await run_mercari_serial_async(queue_key_for_mercari_account(int(aid)), _do_refresh)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)

def refresh_order_progress(job_id: str):
    """订单单行刷新进度轮询（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _REFRESH_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}
