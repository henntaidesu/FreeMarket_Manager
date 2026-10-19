# -*- coding: utf-8 -*-
"""条码 × 款式 × 品相：一个条码下的多件商品怎么编号。

三样东西各存一列，**不拼进同一个字段**：
  · ``product_barcode``：纯条码（图片识别 / 扫码得到的原样）；
  · ``variant_no``：款式号 1、2、3…；
  · ``grade``：品相 ``S`` 良品 / ``A`` 一般 / ``J`` 损坏，NULL = 未定。

一个条码要么是**一对一**（条码只对应一种商品）：款式号全部为空，编号只追加品相 ``条码-S``；
要么是**一对多**（同一条码印在不同商品上，盲盒不同款等）：每件都有款式号 ``条码-1-S``。
模式不另存，按「该条码下有没有带款式号的商品」推断——款式号本身就落在每行上，不会与模式漂开。

**每个「款式 × 品相」是一件独立商品**（自己的图片组与库存），整数 ``inventory.id`` 不变
（图片暗码 / 描述暗号只认这个整数）。显示用编号由 API 现拼：
  · 条码编号 ``barcode_code`` = 条码[-款式][-品相]；
  · 管理编号 ``mgmt_code`` = 基础番号[-款式][-品相]；款式、品相都没有时就是 id 本身。
``base_mgmt_id`` = 这个条码下第一件商品的 id，**落库**：第一件被删 / 被合并后现算的号会变，
已贴的标签就对不上了。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ..db_manage.database import DatabaseManager

GRADES = ("S", "A", "J")
#: 品相 → 出品时的「商品の状態」（自动带出，表单里仍可改）
GRADE_TO_LISTING_STATUS = {"S": "new_unused", "A": "good", "J": "bad"}

_VARIANT_RE = re.compile(r"^(.+)-(\d+)$")
_DISPLAY_RE = re.compile(r"^(.+?)(?:-(\d+))?(?:-([SAJ]))?$", re.IGNORECASE)


def normalize_grade(raw: Any) -> Optional[str]:
    g = str(raw or "").strip().upper()
    if not g:
        return None
    if g not in GRADES:
        raise ValueError("品相只能是 S / A / J")
    return g


def normalize_variant(raw: Any) -> Optional[int]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError("款式号必须是正整数") from None
    if n < 1:
        raise ValueError("款式号必须是正整数")
    return n


def parse_display_code(text: str) -> Optional[Tuple[str, Optional[int], Optional[str]]]:
    """``X[-款式][-品相]`` → (X, 款式, 品相)；没有任何后缀返回 None（那就是原样的条码 / 番号）。"""
    m = _DISPLAY_RE.match((text or "").strip())
    if not m or (m.group(2) is None and m.group(3) is None):
        return None
    return m.group(1), (int(m.group(2)) if m.group(2) else None), (m.group(3).upper() if m.group(3) else None)


def _suffix(variant_no: Any, grade: Optional[str]) -> str:
    s = f"-{int(variant_no)}" if variant_no not in (None, "") else ""
    return s + (f"-{grade}" if grade else "")


def barcode_code(product_barcode: Optional[str], variant_no: Any, grade: Optional[str]) -> Optional[str]:
    pb = (product_barcode or "").strip()
    return pb + _suffix(variant_no, grade) if pb else None


def mgmt_code(inv_id: Any, base_mgmt_id: Any, variant_no: Any, grade: Optional[str]) -> str:
    suffix = _suffix(variant_no, grade)
    return f"{base_mgmt_id or inv_id}{suffix}" if suffix else str(inv_id)


def barcode_is_multi(code: str, exclude_ids: Tuple[int, ...] = ()) -> bool:
    """该条码是否为一对多（未删除商品里有带款式号的）。"""
    code = (code or "").strip()
    if not code:
        return False
    sql = (
        "SELECT 1 FROM [inventory] WHERE COALESCE([is_delete], 0) = 0 AND [product_barcode] = ? "
        "AND [variant_no] IS NOT NULL"
    )
    params: list = [code]
    if exclude_ids:
        sql += f" AND [id] NOT IN ({','.join('?' * len(exclude_ids))})"
        params += [int(i) for i in exclude_ids]
    return bool(DatabaseManager().execute_query(sql + " LIMIT 1", tuple(params)))


def sync_base_mgmt_id(inv_id: int) -> None:
    """按当前 ``product_barcode`` 重定 ``base_mgmt_id``：沿用同条码其它商品的基础番号，没有就用自己的 id。"""
    db = DatabaseManager()
    row = db.execute_query("SELECT [product_barcode] FROM [inventory] WHERE [id] = ? LIMIT 1", (int(inv_id),))
    if not row:
        return
    pb = (row[0][0] or "").strip()
    if not pb:
        db.execute_update("UPDATE [inventory] SET [base_mgmt_id] = NULL WHERE [id] = ?", (int(inv_id),))
        return
    other = db.execute_query(
        "SELECT MIN(COALESCE([base_mgmt_id], [id])) FROM [inventory] WHERE COALESCE([is_delete], 0) = 0 "
        "AND [product_barcode] = ? AND [id] <> ?",
        (pb, int(inv_id)),
    )
    val = int(other[0][0]) if other and other[0][0] is not None else int(inv_id)
    db.execute_update("UPDATE [inventory] SET [base_mgmt_id] = ? WHERE [id] = ?", (val, int(inv_id)))


def sync_barcode_mode(inv_id: int) -> None:
    """一件商品带上款式号后，同条码里还没有款式号的商品补成款式 1（一对一 → 一对多的转换点）。
    只在本商品不是款式 1 时做，否则就和它们撞成同一款了。"""
    db = DatabaseManager()
    row = db.execute_query(
        "SELECT [product_barcode], [variant_no] FROM [inventory] WHERE [id] = ? LIMIT 1", (int(inv_id),)
    )
    if not row or not (row[0][0] or "").strip() or row[0][1] is None or int(row[0][1]) == 1:
        return
    db.execute_update(
        "UPDATE [inventory] SET [variant_no] = 1 WHERE COALESCE([is_delete], 0) = 0 AND [product_barcode] = ? "
        "AND [variant_no] IS NULL AND [id] <> ?",
        (row[0][0].strip(), int(inv_id)),
    )


def migrate_variant_codes() -> Dict[str, int]:
    """启动迁移（幂等，两种方言都跑）：

    1. 拆字段：``product_barcode`` 里的 ``条码-N``（旧的一码多品编号）拆成 纯条码 + ``variant_no=N``；
    2. 只有款式 1 的条码其实是一对一 → 清空款式号；
    3. 补齐 ``base_mgmt_id``。
    """
    db = DatabaseManager()
    stats = {"split": 0, "to_single": 0, "base_filled": 0}
    rows = db.execute_query(
        "SELECT [id], TRIM([product_barcode]), [variant_no] FROM [inventory] "
        "WHERE [product_barcode] IS NOT NULL AND TRIM([product_barcode]) <> ''"
    ) or []
    for iid, pb, vno in rows:
        m = _VARIANT_RE.match(pb or "")
        if not m:
            continue
        db.execute_update(
            "UPDATE [inventory] SET [product_barcode] = ?, [variant_no] = ? WHERE [id] = ?",
            (m.group(1), vno if vno is not None else int(m.group(2)), int(iid)),
        )
        stats["split"] += 1
    if stats["split"]:
        # 拆完后某条码下只有款式 1：当初只是被补成了 -1，并不是真的一对多
        singles = db.execute_query(
            "SELECT [product_barcode] FROM [inventory] WHERE COALESCE([is_delete], 0) = 0 "
            "AND [product_barcode] IS NOT NULL AND [variant_no] IS NOT NULL "
            "GROUP BY [product_barcode] HAVING MAX([variant_no]) = 1 AND MIN([variant_no]) = 1"
        ) or []
        for (code,) in singles:
            stats["to_single"] += db.execute_update(
                "UPDATE [inventory] SET [variant_no] = NULL WHERE [product_barcode] = ? AND [variant_no] = 1",
                (code,),
            )
    pending = db.execute_query(
        "SELECT [id], TRIM([product_barcode]), [base_mgmt_id] FROM [inventory] WHERE COALESCE([is_delete], 0) = 0 "
        "AND [product_barcode] IS NOT NULL AND TRIM([product_barcode]) <> '' ORDER BY [id]"
    ) or []
    base_min: Dict[str, int] = {}
    for iid, pb, bm in pending:
        cur = int(bm) if bm is not None else int(iid)
        base_min[pb] = min(base_min.get(pb, cur), cur)
    for iid, pb, bm in pending:
        if bm is None or int(bm) != base_min[pb]:
            db.execute_update("UPDATE [inventory] SET [base_mgmt_id] = ? WHERE [id] = ?", (base_min[pb], int(iid)))
            stats["base_filled"] += 1
    return stats
