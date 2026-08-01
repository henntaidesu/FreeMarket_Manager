# -*- coding: utf-8 -*-
"""库存创建/更新/删除端点。"""
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager

from .inventory_helpers import (
    _query_inventory_with_joins,
    _inventory_exists,
    _warehouse_exists,
    _user_exists,
    _legacy_paths_from_db_columns,
    images_json_from_paths,
)
from .inventory_images import (
    _normalize_images_input_list,
    _convert_image_list_to_paths,
    _delete_paths_removed,
    _convert_image_payload,
    _resolve_paths_for_create,
)
from .inventory_combined import _parse_combined_items
from .inventory_models import InventoryCreate, InventoryUpdate
from ..image_search import enqueue_inventory as _enqueue_image_index

db = DatabaseManager()


def create_inventory(data: InventoryCreate, _claims: dict = Depends(require_auth)):
    if not (data.barcode or "").strip():
        raise HTTPException(status_code=400, detail="条形码必填")
    if data.warehouse_id is not None and not _warehouse_exists(data.warehouse_id):
        raise HTTPException(status_code=400, detail="所属货架不存在")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")
    paths = _resolve_paths_for_create(data)
    images_json_val = images_json_from_paths(paths)
    try:
        new_id = db.execute_insert(
            """
            INSERT INTO [inventory] (
                name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                mercari_item_id, on_sale_quantity, pending_outbound_qty, auto_listing_enabled, auto_listing_watermark,
                description, listing_title, listing_body,
                listing_status, listing_account_id, shipping_payer, shipping_method,
                shipping_from_area_id, shipping_days, sale_type, auction_duration,
                images_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.name,
                data.barcode.strip(),
                data.category_id,
                data.product_type_id,
                data.owner_user_id,
                data.warehouse_id,
                data.price,
                data.quantity,
                (data.mercari_item_id or "").strip() or None,
                int(data.on_sale_quantity) if data.on_sale_quantity is not None else 0,
                0,
                1 if int(data.auto_listing_enabled or 0) == 1 else 0,
                1 if (data.auto_listing_watermark is None or int(data.auto_listing_watermark) == 1) else 0,
                data.description,
                data.listing_title,
                data.listing_body,
                data.listing_status,
                data.listing_account_id,
                data.shipping_payer,
                data.shipping_method,
                data.shipping_from_area_id,
                data.shipping_days,
                data.sale_type,
                data.auction_duration,
                images_json_val,
            ),
        )
    except Exception as exc:
        err = str(exc).lower()
        if "unique" in err and "barcode" in err:
            raise HTTPException(status_code=400, detail="保存失败，条形码可能重复")
        raise HTTPException(status_code=400, detail="保存失败，请检查填写内容后重试")
    # 新行的 listable_quantity 需立即落库，否则展示值（读取时重算）与出品预扣减的 CAS 判据不一致
    from ....use_mercari.inventory_counters import recompute_listable_quantity
    recompute_listable_quantity([int(new_id)])
    _enqueue_image_index(new_id)
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return inventory_items[0] if inventory_items else {"id": new_id}


def update_inventory(pid: int, data: InventoryUpdate, _claims: dict = Depends(require_auth)):
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    update_data = data.model_dump(exclude_unset=True)
    if 'barcode' in update_data and not (update_data.get('barcode') or '').strip():
        raise HTTPException(status_code=400, detail="条形码不能为空")
    if 'barcode' in update_data:
        update_data['barcode'] = update_data['barcode'].strip()
    existing = db.execute_query(
        """
        SELECT images_json, warehouse_id, owner_user_id,
               is_combined, combined_items
        FROM [inventory] WHERE id = ? LIMIT 1
        """,
        (pid,),
    )
    old_images_json = existing[0][0] if existing else None
    old_warehouse_id = existing[0][1] if existing else None
    old_owner_user_id = existing[0][2] if existing else None
    old_is_combined = int(existing[0][3] or 0) if existing else 0
    old_combined_items = existing[0][4] if existing else None

    old_paths = _legacy_paths_from_db_columns(old_images_json)

    if 'images' in update_data:
        update_data.pop('image_front', None)
        update_data.pop('image_back', None)
        update_data.pop('image', None)
        raw_images = update_data.pop('images')
        normalized = _normalize_images_input_list(raw_images, "images")
        if normalized is None:
            normalized = []
        new_paths = _convert_image_list_to_paths(normalized)
        _delete_paths_removed(old_paths, new_paths)
        update_data['images_json'] = images_json_from_paths(new_paths)
    elif 'image_front' in update_data or 'image_back' in update_data:
        # 兼容旧传输：单独传 image_front / image_back（保留未指定的一侧）
        cur_front = old_paths[0] if len(old_paths) > 0 else None
        cur_back = old_paths[1] if len(old_paths) > 1 else None
        if 'image_front' in update_data:
            cur_front = _convert_image_payload(update_data.pop('image_front'), "inventory_front")
        if 'image_back' in update_data:
            cur_back = _convert_image_payload(update_data.pop('image_back'), "inventory_back")
        update_data.pop('image', None)
        new_paths = [p for p in [cur_front, cur_back] if p]
        _delete_paths_removed(old_paths, new_paths)
        update_data['images_json'] = images_json_from_paths(new_paths)
    final_warehouse_id = update_data['warehouse_id'] if 'warehouse_id' in update_data else old_warehouse_id
    if 'warehouse_id' in update_data:
        if final_warehouse_id is not None and not _warehouse_exists(final_warehouse_id):
            raise HTTPException(status_code=400, detail="所属货架不存在")
    if 'owner_user_id' in update_data:
        new_owner_user_id = update_data['owner_user_id']
        if new_owner_user_id is not None and not _user_exists(new_owner_user_id):
            raise HTTPException(status_code=400, detail="商品归属用户不存在")
    if "auto_listing_enabled" in update_data:
        update_data["auto_listing_enabled"] = 1 if int(update_data.get("auto_listing_enabled") or 0) == 1 else 0
    if "auto_listing_watermark" in update_data:
        update_data["auto_listing_watermark"] = 1 if int(update_data.get("auto_listing_watermark") or 0) == 1 else 0
    allowed_fields = {
        "name", "barcode", "category_id", "product_type_id", "owner_user_id", "warehouse_id", "price",
        "quantity",
        "mercari_item_id", "on_sale_quantity", "auto_listing_enabled", "auto_listing_watermark",
        "description", "listing_title", "listing_body",
        "listing_status", "listing_account_id", "shipping_payer", "shipping_method",
        "shipping_from_area_id", "shipping_days", "sale_type", "auction_duration",
        "images_json",
    }
    update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    # 组合商品上调套数前校验来源子商品是否够预留（排除本组合自身既有预留），避免幽灵预留
    if old_is_combined and "quantity" in update_data:
        from .inventory_combined import _validate_combined_quantity_for_update
        _validate_combined_quantity_for_update(pid, old_combined_items, update_data["quantity"])
    if update_data:
        set_sql = ", ".join([f"[{k}] = ?" for k in update_data.keys()])
        params = tuple(update_data.values()) + (pid,)
        try:
            db.execute_update(f"UPDATE [inventory] SET {set_sql} WHERE id = ?", params)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
        # 改动库存/在售会改变本商品可上架；组合商品套数变化还会改变来源商品被「拉走」的件数，
        # 一并重算来源可上架（组合不扣减来源库存）。
        if "quantity" in update_data or "on_sale_quantity" in update_data:
            from ....use_mercari.inventory_counters import recompute_listable_quantity
            touched = [pid]
            if old_is_combined and "quantity" in update_data:
                touched += [int(it["inventory_id"]) for it in _parse_combined_items(old_combined_items)]
            recompute_listable_quantity(touched)
    if "images_json" in update_data:
        _enqueue_image_index(pid)
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
    return inventory_items[0]


def delete_inventory(pid: int):
    """假删除：仅置 is_delete=1，保留图片与数据，可通过数据库手动恢复（SET is_delete=0）。

    **排队中的出品任务会挡住删除**：出品在入队那一刻就占了 ``pending_listing_qty``，
    任务真正执行时才知道该不该挂牌。这时把商品删掉，任务照跑不误、挂出去的商品却已无库存
    可绑，占用也要等 6 小时 TTL 才释放。与其事后收拾，不如先让用户取消任务。

    已挂在售（``on_sale_quantity > 0``）只提示、不阻止：商品下架/售出后在售同步会把
    ``reconcile_listing_counts`` 跑一遍，凭 ``counted_inventory_ids`` 正确退回计数，
    删掉的行也能被找到——这条路径本来就自洽。
    """
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")

    pending = _pending_listing_task_ids(int(pid))
    if pending:
        ids = "、".join(f"#{t}" for t in pending[:5])
        more = f" 等 {len(pending)} 条" if len(pending) > 5 else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"该商品还有出品任务在队列中（{ids}{more}），删除后任务仍会执行并挂出无库存可绑的商品。"
                f"请先到「任务队列」取消这些任务再删除。"
            ),
        )

    db.execute_update(
        "UPDATE [inventory] SET is_delete = 1 WHERE id = ? AND COALESCE(is_delete, 0) = 0",
        (pid,),
    )
    _enqueue_image_index(pid)
    return {"message": "删除成功"}


def _pending_listing_task_ids(inventory_id: int) -> list:
    """该库存上还没执行完的出品任务 id（pending / running）。查询失败按「没有」处理——
    队列不可用不该连累删除。"""
    try:
        from ....db_manage.models.system.task_queue import ACTIVE_STATUSES
        from ....task_queue.registry import INVENTORY_LISTING

        ph = ", ".join("?" * len(ACTIVE_STATUSES))
        rows = db.execute_query(
            f"SELECT [id], [payload] FROM [task_queue] "
            f"WHERE [task_type] = ? AND [status] IN ({ph}) ORDER BY [id]",
            (INVENTORY_LISTING, *ACTIVE_STATUSES),
        ) or []
    except Exception:  # noqa: BLE001
        return []
    import json

    out = []
    for tid, payload in rows:
        try:
            ids = (json.loads(payload) or {}).get("inventory_ids") or []
        except (TypeError, ValueError):
            continue
        if any(int(x) == int(inventory_id) for x in ids if x is not None):
            out.append(int(tid))
    return out
