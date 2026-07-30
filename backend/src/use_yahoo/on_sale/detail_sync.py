# -*- coding: utf-8 -*-
"""雅虎在售商品详情同步：把说明末行的管理番号暗号解析回库存。

没有这一步，雅虎挂牌就绑不到库存——``inventory.mercari_item_id`` 不写、在售数不涨、
出品预扣减（``pending_listing_qty``）也没人核销，只能等 6 小时 TTL。

取数走**商品编辑页** ``/item/{id}/edit``：说明直接从 textarea 读原值，比解析商品页正文稳
（管理番号暗号是 ``-=~<>`` 这类字符，正文里容易被排版和相邻文案粘连）；发货天数也能直接从
``select[name=timeToShip]`` 拿到枚举值。

解析到的东西塞成与煤炉 ``items/get`` 同形状的伪响应，直接交给
``detail_sync_inventory_from_item_get_response``——暗号解析、组合出品拆分、库存回写、
在售数对账全部复用煤炉那一套，不重写第二份。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser
from ...web_drive.listing.units.post_to_yahoo._constants import (
    DESCRIPTION_PLACEHOLDER_MARK,
    NAME_INPUT_PLACEHOLDER,
    SHIPPING_DAYS_SELECT_NAME,
)

log = logging.getLogger(__name__)


def yahoo_item_edit_url(item_id: str) -> str:
    return f"{YAHOO_BASE_URL}/item/{str(item_id).strip()}/edit"


#: 雅虎发货天数枚举 → 煤炉 shipping_duration 的 (id, 展示名)，让两边在售页显示一致
_SHIPPING_DURATION_BY_YAHOO = {
    "ONE_TO_TWO_DAYS": (1, "1~2日で発送"),
    "TWO_TO_THREE_DAYS": (2, "2~3日で発送"),
    "THREE_TO_SEVEN_DAYS": (3, "4~7日で発送"),
}

#: 雅虎恒为出品者負担（送料込み），与煤炉 shipping_payer id=2 同义
_SHIPPING_PAYER_SELLER = (2, "送料込み(出品者負担)")

_READ_FORM_JS = """
(sel) => {
  const name = document.querySelector(sel.name);
  const desc = document.querySelector(sel.desc);
  const days = document.querySelector(sel.days);
  return {
    name: name ? name.value : null,
    description: desc ? desc.value : null,
    timeToShip: days ? days.value : null,
    notFound: (document.body ? document.body.innerText : '').includes('ご指定のページが見つかりませんでした'),
  };
}
"""


def _build_pseudo_item_get(
    item_id: str,
    form: Dict[str, Any],
    *,
    seller_id: Optional[str],
    status: str,
) -> Dict[str, Any]:
    """拼成煤炉 ``items/get`` 的形状，好让煤炉的详情写库逻辑原样吃下。"""
    dur = _SHIPPING_DURATION_BY_YAHOO.get(str(form.get("timeToShip") or "").strip())
    data: Dict[str, Any] = {
        "id": str(item_id).strip(),
        "name": form.get("name"),
        "description": form.get("description"),
        "status": status,
        "shipping_payer": {"id": _SHIPPING_PAYER_SELLER[0], "name": _SHIPPING_PAYER_SELLER[1]},
    }
    if seller_id:
        data["seller"] = {"id": str(seller_id).strip()}
    if dur:
        data["shipping_duration"] = {"id": dur[0], "name": dur[1]}
    return {"result": "OK", "data": data}


async def _read_edit_form(page: Any, item_id: str) -> Dict[str, Any]:
    await page.goto(yahoo_item_edit_url(item_id), wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    return await page.evaluate(
        _READ_FORM_JS,
        {
            "name": f'input[placeholder="{NAME_INPUT_PLACEHOLDER}"]',
            "desc": f'textarea[placeholder*="{DESCRIPTION_PLACEHOLDER_MARK}"]',
            "days": f'select[name="{SHIPPING_DAYS_SELECT_NAME}"]',
        },
    )


async def sync_yahoo_item_details(
    account_id: int,
    item_ids: List[str],
    *,
    seller_id: Optional[str] = None,
    status: str = "on_sale",
) -> Dict[str, Any]:
    """逐件打开编辑页读说明并回写库存绑定。返回统计（失败逐件记录，不中断其余）。"""
    from ...use_mercari.on_sale.on_sale_item_detail_sync.detail_sync import (
        detail_sync_inventory_from_item_get_response,
    )

    ids = [str(i).strip() for i in item_ids if str(i or "").strip()]
    stats: Dict[str, Any] = {
        "requested": len(ids), "fetched": 0, "bound": 0, "failed": 0, "errors": [],
    }
    if not ids:
        return stats

    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_item_edit_url(ids[0])
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        for iid in ids:
            try:
                form = await _read_edit_form(page, iid)
                if not form or form.get("notFound"):
                    raise RuntimeError("编辑页打不开（商品可能已售出/已删除）")
                if form.get("description") is None:
                    raise RuntimeError("编辑页未读到商品说明（页面结构可能已变更）")
                stats["fetched"] += 1
                resp = _build_pseudo_item_get(
                    iid, form, seller_id=seller_id, status=status
                )
                out = detail_sync_inventory_from_item_get_response(iid, resp)
                if (out.get("sync") or {}).get("inventory_id") is not None:
                    stats["bound"] += 1
            except Exception as exc:  # noqa: BLE001 单件失败不影响其余
                stats["failed"] += 1
                stats["errors"].append({"item_id": iid, "error": str(exc)[:180]})
                log.warning("[yahoo_detail] %s 详情同步失败：%s", iid, exc)
    log.info("[yahoo_detail] 账号#%s 详情同步：%s", account_id, {
        k: v for k, v in stats.items() if k != "errors"
    })
    return stats


async def full_update_yahoo_details(
    account_id: int,
    *,
    seller_id: Optional[str] = None,
) -> Dict[str, Any]:
    """全量重刷该账号所有雅虎在售商品的详情（与煤炉「全量更新」同口径：出售中 + 暂停出售）。"""
    from ...db_manage.database import DatabaseManager
    from ..seller import resolve_yahoo_seller_id

    aid = int(account_id)
    sid = str(seller_id or "").strip() or await resolve_yahoo_seller_id(aid)
    rows = DatabaseManager().execute_query(
        "SELECT [item_id] FROM [on_sale_items] "
        "WHERE TRIM(IFNULL([seller_id], '')) = TRIM(?) "
        "AND TRIM(IFNULL([platform], '')) = 'yahoo' "
        "AND COALESCE([is_delete], 0) = 0 "
        "AND IFNULL([status], '') IN ('on_sale', 'stop')",
        (sid,),
    ) or []
    ids = [str(r[0]).strip() for r in rows if r and str(r[0] or "").strip()]
    stats = await sync_yahoo_item_details(aid, ids, seller_id=sid)
    # 字段名对齐煤炉 full_update 的统计口径，便于上层汇总
    return {
        "account_id": aid,
        "platform": "yahoo",
        "target_count": stats["requested"],
        "attempted": stats["fetched"],
        "updated": stats["bound"],
        "failed": stats["failed"],
        "errors": stats["errors"],
    }
