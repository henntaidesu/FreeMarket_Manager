# -*- coding: utf-8 -*-
"""
お知らせ通知查询：分页 + 多条件过滤；联表 mercari_accounts 取 account_name。
"""

from typing import Any, Dict, List, Optional

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

# 事务局消息分组：kind 含 merpay 的通知（如 merpay-egp-ian-promotion）
# 视同 PrivateMessage，随「事務局メッセージを表示」一起显示/隐藏。
_PRIVATE_MESSAGE_KIND = "PrivateMessage"
_MERPAY_LIKE = "%merpay%"


def _split_kinds(raw: Optional[str]) -> List[str]:
    """逗号分隔的 kind 串 → 去重去空白后的 list（顺序保留）。"""
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    for part in str(raw).split(","):
        s = part.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def list_notifications(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    exclude_kinds: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """
    分页列出本地 ``notifications``，附 ``account_name``。

    - ``only_unread=True`` 仅显示未读（``is_read=0``）
    - ``keyword`` 匹配 message / item_id / item_name
    - ``exclude_kinds`` 逗号分隔串，排除指定 kind（默认不应用，前端控制；
      若与 ``kind`` 过滤的值重叠，``kind`` 优先生效）
    - 排序：顶置 ``BundleRequestCreated`` / ``Comment`` → mercari_created DESC → id DESC
    """
    db = DatabaseManager()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    where = ["1=1"]
    params: List[Any] = []
    if only_unread:
        # is_read 为 NOT NULL DEFAULT 0，等价于 COALESCE(...,0)=0，但裸列比较可命中索引
        where.append("n.[is_read] = 0")
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
    selected_kind = str(kind).strip() if kind else ""
    if selected_kind == _PRIVATE_MESSAGE_KIND:
        # 事务局消息分组：精确 PrivateMessage 或 kind 含 merpay 的都算
        where.append("(n.[kind] = ? OR LOWER(IFNULL(n.[kind], '')) LIKE ?)")
        params.extend([selected_kind, _MERPAY_LIKE])
    elif selected_kind:
        where.append("n.[kind] = ?")
        params.append(selected_kind)
    else:
        ex_list = _split_kinds(exclude_kinds)
        if ex_list:
            placeholders = ",".join(["?"] * len(ex_list))
            where.append(
                f"(n.[kind] IS NULL OR n.[kind] NOT IN ({placeholders}))"
            )
            params.extend(ex_list)
            if _PRIVATE_MESSAGE_KIND in ex_list:
                # 排除事务局消息时，kind 含 merpay 的一并排除
                where.append(
                    "(n.[kind] IS NULL OR LOWER(n.[kind]) NOT LIKE ?)"
                )
                params.append(_MERPAY_LIKE)
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(n.[message], '') LIKE ? "
            "OR IFNULL(n.[item_id], '') LIKE ? "
            "OR IFNULL(n.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw])

    where_sql = " AND ".join(where)
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
        LEFT JOIN [mercari_accounts] a ON a.[id] = n.[account_id]
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

    kind 含 merpay 的归入事务局消息分组，不单独列出；
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


def mark_all_read(account_id: Optional[int] = None) -> Dict[str, Any]:
    """把某账号（或全部）未读通知标记为已读。"""
    db = DatabaseManager()
    if account_id is not None:
        affected = db.execute_update(
            "UPDATE [notifications] SET [is_read] = 1 "
            "WHERE [account_id] = ? AND COALESCE([is_read], 0) = 0",
            (int(account_id),),
        )
    else:
        affected = db.execute_update(
            "UPDATE [notifications] SET [is_read] = 1 WHERE COALESCE([is_read], 0) = 0"
        )
    return {"updated": int(affected or 0)}
