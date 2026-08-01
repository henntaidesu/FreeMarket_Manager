# -*- coding: utf-8 -*-
"""
自动出品（售出即补挂）。

当增量订单同步发现某商品的**新售出订单**时，若满足：
  · 该账号开启了「自动上架」同步项（mercari_accounts.auto_fetch_relist=1）
  · 该商品单品开关开启（inventory.auto_listing_enabled=1）
  · 仍有剩余可售库存（quantity - on_sale_quantity - pending_outbound_qty > 0）
则在售出该商品的同一煤炉账号下，用商品当前保存的出品设置（不再读系统出品默认值，
缺省仅回落硬编码安全兜底），复用既有出品自动化 `post_to_market` 把它重新上架。

出品说明末行写入管理番号暗号（``encode_mgmt_id``），下次在售同步即可把新挂牌
``item_id`` 重新绑回 ``inventory.id``，与手动「出品」保持一致。

去重（防无限循环出品，三层）：
  1. 订单级：以 ``orders.auto_relisted`` 标记，一个售出订单最多触发一次补挂；
  2. 同轮级：一次 ``run_auto_relist_for_orders`` 内同一库存最多补挂一次
     （同批多笔售出订单指向同一库存时，剩余可售计数尚未更新，不去重会连续重复上架）；
  3. 台账级：**走任务队列的可上架预扣减**（``task_queue.reservations``，落在
     ``inventory.pending_listing_qty``）。入队即占位、在售同步绑定时核销、6 小时 TTL 兜底。

第 3 层过去是本模块自己的进程内字典 ``_unsynced_relists``：补挂发出后 +1，在售同步绑定时 -1。
**它扛不住重启**——补挂已发出、在售同步还没跑时后端重启，计数清零，下一单售出会对同一件
库存再补挂一次，形成重复上架（不可逆）。而且它是「先出品、返回后才记账」，进程在出品途中
被杀连一笔都记不下。现在改为提交 ``inventory.listing`` 任务：预扣减在**入队那一刻**写进
数据库，与手动出品完全同一套闸门，重启不丢。
"""

from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, Set

from ..db_manage.database import DatabaseManager
from ..db_manage.models.inventory.inventory import InventoryModel
from ..db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ..db_manage.models.orders.order import OrderModel
from ..db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from ..db_manage.models.system.system_log import SystemLogModel
from .mgmt_id_cipher import encode_mgmt_id, is_cipher_mgmt_line

log = logging.getLogger(__name__)

# 出品说明总长上限（与手动出品 SingleListingFormDialog 一致）
_DESCRIPTION_MAX_LEN = 1000




def _account_relist_enabled(account_id: Optional[int]) -> bool:
    """该账号是否开启了「自动上架」同步项（账号级开关）。"""
    if account_id is None:
        return False
    try:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        return acc is not None and int(getattr(acc, "auto_fetch_relist", 0) or 0) == 1
    except Exception:
        return False


async def run_auto_relist_for_orders(
    order_nos: Iterable[str],
    *,
    seller_id: Optional[str] = None,
    account_id: Optional[int] = None,
) -> None:
    """为若干新售出订单**提交**补挂任务（不在这里跑出品自动化）。

    每件合格库存提交一条 ``inventory.listing`` 任务，由全局单 worker 依次执行；可上架的
    预扣减在入队那一刻就落库，因此本函数返回时占用已经生效——即便后端随即重启，
    也不会重复补挂。出品的浏览器会话、全局出品锁、类目 position 等全在任务处理器里，
    与手动出品同一条路径。

    全程吞异常，绝不影响同步主流程。
    """
    nos = [str(x).strip() for x in (order_nos or []) if str(x or "").strip()]
    if not nos:
        return
    # 账号级「自动上架」开关：传入了 account_id 且未开启 → 直接跳过
    if account_id is not None and not _account_relist_enabled(account_id):
        return
    # 同轮去重：同一库存在本次调用内最多补挂一次（防同批多笔售出订单重复上架）
    relisted_in_run: Set[int] = set()
    for ono in nos:
        try:
            await _relist_for_order(
                ono,
                seller_id=seller_id,
                account_id=account_id,
                relisted_in_run=relisted_in_run,
            )
        except Exception as exc:  # 单个订单失败不影响其余订单与同步主流程
            log.exception("[auto_relist] 订单 %s 补挂异常：%s", ono, exc)


def _resolve_account_id(seller_id: Optional[str], account_id: Optional[int]) -> Optional[int]:
    """优先用同步传入的 account_id；否则按 seller_id 反查 mercari_accounts。"""
    if account_id is not None:
        try:
            return int(account_id)
        except (TypeError, ValueError):
            pass
    sid = str(seller_id or "").strip()
    if not sid:
        return None
    rows = ShopAccountModel.find_all(
        where="TRIM(IFNULL([seller_id], '')) = TRIM(?)",
        params=(sid,),
        limit=1,
    )
    if not rows:
        return None
    try:
        return int(getattr(rows[0], "id"))
    except (TypeError, ValueError):
        return None


def _account_name(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号名（用于系统日志冗余展示）；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        name = str(getattr(acc, "account_name", "") or "").strip()
        return name or None
    except Exception:
        return None


def _inventory_ids_for_order(order_no: str) -> List[int]:
    lines = OrderOutboundLineModel.find_all(
        where="[order_no] = ? AND [inventory_id] IS NOT NULL",
        params=(order_no,),
    )
    out: List[int] = []
    seen: Set[int] = set()
    for ln in lines:
        try:
            iid = int(getattr(ln, "inventory_id"))
        except (TypeError, ValueError):
            continue
        if iid > 0 and iid not in seen:
            seen.add(iid)
            out.append(iid)
    return out


def _build_relist_description(body_raw: Optional[str], inventory_id: int) -> str:
    """正文去掉末行旧暗号后，追加本商品的管理番号暗号（沿用 1000 字截断逻辑）。"""
    body = str(body_raw or "").rstrip()
    # 去掉末尾仅由暗号组成的行（避免重复 / 旧暗号残留）
    lines = body.splitlines()
    while lines and (not lines[-1].strip() or is_cipher_mgmt_line(lines[-1])):
        lines.pop()
    body = "\n".join(lines).rstrip()
    foot = encode_mgmt_id(inventory_id)
    max_body = max(0, _DESCRIPTION_MAX_LEN - len(foot) - 2)
    if len(body) > max_body:
        body = body[:max_body]
    return f"{body}\n\n{foot}" if body else foot


def _inventory_image_urls(inv) -> List[str]:
    from ..use_web.inventory.units.inventory_helpers import (
        _inventory_paths_from_parsed_row,
    )

    return _inventory_paths_from_parsed_row(
        {"images_json": getattr(inv, "images_json", None)}
    )


async def _relist_for_order(
    order_no: str,
    *,
    seller_id: Optional[str],
    account_id: Optional[int],
    relisted_in_run: Optional[Set[int]] = None,
) -> None:
    """处理单个售出订单的补挂。全程吞异常，仅记日志，绝不影响同步主流程。"""
    try:
        orders = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not orders:
            return
        order = orders[0]
        if int(getattr(order, "auto_relisted", 0) or 0) == 1:
            return

        aid = _resolve_account_id(
            seller_id or getattr(order, "data_user", None), account_id
        )
        if aid is None:
            log.warning(
                "[auto_relist] 订单 %s 找不到对应煤炉账号（seller_id=%s），跳过补挂",
                order_no,
                seller_id or getattr(order, "data_user", None),
            )
            return
        # 账号级「自动上架」开关未开 → 不补挂（不标记，便于将来开启后由新订单触发）
        if not _account_relist_enabled(aid):
            return

        # 乐观占用：先标记已处理，避免重复触发造成重复上架（上架涉及真实挂牌）。
        DatabaseManager().execute_update(
            "UPDATE [orders] SET [auto_relisted] = 1 WHERE [order_no] = ?",
            (order_no,),
        )

        inventory_ids = _inventory_ids_for_order(order_no)
        if not inventory_ids:
            return

        for inv_id in inventory_ids:
            try:
                await _relist_single_inventory(inv_id, aid, relisted_in_run=relisted_in_run)
            except Exception as exc:  # 单品失败不影响同订单其它商品
                log.exception("[auto_relist] 商品 %s 补挂异常：%s", inv_id, exc)
    except Exception as exc:
        log.exception("[auto_relist] 订单 %s 补挂异常：%s", order_no, exc)


async def _relist_single_inventory(
    inventory_id: int,
    account_id: int,
    *,
    relisted_in_run: Optional[Set[int]] = None,
) -> None:
    if relisted_in_run is not None and inventory_id in relisted_in_run:
        log.info(
            "[auto_relist] 商品 %s 本轮已补挂过，跳过（防同批订单重复上架）", inventory_id
        )
        return

    inv = InventoryModel.find_by_id(id=inventory_id)
    if inv is None:
        return
    if int(getattr(inv, "auto_listing_enabled", 0) or 0) != 1:
        return

    # 余量判断不在这里做终局判定：真正的闸门是入队时 reservations.reserve() 的 CAS
    #（``pending_listing_qty += 1 WHERE listable_quantity >= 1``）。这里只做一次早退，
    # 省掉「明显没余量还去拼一堆出品参数」的无用功。
    from .inventory_counters import recompute_listable_quantity

    recompute_listable_quantity([int(inventory_id)])
    inv = InventoryModel.find_by_id(id=inventory_id) or inv
    listable = int(getattr(inv, "listable_quantity", 0) or 0)
    if listable <= 0:
        log.info("[auto_relist] 商品 %s 无剩余可售库存（listable=0），跳过", inventory_id)
        return

    product_type_id = getattr(inv, "product_type_id", None)
    if product_type_id is None:
        log.warning("[auto_relist] 商品 %s 缺少 product_type_id（商品类型），跳过", inventory_id)
        return

    image_urls = _inventory_image_urls(inv)
    if not image_urls:
        log.warning("[auto_relist] 商品 %s 无可用图片，跳过", inventory_id)
        return

    name = (
        str(getattr(inv, "listing_title", "") or "").strip()
        or str(getattr(inv, "name", "") or "").strip()
    )
    if not name:
        log.warning("[auto_relist] 商品 %s 缺少出品标题/名称，跳过", inventory_id)
        return

    body_raw = getattr(inv, "listing_body", None) or getattr(inv, "description", None)
    description = _build_relist_description(body_raw, inventory_id)
    price = int(getattr(inv, "price", 0) or 0)

    # 出品设置：只用商品自身保存值，缺省回落硬编码安全兜底（不再读系统出品默认值）。
    # 前端已保证：商品缺出品必填字段时无法开启自动出品，故兜底几乎不会触发，仅防空值出品报错。
    def _pick(item_val, fallback):
        s = str(item_val if item_val is not None else "").strip()
        return s or fallback

    status = _pick(getattr(inv, "listing_status", None), "new_unused")
    sale_type = _pick(getattr(inv, "sale_type", None), "instant_buy")
    shipping_payer = _pick(getattr(inv, "shipping_payer", None), "seller")
    shipping_method = _pick(getattr(inv, "shipping_method", None), "undecided")
    shipping_days = _pick(getattr(inv, "shipping_days", None), "2_3_days")
    shipping_from_area_id = str(getattr(inv, "shipping_from_area_id", None) or "").strip()
    auction_duration = str(getattr(inv, "auction_duration", None) or "normal").strip() or "normal"
    # 自动出品的出品方式：1=水印出品（默认），0=原图出品
    watermark = int(getattr(inv, "auto_listing_watermark", 1) or 0) == 1
    # 发货地无合法兜底值：为空则不补挂（与前端门控一致——发货地为空时无法开启自动出品）
    if not shipping_from_area_id:
        log.warning(
            "[auto_relist] 商品 %s：未保存发货地，跳过补挂", inventory_id
        )
        return

    # 提交到任务队列，而不是在这里直接跑出品自动化。
    # 关键差别是**预扣减的时机与持久化**：submit_task 在入队那一刻就把
    # inventory.pending_listing_qty +1 写进数据库（可上架不足直接 InsufficientListableError），
    # 之后由在售同步绑定时核销、6 小时 TTL 兜底。原来的做法是先跑完出品再往进程内存里记一笔，
    # 补挂已发出但后端在在售同步之前重启，那笔记账就没了 → 下一单售出重复补挂。
    # 顺带拿到的：出品在任务页可见/可取消/可重试，失败有终态，与手动出品同一条代码路径。
    from ..task_queue import submit_task
    from ..task_queue.reservations import InsufficientListableError
    from ..task_queue.store import SYSTEM_USERNAME, TaskDuplicateError
    from ..web_drive.core.paths import mercari_account_key

    payload = {
        "inventory_ids": [int(inventory_id)],
        "account_key": mercari_account_key(account_id),
        "account_id": int(account_id),
        "name": name,
        "description": description,
        "image_urls": image_urls,
        "category_mapping_id": str(product_type_id),
        "status": status,
        "shipping_payer": shipping_payer,
        "shipping_method": shipping_method,
        "sale_type": sale_type,
        "auction_duration": auction_duration,
        "price": price,
        "shipping_days": shipping_days,
        "shipping_from_area_id": shipping_from_area_id,
        "watermark": watermark,
        "use_mitm_proxy": True,
    }

    account_name = _account_name(account_id)
    log.info(
        "[auto_relist] 商品 %s 触发补挂：account_id=%s price=%s name=%s",
        inventory_id, account_id, price, name,
    )
    # 入队尝试前即占位：同一轮内绝不对同一库存二次补挂
    if relisted_in_run is not None:
        relisted_in_run.add(inventory_id)

    try:
        task, _created = submit_task(
            task_type="inventory.listing",
            payload=payload,
            user_id=None,
            username=SYSTEM_USERNAME,
        )
    except InsufficientListableError as exc:
        # 可上架已被别的排队出品/在售占满：这正是闸门在起作用，不是错误
        log.info("[auto_relist] 商品 %s 可上架不足，跳过补挂：%s", inventory_id, exc)
        return
    except TaskDuplicateError as exc:
        log.info("[auto_relist] 商品 %s 已有同语义任务在队列，跳过：%s", inventory_id, exc)
        return
    except Exception as exc:
        log.exception("[auto_relist] 商品 %s 补挂入队失败：%s", inventory_id, exc)
        SystemLogModel.add(
            category="auto_relist",
            level="error",
            account_id=account_id,
            account_name=account_name,
            message=f"重新上架入队失败：#{inventory_id} {name}（¥{price}）：{exc}",
            detail={"inventory_id": inventory_id, "name": name, "price": price,
                    "account_id": account_id, "error": str(exc)},
        )
        return

    log.info("[auto_relist] 商品 %s 补挂已入队：任务 #%s", inventory_id, task["id"])
    SystemLogModel.add(
        category="auto_relist",
        level="info",
        account_id=account_id,
        account_name=account_name,
        message=f"重新上架已加入任务队列：#{inventory_id} {name}（¥{price}）→ 任务 #{task['id']}",
        detail={"inventory_id": inventory_id, "name": name, "price": price,
                "account_id": account_id, "task_id": task["id"]},
    )
