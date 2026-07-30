# -*- coding: utf-8 -*-
"""在售商品列表处理器：从煤炉同步及详情拉取。"""
import logging
import re
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    resolve_mercari_account_id,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_automation_key
from ....use_mercari.on_sale.on_sale_item_detail_sync import fetch_detail_and_sync_inventory
from ....use_mercari.on_sale.on_sale_items_sync import (
    full_update_on_sale_details_from_mercari,
    sync_on_sale_items_from_mercari,
)
from ....use_mercari.on_sale.on_sale_sync_progress import (
    clear_on_sale_sync_progress,
    get_on_sale_sync_progress,
)
from ....use_mercari.sync.sync_progress import clear_sync_progress
from ....use_mercari.sync.sync_lock import (
    LABEL_FULL,
    begin_or_conflict as sync_lock_begin,
    end as sync_lock_end,
)
from ....use_mercari.sync.sync_data import (
    resolve_account_id_by_seller_id,
    resolve_enabled_account_ids,
)

from .on_sale_items_models import (
    FetchOnSaleDetailRequest,
    FetchOnSaleDetailsBatchRequest,
    SyncOnSaleRequest,
)


_FETCH_DETAILS_BATCH_MAX = 200
# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

log = logging.getLogger(__name__)


async def sync_on_sale(data: SyncOnSaleRequest):
    """
    从煤炉同步所有启用账号（status=active；不要求自动获取开启）的在售列表并写入本地：用各账号主
    profile ``mercari_{id}`` 经 MITM 打开 jp.mercari.com/mypage/listings，截获
    api.mercari.jp/items/get_items 响应。
    在同一浏览器会话内，对本次**新增**的商品依次打开商品页截获 items/get，执行与「获取详情」相同的库存回写（可用 WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL=0 关闭）。
    新列表中不存在的本地记录不物理删除，而是标记 is_delete=1（软删除）。
    列表接口默认仅返回 is_delete=0 数据。须已启动 mitmdump（与出品/抓包共用）。

    不传 ``account_id``：点击即同步全部已开启账号，逐个串行执行并汇总结果——每个账号的在售
    抓取走按 seller 区分的响应文件，且每账号完成后立即关闭其浏览器，确保严格不重叠。
    传 ``account_id``（如出品成功后的联动同步）：仅同步该账号，立刻刷新在售列表与新商品详情。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 配合，
    供前端轮询当前步骤展示全屏等待框。
    """
    jid = (data.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        account_ids = resolve_sync_account_ids(data.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lock_token = sync_lock_begin("page", LABEL_FULL)
    try:
        data_out = await sync_on_sale_core(account_ids=account_ids, progress_job_id=jid)
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_on_sale_sync_progress(jid)

    return {"success": True, "data": data_out}


def resolve_sync_account_ids(account_id: Optional[int]) -> List[int]:
    """指定了 account_id 就只同步它，否则取全部启用账号。RuntimeError 由调用方转 400。"""
    if account_id is not None:
        return [int(account_id)]
    return resolve_enabled_account_ids()


def _account_platform(account_id: int) -> str:
    """账号所属市集平台：``mercari``（默认）/ ``yahoo``。"""
    try:
        from ....db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return "mercari"
        return str(getattr(acc, "platform", "") or "").strip() or "mercari"
    except Exception:
        log.warning("[on_sale] 查询账号#%s 平台失败，按煤炉处理", account_id, exc_info=True)
        return "mercari"


async def sync_on_sale_core(
    *,
    account_ids: List[int],
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """「从煤炉同步」主体：不含 HTTP 与锁语义，**调用方须自行持有全局同步锁**。

    HTTP 入口 ``sync_on_sale`` 与任务队列处理器
    （``task_queue/handlers/on_sale.py``，用 ``begin_waiting`` 排队等锁）共用本函数。
    """
    accounts: List[Dict[str, Any]] = []
    api_item_count = inserted = updated = marked_deleted = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    for aid in account_ids:
        try:
            # 雅虎账号走雅虎的页面解析同步；写库规则与煤炉完全一致（同一 apply_on_sale_list_sync）
            if _account_platform(aid) == "yahoo":
                from ....use_yahoo.on_sale import sync_yahoo_on_sale_items

                runner = lambda aid=aid: sync_yahoo_on_sale_items(
                    account_id=aid, progress_job_id=progress_job_id
                )
            else:
                runner = lambda aid=aid: sync_on_sale_items_from_mercari(
                    account_id=aid,
                    progress_job_id=progress_job_id,
                )
            stats = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid),
                runner,
            )
        except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
            fail_count += 1
            accounts.append({"account_id": aid, "error": str(exc)})
            continue
        else:
            api_item_count += int(stats.get("api_item_count", 0) or 0)
            inserted += int(stats.get("inserted", 0) or 0)
            updated += int(stats.get("updated", 0) or 0)
            marked_deleted += int(stats.get("marked_deleted", 0) or 0)
            accounts.append(stats)
        finally:
            # 关闭当前账号浏览器，确保与下一账号不重叠（队列层默认 ~10s 后才关）。
            try:
                await mgr.close_session(mercari_automation_key(aid), force=True)
            except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                log.warning(
                    "[on_sale] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                )

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "fail_count": fail_count,
        "api_item_count": api_item_count,
        "inserted": inserted,
        "updated": updated,
        "marked_deleted": marked_deleted,
    }


async def full_update_on_sale(data: SyncOnSaleRequest):
    """
    TEMP_FULL_UPDATE: 临时功能，现有数据补齐发货时效后删除本函数及其路由/前端入口。

    全量更新：对所有启用账号（或指定 account_id）的「出售中 / 暂停出售」商品，逐个重新截获
    items/get 详情并回写（补齐 発送までの日数 / shipping_duration、刷新说明与库存关联）。

    与 ``sync_on_sale`` 同样使用 page 级同步锁与各账号串行队列；``progress_job_id`` 配合
    GET /use_web/on-sale-items/sync-progress/{job_id} 轮询当前步骤。
    """
    jid = (data.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        account_ids = resolve_sync_account_ids(data.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lock_token = sync_lock_begin("page", LABEL_FULL)
    try:
        data_out = await full_update_on_sale_core(
            account_ids=account_ids, progress_job_id=jid
        )
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_on_sale_sync_progress(jid)

    return {"success": True, "data": data_out}


async def full_update_on_sale_core(
    *,
    account_ids: List[int],
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """「全量更新」主体：不含 HTTP 与锁语义，**调用方须自行持有全局同步锁**。"""
    accounts: List[Dict[str, Any]] = []
    target_count = attempted = updated = failed = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    for aid in account_ids:
        try:
            if _account_platform(aid) == "yahoo":
                from ....use_yahoo.on_sale import full_update_yahoo_details

                runner = lambda aid=aid: full_update_yahoo_details(account_id=aid)
            else:
                runner = lambda aid=aid: full_update_on_sale_details_from_mercari(
                    account_id=aid,
                    progress_job_id=progress_job_id,
                )
            stats = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid),
                runner,
            )
        except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
            fail_count += 1
            accounts.append({"account_id": aid, "error": str(exc)})
            continue
        else:
            target_count += int(stats.get("target_count", 0) or 0)
            attempted += int(stats.get("attempted", 0) or 0)
            updated += int(stats.get("updated", 0) or 0)
            failed += int(stats.get("failed", 0) or 0)
            accounts.append(stats)
        finally:
            try:
                await mgr.close_session(mercari_automation_key(aid), force=True)
            except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                log.warning(
                    "[on_sale] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                )

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "fail_count": fail_count,
        "target_count": target_count,
        "attempted": attempted,
        "updated": updated,
        "failed": failed,
    }


def on_sale_sync_progress(job_id: str):
    """在售同步执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_on_sale_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}


async def fetch_on_sale_item_detail(data: FetchOnSaleDetailRequest):
    """
    使用对应账号 Edge（MITM）打开 ``https://jp.mercari.com/item/m{item_id}``，
    截获 api.mercari.jp/items/get 响应；解析 data.description 中的末行暗号（-=~<>）、
    「管理ID / 管理番号 / バーコード」，
    匹配库存后写入 mercari_item_id、on_sale_quantity。须已启动 mitmdump。

    ``progress_job_id`` 与 GET /use_web/on-sale-items/sync-progress/{job_id} 配合，
    供前端轮询当前步骤展示全屏等待框。
    """
    item_id = (data.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    jid = (data.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    account_id = data.account_id
    if account_id is None:
        rows = OnSaleItemModel.find_all(
            where="TRIM([item_id]) = TRIM(?)",
            params=(item_id,),
            limit=1,
        )
        seller_id = None
        if rows:
            seller_id = str(rows[0].seller_id or "").strip() or None
        if seller_id:
            account_id = resolve_account_id_by_seller_id(seller_id)
        if account_id is None:
            raise HTTPException(
                status_code=400,
                detail="请传 account_id，或在在售列表中存在该商品且卖家已绑定 active 煤炉账号（seller_id）",
            )

    try:
        qk = queue_key_for_mercari_account(int(account_id))
        if _account_platform(int(account_id)) == "yahoo":
            # 雅虎从商品编辑页读说明（没有 items/get 这种接口），写库仍复用煤炉那套绑定逻辑
            from ....use_yahoo.on_sale import sync_yahoo_item_details

            runner = lambda: sync_yahoo_item_details(int(account_id), [item_id])
        else:
            runner = lambda: fetch_detail_and_sync_inventory(
                item_id,
                account_id=account_id,
                progress_job_id=jid,
            )
        payload = await run_mercari_serial_async(qk, runner)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {exc}") from exc
    finally:
        if jid:
            clear_sync_progress(jid)

    return {"success": True, "data": payload}


async def fetch_on_sale_item_details_batch(data: FetchOnSaleDetailsBatchRequest):
    """
    对多个 item_id 依次执行 fetch_detail_and_sync_inventory，且整段只提交一次
    run_mercari_serial_async（与单条 fetch-detail、在售同步同一队列键 FIFO），避免多 HTTP
    并发在同一账号下抢占 Edge / MITM。
    """
    raw_ids = data.item_ids or []
    cleaned: List[str] = []
    seen: Set[str] = set()
    for x in raw_ids:
        t = str(x or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    if not cleaned:
        raise HTTPException(status_code=400, detail="item_ids 不能为空")
    if len(cleaned) > _FETCH_DETAILS_BATCH_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多处理 {_FETCH_DETAILS_BATCH_MAX} 个商品 ID",
        )

    try:
        aid = resolve_mercari_account_id(data.account_id)
        qk = queue_key_for_mercari_account(int(aid))

        is_yahoo = _account_platform(int(aid)) == "yahoo"

        async def _fetch_one(iid: str) -> Dict[str, Any]:
            """雅虎从编辑页读说明，煤炉走 MITM 截 items/get；返回结构一致。"""
            if not is_yahoo:
                return await fetch_detail_and_sync_inventory(iid, account_id=aid)
            from ....use_yahoo.on_sale import sync_yahoo_item_details

            st = await sync_yahoo_item_details(int(aid), [iid])
            if st.get("errors"):
                raise RuntimeError(st["errors"][0].get("error") or "详情同步失败")
            return {"sync": {"updated": bool(st.get("bound"))}}

        async def _run_batch() -> Dict[str, Any]:
            results: List[Dict[str, Any]] = []
            ok_synced = 0
            not_ok = 0
            for iid in cleaned:
                try:
                    payload = await _fetch_one(iid)
                    sync = payload.get("sync") if isinstance(payload.get("sync"), dict) else {}
                    if sync.get("updated"):
                        ok_synced += 1
                    else:
                        not_ok += 1
                    results.append({"item_id": iid, "sync": sync})
                except Exception as exc:
                    not_ok += 1
                    results.append({"item_id": iid, "sync": None, "error": str(exc)})
            return {
                "account_id": int(aid),
                "total": len(cleaned),
                "ok_synced": ok_synced,
                "not_ok": not_ok,
                "results": results,
            }

        out = await run_mercari_serial_async(qk, _run_batch)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"批量获取详情失败: {exc}") from exc

    return {"success": True, "data": out}
