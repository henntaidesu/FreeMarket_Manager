# -*- coding: utf-8 -*-
"""库存计数器：在售(on_sale_quantity) 的事件驱动维护，以及可上架(listable_quantity) 的派生重算。

数量模型（出品 1 件 = 1）：
  · 库存 quantity   = 物理总持有数，仅由入库/出库（扫码、组合）变动；上架/下架/售出都不改它。
  · 在售 on_sale_quantity = 当前已挂在售（含暂停 stop）的件数，事件驱动维护：
        - 上架成功 / 详情绑定后仍在售：在售 +1
        - 暂停出售(on_sale→stop) / 恢复出售(stop→on_sale)：不变
        - 下架/删除 或 售出（从在售消失）：在售 -1
  · 待出 pending_outbound_qty = 非终态订单且未出库的明细合计，由订单管线派生维护
        （见 description_mgmt_ids.refresh_inventory_pending_outbound_qty）。
  · 组合预留 = Σ(组合商品库存 × 每套该商品数量)，被组合商品拉走但不扣库存，仅在可上架中扣减。
  · 可上架 listable_quantity = max(0, 库存 - 在售 - 待出 - 组合预留)，落库的派生值，出品可否以此判断。

「在售」的增减统一由本模块在「在售列表同步」(sync.apply_on_sale_list_sync) 与「详情绑定」
(detail_sync) 两处通过 ``reconcile_listing_counts`` 应用，并以 ``on_sale_items.counted_on_sale``
标记保证幂等（同步重复运行不会重复增减）。下架与售出都只是「从在售消失」→ 在售 -1，库存不变，
因此无需区分二者（待出由订单派生）。

``listable_quantity`` 在「在售/待出」变动处即时重算；库存列表读取时也会自愈
（见 inventory_helpers._query_inventory_with_joins）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..db_manage.database import DatabaseManager
from .on_sale.on_sale_items_sync.inventory_qty import (
    _mercari_id_lookup_keys,
    _split_mercari_item_ids,
)

log = logging.getLogger(__name__)

# 视为「仍挂在售（占用在售名额）」的煤炉状态：含暂停 stop（暂停不释放在售名额）
LISTED_STATUSES: Tuple[str, ...] = ("on_sale", "stop")


def _norm_keys(item_id: str) -> List[str]:
    """item_id 的查询键（兼容 m 前缀与纯数字）。"""
    return _mercari_id_lookup_keys(item_id)


def _combined_reserved_sql_expr(inv_alias: str = "[inventory]",
                                materialize_source: bool = False) -> str:
    """该商品被「组合商品」拉走（预留）的件数：Σ(组合商品库存 × 每套该商品数量)。

    仅统计未软删的组合商品。组合商品不再扣减来源库存，改由本预留量在「可上架」中扣减、
    并在库存页「组合」列展示。``inv_alias`` 为外层 inventory 行的引用（UPDATE 时为
    ``[inventory]``，库存列表查询里别名为 ``p``）。

    ``materialize_source`` 用于本表达式作为 ``UPDATE [inventory]`` 子查询时：MySQL 不允许
    在 UPDATE 目标表的子查询 FROM 中再引用该表（错误 1093），需把内层 inventory 包成派生表。
    """
    d = DatabaseManager().dialect
    each = d.json_array_each("cmb.[combined_items]", "je")
    qty_expr = d.json_extract_int("je.value", "quantity")
    inv_id_expr = d.json_extract_int("je.value", "inventory_id")
    src = d.table_source("[inventory]", "cmb", materialize_source)
    return (
        "(SELECT COALESCE(SUM("
        "COALESCE(cmb.[quantity], 0) * "
        f"{qty_expr}), 0) "
        f"FROM {src}, {each} "
        "WHERE COALESCE(cmb.[is_combined], 0) = 1 "
        "AND COALESCE(cmb.[is_delete], 0) = 0 "
        f"AND {inv_id_expr} = {inv_alias}.[id])"
    )


def _combined_reserved_agg_subquery() -> str:
    """把「每个来源子商品被组合预留的件数」预聚合为派生表，供库存列表一次性 LEFT JOIN。

    等价于对每行都跑一遍 ``_combined_reserved_sql_expr`` 的相关子查询，但只对组合商品做
    「一次」JSON 展开 + 分组，避免库存列表 O(N) 次全表 JSON 展开。输出列：
    ``src_id``（来源子商品 inventory.id）、``reserved``（Σ 组合库存 × 每套用量）。
    连接方式：``LEFT JOIN <本子查询> cr ON cr.src_id = p.id``，取 ``COALESCE(cr.reserved, 0)``。
    """
    d = DatabaseManager().dialect
    each = d.json_array_each("cmb.[combined_items]", "je")
    qty_expr = d.json_extract_int("je.value", "quantity")
    inv_id_expr = d.json_extract_int("je.value", "inventory_id")
    return (
        f"(SELECT {inv_id_expr} AS src_id, "
        f"COALESCE(SUM(COALESCE(cmb.[quantity], 0) * {qty_expr}), 0) AS reserved "
        f"FROM [inventory] cmb, {each} "
        "WHERE COALESCE(cmb.[is_combined], 0) = 1 "
        "AND COALESCE(cmb.[is_delete], 0) = 0 "
        f"GROUP BY {inv_id_expr})"
    )


def _listable_sql_expr() -> str:
    """可上架 = max(0, 库存 - 在售 - 待出 - 组合预留 - 出品预扣减) 的 SQL 表达式（基于同表列）。

    ``pending_listing_qty``（出品预扣减）：已提交到任务队列但尚未被在售同步计入 on_sale 的件数，
    见 task_queue/reservations.py。点「出品」后可上架立刻减少，防止重复提交超量出品。
    """
    inner = (
        "COALESCE([quantity], 0) "
        "- COALESCE([on_sale_quantity], 0) "
        "- COALESCE([pending_outbound_qty], 0) "
        "- COALESCE([pending_listing_qty], 0) "
        f"- {_combined_reserved_sql_expr(materialize_source=True)}"
    )
    return DatabaseManager().dialect.greatest("0", inner)


def recompute_listable_quantity(inv_ids: Optional[Iterable[int]] = None) -> int:
    """重算并落库 inventory.listable_quantity = max(0, 库存 - 在售 - 待出 - 组合预留)。

    inv_ids 为空时重算全表；返回受影响行数。
    """
    db = DatabaseManager()
    expr = _listable_sql_expr()
    if inv_ids is None:
        return int(db.execute_update(
            f"UPDATE [inventory] SET [listable_quantity] = {expr}"
        ) or 0)
    ids = sorted({int(i) for i in inv_ids if i is not None})
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    return int(db.execute_update(
        f"UPDATE [inventory] SET [listable_quantity] = {expr} WHERE [id] IN ({ph})",
        tuple(ids),
    ) or 0)


def _combined_children(combo_inv_id: int) -> List[Tuple[int, int]]:
    """返回组合商品的 (来源子商品 id, 每套用量) 列表；非组合/已软删/无效则返回空。"""
    if combo_inv_id is None:
        return []
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [combined_items] FROM [inventory] "
        "WHERE [id] = ? AND COALESCE([is_combined], 0) = 1 AND COALESCE([is_delete], 0) = 0 LIMIT 1",
        (int(combo_inv_id),),
    )
    if not rows:
        return []
    try:
        parsed = json.loads(rows[0][0]) if rows[0][0] else []
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: List[Tuple[int, int]] = []
    for it in parsed:
        if not isinstance(it, dict):
            continue
        try:
            child_id = int(it.get("inventory_id"))
            per_set = int(it.get("quantity"))
        except (TypeError, ValueError):
            continue
        if child_id > 0 and per_set > 0:
            out.append((child_id, per_set))
    return out


def is_combined_source(inv_id: int) -> bool:
    """该库存是否被任一未软删的组合商品引用为来源子商品（用于禁止拆分/归属转化等会改变其数量的操作）。"""
    if inv_id is None:
        return False
    db = DatabaseManager()
    each = db.dialect.json_array_each("cmb.[combined_items]", "je")
    inv_id_expr = db.dialect.json_extract_int("je.value", "inventory_id")
    rows = db.execute_query(
        f"SELECT 1 FROM [inventory] cmb, {each} "
        "WHERE COALESCE(cmb.[is_combined], 0) = 1 AND COALESCE(cmb.[is_delete], 0) = 0 "
        f"AND {inv_id_expr} = ? LIMIT 1",
        (int(inv_id),),
    )
    return bool(rows)


def cascade_combined_child_deduction(
    combo_inv_id: int,
    combo_qty_reduced: int,
    *,
    reason: str,
) -> None:
    """组合商品因售出/出库导致库存(套数)减少时，按每套用量级联扣减来源子商品的物理库存。

    组合采用「不扣库存、仅预留」模型：来源子商品的 quantity 含被组合「拉走」的件数，其
    可上架由 Σ(组合库存 × 每套用量) 预留扣减（见 ``_combined_reserved_sql_expr``）。组合售出
    N 套时，物理上每个子商品有 (N × 每套用量) 件随组合一并发出，故须同步从子商品 quantity
    扣减（不低于 0），并按子商品所在货架写一条出库流水。

    调用时机：必须在「组合自身 quantity 已扣减完成」之后调用——此时组合预留已随之下降，
    本函数再扣减子商品物理库存，二者在「可上架 = 库存 - 预留」中恰好抵消，可上架保持正确。

    仅当 ``combo_inv_id`` 确为未软删的组合商品且 ``combo_qty_reduced > 0`` 时生效；对普通
    商品为无副作用的空操作（调用方无需自行判断是否组合）。
    """
    try:
        reduced = int(combo_qty_reduced or 0)
    except (TypeError, ValueError):
        return
    if reduced <= 0:
        return
    db = DatabaseManager()
    touched: List[int] = []
    for child_id, per_set in _combined_children(combo_inv_id):
        need = per_set * reduced
        # 乐观锁 CAS 重试：防组合子商品并发扣减丢更新/负库存（保留钳 0 语义）
        real_deduct = 0
        warehouse_id = None
        for _cas in range(6):
            crows = db.execute_query(
                "SELECT [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (child_id,),
            )
            if not crows:
                break
            current = int(crows[0][0] or 0)
            warehouse_id = crows[0][1]
            new_qty = max(0, current - need)
            deduct = current - new_qty
            if deduct <= 0:
                break
            affected = db.execute_update(
                "UPDATE [inventory] SET [quantity] = ? WHERE [id] = ? AND COALESCE([quantity], 0) = ?",
                (new_qty, child_id, current),
            )
            if affected:
                real_deduct = deduct
                break
        else:
            # 6 次 CAS 全部失联（持续并发写同一子商品）：静默跳过会让子商品物理库存
            # 虚高而可能超卖，必须留痕供人工核对
            log.warning(
                "[combined] 子商品 %s 级联扣减 CAS 重试耗尽（需扣 %s），本次未扣减，"
                "库存可能虚高，请人工核对（组合 %s，原因：%s）",
                child_id, need, combo_inv_id, reason,
            )
        if real_deduct <= 0:
            continue
        if warehouse_id is not None:
            try:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("out", child_id, warehouse_id, real_deduct, reason, int(time.time())),
                )
            except Exception:
                log.exception(
                    "[inventory_counters] 组合级联扣减写出库流水失败 combo=%s child=%s",
                    combo_inv_id, child_id,
                )
        touched.append(child_id)

    if touched:
        recompute_listable_quantity(touched)
        log.info(
            "[inventory_counters] 组合 %s 售出 %s 套，级联扣减来源子商品 %s",
            combo_inv_id, reduced, touched,
        )


def cascade_combined_child_restock(
    combo_inv_id: int,
    combo_qty_added: int,
    *,
    reason: str,
) -> None:
    """``cascade_combined_child_deduction`` 的逆操作：组合因订单作废（删除/取消）回吐库存(套数)时，
    按每套用量反向回吐来源子商品物理库存（+= N × 每套用量），并按子商品货架写一条入库流水。

    须在「组合自身 quantity 已回吐完成」之后调用，使可上架口径与扣减时对称保持一致。
    """
    try:
        added = int(combo_qty_added or 0)
    except (TypeError, ValueError):
        return
    if added <= 0:
        return
    db = DatabaseManager()
    touched: List[int] = []
    for child_id, per_set in _combined_children(combo_inv_id):
        add = per_set * added
        crows = db.execute_query(
            "SELECT [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
            (child_id,),
        )
        if not crows:
            continue
        warehouse_id = crows[0][0]
        db.execute_update(
            "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
            (add, child_id),
        )
        if warehouse_id is not None:
            try:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("in", child_id, warehouse_id, add, reason, int(time.time())),
                )
            except Exception:
                log.exception(
                    "[inventory_counters] 组合级联回吐写入库流水失败 combo=%s child=%s",
                    combo_inv_id, child_id,
                )
        touched.append(child_id)

    if touched:
        recompute_listable_quantity(touched)
        log.info(
            "[inventory_counters] 组合 %s 作废回吐 %s 套，级联回吐来源子商品 %s",
            combo_inv_id, added, touched,
        )


def _adjust_on_sale(
    db: DatabaseManager, inv_id: int, on_sale_delta: int, *, consume: bool = True
) -> bool:
    """对单个库存行的在售数量应用增量（clamp >= 0），并同步重算可上架。返回是否实际更新。

    ``consume=False``：正增量不核销「出品预扣减/未同步补挂」台账。用于「换绑挪计数」——
    在售名额只是从旧库存挪到新库存，并非新挂牌，不应吃掉新库存排队中的出品预留。
    """
    if on_sale_delta == 0:
        return False
    on_sale_expr = db.dialect.greatest("0", "COALESCE([on_sale_quantity], 0) + ?")
    changed = db.execute_update(
        f"""
        UPDATE [inventory]
        SET [on_sale_quantity] = {on_sale_expr}
        WHERE [id] = ?
        """,
        (int(on_sale_delta), int(inv_id)),
    )
    recompute_listable_quantity([int(inv_id)])
    if on_sale_delta > 0 and consume:
        # 新挂牌已计入在售 → 核销 auto_relist「未同步补挂」台账（防无限循环出品）
        try:
            from .auto_relist import consume_unsynced_relists

            consume_unsynced_relists(int(inv_id), int(on_sale_delta))
        except Exception:
            pass
        # 同理核销任务队列的「出品预扣减」：新挂牌已入账，占用可以放行了
        try:
            from ..task_queue import reservations

            reservations.consume(int(inv_id), int(on_sale_delta))
        except Exception:
            pass
    return bool(changed)


def _set_counted_flag(
    db: DatabaseManager,
    item_id: str,
    flag: int,
    inv_ids: Optional[Iterable[int]] = None,
) -> None:
    """按 on_sale_items.item_id 设置 counted_on_sale 标记，并同步记录实际被计入的库存 id。

    flag=1 时把 ``inv_ids`` 写入 counted_inventory_ids（JSON 数组），供换绑/解绑时把 -1
    精确退回「当初 +1 的那些库存」；flag=0 时清空记录。
    """
    iid = str(item_id or "").strip()
    if not iid:
        return
    ids_json: Optional[str] = None
    if int(flag) and inv_ids:
        ids = sorted({int(i) for i in inv_ids})
        if ids:
            ids_json = json.dumps(ids)
    db.execute_update(
        "UPDATE [on_sale_items] SET [counted_on_sale] = ?, [counted_inventory_ids] = ? "
        "WHERE TRIM([item_id]) = TRIM(?)",
        (int(flag), ids_json, iid),
    )


def _parse_counted_inventory_ids(raw: object) -> Optional[Set[int]]:
    """解析 on_sale_items.counted_inventory_ids（JSON 数组）→ 库存 id 集合。

    NULL/空串/不可解析/空数组 均视为 None（旧数据无记录，调用方回退按当前绑定处理）。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    out: Set[int] = set()
    for v in parsed:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i > 0:
            out.add(i)
    return out or None


def _bound_inventory_map(db: DatabaseManager) -> Dict[str, Set[int]]:
    """构建「煤炉商品 ID（含规范化键）→ 绑定的库存 id 集合」。

    inventory.mercari_item_id 可能一行多 ID（、分隔），逐个拆分匹配。
    """
    rows = db.execute_query(
        """
        SELECT [id], [mercari_item_id]
        FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0
          AND TRIM(IFNULL([mercari_item_id], '')) != ''
        """
    )
    out: Dict[str, Set[int]] = {}
    for inv_id_raw, mids_raw in rows or []:
        try:
            inv_id = int(inv_id_raw)
        except (TypeError, ValueError):
            continue
        for mid in _split_mercari_item_ids(mids_raw):
            for key in _norm_keys(mid):
                out.setdefault(key, set()).add(inv_id)
    return out


def _load_listing_states(
    db: DatabaseManager, item_ids: Iterable[str]
) -> Dict[str, Dict[str, object]]:
    """按 item_id 读取 on_sale_items 的 status / is_delete / counted_on_sale /
    counted_inventory_ids（未软删的最新一条）。

    返回 {规范化键: {item_id, status, is_delete, counted, counted_inv}}。同一商品多键都会指向同一状态。
    """
    cleaned: List[str] = []
    seen: Set[str] = set()
    for raw in item_ids:
        for key in _norm_keys(raw):
            if key not in seen:
                seen.add(key)
                cleaned.append(key)
    if not cleaned:
        return {}
    ph = ",".join("?" * len(cleaned))
    rows = db.execute_query(
        f"""
        SELECT [item_id], [status], COALESCE([is_delete], 0), COALESCE([counted_on_sale], 0),
               [counted_inventory_ids]
        FROM [on_sale_items]
        WHERE TRIM([item_id]) IN ({ph})
        ORDER BY [id] DESC
        """,
        tuple(cleaned),
    )
    out: Dict[str, Dict[str, object]] = {}
    for item_id, status, is_delete, counted, counted_inv_raw in rows or []:
        state = {
            "item_id": str(item_id or "").strip(),
            "status": (str(status or "").strip() or None),
            "is_delete": int(is_delete or 0),
            "counted": int(counted or 0),
            "counted_inv": _parse_counted_inventory_ids(counted_inv_raw),
        }
        for key in _norm_keys(str(item_id or "")):
            out.setdefault(key, state)
    return out


def reconcile_listing_counts(item_ids: Iterable[str]) -> Dict[str, int]:
    """对给定煤炉商品 ID 集合，依据 on_sale_items 当前状态与绑定库存，对齐「在售」计数（库存不变）。

    幂等：凭 on_sale_items.counted_on_sale 标记，仅在「应计入」状态翻转时增减在售；
    counted_inventory_ids 记录「实际被 +1 的库存」，保证 -1 精确退回原库存。
      · counted 0 → 应计入(未软删 + status∈on_sale/stop + 已绑定存在库存)：上架 → 每个绑定库存
        在售 +1，标记=1 并记录被计入的库存 id
      · counted 1 → 不应计入(软删/下架/售出从在售消失，或解绑)：按记录退回 在售 -1（旧数据无
        记录时回退按当前绑定），标记=0 并清空记录
      · counted 1 且仍应计入，但记录与当前绑定不一致（说明被编辑改指向其他库存，换绑）：
        把在售名额从旧库存挪到新库存（旧 -1 / 新 +1，+1 不核销出品预扣减），更新记录
      · 其余（暂停/恢复、未绑定、状态不变）：不动

    库存 quantity 不在此变动（仅入库/出库改变）；可上架由 _adjust_on_sale 同步重算。
    返回统计 {listed_inc, listed_dec}。
    """
    db = DatabaseManager()
    states = _load_listing_states(db, item_ids)
    if not states:
        return {"listed_inc": 0, "listed_dec": 0}

    bound_map = _bound_inventory_map(db)

    # 去重：按 item_id 唯一处理（多键指向同一 state）
    unique_states: Dict[str, Dict[str, object]] = {}
    for state in states.values():
        iid = str(state.get("item_id") or "").strip()
        if iid:
            unique_states[iid] = state

    stats = {"listed_inc": 0, "listed_dec": 0}

    for iid, state in unique_states.items():
        status = state.get("status")
        is_delete = int(state.get("is_delete") or 0)
        counted = int(state.get("counted") or 0)

        bound: Set[int] = set()
        for key in _norm_keys(iid):
            bound |= bound_map.get(key, set())

        should_count = (
            is_delete == 0
            and (status in LISTED_STATUSES)
            and bool(bound)
        )

        recorded = state.get("counted_inv")  # 实际被 +1 的库存记录；None=旧数据无记录

        if should_count and counted == 0:
            # 上架：每个绑定库存 在售 +1（库存不变），并记录实际被计入的库存
            for inv_id in bound:
                _adjust_on_sale(db, inv_id, +1)
            _set_counted_flag(db, iid, 1, bound)
            stats["listed_inc"] += len(bound)
        elif not should_count and counted == 1:
            # 退出在售（下架/售出/解绑）：按记录把 -1 退回「当初 +1 的库存」（库存不变；
            # 待出由订单派生）。解绑到空时 bound 为空，凭记录仍能正确退回；旧数据无记录
            # 时回退按当前绑定处理（历史行为）。
            targets = recorded if recorded is not None else bound
            for inv_id in targets:
                _adjust_on_sale(db, inv_id, -1)
                stats["listed_dec"] += 1
            _set_counted_flag(db, iid, 0)
        elif should_count and counted == 1:
            if recorded is None:
                # 旧数据补录：不增减在售，仅把当前绑定回填为「已计入」记录
                _set_counted_flag(db, iid, 1, bound)
            elif recorded != bound:
                # 换绑（说明被编辑改指向其他库存）：把在售名额从旧库存挪到新库存。
                # 非新挂牌，+1 不核销出品预扣减/未同步补挂台账（consume=False）。
                for inv_id in recorded - bound:
                    _adjust_on_sale(db, inv_id, -1)
                    stats["listed_dec"] += 1
                for inv_id in bound - recorded:
                    _adjust_on_sale(db, inv_id, +1, consume=False)
                    stats["listed_inc"] += 1
                _set_counted_flag(db, iid, 1, bound)
        # 其余情形：暂停/恢复（counted 保持 1）、未绑定（counted 保持 0）等，不动

    if stats["listed_inc"] or stats["listed_dec"]:
        log.info("[inventory_counters] reconcile %s -> %s", list(unique_states.keys()), stats)
    return stats
