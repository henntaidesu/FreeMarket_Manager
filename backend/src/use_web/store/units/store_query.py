# -*- coding: utf-8 -*-
"""对外商城（/store）的只读查询：商品列表 / 商品详情 / 筛选项。

这是全站唯一一组**既不需要登录、又返回业务数据**的接口（另外两个公开端点只回图片字节），
所以有三条规矩贯穿本文件，加字段前先读：

1. **字段是白名单挑出来的，不是把库存行整行发出去。** inventory 一行里同时带着条码、SKU、
   货架位置、归属人、煤炉商品 ID 和内部备注 —— 对买家既无用又不该外泄。下面每个 SELECT 都
   只列 ``_CARD_SELECT`` 里那几列；新增一列前先问「这句话可以印在商品页上吗」。
   ``description`` 是内部备注，``listing_body`` 是已经发布在市集上的公开正文 —— 只放后者。

2. **关键词不按管理番号 / 暗号检索。** 库存页那条 ``p.id = ?`` 与 ``decode_mgmt_id_cipher``
   分支是内部查号用的，对外开放等于把「输入暗号即可定位任意一件库存」送出去。这里只搜名称。

3. **每个处理器自己调 check_public_rate_limit。** 见 rate_limit.py 模块注释：公开端点要为
   自己让服务端干的活计费，这里是 DB 查询。

在售口径直接复用库存页那一份 —— 可上架 = max(0, 库存 - 在售 - 待出 - 组合预留 - 出品预扣减)，
取自 ``inventory_helpers.inventory_listable_sql_expr()``，配 ``cr`` 派生表 LEFT JOIN。
该表达式引用 ``cr.reserved``，而 ``_combined_reserved_agg_subquery`` 从不把 inventory 包进
外层派生表，天然是 SELECT 安全的（见 CLAUDE.md 里 ``materialize_source`` 那条 MySQL 陷阱：
SELECT 场景一旦物化，JSON_TABLE 会收到 combined_items 为 NULL 的行并报 1210）。

商城**只读**：不下单、不扣库存，所以它不是第六个扣减项，三处重算可上架的口径一个都不用动。
"""
from typing import Optional

from fastapi import HTTPException, Request

from ....db_manage.database import DatabaseManager
from ....rate_limit import check_public_rate_limit
from ....use_mercari.inventory_counters import _combined_reserved_agg_subquery
from ....use_mercari.mgmt_id_cipher import is_cipher_mgmt_line
from ...inventory.units.inventory_helpers import (
    _paths_from_images_json,
    inventory_listable_sql_expr,
)

db = DatabaseManager()

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 60

#: 允许的排序 → ORDER BY 片段。排序参数是唯一会进入 ORDER BY 的用户输入，
#: 不在表里的值一律回落默认，绝不拼进 SQL（与 inventory_query._SORTABLE_COLUMNS 同做法）。
_SORT_EXPRS = {
    "newest": "p.id DESC",
    "price_asc": "COALESCE(p.price, 0) ASC, p.id DESC",
    "price_desc": "COALESCE(p.price, 0) DESC, p.id DESC",
}

#: 对外可见列白名单。顺序即下方 _row_to_card 的取值顺序。
_CARD_SELECT = (
    "p.id, p.name, p.listing_title, p.price, p.images_json, p.listing_status, "
    "c.name, ptcm.product_type"
)


def _from_where(where_extra: str = "") -> str:
    """列表 / 计数 / 筛选项共用的 FROM + WHERE。

    计数也必须带上这一整套 JOIN：可上架表达式引用 ``cr.reserved``，少了派生表就不是同一个
    条件，total 会和实际能翻到的页数对不上。
    """
    return f"""
        FROM [inventory] p
        LEFT JOIN [categories] c ON c.id = p.category_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        LEFT JOIN {_combined_reserved_agg_subquery()} cr ON cr.src_id = p.id
        WHERE COALESCE(p.is_delete, 0) = 0 AND {inventory_listable_sql_expr()} > 0
        {where_extra}
    """


def _build_filters(
    keyword: Optional[str],
    category_id: Optional[int],
    product_type_id: Optional[int],
) -> tuple:
    parts: list = []
    params: list = []
    kw = (keyword or "").strip()
    if kw:
        # 只搜商品名与出品标题，不搜管理番号 / 暗号（见模块注释第 2 条）
        parts.append("AND (p.name LIKE ? OR p.listing_title LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    if category_id:
        parts.append("AND p.category_id = ?")
        params.append(int(category_id))
    if product_type_id:
        parts.append("AND p.product_type_id = ?")
        params.append(int(product_type_id))
    return " ".join(parts), params


def _display_name(name, listing_title, pid) -> str:
    """商品名优先，退到出品标题，再退到管理番号 —— 商品卡上不能出现空标题。"""
    for v in (name, listing_title):
        s = str(v or "").strip()
        if s:
            return s
    return f"商品 {pid}"


#: 剥离暗号时两种模式都要试。/x9 换过模式以后，早先上架的商品说明里留的仍是旧字符集，
#: 只按 get_cipher_mode() 的当前模式判断会漏掉它们。
_CIPHER_MODES = ("base5", "binary")


def _strip_mgmt_cipher_tail(text) -> Optional[str]:
    """去掉商品说明最末尾的管理番号暗号行。

    ``listing_body`` 是直接发在市集上的正文，末行是 ``-=~<>`` / ``◇◆`` 编码的管理番号
    （见 use_mercari/mgmt_id_cipher）。它在市集页面上本来就是公开的，所以这不算新增泄露；
    但印在自家商品页上纯粹是一串看不懂的符号，而且等于把「本店商品 ↔ 库存行」的对照表
    整整齐齐地摆出来。两个理由都指向同一件事：展示前摘掉。

    代价：一行只由 ``-`` 组成的分隔线（``-----``）也是合法的五进制 token，会被一并摘掉。
    这与真正的绑定解析 ``parse_trailing_cipher_mgmt_tokens`` 是同一个歧义，且只影响末行的
    装饰性分隔线，不值得为它再引一套启发式。
    """
    s = str(text or "")
    if not s.strip():
        return None
    lines = s.splitlines()
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()          # 暗号行之上通常还有空行，一并收掉
            continue
        if any(is_cipher_mgmt_line(last, mode=m) for m in _CIPHER_MODES):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip() or None


def _row_to_card(row: tuple) -> dict:
    """列表行 → 商品卡。row 尾列是可上架数量（即对外可售数）。"""
    return {
        "id": int(row[0]),
        "name": _display_name(row[1], row[2], row[0]),
        "price": int(row[3] or 0),
        "images": _paths_from_images_json(row[4]),
        "condition": (row[5] or "").strip() or None,
        "category_name": (row[6] or "").strip() or None,
        "product_type_name": (row[7] or "").strip() or None,
        "stock": int(row[-1] or 0),
    }


def list_store_items(
    request: Request,
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    product_type_id: Optional[int] = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
):
    """商城商品列表。信封与站内其余列表一致：``{items,total,page,page_size}``。"""
    check_public_rate_limit(request)

    where_extra, params = _build_filters(keyword, category_id, product_type_id)
    from_where = _from_where(where_extra)

    total_rows = db.execute_query(f"SELECT COUNT(*) {from_where}", tuple(params))
    total = int(total_rows[0][0] or 0) if total_rows else 0

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    order_sql = _SORT_EXPRS.get((sort or "").strip(), _SORT_EXPRS["newest"])

    rows = db.execute_query(
        f"SELECT {_CARD_SELECT}, {inventory_listable_sql_expr()} AS stock "
        f"{from_where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        tuple(params) + (page_size, (page - 1) * page_size),
    )
    return {
        "items": [_row_to_card(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_store_item(request: Request, pid: int):
    """商品详情。

    条件与列表完全一致（含可上架 > 0）：售罄或被删的商品直接 404，而不是渲染一个
    「库存 0」的页面 —— 目录对外的承诺就是「列出来的都还能买」，两处口径必须同一个。
    """
    check_public_rate_limit(request)

    rows = db.execute_query(
        f"SELECT {_CARD_SELECT}, p.listing_body, p.created_at, "
        f"{inventory_listable_sql_expr()} AS stock "
        f"{_from_where('AND p.id = ?')}",
        (int(pid),),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="商品不存在或已售罄")

    row = rows[0]
    item = _row_to_card(row)
    item["body"] = _strip_mgmt_cipher_tail(row[8])
    item["created_at"] = row[9]
    return item


def store_filters(request: Request):
    """筛选项：只列出目录里**真实存在**的分类与商品类型。

    直接读全表会把只存在于已售罄/未上架商品上的分类也列出来，选了就是空结果页。
    """
    check_public_rate_limit(request)
    from_where = _from_where()

    cat_rows = db.execute_query(
        f"SELECT DISTINCT p.category_id, c.name {from_where} "
        "AND p.category_id IS NOT NULL AND TRIM(COALESCE(c.name, '')) != '' "
        "ORDER BY c.name"
    )
    type_rows = db.execute_query(
        f"SELECT DISTINCT p.product_type_id, ptcm.product_type {from_where} "
        "AND p.product_type_id IS NOT NULL AND TRIM(COALESCE(ptcm.product_type, '')) != '' "
        "ORDER BY ptcm.product_type"
    )
    return {
        "categories": [{"id": int(r[0]), "name": r[1]} for r in cat_rows],
        "product_types": [{"id": int(r[0]), "name": r[1]} for r in type_rows],
    }
