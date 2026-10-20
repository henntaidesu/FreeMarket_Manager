# -*- coding: utf-8 -*-
"""导入历史库存：把勾选的 inventory_old 行逐条复制成新库存（**新管理番号**）。

- id 一律由自增分配，绝不沿用归档里的 id：历史订单的出库明细按「id 在 inventory_old 而不在
  inventory」判定指向归档（``OrderOutboundLineModel.save`` / ``backfill_archived_lines``），
  旧 id 一旦出现在 inventory 里，那些明细就会改指这条新商品。
- 内部条码 ``barcode``（唯一键）原样带过来，于是同一件历史商品重复导入会撞唯一约束——这就是
  「已导入过」的判据，不另设标记列。
- 产品条码 / 款式 / 品相照搬，``base_mgmt_id`` 按新库里的同条码商品重算（``sync_base_mgmt_id``）。
- 在售 / 待出 / 出品预扣减、绑定的挂牌一律清零；自动出品关掉，免得导入即触发补挂。
  出品说明末行的旧管理番号暗号去掉，否则下次出品会把旧 id 写进描述与图片暗码。
- 图片物理复制一份（与复制商品同理），新旧两条不共享文件。组合商品不导入：构成明细引用的是旧 id。
- 数量照搬，作为一个首批次落到原货架上（货架已不存在则放默认仓库）。
"""
from typing import Optional

from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....use_mercari.mgmt_id_cipher import is_cipher_mgmt_line
from ...image_storage import duplicate_image

from .inventory_helpers import (
    images_json_from_paths,
    _legacy_paths_from_db_columns,
    _warehouse_exists,
    _user_exists,
)
from .inventory_models import InventoryImportArchiveRequest

db = DatabaseManager()

MAX_IMPORT = 200

_COLS = (
    "id", "name", "barcode", "product_barcode", "barcode_scan_status", "barcode_candidates",
    "variant_no", "grade", "barcode_confirmed", "base_mgmt_id", "category_id", "product_type_id",
    "owner_user_id", "warehouse_id", "price", "quantity", "description", "listing_title",
    "listing_body", "listing_status", "listing_account_id", "shipping_payer", "shipping_method",
    "shipping_from_area_id", "shipping_days", "sale_type", "auction_duration", "images_json",
    "auto_listing_watermark", "is_combined",
)

# 照搬到新行的列（id / base_mgmt_id / images_json / is_combined 单独处理）
_COPY_COLS = (
    "name", "barcode", "product_barcode", "barcode_scan_status", "barcode_candidates",
    "variant_no", "grade", "barcode_confirmed", "category_id", "product_type_id",
    "owner_user_id", "warehouse_id", "price", "quantity", "description", "listing_title",
    "listing_body", "listing_status", "listing_account_id", "shipping_payer", "shipping_method",
    "shipping_from_area_id", "shipping_days", "sale_type", "auction_duration",
    "auto_listing_watermark",
)


def _strip_trailing_cipher(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    lines = str(text).rstrip().split("\n")
    if lines and is_cipher_mgmt_line(lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines).rstrip()


def _import_one(src: dict) -> int:
    from ....inventory_barcode.variant import sync_barcode_mode, sync_base_mgmt_id
    from ....use_mercari.inventory_batches import insert_initial_batch

    row = {c: src[c] for c in _COPY_COLS}
    row["listing_body"] = _strip_trailing_cipher(row["listing_body"])
    if row["warehouse_id"] is not None and not _warehouse_exists(int(row["warehouse_id"])):
        row["warehouse_id"] = None
    if row["owner_user_id"] is not None and not _user_exists(int(row["owner_user_id"])):
        row["owner_user_id"] = None
    if row["barcode_scan_status"] == "merged":
        row["barcode_scan_status"] = "found" if (row["product_barcode"] or "").strip() else None
    qty = max(0, int(row["quantity"] or 0))
    row["quantity"] = qty

    new_paths = [duplicate_image(p, prefix="inv_import") for p in _legacy_paths_from_db_columns(src["images_json"])]
    row["images_json"] = images_json_from_paths(new_paths)
    row.update({
        "mercari_item_id": None, "on_sale_quantity": 0, "pending_outbound_qty": 0,
        "pending_listing_qty": 0, "auto_listing_enabled": 0, "is_combined": 0, "is_delete": 0,
    })

    cols = list(row.keys())
    new_id = db.execute_insert(
        f"INSERT INTO [inventory] ({', '.join(f'[{c}]' for c in cols)}) VALUES ({', '.join('?' * len(cols))})",
        tuple(row[c] for c in cols),
    )
    new_id = int(new_id)
    if (row["product_barcode"] or "").strip():
        sync_base_mgmt_id(new_id)
        sync_barcode_mode(new_id)
    if qty > 0:
        insert_initial_batch(new_id, quantity=qty, warehouse_id=row["warehouse_id"],
                             remark=f"导入自历史库存 {src['old_mgmt_code']}")
    return new_id


def import_archive_inventory(data: InventoryImportArchiveRequest, _claims: dict = Depends(require_auth)):
    """按勾选的历史库存 id 导入，返回每条的新管理番号与跳过原因。单条失败不影响其余。"""
    from ....inventory_barcode.variant import mgmt_code
    from ....use_mercari.inventory_counters import recompute_listable_quantity
    from ..image_search import enqueue_inventory as _enqueue_image_index

    ids = list(dict.fromkeys(int(i) for i in (data.ids or [])))
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要导入的历史库存")
    if len(ids) > MAX_IMPORT:
        raise HTTPException(status_code=400, detail=f"一次最多导入 {MAX_IMPORT} 条")

    rows = db.execute_query(
        f"SELECT {', '.join(f'[{c}]' for c in _COLS)} FROM [inventory_old] "
        f"WHERE COALESCE([is_delete], 0) = 0 AND [id] IN ({','.join('?' * len(ids))})",
        tuple(ids),
    )
    by_id = {int(r[0]): dict(zip(_COLS, r)) for r in rows}

    imported, skipped, new_ids = [], [], []
    for old_id in ids:
        src = by_id.get(old_id)
        if not src:
            skipped.append({"old_id": old_id, "reason": "历史库存不存在或已删除"})
            continue
        src["old_mgmt_code"] = mgmt_code(old_id, src["base_mgmt_id"], src["variant_no"], src["grade"])
        if int(src["is_combined"] or 0):
            skipped.append({"old_id": old_id, "old_mgmt_code": src["old_mgmt_code"], "reason": "组合商品不能导入"})
            continue
        if src["barcode"] and db.execute_query(
            "SELECT [id] FROM [inventory] WHERE [barcode] = ? LIMIT 1", (src["barcode"],)
        ):
            skipped.append({"old_id": old_id, "old_mgmt_code": src["old_mgmt_code"], "reason": "已导入过"})
            continue
        try:
            new_id = _import_one(src)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"old_id": old_id, "old_mgmt_code": src["old_mgmt_code"], "reason": f"导入失败：{exc}"})
            continue
        new_ids.append(new_id)
        imported.append({"old_id": old_id, "old_mgmt_code": src["old_mgmt_code"], "new_id": new_id})

    if new_ids:
        recompute_listable_quantity(new_ids)
        for nid in new_ids:
            _enqueue_image_index(nid)
        codes = db.execute_query(
            f"SELECT [id], [base_mgmt_id], [variant_no], [grade] FROM [inventory] "
            f"WHERE [id] IN ({','.join('?' * len(new_ids))})",
            tuple(new_ids),
        )
        code_by_id = {int(r[0]): mgmt_code(r[0], r[1], r[2], r[3]) for r in codes}
        for it in imported:
            it["new_mgmt_code"] = code_by_id.get(it["new_id"], str(it["new_id"]))

    return {"imported": imported, "skipped": skipped}
