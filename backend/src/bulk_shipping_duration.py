# -*- coding: utf-8 -*-
"""一键修改发货时效：把在售商品的「発送までの日数」整批改成同一个值。

和在售页的批量修改是同一件事的两个尺度——那里一次最多勾 10 件，这里按「平台 / 账号」筛一遍，
把**所有**还不是目标值的在售商品一次排完。三条约束：

1. **只走 ``revise_on_sale_item``。** 它已经按 ``shop_accounts.platform`` 分派煤炉 / 雅虎，
   并把煤炉的 ``1/2/3`` 映射成雅虎的枚举，这里不再有第二份平台分支。
2. **商品按账号分组**：组间并发（各账号的浏览器/串行队列本就互不相干），组内严格逐件，
   每件之间随机等待 ``BULK_SHIPPING_DURATION_ITEM_DELAY_MIN_SEC`` ~ ``..._MAX_SEC``
   （默认 30/90 秒）——限速按账号计，因为被平台盯上的是单账号的连续快速操作。
   sleep 同时是取消点：任务页「取消」可中断整批。
3. **幂等**：目标集合每次按当前数据库重算，只取 ``shipping_duration_id`` 不等于目标的行，
   中途失败后再提交一次同样的参数就只处理剩下的。这条依赖「改成功后本地
   ``shipping_duration_id`` 被回写」——煤炉在 ``revise/units/revise_order.py``，雅虎在
   ``yahoo_item/units/item_edit.py``；少一边就会每次重跑同一批商品。

作用范围包含 ``status='stop'``（暂停出售）的商品：两个平台的编辑页在停止状态下同样能改
発送までの日数，恢复出售后即为新值；漏掉它们会让「一键」名不副实。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from .db_manage.database import DatabaseManager

log = logging.getLogger(__name__)

#: 煤炉「発送までの日数」option value → 展示名（与 revise_order / 在售页同一套口径）
TARGET_NAMES: Dict[str, str] = {
    "1": "1~2日で発送",
    "2": "2~3日で発送",
    "3": "4~7日で発送",
}

#: 参与批量的状态：出售中 + 暂停出售
_TARGET_STATUSES = ("on_sale", "stop")

_DEFAULT_DELAY_MIN_SEC = 30.0
_DEFAULT_DELAY_MAX_SEC = 90.0


# ──────────────────────── 入参规范化 ──────────────────────── #

def normalize_target(value: Any) -> str:
    """校验目标时效（煤炉 option value ``1``/``2``/``3``）。非法值抛 ``ValueError``。"""
    v = str(value or "").strip()
    if v not in TARGET_NAMES:
        raise ValueError(f"发货时效只能是 {'/'.join(TARGET_NAMES)}，收到：{value!r}")
    return v


def normalize_platform(value: Any) -> Optional[str]:
    """校验平台筛选；空 = 不限。"""
    v = str(value or "").strip().lower()
    if not v:
        return None
    if v not in ("mercari", "yahoo"):
        raise ValueError(f"平台只能是 mercari / yahoo，收到：{value!r}")
    return v


def resolve_seller_id(account_id: Optional[int]) -> Optional[str]:
    """账号筛选：``shop_accounts.id`` → ``seller_id``（在售表里只有 seller_id）。空 = 不限。"""
    if account_id is None:
        return None
    from .db_manage.models.shop_accounts.shop_account import ShopAccountModel

    acc = ShopAccountModel.find_by_id(id=int(account_id))
    if not acc:
        raise ValueError(f"账号#{account_id} 不存在")
    sid = str(getattr(acc, "seller_id", "") or "").strip()
    if not sid:
        raise ValueError(f"账号#{account_id} 还没有卖家ID，无法按账号筛选在售商品")
    return sid


def scope_label(seller_id: Optional[str], platform: Optional[str], account_name: str = "") -> str:
    """任务标题/日志里的范围描述。"""
    parts: List[str] = []
    if platform:
        parts.append("煤炉" if platform == "mercari" else "雅虎")
    if seller_id:
        parts.append(account_name.strip() or f"卖家 {seller_id}")
    return "、".join(parts) if parts else "全部账号"


# ──────────────────────── 目标集合 ──────────────────────── #

def _scope_sql(seller_id: Optional[str], platform: Optional[str]) -> Tuple[str, List[Any]]:
    """范围条件（不含时效比较）。平台口径与在售页筛选一致：历史行无 platform 按煤炉处理。"""
    placeholders = ", ".join("?" for _ in _TARGET_STATUSES)
    sql = (
        "COALESCE([is_delete], 0) = 0 "
        f"AND TRIM(IFNULL([status], '')) IN ({placeholders})"
    )
    params: List[Any] = list(_TARGET_STATUSES)
    if seller_id:
        sql += " AND TRIM(IFNULL([seller_id], '')) = TRIM(?)"
        params.append(seller_id)
    if platform == "mercari":
        sql += " AND COALESCE(NULLIF(TRIM([platform]), ''), 'mercari') = 'mercari'"
    elif platform:
        sql += " AND TRIM(IFNULL([platform], '')) = TRIM(?)"
        params.append(platform)
    return sql, params


def _count(where: str, params: List[Any]) -> int:
    rows = DatabaseManager().execute_query(
        f"SELECT COUNT(1) FROM [on_sale_items] WHERE {where}", tuple(params)
    )
    return int(rows[0][0] or 0) if rows else 0


def preview(
    target: str,
    *,
    account_id: Optional[int] = None,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """范围内的件数：``pending`` 待修改（含从未同步过详情、时效为空的行）/ ``already`` 已是目标。"""
    tgt = normalize_target(target)
    plat = normalize_platform(platform)
    sid = resolve_seller_id(account_id)

    scope, params = _scope_sql(sid, plat)
    pending = _count(f"{scope} AND COALESCE([shipping_duration_id], 0) <> ?", params + [int(tgt)])
    already = _count(f"{scope} AND COALESCE([shipping_duration_id], 0) = ?", params + [int(tgt)])
    return {
        "target": tgt,
        "target_name": TARGET_NAMES[tgt],
        "pending": pending,
        "already": already,
        "total": pending + already,
    }


def _targets(
    target: str, seller_id: Optional[str], platform: Optional[str]
) -> List[Dict[str, Any]]:
    """要改的行：范围内 ``shipping_duration_id`` 不等于目标的全部商品。"""
    scope, params = _scope_sql(seller_id, platform)
    rows = DatabaseManager().execute_query(
        "SELECT [item_id], [seller_id], [name] FROM [on_sale_items] "
        f"WHERE {scope} AND COALESCE([shipping_duration_id], 0) <> ? ORDER BY [id] ASC",
        tuple(params + [int(target)]),
    )
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        iid = str(r[0] or "").strip()
        if not iid:
            continue
        out.append({
            "item_id": iid,
            "seller_id": str(r[1] or "").strip(),
            "name": str(r[2] or "").strip(),
        })
    return out


# ──────────────────────── 随机间隔 ──────────────────────── #

def _delay_bounds() -> Tuple[float, float]:
    def _read(name: str, default: float) -> float:
        try:
            v = float((os.environ.get(name) or "").strip() or default)
        except ValueError:
            return default
        return v if v >= 0 else default

    lo = _read("BULK_SHIPPING_DURATION_ITEM_DELAY_MIN_SEC", _DEFAULT_DELAY_MIN_SEC)
    hi = _read("BULK_SHIPPING_DURATION_ITEM_DELAY_MAX_SEC", _DEFAULT_DELAY_MAX_SEC)
    return (lo, hi) if hi >= lo else (hi, lo)


def next_delay_sec() -> float:
    lo, hi = _delay_bounds()
    return random.uniform(lo, hi)


# ──────────────────────── 批量执行 ──────────────────────── #

def _account_for(seller_id: str, cache: Dict[str, tuple]) -> tuple:
    """seller_id → ``(mercari_{account_id}, 账号名)``；没有对应的 active 账号则 ``(None, "")``。

    account_key 一律是 ``mercari_{id}``——雅虎账号也用这个前缀（见 CLAUDE.md），
    平台由 ``revise_on_sale_item`` 从 ``shop_accounts`` 解析，不看 key。
    """
    sid = str(seller_id or "").strip()
    if sid in cache:
        return cache[sid]

    from .db_manage.models.shop_accounts.shop_account import ShopAccountModel
    from .use_mercari.sync.sync_data import resolve_account_id_by_seller_id
    from .web_drive.core.paths import mercari_account_key

    found: tuple = (None, "")
    try:
        aid = resolve_account_id_by_seller_id(sid)
        if aid is not None:
            acc = ShopAccountModel.find_by_id(id=int(aid))
            name = str(getattr(acc, "account_name", "") or "").strip() if acc else ""
            found = (mercari_account_key(int(aid)), name or f"账号#{aid}")
    except Exception:
        log.exception("[shipping_duration] 解析卖家 %s 的账号失败", sid)
    cache[sid] = found
    return found


async def _apply_one(account_key: str, item_id: str, target: str) -> None:
    """改单件的発送までの日数。内部已按账号平台（煤炉 / 雅虎）分派，失败抛异常。"""
    from .use_web.web_drive.units.web_drive_handler.items import (
        ReviseMercariItemBody,
        revise_on_sale_item,
    )

    await revise_on_sale_item(
        ReviseMercariItemBody(
            account_key=account_key,
            item_id=item_id,
            shipping_duration=target,
            use_mitm_proxy=True,
        )
    )


def _group_by_account(
    targets: List[Dict[str, Any]], stats: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """按账号分组；解析不到账号的就地计入 skipped。

    分组在并发**之前**一次做完：账号解析是同步 DB 查询，留在协程里做只会让缓存变成竞态。
    """
    cache: Dict[str, tuple] = {}
    groups: Dict[str, Dict[str, Any]] = {}
    for row in targets:
        account_key, account_name = _account_for(row["seller_id"], cache)
        if not account_key:
            stats["skipped"] += 1
            stats["errors"].append(
                {"item_id": row["item_id"], "error": f"卖家 {row['seller_id']} 无启用账号"}
            )
            continue
        grp = groups.setdefault(account_key, {"name": account_name, "rows": []})
        grp["rows"].append(row)
    return groups


async def run(
    target: str,
    *,
    account_id: Optional[int] = None,
    platform: Optional[str] = None,
    report: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """把范围内所有「时效 ≠ 目标」的在售商品逐件改成目标时效。

    多个账号同时进行，单个账号内逐件并在两件之间随机等待。返回统计；有失败时由调用方
    抛错让任务落 failed（统计写在错误文案里），再提交一次即可只重跑剩下的。
    """
    say = report or (lambda step, label: None)
    tgt = normalize_target(target)
    plat = normalize_platform(platform)
    sid = resolve_seller_id(account_id)
    name = TARGET_NAMES[tgt]

    targets = _targets(tgt, sid, plat)
    stats: Dict[str, Any] = {
        "target": tgt,
        "target_name": name,
        "scope": scope_label(sid, plat),
        "total": len(targets),
        "ok": 0,
        "failed": 0,
        "skipped": 0,
        "accounts": 0,
        "errors": [],
    }
    say("scan", f"发货时效改为「{name}」：共 {stats['total']} 件待修改（{stats['scope']}）")
    if not targets:
        return stats

    groups = _group_by_account(targets, stats)
    stats["accounts"] = len(groups)
    pending = sum(len(g["rows"]) for g in groups.values())
    if not pending:
        return stats

    say("scan", f"共 {pending} 件待修改，{len(groups)} 个账号同时进行")
    # 进度是全局计数：多个账号并发写同一个任务行，标签里带上账号名才看得出是谁在动
    done = 0

    async def _run_account(account_key: str, group: Dict[str, Any]) -> None:
        nonlocal done
        rows = group["rows"]
        who = group["name"]
        for idx, row in enumerate(rows):
            iid = row["item_id"]
            try:
                await _apply_one(account_key, iid, tgt)
                stats["ok"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 单件失败不影响同账号的其余商品
                detail = str(getattr(exc, "detail", "") or exc) or exc.__class__.__name__
                log.warning(
                    "[shipping_duration] 修改失败 account=%s item=%s: %s", who, iid, detail
                )
                stats["failed"] += 1
                stats["errors"].append({"item_id": iid, "account": who, "error": detail})

            done += 1
            say("apply", f"[{done}/{pending}] {who}：已修改 {row['name'] or iid}")

            # 随机间隔：同一账号连续操作过快才是风险，因此按账号计。最后一件之后不再等待。
            if idx < len(rows) - 1:
                wait = next_delay_sec()
                say("wait", f"[{done}/{pending}] {who}：等待 {wait:.0f} 秒后继续…")
                await asyncio.sleep(wait)

    # return_exceptions=True：某个账号意外整条崩掉时，其余账号继续跑完而不是被连坐取消。
    # 任务被用户取消时 gather 仍会把取消向下传给每个账号协程（停在它们的 sleep 上）。
    results = await asyncio.gather(
        *(_run_account(k, g) for k, g in groups.items()), return_exceptions=True
    )
    for account_key, res in zip(groups.keys(), results):
        if isinstance(res, Exception):
            who = groups[account_key]["name"]
            log.exception("[shipping_duration] 账号 %s 整体失败", who, exc_info=res)
            stats["failed"] += 1
            stats["errors"].append({"account": who, "error": str(res) or res.__class__.__name__})

    return stats
