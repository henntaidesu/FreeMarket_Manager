# -*- coding: utf-8 -*-
"""虚拟发货：平台侧照常发完，本地留一笔「实物还没投函」的账。

卖家手上已经有 専用箱 / 発送用シール / 専用封筒，就能在家里把平台侧的发货流程整套跑完
（发行配送コード → 発送通知），实物晚些再投进邮筒。这中间买家已经看到「已发货」、
受取期限也开始走了，唯独包裹还在桌上——**这段空窗必须有人盯着**，而普通发货的收尾
（``mark_scanned_and_cleanup`` / ``finalize_post_shipping``）恰恰是把这单从所有列表里抹掉。
本模块就是那笔账：平台侧一步不改，只在本地把行留在「虚拟发货」筛选里，直到有人点
「已实际发货」。

**为什么只有 ゆうパケットポスト / ゆうパケットポストmini**：也只有这两种能在家里凭手上的
箱子/シール 完成登记（扫码即発行 + 通知）。其余方式要把包裹交到柜台/営業所，発送通知本身
就是柜台扫描的结果，没有「先通知、后寄出」这回事，虚拟发货无从谈起。

平台侧走的就是普通发货那条 ``todos.shipping_qr`` 任务，一步不少——所以本模块里没有任何
自动化代码，只有 ``todo_items.virtual_ship_state`` 的四个状态迁移：

    提交（虚拟）  → 'pending'   意图。任务失败退回待发货时**保住它**，
                               否则「重新扫码」重跑一遍就悄悄变成普通发货了
    任务成功      → 'shipped'   平台已办完 → 进「虚拟发货」筛选，等实物投函
    点「已实际发货」→ 'done'     软删收尾，与普通发货成功后的下场一致
    提交（普通）  → NULL        同一行改走普通发货时要把旧意图清掉
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException

log = logging.getLogger(__name__)

#: 允许虚拟发货的商品尺寸。两个平台用的是同一组日文原文（煤炉 SHIPPING_OPTIONS 里
#: ``auto_finish_no_facility`` 的两项，雅虎 App API 的投函型两项），故只有这一份。
VIRTUAL_SHIP_SIZES = frozenset({"ゆうパケットポスト", "ゆうパケットポストmini"})


def _update(todo_id: int, sql_set: str, params: tuple, extra_where: str = "") -> int:
    from .....db_manage.database import DatabaseManager

    return int(
        DatabaseManager().execute_update(
            f"UPDATE [todo_items] SET {sql_set} WHERE [id] = ? {extra_where}".rstrip(),
            (*params, int(todo_id)),
        )
        or 0
    )


def ensure_size_allowed(size: Optional[str]) -> None:
    """尺寸不在白名单就地 400。

    在**入队前**拦：排进队列之后才发现尺寸不对，配送コード可能已经发行出去了，
    那是不可撤回的。
    """
    s = str(size or "").strip()
    if s not in VIRTUAL_SHIP_SIZES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"「{s or '未选择'}」不能虚拟发货——只有 "
                f"{' / '.join(sorted(VIRTUAL_SHIP_SIZES))} 能在寄出前先完成平台侧发货登记"
            ),
        )


def set_intent(todo_id: int, virtual: bool) -> None:
    """记下本次发货是不是虚拟发货。

    非虚拟时显式写回 NULL 而不是「什么都不做」：同一行上次虚拟发货失败（``'pending'``
    还留着）、这次改走普通发货的话，不清掉的话任务成功后会被 ``mark_shipped`` 认成
    虚拟发货，凭空多出一条永远等不到「已实际发货」的行。
    """
    try:
        _update(
            int(todo_id),
            "[virtual_ship_state] = ?",
            ("pending" if virtual else None,),
        )
    except Exception:
        log.exception("[virtualship] 记录虚拟发货意图失败 todo_id=%s", todo_id)


def mark_shipped(todo_id: int) -> bool:
    """平台侧发货流程跑完 → ``'pending'`` 转 ``'shipped'``，返回是否命中。

    条件更新只认 ``'pending'``：普通发货的行（NULL）不会被误标成虚拟发货，
    重复调用也不会把 ``virtual_shipped_at`` 一次次往后推。
    """
    try:
        n = _update(
            int(todo_id),
            "[virtual_ship_state] = ?, [virtual_shipped_at] = ?",
            ("shipped", int(time.time())),
            extra_where="AND IFNULL([virtual_ship_state], '') = 'pending'",
        )
    except Exception:
        log.exception("[virtualship] 标记虚拟发货完成失败 todo_id=%s", todo_id)
        return False
    if n:
        log.info("[virtualship] 待办 %s 平台侧已发货，等待实物投函", todo_id)
    return bool(n)


def confirm_actual_shipped(todo_id: int) -> Dict[str, Any]:
    """端点：「已实际发货」——包裹真的投出去了，本单收尾。

    平台侧早在虚拟发货那一步就办完了，这里纯本地写：不开浏览器、不进账号串行队列。
    收尾口径与普通发货成功后一致（``is_delete=1`` + ``shipped_finalized=1``），
    行随即从「虚拟发货」筛选消失；``virtual_shipped_at`` **不清**——「虚拟了多久才真发出去」
    只能靠它算。
    """
    from .....db_manage.models.todos.todo_item import TodoItemModel

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    state = (getattr(todo, "virtual_ship_state", "") or "").strip().lower()
    if state == "done":
        # 幂等：重复点（或两个标签页各点一次）不该报错，本来就已经是想要的结果
        return {"success": True, "data": {"changed": False}}
    if state != "shipped":
        raise HTTPException(status_code=400, detail="该待办不处于虚拟发货状态")

    n = _update(
        int(todo_id),
        "[virtual_ship_state] = ?, [is_delete] = 1, [shipped_finalized] = 1",
        ("done",),
        extra_where="AND IFNULL([virtual_ship_state], '') = 'shipped'",
    )
    log.info("[virtualship] 待办 %s 已实际发货，收尾（更新 %s 行）", todo_id, n)
    return {"success": True, "data": {"changed": bool(n)}}
