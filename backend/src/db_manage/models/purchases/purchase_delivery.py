# -*- coding: utf-8 -*-
"""购入商品的配送口径：展示状态四态、到货判定，以及配送履历的落库。

**为什么要有「展示状态」这一层。** 煤炉买家侧只给三个值
（``STATE_WAITING_SHIPPING`` / ``STATE_WAITING_BUYER_REVIEW`` / ``STATE_COMPLETED``），
中间那个从「卖家点了発送通知」一直挂到「买家提交受取評価」，把**在途**和**已到手待评价**
两件事压成了一个。本地按到货与否把它拆成两态：

===========================  ==================================================
``STATE_WAITING_SHIPPING``   等待发货
``STATE_WAITING_RECEIPT``    等待收货 —— **本地态**，煤炉没有这个值
``STATE_WAITING_BUYER_REVIEW``  等待评价（已到货）
``STATE_COMPLETED``          交易完成
===========================  ==================================================

拆分**只发生在读取时**（``display_state_sql``），``state`` 列仍原样存煤炉的值。
这样列表同步 / 详情回填照旧覆盖 ``state``，不会和本地态打架——否则每次同步都要
小心别把本地推进的状态写回去，那是一条早晚会漏的规矩。

**到货判定有两个来源，缺一不可**（``delivered_sql``）：

- ``delivered_at``：来自点击运单号时抓的黑猫 / 邮局配送履历，是唯一带**时间**的来源。
- ``delivery_status_name``：煤炉 ``delivery(_japan_post)/status`` 给的状态文案，
  实测已经会是「お届け先にお届け済み」。没有时间，但不用人点一下就能推进状态。

**不要用 ``is_delivered``**：实测一笔状态文案已是「お届け先にお届け済み」的购入，
该字段仍是 0（item_id=m67663910332）。它不是「是否已送达」。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...database import DatabaseManager

#: 煤炉没有这个值：``display_state_sql`` 在「已发货但还没到货」时合成出来。
#: 前端 ``stateConfig`` 与三份 i18n 都按这个字符串取标签。
STATE_WAITING_RECEIPT = "STATE_WAITING_RECEIPT"

_STATE_WAITING_BUYER_REVIEW = "STATE_WAITING_BUYER_REVIEW"

#: 判定「已送达」的状态文案片段。两家承运公司 + 煤炉转述的说法都收在这里，
#: 因为 ``delivery_status_name`` 可能来自煤炉，也可能来自我们自己抓的履历。
#: 「持ち戻り」「保管」「不在」一类**不算**送达，所以只匹配这几个明确的完成词。
DELIVERED_TEXTS: Tuple[str, ...] = (
    "お届け済み",   # 日本郵便：お届け先にお届け済み
    "配達完了",     # ヤマト
    "投函完了",     # ヤマト ネコポス / DM便
    "お渡し",       # 窓口でお渡し（郵便局/営業所 受取）
)


def is_delivered_text(text: Optional[str]) -> bool:
    """状态文案是否表示「已送达」。与 :func:`delivered_sql` 是同一张词表。"""
    s = (text or "").strip()
    return any(k in s for k in DELIVERED_TEXTS) if s else False


def delivered_sql(alias: str = "t") -> str:
    """「已到货」谓词。恒为 0/1，不会是 NULL（外层 ``NOT (...)`` 因此可靠）。"""
    likes = " OR ".join(
        f"COALESCE({alias}.[delivery_status_name], '') LIKE '%{k}%'" for k in DELIVERED_TEXTS
    )
    return f"({alias}.[delivered_at] IS NOT NULL OR {likes})"


def display_state_sql(alias: str = "t") -> str:
    """展示状态（四态）。唯一口径——列表、筛选、下拉选项都从这里取，不各算各的。

    只在「受取評価待ち且未到货」这一种情况下改写，其余原样返回 ``state``：
    未收录的 ``STATE_*`` 值因此照旧原样透出（前端对未知值不猜、直接显示）。
    """
    return (
        "CASE WHEN COALESCE({a}.[state], '') = '{review}'"
        "      AND NOT {delivered}"
        "     THEN '{receipt}' ELSE {a}.[state] END"
    ).format(
        a=alias,
        review=_STATE_WAITING_BUYER_REVIEW,
        delivered=delivered_sql(alias),
        receipt=STATE_WAITING_RECEIPT,
    )


def mark_shipped_from_todos(account_id: int, items: Iterable[Tuple[str, Optional[int]]]) -> int:
    """「待收货」待办出现 ⇒ 把对应购入行推进到 ``STATE_WAITING_BUYER_REVIEW`` 并记发货时间。

    ``items`` 是 ``(item_id, 待办创建时间 epoch 秒)``；返回实际改动的行数。

    这条待办（``kind='Shipped'`` / 受取評価をしてください）与 ``purchase_items`` 的一行
    是同一笔交易的两个视角，它一出现就说明卖家已经点了発送通知。待办同步比购入同步轻得多
    （后者要开浏览器翻整个购入列表），所以这里用**纯 SQL** 抢先把状态推过去，
    `/#/system/purchases` 不用等下一次购入同步才跟上。

    两条性质都是刻意的：

    - **单调**：只从「未知 / 等待发货」推进到「受取評価待ち」，已经是 ``STATE_COMPLETED``
      的行不会被一条残留待办拖回去。
    - **发货时间写一次**：``COALESCE([shipped_at], ?)``。详情回填那边也会写这一列
      （见 ``purchase_detail._apply_shipped_at``），两个来源相差不过几秒，
      让先到的那个说了算，免得同一行的时间来回跳。
    """
    db = DatabaseManager()
    changed = 0
    now = int(time.time())
    for item_id, created_at in items:
        iid = str(item_id or "").strip()
        if not iid:
            continue
        changed += db.execute_update(
            "UPDATE [purchase_items] SET "
            "  [state] = CASE WHEN COALESCE([state], '') IN ('', 'STATE_WAITING_SHIPPING') "
            f"                THEN '{_STATE_WAITING_BUYER_REVIEW}' ELSE [state] END, "
            "  [shipped_at] = COALESCE([shipped_at], ?) "
            "WHERE [account_id] = ? AND [item_id] = ? "
            "  AND (COALESCE([state], '') IN ('', 'STATE_WAITING_SHIPPING') "
            "       OR [shipped_at] IS NULL)",
            (int(created_at or now), int(account_id), iid),
        ) or 0
    return changed


def items_missing_tracking(account_id: int, item_ids: Iterable[str]) -> List[str]:
    """这批商品里还没有运单号的那些——新「待收货」待办出现后要补抓详情的就是它们。"""
    ids = [str(i or "").strip() for i in item_ids]
    ids = list(dict.fromkeys([i for i in ids if i]))
    if not ids:
        return []
    ph = ",".join(["?"] * len(ids))
    rows = DatabaseManager().execute_query(
        f"SELECT [item_id] FROM [purchase_items] "
        f"WHERE [account_id] = ? AND [item_id] IN ({ph}) "
        f"AND COALESCE([tracking_no], '') = ''",
        tuple([int(account_id)] + ids),
    )
    return [str(r[0]) for r in rows if r and r[0]]


def save_delivery_trace(item_id: str, trace: Dict[str, Any]) -> bool:
    """把一次承运公司查询的结果写回该购入行。找不到行返回 ``False``。

    只写配送这几列，不碰同步链路的其它字段——``delivery_status_name`` 两边都写：
    它就是「最新配送状态文案」这一个口径，谁跑得晚谁的更新，两个来源本来也是同一条信息
    （煤炉那个也是从承运公司转述的）。``delivered_at`` 反过来只有这里写得出，
    因为煤炉压根不给送达时间。
    """
    iid = str(item_id or "").strip()
    if not iid:
        return False
    sets = {
        "delivery_carrier": trace.get("carrier"),
        "delivery_trace_json": json.dumps(trace, ensure_ascii=False),
        "delivery_trace_at": int(time.time()),
    }
    # 查不到履历时（单号刚发行、或号码有误）不要用空值把已有的状态/送达时间抹掉。
    if trace.get("status"):
        sets["delivery_status_name"] = trace.get("status")
    if trace.get("delivered_at"):
        sets["delivered_at"] = int(trace["delivered_at"])

    assigns = [f"[{k}] = ?" for k in sets]
    params: List[Any] = list(sets.values())
    # 发货时间兜底：履历第一条（引受 / 荷物受付）就是承运公司收件的时刻。
    # 取引详情那条来源只对「还在候选集里」的行有效——已完成的历史购入再也不会重抓，
    # 点一次运单号是它们唯一能把时间轴左端补上的机会。仍是写一次，不覆盖已有值。
    events = trace.get("events") or []
    first_at = next((e.get("at") for e in events if e.get("at")), None)
    if first_at:
        assigns.append("[shipped_at] = COALESCE([shipped_at], ?)")
        params.append(int(first_at))

    params.append(iid)
    n = DatabaseManager().execute_update(
        f"UPDATE [purchase_items] SET {', '.join(assigns)} WHERE [item_id] = ?",
        tuple(params),
    )
    return bool(n)
