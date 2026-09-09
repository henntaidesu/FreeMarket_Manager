# -*- coding: utf-8 -*-
"""
待办事项查询：分页 + 多条件过滤；联表 mercari_accounts 取 account_name 用于前端显示。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ....db_manage.database import DatabaseManager


# 「待发货」类判定：标题「発送をしてください」或 kind 属于待发货系列。
# 雅虎侧标题是「発送依頼」、kind 为 YahooShipRequest，语义同样是「已售出待发货」。
_WAIT_SHIPPING_COND = (
    "(IFNULL(t.[title], '') IN ('発送をしてください', '発送依頼')"
    " OR IFNULL(t.[kind], '') IN ('WaitShippingCard', 'WaitShippingPoint', 'WaitShippingCarrier',"
    " 'TransactionWaitShippingFunds', 'YahooShipRequest'))"
)
# 「待回复」类判定：买家来信（IncomingMessage）。
# 雅虎侧是 YahooIncomingMessage（取引メッセージ）——它不来自待办接口而来自通知流，
# 见 use_yahoo/todos/todo_sync.py 的模块说明。
_WAIT_REPLY_COND = (
    "IFNULL(t.[kind], '') IN ('IncomingMessage', 'YahooIncomingMessage')"
)
# 「待评价」类判定：卖家待评价（ReviewedSeller）。
_WAIT_REVIEW_COND = "IFNULL(t.[kind], '') = 'ReviewedSeller'"
# 「待收货」类判定：已发货（Shipped）。绝大多数情况下这是**本账号作为买家**收到的通知——
# 卖家已发货，等待本账号勾选「商品の中身を確認しました」并提交受取評価，title 固定为
# 「受取評価をしてください」（真实同步数据验证过，见 use_mercari/get_to_du_list/
# transaction_detail/buyer_receipt.py 的「确认收货」自动化 + 前端 script.js 的
# isBuyerReceiptRow）。旧注释曾误判这一步「卖家无事可做」——那是没考虑到本账号也会
# 买入商品的情形，实测数据不支持，故已改正。
# 注意与 awaiting_feedback 不是一回事：那仍是待发货 kind 的行（已通知、煤炉数据连携确认中）。
# 雅虎侧是 ``Yahoo:rsura``：同样是买家侧通知，但没有对应可驱动的卖家页面（见 use_yahoo/todos/
# todo_sync.py 模块说明），故只随通知流展示（只驱动动作的 type 才在该文件里给具名 ``Yahoo*``
# kind，纯展示的按 ``Yahoo:{type}`` 原样匹配），不接「确认收货」动作。
_WAIT_RECEIPT_COND = "IFNULL(t.[kind], '') IN ('Shipped', 'Yahoo:rsura')"
# 「退货」类判定：买家发起取消/退货申请（キャンセル申請），以及卖家同意后需要填退货信息
# 并确认退回商品（返品に必要な情報の入力と、返品された商品の確認 → 前端类型显示「退货地址」）。
# 这两步是同一件事的前后段，合成一个筛选；它们从「其他」里摘出来单列。
_CANCELLATION_COND = (
    "IFNULL(t.[kind], '') IN ('CancellationRequested', 'CancellationRequestApprovedSeller')"
)

# 「发货中」判定：已提交扫码照片、后台任务进行中。这类行不再算作「待发货」——
# 用户已经拍完码交给系统了，再列在待发货里会让人以为还没处理。失败后 state 变 'failed'，
# 本条件不再成立，行自动退回「待发货」并带上当时那张照片。
_SHIPPING_IN_PROGRESS_COND = "IFNULL(t.[ship_qr_state], '') = 'shipping'"

# 「虚拟发货」判定：平台侧的发货流程已整套跑完（配送コード已发行、買家已收到発送通知），
# 只差把实物投进邮筒。见 todos_sync/virtual_ship.py。
# 这类行必须移出「待发货」：平台那边已经没有任何待办动作了，留在待发货里会被当成还没发。
# 它们同时也是 ``is_delete=1``（发货成功即按普通发货收尾软删），所以「虚拟发货」筛选
# 与「已扫码」一样**故意不套用 is_delete**，否则一条都看不见。
_VIRTUAL_SHIPPED_COND = "IFNULL(t.[virtual_ship_state], '') = 'shipped'"

# 前端「待发货 / 待回复 / 待评价 / 待收货 / 退货 / 其他」分类筛选（chip）。
# 「其他」= 上述具名分类都不是的行——每加一个分类，这里必须同步排除，否则该分类的行
# 会同时出现在自己的 chip 和「其他」里。
# 传入多个分类时取并集；未传（默认）不做分类过滤，全部显示。
_CATEGORY_CONDS = {
    "wait_shipping": (
        f"{_WAIT_SHIPPING_COND} AND NOT ({_SHIPPING_IN_PROGRESS_COND})"
        f" AND NOT ({_VIRTUAL_SHIPPED_COND})"
    ),
    "wait_reply": _WAIT_REPLY_COND,
    "wait_review": _WAIT_REVIEW_COND,
    "wait_receipt": _WAIT_RECEIPT_COND,
    "cancellation": _CANCELLATION_COND,
    "other": (
        f"NOT {_WAIT_SHIPPING_COND}"
        f" AND NOT ({_WAIT_REPLY_COND})"
        f" AND NOT ({_WAIT_REVIEW_COND})"
        f" AND NOT ({_WAIT_RECEIPT_COND})"
        f" AND NOT ({_CANCELLATION_COND})"
    ),
}

# 「已打包」判定（与前端 isPackedRow 一致）：已发行发货二维码/条形码、非待反馈、
# 非待收货(Shipped)，且属于待发货类（标题「発送をしてください」或 kind 为待发货类）。
# 默认列表隐藏这些行，勾选「已打包」筛选后才一并显示。全部字段用 IFNULL/COALESCE 包裹，
# 保证该条件恒为 0/1（不会因 NULL 让外层 NOT(...) 误排除正常行）。
_PACKED_COND = (
    "IFNULL(t.[qr_image_path], '') != ''"
    " AND COALESCE(t.[awaiting_feedback], 0) = 0"
    " AND IFNULL(t.[kind], '') != 'Shipped'"
    f" AND {_WAIT_SHIPPING_COND}"
)


_LIST_COLS = (
    "id",
    "account_id",
    "platform",
    "uuid",
    "kind",
    "title",
    "message",
    "photo_url",
    "photo_type",
    "status",
    "args_json",
    "intent_json",
    "item_id",
    "item_name",
    "sender_id",
    "mercari_created",
    "mercari_updated",
    "is_delete",
    "synced_at",
    "qr_image_path",
    "awaiting_feedback",
    "shipping_duration",
    "ship_qr_scanned_at",
    "ship_qr_photo_path",
    "ship_qr_state",
    "ship_qr_class_text",
    "ship_qr_text",
    "virtual_ship_state",
    "virtual_shipped_at",
)


_DIGITS_RE = re.compile(r"\d+")


_DAY_MS = 24 * 3600 * 1000


def _ship_base_ms(item: Dict[str, Any]) -> int:
    """发货期限的计时起点(ms)：买家**购入**时刻 ``orders.purchase_time``（unix 秒）。

    不能用 todo 自己的 ``mercari_created``：那是待办在平台侧出现/刷新的时刻，煤炉每次
    刷新都会把它改掉，实测能比真实购入时间晚 1~5 天，用它算出的截止日整体后移，
    页面会显示还有富余、实际早该发货了。仅在订单尚未同步到本地（查不到 purchase_time）
    时才回落到 ``mercari_created`` / ``mercari_updated``。
    """
    try:
        purchase = int(item.get("purchase_time") or 0)
    except (TypeError, ValueError):
        purchase = 0
    if purchase > 0:
        return purchase * 1000
    try:
        return int(item.get("mercari_created") or item.get("mercari_updated") or 0)
    except (TypeError, ValueError):
        return 0


def _ship_deadline_ts(item: Dict[str, Any]) -> Optional[int]:
    """发货截止时刻(ms) = 购入时刻 + N × 24 小时。

    与前端 ``shipDeadlineTs`` 同口径：``shipping_duration`` 形如「4~7日で発送」，
    取其中最大天数（卖家承诺的最迟发货天数）。按整 24 小时计、不做日界对齐——
    对齐到日终会让剩余时间超过承诺天数（2~3日 的单能显示「剩余 3 天 4 小时」）。
    计时起点见 ``_ship_base_ms``。任一项取不到则返回 None（无法推算）。
    """
    nums = _DIGITS_RE.findall(str(item.get("shipping_duration") or ""))
    if not nums:
        return None
    days = max(int(n) for n in nums)
    if not days:
        return None
    base = _ship_base_ms(item)
    if not base:
        return None
    return base + days * _DAY_MS


_WAIT_SHIPPING_KINDS_PY = {
    "WaitShippingCard", "WaitShippingPoint", "WaitShippingCarrier", "TransactionWaitShippingFunds",
    "YahooShipRequest",
}
_WAIT_SHIPPING_TITLES_PY = {"発送をしてください", "発送依頼"}


def _is_wait_shipping_item(item: Dict[str, Any]) -> bool:
    """Python 侧的「待发货」判定，与 _WAIT_SHIPPING_COND 同口径。"""
    return (
        str(item.get("title") or "").strip() in _WAIT_SHIPPING_TITLES_PY
        or str(item.get("kind") or "") in _WAIT_SHIPPING_KINDS_PY
    )


def _ship_deadline_sort_key(item: Dict[str, Any]):
    """排序键：能推算发货期限的排在前面（截止越早越前）；推算不出的统一垫底。

    仅对「待发货」行按截止时间排序：shipping_duration 抓取时按 account_id+item_id
    写入同交易的**所有**待办行，待回复/待评价行也会带上该值——那不是它们的期限，
    不应参与截止排序（否则混合视图里这些行被伪期限顶到前面）。
    """
    if not _is_wait_shipping_item(item):
        return (1, 0)
    dl = _ship_deadline_ts(item)
    return (1, 0) if dl is None else (0, dl)


def _build_todo_where(
    *,
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    packed_only: bool = False,
    scanned_only: bool = False,
    virtual_only: bool = False,
    categories: Optional[str] = None,
    platform: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    """拼 ``todo_items t`` 的 WHERE（含参数）。

    列表与顶部筛选计数共用这一处：计数若另写一套条件，数字和点进去看到的行数迟早对不上。
    """
    where = ["1=1"]
    params: List[Any] = []
    if virtual_only:
        # 与 scanned_only 同一处理：这些行发货成功时已按普通发货收尾软删（is_delete=1），
        # 套用默认的 is_delete / 已打包两个条件就一条都看不见了。
        where.append(f"({_VIRTUAL_SHIPPED_COND})")
    elif scanned_only:
        # 只看「还没办完」的：排队中/执行中(shipping) 与 出错(failed)。
        # 成功的已 finalize，不该再出现在这里。
        where.append("IFNULL(t.[ship_qr_state], '') IN ('shipping', 'failed')")
    else:
        if not include_deleted:
            where.append("COALESCE(t.[is_delete], 0) = 0")
        if packed_only:
            where.append(f"({_PACKED_COND})")
        else:
            where.append(f"NOT ({_PACKED_COND})")
    if categories:
        cats = [c.strip() for c in str(categories).split(",") if c.strip() in _CATEGORY_CONDS]
        if cats:
            where.append("(" + " OR ".join(f"({_CATEGORY_CONDS[c]})" for c in cats) + ")")
    if account_id is not None:
        where.append("t.[account_id] = ?")
        params.append(int(account_id))
    if kind:
        where.append("t.[kind] = ?")
        params.append(str(kind).strip())
    if platform is not None and str(platform).strip():
        # 历史行（平台字段上线前同步的）没有值，按煤炉处理
        plat = str(platform).strip()
        if plat == "mercari":
            where.append("COALESCE(NULLIF(TRIM(t.[platform]), ''), 'mercari') = 'mercari'")
        else:
            where.append("TRIM(t.[platform]) = TRIM(?)")
            params.append(plat)
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(t.[title], '') LIKE ? "
            "OR IFNULL(t.[message], '') LIKE ? "
            "OR IFNULL(t.[item_id], '') LIKE ? "
            "OR IFNULL(t.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw, kw])
    return " AND ".join(where), params


#: 顶部筛选 chip → 该 chip 单独选中时的筛选参数（与前端 selectFilterChip 一一对应）。
#: 「已打包」「已扫码」不是分类而是各自的基础条件，故不能塞进 categories。
_CHIP_FILTERS: Dict[str, Dict[str, Any]] = {
    "wait_shipping": {"categories": "wait_shipping"},
    "wait_reply": {"categories": "wait_reply"},
    "wait_review": {"categories": "wait_review"},
    "wait_receipt": {"categories": "wait_receipt"},
    "cancellation": {"categories": "cancellation"},
    "packed": {"packed_only": True},
    "scanned": {"scanned_only": True},
    "virtual": {"virtual_only": True},
    "other": {"categories": "other"},
}


def count_todos_by_chip(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    platform: Optional[str] = None,
) -> Dict[str, int]:
    """每个顶部筛选 chip 各自的条数。

    只套用**非分类**的筛选（账号 / 平台 / 关键字 / kind / 是否含已完成）——
    当前选中了哪个 chip 不影响其余 chip 的计数，否则选中一个后其他全变 0，就没法据此切换了。
    """
    db = DatabaseManager()
    out: Dict[str, int] = {}
    for chip, extra in _CHIP_FILTERS.items():
        where_sql, params = _build_todo_where(
            account_id=account_id,
            kind=kind,
            keyword=keyword,
            include_deleted=include_deleted,
            platform=platform,
            **extra,
        )
        rows = db.execute_query(
            f"SELECT COUNT(*) FROM [todo_items] t WHERE {where_sql}", tuple(params)
        )
        out[chip] = int(rows[0][0]) if rows and rows[0] else 0
    return out


def count_overdue_wait_shipping(now_ts: int) -> int:
    """已过発送期限、仍停在「待发货」的条数（控制台红色提醒用）。

    期限规则见 ``_ship_deadline_ts``——只有这里知道 ``shipping_duration`` 文本怎么解析成
    截止时刻，所以计数放在同一处，避免控制台自己抄一份日期规则后与待办页对不上。
    推算不出期限（无 ``shipping_duration``）的行不计入：宁可少报，不误报逾期。
    """
    db = DatabaseManager()
    where_sql, params = _build_todo_where(categories="wait_shipping")
    rows = db.execute_query(
        "SELECT t.[shipping_duration], t.[mercari_created], t.[mercari_updated], t.[title], t.[kind], "
        "o.[purchase_time] "
        "FROM [todo_items] t "
        # order_no 唯一，LEFT JOIN 不会让待办行翻倍
        "LEFT JOIN [orders] o ON o.[order_no] = t.[item_id] "
        f"WHERE {where_sql}",
        tuple(params),
    )
    keys = ("shipping_duration", "mercari_created", "mercari_updated", "title", "kind",
            "purchase_time")
    limit_ms = int(now_ts) * 1000
    overdue = 0
    for row in rows or []:
        item = dict(zip(keys, row))
        deadline = _ship_deadline_ts(item)
        if deadline is not None and deadline < limit_ms:
            overdue += 1
    return overdue


def list_todos(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    packed_only: bool = False,
    scanned_only: bool = False,
    virtual_only: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """
    分页列出本地 ``todo_items``，附 ``account_name``。

    - ``include_deleted=False``（默认）只显示未完成（``is_delete=0``）
    - ``packed_only=False``（默认）隐藏「已打包」行（见 ``_PACKED_COND``），
      只显示待发货/待回复等；``packed_only=True`` 则只显示「已打包」行
    - ``scanned_only=True`` 只显示**尚未完成**的扫码行（``ship_qr_state`` 为
      ``shipping`` 排队/执行中 或 ``failed`` 出错）。已成功发出発送通知的不再显示——
      那些单子已经办完了，留在这里只会干扰判断「还有哪些要我管」。
      此筛选下不套用 is_delete 与「已打包」两个默认条件，否则中间态的行一条都看不到。
    - ``virtual_only=True`` 只显示「虚拟发货」行：平台侧已整套发完、只差把实物投进邮筒
      （见 ``todos_sync/virtual_ship.py``）。同样不套用上面两个默认条件——这些行在平台侧
      已经办完，本地是按普通发货收尾软删过的。
    - ``categories`` 逗号分隔的分类筛选（``wait_shipping`` / ``wait_reply`` / ``other``），
      多个取并集；为空（默认）不做分类过滤，全部显示
    - ``keyword`` 匹配 title / message / item_id / item_name
    """
    db = DatabaseManager()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    where_sql, params = _build_todo_where(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        include_deleted=include_deleted,
        packed_only=packed_only,
        scanned_only=scanned_only,
        virtual_only=virtual_only,
        categories=categories,
        platform=platform,
    )

    sel_cols = (
        ", ".join(f"t.[{c}]" for c in _LIST_COLS)
        + ", a.[account_name] AS account_name, o.[purchase_time] AS purchase_time"
    )
    # 按「发货期限剩余时间」升序（越紧急越前）排序。截止时刻要由 shipping_duration
    # 文本（「4~7日で発送」）解析天数再与购入时间相加，SQLite / MySQL 的字符串函数不通用，
    # 故整表取出后在 Python 里排序、分页（待办为在办事项，行数很小）。
    rows = db.execute_query(
        f"""
        SELECT {sel_cols}
        FROM [todo_items] t
        LEFT JOIN [shop_accounts] a ON a.[id] = t.[account_id]
        LEFT JOIN [orders] o ON o.[order_no] = t.[item_id]
        WHERE {where_sql}
        ORDER BY t.[id] ASC
        """,
        tuple(params),
    )
    keys = list(_LIST_COLS) + ["account_name", "purchase_time"]
    items = [dict(zip(keys, row)) for row in rows]
    # 稳定排序：推算不出发货期限的行保持原有 id 升序垫底
    items.sort(key=_ship_deadline_sort_key)
    offset = (page - 1) * page_size
    return {
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "items": items[offset:offset + page_size],
    }


def _combined_component_locations(db: DatabaseManager, combined_items_raw: Any) -> List[Dict[str, Any]]:
    """解析组合商品的 ``combined_items``，返回每个来源商品的名称、数量与仓库位置。

    保持 ``combined_items`` 中的原始顺序，同一来源出现多次时合并数量。
    """
    if not combined_items_raw:
        return []
    try:
        parsed = json.loads(combined_items_raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []

    qty_by_id: Dict[int, int] = {}
    order: List[int] = []
    for it in parsed:
        if not isinstance(it, dict):
            continue
        try:
            cid = int(it.get("inventory_id"))
            qty = int(it.get("quantity"))
        except (TypeError, ValueError):
            continue
        if cid > 0 and qty > 0:
            if cid not in qty_by_id:
                order.append(cid)
            qty_by_id[cid] = qty_by_id.get(cid, 0) + qty
    if not order:
        return []

    placeholders = ",".join("?" for _ in order)
    rows = db.execute_query(
        f"""
        SELECT c.id, c.name,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code
        FROM [inventory] c
        LEFT JOIN [warehouses] w ON w.id = c.warehouse_id
        WHERE c.id IN ({placeholders})
        """,
        tuple(order),
    )
    by_id = {int(r[0]): r for r in rows}

    out: List[Dict[str, Any]] = []
    for cid in order:
        r = by_id.get(cid)
        out.append({
            "id": cid,
            "name": r[1] if r is not None else None,
            "quantity": qty_by_id[cid],
            "warehouse_name": r[2] if r is not None else None,
            "shelf_name": r[3] if r is not None else None,
            "shelf_code": r[4] if r is not None else None,
        })
    return out


def match_inventory_for_item(item_id: str) -> Dict[str, Any]:
    """
    「発送をしてください」处理：按煤炉商品 ID 反查本地库存与关联订单。

    链路：todo.item_id 即订单号（orders.order_no == item_id）
          → order_outbound_lines.inventory_id（库存ID，组合购买可多条）
          → inventory 本地图片。

    返回该订单关联的每条库存的本地图片路径列表（images_json / image_front /
    image / image_back），供前端在处理弹窗中展示全部图片。
    """
    from ...inventory.units.inventory_helpers import _inventory_paths_from_parsed_row

    iid = (item_id or "").strip()
    if not iid:
        return {"item_id": "", "inventory": [], "order_nos": []}

    db = DatabaseManager()
    # item_id 即订单号：取该订单出库明细关联的库存（去重，按明细排序）
    inv_rows = db.execute_query(
        """
        SELECT p.id, p.name, p.images_json,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code,
               ptcm.product_type AS product_type_name,
               COALESCE(p.is_combined, 0) AS is_combined,
               p.combined_items AS combined_items,
               MIN(l.sort_index) AS sort_index, MIN(l.id) AS line_id
        FROM [order_outbound_lines] l
        INNER JOIN [inventory] p ON p.id = l.inventory_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        WHERE l.order_no = ?
          AND l.inventory_id IS NOT NULL
          AND COALESCE(p.is_delete, 0) = 0
        GROUP BY p.id
        ORDER BY sort_index ASC, line_id ASC
        """,
        (iid,),
    )
    keys = [
        "id", "name", "images_json",
        "warehouse_name", "shelf_name", "shelf_code", "product_type_name",
        "is_combined", "combined_items",
        "sort_index", "line_id",
    ]
    inventory: List[Dict[str, Any]] = []
    for row in inv_rows:
        d = dict(zip(keys, row))
        is_combined = bool(int(d.get("is_combined") or 0))
        # 组合（捆绑）库存：展开其来源商品，逐个回显仓库位置（组合本身的位置往往为空）
        components = (
            _combined_component_locations(db, d.get("combined_items"))
            if is_combined
            else []
        )
        inventory.append({
            "id": d["id"],
            "name": d["name"],
            "product_type_name": d["product_type_name"],
            "images": _inventory_paths_from_parsed_row(d),
            "warehouse_name": d["warehouse_name"],
            "shelf_name": d["shelf_name"],
            "shelf_code": d["shelf_code"],
            "is_combined": is_combined,
            "components": components,
        })

    # 订单号即 item_id：仅当库中确有该订单时回显
    order_nos: List[str] = []
    has_order = db.execute_query(
        "SELECT 1 FROM [orders] WHERE order_no = ? LIMIT 1",
        (iid,),
    )
    if has_order:
        order_nos = [iid]

    return {"item_id": iid, "inventory": inventory, "order_nos": order_nos}


def list_kinds() -> List[str]:
    """返回所有出现过的 kind（前端做下拉用，含已删行也算）。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT DISTINCT [kind] FROM [todo_items] "
        "WHERE [kind] IS NOT NULL AND TRIM([kind]) != '' ORDER BY [kind] ASC"
    )
    return [r[0] for r in rows if r and r[0]]
