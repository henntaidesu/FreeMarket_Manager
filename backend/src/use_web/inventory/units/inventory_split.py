# -*- coding: utf-8 -*-
"""由已有商品复制出一条新库存（新管理番号）的端点，可指定不同的商品归属。

来源库存不动，新记录的数量是这次新到的货；不继承来源的货位（warehouse_id 恒为 NULL），
图片物理复制一份。原「拆分」端点已删除——给某位买家单独挂链接改用库存详情页的「专用出品」，
不再新开管理番号。
"""
import time
import uuid
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....use_mercari.inventory_counters import recompute_listable_quantity
from ...image_storage import duplicate_image

from .inventory_helpers import (
    images_json_from_paths,
    _query_inventory_with_joins,
    _inventory_exists,
    _user_exists,
    _legacy_paths_from_db_columns,
)
from .inventory_models import InventoryCopyRequest

db = DatabaseManager()


def _duplicate_image_file(path: str) -> str:
    """复制一张 /imges/xxx 图片，返回新路径，避免复制后两条记录共享同一文件导致删除冲突。

    实现搬到了 ``image_storage.duplicate_image``：复制的方式取决于图片现在在哪
    （本地是一次 copy，图床是下载再上传），而那个判断只应该有一处。
    """
    return duplicate_image(path, prefix="inv_split")


def copy_inventory(pid: int, data: InventoryCopyRequest, _claims: dict = Depends(require_auth)):
    """按已有商品复制出一条新库存（新管理番号），来源库存不变，并可同时切换商品归属。

    与拆分的区别只在数量的来路：拆分是把来源的货挪一部分过去，复制是这次**新到**的货沿用
    同一份商品资料。所以这里既不扣来源库存，也不写 split_parent_id（列表里的「拆自」是拆分
    专属的溯源，复制出来的是一条独立记录），自然也不需要拆分那套并发复查。
    """
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    copy_qty = int(data.quantity or 0)
    if copy_qty < 0:
        raise HTTPException(status_code=400, detail="复制数量不能小于0")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")

    rows = db.execute_query(
        """
        SELECT name, barcode, category_id, product_type_id, owner_user_id, warehouse_id,
               price, quantity, description, listing_title, listing_body,
               images_json, is_combined
        FROM [inventory] WHERE id = ? LIMIT 1
        """,
        (pid,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="商品不存在")
    src = rows[0]
    # 组合商品的构成明细（combined_items）不在复制范围内，照抄出来的会是一个引用着别人库存
    # 却没有预留的空壳，和拆分一样直接挡掉
    if int(src[12] or 0):
        raise HTTPException(status_code=400, detail="组合商品不能复制")

    new_owner = data.owner_user_id if data.owner_user_id is not None else src[4]
    new_barcode = f"COPY-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

    src_paths = _legacy_paths_from_db_columns(src[11])
    new_paths = [_duplicate_image_file(p) for p in src_paths]
    new_images_json = images_json_from_paths(new_paths)

    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty, split_parent_id,
                    description, listing_title, listing_body, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src[0], new_barcode, src[2], src[3], new_owner, None, src[6], copy_qty,
                    None, 0, 0, None,
                    src[8], src[9], src[10],
                    new_images_json,
                ),
            )
            new_id = cur.lastrowid
            db.dialect.commit(conn)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="复制失败，请稍后重试")

    from ..image_search import enqueue_inventory as _enqueue_image_index
    _enqueue_image_index(new_id)

    # 来源没动，只需要算新行的可上架
    recompute_listable_quantity([int(new_id)])

    items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return items[0] if items else {"id": new_id}
