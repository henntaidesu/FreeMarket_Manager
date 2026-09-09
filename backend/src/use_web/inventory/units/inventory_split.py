# -*- coding: utf-8 -*-
"""由已有商品派生出一条新库存（新管理番号）的两个端点，可指定不同的商品归属：

- 拆分：数量从来源身上**挪**过来，来源库存等额减少；
- 复制：来源库存**不动**，新记录的数量是这次新到的货。

两者都不继承来源的货位（warehouse_id 恒为 NULL = 默认仓库），也都会把图片物理复制一份。
"""
import time
import uuid
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....use_mercari.inventory_counters import (
    is_combined_source,
    recompute_listable_quantity,
    _listable_sql_expr,
)
from ...image_storage import duplicate_image

from .inventory_helpers import (
    images_json_from_paths,
    _query_inventory_with_joins,
    _inventory_exists,
    _user_exists,
    _legacy_paths_from_db_columns,
)
from .inventory_models import InventoryCopyRequest, InventorySplitRequest

db = DatabaseManager()


def _duplicate_image_file(path: str) -> str:
    """复制一张 /imges/xxx 图片，返回新路径，避免拆分后两条记录共享同一文件导致删除冲突。

    实现搬到了 ``image_storage.duplicate_image``：复制的方式取决于图片现在在哪
    （本地是一次 copy，图床是下载再上传），而那个判断只应该有一处。
    """
    return duplicate_image(path, prefix="inv_split")


def split_inventory(pid: int, data: InventorySplitRequest, _claims: dict = Depends(require_auth)):
    """将商品按指定数量拆分出一条新库存（新管理番号），并可同时切换商品归属。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    split_qty = int(data.split_quantity or 0)
    if split_qty < 0:
        raise HTTPException(status_code=400, detail="拆分数量不能小于0")
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
    src_quantity = int(src[7] or 0)
    is_combined = int(src[12] or 0)

    if is_combined:
        raise HTTPException(status_code=400, detail="组合商品不能拆分")
    combined_src = is_combined_source(pid)
    if combined_src:
        # 被组合商品引用：允许拆分，但只能拆「可上数量」（库存 - 在售 - 待出 - 组合预留）内的部分，
        # 否则来源物理库存会低于组合预留，产生超过实物的「幽灵预留」。
        lst_rows = db.execute_query(
            f"SELECT {_listable_sql_expr(materialize_source=False)} FROM [inventory] WHERE id = ? LIMIT 1",
            (pid,),
        )
        listable = int(lst_rows[0][0] or 0) if lst_rows else 0
        if split_qty > listable:
            raise HTTPException(
                status_code=400,
                detail=f"该商品被组合商品引用，拆分数量不能超过可上数量（{listable}）",
            )
    elif split_qty > src_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"拆分数量不能超过当前库存（{src_quantity}）",
        )

    new_owner = data.owner_user_id if data.owner_user_id is not None else src[4]
    new_barcode = f"SPLIT-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

    src_paths = _legacy_paths_from_db_columns(src[11])
    new_paths = [_duplicate_image_file(p) for p in src_paths]
    new_images_json = images_json_from_paths(new_paths)

    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            if split_qty > 0:
                # 事务内复查后再扣减。上面那些校验发生在事务**之外**，而且与这里之间还隔着
                # _duplicate_image_file 的图片复制（文件 IO，可能几十毫秒），窗口足够两个并发
                # 拆分请求同时通过前置校验、各扣一次，把 quantity 扣成负数，或跌破组合预留
                # 产生上面注释要防的「幽灵预留」。出库路径（inventory_stock.py）就是在事务内
                # 重读并复查后才扣减的，这里对齐同一做法。
                if combined_src:
                    cur.execute(
                        f"SELECT {_listable_sql_expr(materialize_source=False)} FROM [inventory] WHERE id = ? LIMIT 1",
                        (pid,),
                    )
                    row_l = cur.fetchone()
                    if int((row_l[0] if row_l else 0) or 0) < split_qty:
                        raise HTTPException(
                            status_code=409,
                            detail="拆分失败：可上数量已被其它操作占用，请刷新后重试",
                        )
                cur.execute(
                    "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? "
                    "WHERE id = ? AND COALESCE(quantity, 0) >= ?",
                    (split_qty, pid, split_qty),
                )
                if cur.rowcount <= 0:
                    raise HTTPException(
                        status_code=409,
                        detail="拆分失败：库存已被其它操作变更，请刷新后重试",
                    )
            # warehouse_id 固定为 NULL（= 默认仓库），不继承来源的货位：拆分同时也是「新到的货
            # 要一个自己的管理番号」的入口，这批货还没上架子，写上来源的货位等于凭空声明它在那儿。
            # 上架后由库存列表的货位内联编辑改成实际货架。
            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty, split_parent_id,
                    description, listing_title, listing_body, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src[0], new_barcode, src[2], src[3], new_owner, None, src[6], split_qty,
                    None, 0, 0, pid,
                    src[8], src[9], src[10],
                    new_images_json,
                ),
            )
            new_id = cur.lastrowid
            db.dialect.commit(conn)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="拆分失败，请稍后重试")

    from ..image_search import enqueue_inventory as _enqueue_image_index
    _enqueue_image_index(new_id)

    # 来源库存已减少，重算来源与新行的可上架（库存 - 在售 - 待出 - 组合预留）
    recompute_listable_quantity([pid, int(new_id)])

    items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return items[0] if items else {"id": new_id}


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
