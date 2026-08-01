# -*- coding: utf-8 -*-
"""
お知らせ通知查询：分页 + 多条件过滤；联表 mercari_accounts 取 account_name。
"""

from typing import Any, Dict, List, Optional, Tuple

from ....db_manage.database import DatabaseManager


_LIST_COLS = (
    "id",
    "account_id",
    "platform",
    "uuid",
    "kind",
    "message",
    "action_url",
    "photo_url",
    "photo_type",
    "args_json",
    "intent_json",
    "item_id",
    "item_name",
    "item_thumbnail",
    "sender_id",
    "price",
    "bid_price",
    "activity",
    "target_url",
    "mercari_created",
    "is_read",
    "synced_at",
)


# 顶置类型：合并购买请求 / 留言 永远排在列表最前
_PINNED_KINDS = ("BundleRequestCreated", "Comment")

# 煤炉公式消息分组：kind 含 merpay 的通知（如 merpay-egp-ian-promotion）视同 PrivateMessage。
_PRIVATE_MESSAGE_KIND = "PrivateMessage"

# 前端顶部筛选 chip（互斥单选）的分类条件，与 /todos 的 _CATEGORY_CONDS 同构。
#
# 同一件事煤炉会派生出一串 kind 变体（Like / LikeV2、AuctionBidCreated /
# AuctionDeadlineReminderXRemainingTime / AuctionCreatedLikerReminder …），只列举当前
# 见过的值会让新变体默默掉进「其他」。故按 kind 前缀归族，只在前缀会误伤时才逐个列举：
#   · ``Like%`` 会连 ``LikedItemReceiveComment`` 一起吃掉 → 点赞只认 Like / LikeV*（雅虎的
#     いいね 是 YahooLike）
#   · 字面量 ``%`` 由方言层转义（见 db_manage/dialects/_translate.py），无需拆成参数
#
# 雅虎侧只有 いいね 有具名 kind（YahooLike），其余一律是 ``Yahoo:{type}`` 原样透传，
# 故按 type 逐个列举。各 type 的语义（取自接口 title）：
#   obems=取引メッセージ  dosdo=価格の相談  lsodi=商品の値下げ
#   loodo=いいね！した商品へのいいね  cmp/cpon/pbsrf/foobc=雅虎运营公告
_COMMENT_COND = "IFNULL(n.[kind], '') LIKE 'Comment%'"
_BUNDLE_COND = "IFNULL(n.[kind], '') LIKE 'Bundle%'"
_DESIRED_PRICE_COND = (
    "(IFNULL(n.[kind], '') LIKE 'DesiredPrice%'"
    " OR IFNULL(n.[kind], '') = 'Yahoo:dosdo')"
)
_AUCTION_COND = (
    "(IFNULL(n.[kind], '') LIKE 'Auction%'"
    " OR IFNULL(n.[kind], '') = 'FlashAuctionStartNotification')"
)
# 待支付：买家已下单未付款。注意不含 PaymentDone* / BillDone / TransactionPaymentDoneFunds，
# 那些是「已支付完成」的事后通知，语义相反，留在「其他」。
_WAIT_PAYMENT_COND = "IFNULL(n.[kind], '') LIKE 'WaitPayment%'"
_LIKE_COND = (
    "(IFNULL(n.[kind], '') IN ('Like', 'YahooLike', 'Yahoo:loodo')"
    " OR IFNULL(n.[kind], '') LIKE 'LikeV%')"
)
_LIKED_ITEM_COND = (
    "IFNULL(n.[kind], '') IN ('LikedItemReceiveComment', 'PriceDropMessageV2')"
)
# 待回复：雅虎交易留言（買主から取引メッセージ）。煤炉的同类待办在 /todos 页，
# 通知流里没有对应 kind，故当前只有雅虎一项。
_WAIT_REPLY_COND = "IFNULL(n.[kind], '') = 'Yahoo:obems'"
# 商品降价：关注（いいね）过的商品降价了。煤炉的 PriceDropMessageV2 仍归「关注商品」不动。
_PRICE_DROP_COND = "IFNULL(n.[kind], '') = 'Yahoo:lsodi'"
# 煤炉公式：PrivateMessage 系（含 PrivateMessageCustomTitle）、所有 kind 含 merpay 的
# 推广/Merpay 通知，以及事務局からの一斉連絡与客服回复。
_BUREAU_COND = (
    f"(IFNULL(n.[kind], '') LIKE '{_PRIVATE_MESSAGE_KIND}%'"
    " OR LOWER(IFNULL(n.[kind], '')) LIKE '%merpay%'"
    " OR IFNULL(n.[kind], '') IN ('AdminBulkContact', 'AgentReplied'))"
)
# 雅虎公式：运营侧公告/活动/优惠券，与商品和交易无关（多数连 itemId 都没有）。
_YAHOO_OFFICIAL_COND = (
    "IFNULL(n.[kind], '') IN "
    "('Yahoo:cmp', 'Yahoo:cpon', 'Yahoo:pbsrf', 'Yahoo:foobc')"
)

#: chip → WHERE 条件。「其他」= 以上各类都不是（如支付完成、未归类的 Yahoo:* 类型）。
_NAMED_CATEGORY_CONDS = {
    "comment": _COMMENT_COND,
    "bundle": _BUNDLE_COND,
    "desired_price": _DESIRED_PRICE_COND,
    "auction": _AUCTION_COND,
    "wait_payment": _WAIT_PAYMENT_COND,
    "like": _LIKE_COND,
    "liked_item": _LIKED_ITEM_COND,
    "price_drop": _PRICE_DROP_COND,
    "wait_reply": _WAIT_REPLY_COND,
    "bureau": _BUREAU_COND,
    "yahoo_official": _YAHOO_OFFICIAL_COND,
}

_CATEGORY_CONDS = {
    **_NAMED_CATEGORY_CONDS,
    # 由具名分类取反生成：新增一个 chip 只需往上面加一行，「其他」自动收窄，
    # 不会出现漏改导致某类同时出现在两个 chip 里。
    "other": " AND ".join(f"NOT ({c})" for c in _NAMED_CATEGORY_CONDS.values()),
}


def _build_notification_where(
    *,
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    categories: Optional[str] = None,
    platform: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    """拼 ``notifications n`` 的 WHERE（含参数）。

    列表与顶部筛选计数共用这一处：计数若另写一套条件，数字和点进去看到的行数迟早对不上。
    """
    where = ["1=1"]
    params: List[Any] = []
    if only_unread:
        # is_read 为 NOT NULL DEFAULT 0，等价于 COALESCE(...,0)=0，但裸列比较可命中索引
        where.append("n.[is_read] = 0")
    if categories:
        cats = [c.strip() for c in str(categories).split(",") if c.strip() in _CATEGORY_CONDS]
        if cats:
            where.append("(" + " OR ".join(f"({_CATEGORY_CONDS[c]})" for c in cats) + ")")
    if account_id is not None:
        where.append("n.[account_id] = ?")
        params.append(int(account_id))
    if platform is not None and str(platform).strip():
        # 历史行（平台字段上线前同步的）没有值，按煤炉处理
        plat = str(platform).strip()
        if plat == "mercari":
            where.append("COALESCE(NULLIF(TRIM(n.[platform]), ''), 'mercari') = 'mercari'")
        else:
            where.append("TRIM(n.[platform]) = TRIM(?)")
            params.append(plat)
    if kind and str(kind).strip():
        where.append("n.[kind] = ?")
        params.append(str(kind).strip())
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(n.[message], '') LIKE ? "
            "OR IFNULL(n.[item_id], '') LIKE ? "
            "OR IFNULL(n.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw])
    return " AND ".join(where), params


def count_notifications_by_chip(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    platform: Optional[str] = None,
) -> Dict[str, int]:
    """每个顶部筛选 chip 各自的条数。

    只套用**非分类**的筛选（账号 / 平台 / 关键字 / kind / 仅未读）——当前选中了哪个
    chip 不影响其余 chip 的计数，否则选中一个后其他全变 0，就没法据此切换了。
    """
    db = DatabaseManager()
    out: Dict[str, int] = {}
    for chip in _CATEGORY_CONDS:
        where_sql, params = _build_notification_where(
            account_id=account_id,
            kind=kind,
            keyword=keyword,
            only_unread=only_unread,
            categories=chip,
            platform=platform,
        )
        rows = db.execute_query(
            f"SELECT COUNT(*) FROM [notifications] n WHERE {where_sql}", tuple(params)
        )
        out[chip] = int(rows[0][0]) if rows and rows[0] else 0
    return out


def list_notifications(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """
    分页列出本地 ``notifications``，附 ``account_name``。

    - ``only_unread=True`` 仅显示未读（``is_read=0``）
    - ``keyword`` 匹配 message / item_id / item_name
    - ``categories`` 逗号分隔的分类筛选（见 ``_CATEGORY_CONDS``），多个取并集；
      为空（默认）不做分类过滤，全部显示
    - 排序：顶置 ``BundleRequestCreated`` / ``Comment`` → mercari_created DESC → id DESC
    """
    db = DatabaseManager()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    where_sql, params = _build_notification_where(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        only_unread=only_unread,
        categories=categories,
        platform=platform,
    )
    total = db.execute_query(
        f"SELECT COUNT(*) FROM [notifications] n WHERE {where_sql}",
        tuple(params),
    )[0][0]

    pin_placeholders = ",".join(["?"] * len(_PINNED_KINDS))
    pin_case = f"CASE WHEN n.[kind] IN ({pin_placeholders}) THEN 0 ELSE 1 END"

    sel_cols = (
        ", ".join(f"n.[{c}]" for c in _LIST_COLS)
        + ", a.[account_name] AS account_name"
    )
    offset = (page - 1) * page_size
    rows = db.execute_query(
        f"""
        SELECT {sel_cols}
        FROM [notifications] n
        LEFT JOIN [shop_accounts] a ON a.[id] = n.[account_id]
        WHERE {where_sql}
        ORDER BY {pin_case} ASC,
                 COALESCE(n.[mercari_created], 0) DESC,
                 n.[id] DESC
        LIMIT ? OFFSET ?
        """,
        # 占位符顺序按 SQL 文本左→右匹配:
        # WHERE 里的 ? 先(params),ORDER BY {pin_case} 里的 ? 次(_PINNED_KINDS),最后 LIMIT/OFFSET。
        tuple(params + list(_PINNED_KINDS) + [page_size, offset]),
    )
    keys = list(_LIST_COLS) + ["account_name"]
    items = [dict(zip(keys, row)) for row in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def list_kinds() -> List[str]:
    """返回所有出现过的 kind（前端下拉用）。

    kind 含 merpay 的归入煤炉公式消息分组，不单独列出；
    若存在此类数据则保证下拉中有 ``PrivateMessage`` 一项。
    """
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT DISTINCT [kind] FROM [notifications] "
        "WHERE [kind] IS NOT NULL AND TRIM([kind]) != '' ORDER BY [kind] ASC"
    )
    all_kinds = [r[0] for r in rows if r and r[0]]
    kinds = [k for k in all_kinds if "merpay" not in str(k).lower()]
    has_merpay = len(kinds) != len(all_kinds)
    if has_merpay and _PRIVATE_MESSAGE_KIND not in kinds:
        kinds.append(_PRIVATE_MESSAGE_KIND)
    return kinds


def mark_read(ids: List[int], is_read: bool = True) -> Dict[str, Any]:
    """批量标记已读/未读，返回受影响行数。"""
    ids_int = [int(i) for i in (ids or []) if isinstance(i, (int, str)) and str(i).strip().lstrip("-").isdigit()]
    if not ids_int:
        return {"updated": 0}
    db = DatabaseManager()
    placeholders = ",".join(["?"] * len(ids_int))
    affected = db.execute_update(
        f"UPDATE [notifications] SET [is_read] = ? WHERE [id] IN ({placeholders})",
        tuple([1 if is_read else 0] + ids_int),
    )
    return {"updated": int(affected or 0)}


def mark_all_read(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    categories: Optional[str] = None,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """把**当前筛选命中**的所有未读通知标记为已读，返回受影响行数。

    与列表共用 ``_build_notification_where``：按钮的作用范围必须等于用户眼前那个筛选，
    翻到第几页、每页多少条只是显示细节，不该改变「一键已读」读掉哪些行。
    ``only_unread`` 在这里恒为 True——已读的行不必再写一次，行数也才等于真正被改的条数。

    不传任何筛选（全 None）时即「全部未读」，与改动前的行为一致。
    """
    where_sql, params = _build_notification_where(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        only_unread=True,
        categories=categories,
        platform=platform,
    )
    # 别名 n 供 WHERE 引用；SET 左侧必须是未限定列名（SQLite 不接受 n.[is_read]）
    db = DatabaseManager()
    affected = db.execute_update(
        f"UPDATE [notifications] AS n SET [is_read] = 1 WHERE {where_sql}",
        tuple(params),
    )
    return {"updated": int(affected or 0)}
