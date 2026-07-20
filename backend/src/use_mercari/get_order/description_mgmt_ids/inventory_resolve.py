# -*- coding: utf-8 -*-
"""按条码/暗号/まとめ商品标题反查库存 ID"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple
from ....db_manage.database import DatabaseManager
from ...mgmt_id_cipher import parse_trailing_cipher_mgmt_tokens
from ._common import _BUNDLE_INTRO_RE, _BUNDLE_LINE_RE, _BUNDLE_SECTION_HEADER, _BUNDLE_TRAILING_STATE_RE, _normalize_match_text, _split_mercari_item_ids


def _inventory_id_exists(inv_id: int) -> bool:
    db = DatabaseManager()
    r = db.execute_query(
        "SELECT 1 FROM [inventory] WHERE [id] = ? LIMIT 1",
        (int(inv_id),),
    )
    return bool(r)

def _inventory_id_by_barcode(barcode: str) -> Optional[int]:
    """按条形码精确匹配（与库存表 TRIM 后比较）。"""
    bc = (barcode or "").strip()
    if not bc:
        return None
    db = DatabaseManager()
    r = db.execute_query(
        "SELECT [id] FROM [inventory] WHERE TRIM(IFNULL([barcode], '')) = ? LIMIT 1",
        (bc,),
    )
    if not r or r[0][0] is None:
        return None
    try:
        return int(r[0][0])
    except (TypeError, ValueError):
        return None

def _is_bundle_order_description(text: Optional[str]) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    return _BUNDLE_SECTION_HEADER in s and bool(_BUNDLE_INTRO_RE.search(s))

def _extract_bundle_product_titles(text: Optional[str]) -> List[str]:
    s = str(text or "")
    if not s:
        return []
    lines = s.splitlines()
    titles: List[str] = []
    in_section = False
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not in_section:
            if _BUNDLE_SECTION_HEADER in line:
                in_section = True
            continue
        # 遇到下一个「■」小节 → 商品内容结束，停止
        if line.startswith("■"):
            break
        # 空行 / 非「・」杂行（期限提示、末行暗号等）跳过而**不截断**，
        # 避免商品之间夹一空行时把后续商品漏掉（3 件识别成 2 件的主因）。
        if not line:
            continue
        m = _BUNDLE_LINE_RE.match(line)
        if not m:
            continue
        title = (m.group(1) or "").strip()
        title = _BUNDLE_TRAILING_STATE_RE.sub("", title).strip()
        if title:
            titles.append(title)
    return titles

def _resolve_inventory_ids_by_bundle_title(
    title: str, seller_id: Optional[str] = None
) -> List[Tuple[int, Optional[str]]]:
    """返回该标题在 on_sale_items 中可映射到的**全部去重候选** ``(inventory_id, 原始在售商品 item_id)``
    （按 rank 排序）。

    - 仅在 ``seller_id`` 指定的卖出账号内匹配（订单 orders.data_user / 在售 listing 的 seller_id），
      **不跨账号**；同名商品在不同账号各自独立，绝不互相关联。
    - 同名多条在售 → 各自 listing_description 末行暗号 / mercari_item_id 反查，得到多个不同
      「管理番号」，供调用方给重复出现的同名标题**逐个分配不同库存**。
    - 第二元素为**匹配到的原始在售商品 ID**（on_sale_items.item_id），供页面展示来源。
    """
    query_title = str(title or "").strip()
    if not query_title:
        return []
    db = DatabaseManager()
    # 单次查询（含软删记录），排序优先级由 _collect_bundle_title_ids 统一决定：
    #   ① 暂停出售 stop & 未软删  ② 停止出售 stop & 已软删  ③ 出售中 on_sale …
    # 组合子商品被合单后通常转为 stop（并常被本地软删 is_delete=1，如 m78908692730），
    # 因此 stop 记录必须整体优先于仍独立在售的同名 on_sale 记录。
    rows = _query_on_sale_rows_for_bundle(db, include_deleted=True, seller_id=seller_id)
    return list(_collect_bundle_title_ids(db, query_title, rows))


def _resolve_inventory_id_by_bundle_title(
    title: str, seller_id: Optional[str] = None
) -> Optional[int]:
    """单值版：取候选列表首个 inventory_id（暂停出售 → 停止出售 → 出售中 优先）。兼容旧调用方。"""
    ids = _resolve_inventory_ids_by_bundle_title(title, seller_id=seller_id)
    return ids[0][0] if ids else None


def _query_on_sale_rows_for_bundle(
    db: "DatabaseManager", include_deleted: bool, seller_id: Optional[str] = None
):
    where_delete = "" if include_deleted else "COALESCE(o.[is_delete], 0) = 0 AND "
    where_seller = ""
    params: Tuple[Any, ...] = ()
    sid = str(seller_id or "").strip()
    if sid:
        # 账号隔离：只取本账号（卖出账号）的在售记录
        where_seller = "AND TRIM(IFNULL(o.[seller_id], '')) = TRIM(?) "
        params = (sid,)
    return db.execute_query(
        f"""
        SELECT
            o.[item_id],
            TRIM(IFNULL(o.[name], '')),
            IFNULL(o.[listing_description], ''),
            TRIM(IFNULL(o.[status], '')),
            IFNULL(o.[created], 0),
            IFNULL(o.[id], 0),
            COALESCE(o.[is_delete], 0)
        FROM [on_sale_items] o
        WHERE {where_delete}TRIM(IFNULL(o.[item_id], '')) != ''
          AND TRIM(IFNULL(o.[name], '')) != ''
          {where_seller}
        """,
        params,
    )


def _collect_bundle_title_ids(
    db: "DatabaseManager", query_title: str, rows
) -> List[Tuple[int, str]]:
    """在给定在售行中，按 rank 顺序收集该标题可映射到的**全部去重** ``(inventory_id, 来源 item_id)``。"""
    if not rows:
        return []

    target_norm = _normalize_match_text(query_title)
    # 组合(まとめ)子商品被合单后转为 stop（暂停/停止出售），因此**始终优先** status=stop
    # 的记录，且暂停出售(未软删) 先于 停止出售(已软删)，均先于仍独立在售的同名 on_sale。
    # 元组：(item_id, desc, status, is_delete, created, row_id)
    exact_matches: List[Tuple[str, str, str, int, int, int]] = []
    fuzzy_matches: List[Tuple[str, str, str, int, int, int]] = []
    for item_id_raw, name_raw, desc_raw, status_raw, created_raw, row_id_raw, is_delete_raw in rows:
        item_id = str(item_id_raw or "").strip()
        if not item_id:
            continue
        name = str(name_raw or "").strip()
        name_norm = _normalize_match_text(name)
        if not name_norm:
            continue
        desc = str(desc_raw or "")
        status = str(status_raw or "").strip().lower()
        try:
            created = int(created_raw or 0)
        except (TypeError, ValueError):
            created = 0
        try:
            row_id = int(row_id_raw or 0)
        except (TypeError, ValueError):
            row_id = 0
        try:
            is_delete = 1 if int(is_delete_raw or 0) else 0
        except (TypeError, ValueError):
            is_delete = 0
        if name_norm == target_norm:
            exact_matches.append((item_id, desc, status, is_delete, created, row_id))
        elif target_norm and (target_norm in name_norm or name_norm in target_norm):
            fuzzy_matches.append((item_id, desc, status, is_delete, created, row_id))

    matches = exact_matches if exact_matches else fuzzy_matches
    if not matches:
        return []

    # 排序优先级（值越小越靠前）：
    #   ① 暂停出售  status=stop & is_delete=0
    #   ② 停止出售  status=stop & is_delete=1
    #   ③ 出售中等  其余（on_sale …），未软删先于已软删
    #   同档内再按「最新数据」优先（created 更大 → row_id 更大）。
    def _match_rank(m):
        _item_id, _desc, status, is_delete, created, row_id = m
        stop_first = 0 if status == "stop" else 1
        return (stop_first, is_delete, -(created or 0), -(row_id or 0))

    matches = sorted(matches, key=_match_rank)

    out: List[Tuple[int, str]] = []
    seen: set = set()
    # 优先：用 on_sale_items.listing_description 末行暗号直接定位 inventory.id。
    # 暗号 → inventory.id 是出品时编码的强绑定，比 mercari_item_id 反查更可靠。
    # 逐条在售各自解出自己的库存 ID —— 同名多条即得到多个不同「管理番号」；
    # 一并带出该在售记录的 item_id 作为「原始在售商品 ID」。
    #
    # ⚠️ 真实性边界（authenticity boundary）：暗号本身只是混淆、无密钥、可伪造
    # （见 mgmt_id_cipher.py 安全声明）。此处之所以可信，靠的**不是暗号自身**，而是
    # 两道独立约束：(1) desc 来自 _query_on_sale_rows_for_bundle(seller_id=…) 已按**卖出账号**
    # 隔离过滤的在售记录——绝不跨账号；(2) 解出的 inventory.id 再经 _inventory_id_exists 存在性
    # 校验。二者共同构成真实性边界；切勿删掉账号隔离或存在性检查而「仅信任解码结果」。
    for cur_item_id, desc, _status, _is_delete, _created, _row_id in matches:
        for mid, _qty in parse_trailing_cipher_mgmt_tokens(desc):
            if mid not in seen and _inventory_id_exists(mid):
                seen.add(mid)
                out.append((mid, cur_item_id))

    # 回退：按 mercari_item_id 反查 inventory（仅在上面已按账号过滤出的 item_ids 内）。
    item_ids = [m[0] for m in matches]
    inv_rows = db.execute_query(
        """
        SELECT [id], [mercari_item_id]
        FROM [inventory]
        WHERE TRIM(IFNULL([mercari_item_id], '')) != ''
        """,
    )
    inv_by_mid: dict = {}
    for inv_id_raw, mids_raw in inv_rows:
        try:
            inv_id = int(inv_id_raw)
        except (TypeError, ValueError):
            continue
        for mid in _split_mercari_item_ids(mids_raw):
            inv_by_mid.setdefault(mid, []).append(inv_id)

    for item_id in item_ids:
        for key in (item_id, item_id[1:] if item_id.startswith("m") else f"m{item_id}"):
            for inv_id in inv_by_mid.get(key, []):
                if inv_id not in seen:
                    seen.add(inv_id)
                    out.append((inv_id, item_id))
    return out
