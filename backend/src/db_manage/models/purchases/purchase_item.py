# -*- coding: utf-8 -*-
"""
购入商品（Mercari マイページ「購入した商品」/mypage/purchases）本地缓存表。

字段与 ``GET api.mercari.jp/v1/orders`` 的 ``orders[]`` 单项对齐：

    {"originId": "2343394901", "createTime": "2026-09-19T07:22:10Z",
     "orderDetail": {"state": "STATE_WAITING_SHIPPING",
                     "lineItems": [{"product": {"originId": "m546…", "displayName": "…",
                                                "thumbnail": "https://…"},
                                    "listingType": "LISTING_TYPE_CONSUMER",
                                    "productVariant": {"variant": "ZOTAC"},
                                    "state": "STATE_WAITING_SHIPPING"}]}}

列表接口**不返回金额**，金额及其余明细来自逐笔打开 ``/transaction/{item_id}``
（买家视角取引画面）时截获的四个接口，写在 ``detail_*`` 之外的那批列里：

- ``transaction_evidences/get``：金额 / 各项运费 / 支付方式 / 卖家ID / 配送方式·负担·时效·発送元
  / ``status``（``wait_shipping``·``wait_review``·``done``）/ 各时间戳。**响应里还带买家本人的
  收货地址（姓名·电话·住址），按要求不入库**，解析时直接丢弃。
- ``items/get``：``seller`` 对象（昵称·头像）——不必单独去打 ``users/get_profile``。
- ``delivery/status``：追踪号 ``denpyo_no`` 与配送状态，**仅已发货后才有**。
- ``reviews/get_by_item``：双向评价，**仅 ``done`` 后才有**。

交易留言不在本表，复用 ``transaction_messages``（``order_no`` = 本表的 ``item_id``）。

一笔购入记录一旦出现就不会从列表里消失（取引完了后仍在），因此这里**不做缺席软删**，
也就没有 ``is_delete``：同步只 upsert，不删除。

**一行 = 一件购入商品，不是一笔订单**：``lineItems`` 是数组，まとめ買い 一笔订单会带
多件商品。抓到的样本（两个账号共 49 笔）全是单件，但只取 ``lineItems[0]`` 会把合并购买
的其余商品悄悄丢掉，所以唯一键是 ``(order_id, item_id)`` 而不是 ``order_id``。
"""

from typing import Any, Dict, List, Optional, Tuple

from ...base_model import BaseModel


# SELECT 列顺序（find_list 用）
_PURCHASE_ITEM_LIST_KEYS: Tuple[str, ...] = (
    "id",
    "order_id",
    "account_id",
    "item_id",
    "item_name",
    "thumbnail",
    "variant",
    "state",
    "listing_type",
    "purchased_at",
    "synced_at",
    "price",
    "paid_price",
    "payment_fee",
    "buyer_shipping_fee",
    "seller_shipping_fee",
    "paid_method",
    "seller_id",
    "seller_name",
    "seller_photo",
    "shipping_method_id",
    "shipping_method_name",
    "shipping_payer_id",
    "shipping_duration_id",
    "shipping_from_area_id",
    "shipping_due_time",
    "tracking_no",
    "delivery_status_name",
    "is_delivered",
    "evidence_status",
    "evidence_created",
    "evidence_updated",
    "status_set_at",
    "review_given_fame",
    "review_given_message",
    "review_given_at",
    "review_received_fame",
    "review_received_message",
    "review_received_at",
    "detail_synced_at",
    "detail_fetch_failures",
)


class PurchaseItemModel(BaseModel):
    """购入商品"""

    @classmethod
    def get_table_name(cls) -> str:
        return "purchase_items"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 煤炉订单号（orders[].originId）。一笔订单可含多件商品，故它本身不唯一，
            # 唯一键是 (order_id, item_id)，见 get_indexes。
            "order_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            # 买入的是哪个本地店铺账号（/v1/orders 的响应里没有买家标识，只能由发起同步的账号确定）
            "account_id": {
                "type": "INTEGER",
                "not_null": True,
                "default": None,
            },
            "item_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "item_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "thumbnail": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # productVariant.variant，多为空串
            "variant": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 原样保存煤炉的枚举名（STATE_WAITING_SHIPPING / STATE_WAITING_BUYER_REVIEW /
            # STATE_COMPLETED / …）。枚举全集未知，前端只对已知值显示中文，未知值原样展示。
            "state": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "listing_type": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # createTime（RFC3339 UTC）转成 epoch 秒
            "purchased_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "synced_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },

            # ── 以下均来自取引画面详情（见模块文档），列表同步不写 ────────────── #
            # 商品成交价；paid_price 是这笔实际走该支付方式的金额
            # （余额支付时为 0，与 price 不是一回事，别拿它当售价）
            "price": {"type": "INTEGER", "not_null": False, "default": None},
            "paid_price": {"type": "INTEGER", "not_null": False, "default": None},
            "payment_fee": {"type": "INTEGER", "not_null": False, "default": None},
            "buyer_shipping_fee": {"type": "INTEGER", "not_null": False, "default": None},
            "seller_shipping_fee": {"type": "INTEGER", "not_null": False, "default": None},
            # card / deferred_payment / funds_paid / …（原样保存）
            "paid_method": {"type": "TEXT", "not_null": False, "default": None},

            "seller_id": {"type": "TEXT", "not_null": False, "default": None},
            "seller_name": {"type": "TEXT", "not_null": False, "default": None},
            "seller_photo": {"type": "TEXT", "not_null": False, "default": None},

            "shipping_method_id": {"type": "INTEGER", "not_null": False, "default": None},
            "shipping_method_name": {"type": "TEXT", "not_null": False, "default": None},
            "shipping_payer_id": {"type": "INTEGER", "not_null": False, "default": None},
            "shipping_duration_id": {"type": "INTEGER", "not_null": False, "default": None},
            "shipping_from_area_id": {"type": "INTEGER", "not_null": False, "default": None},
            "shipping_due_time": {"type": "INTEGER", "not_null": False, "default": None},
            # 追踪号与配送状态：delivery/status，未发货时该接口根本不存在 → 保持 NULL
            "tracking_no": {"type": "TEXT", "not_null": False, "default": None},
            "delivery_status_name": {"type": "TEXT", "not_null": False, "default": None},
            "is_delivered": {"type": "INTEGER", "not_null": False, "default": None},

            # 取引画面自己的状态词（wait_shipping / wait_review / done），与列表的
            # STATE_* 是同一件事的两套词。展示口径仍是 state；这里留原值便于排查。
            "evidence_status": {"type": "TEXT", "not_null": False, "default": None},
            "evidence_created": {"type": "INTEGER", "not_null": False, "default": None},
            "evidence_updated": {"type": "INTEGER", "not_null": False, "default": None},
            "status_set_at": {"type": "INTEGER", "not_null": False, "default": None},

            # 双向评价（given = 我评卖家，received = 卖家评我）
            "review_given_fame": {"type": "TEXT", "not_null": False, "default": None},
            "review_given_message": {"type": "TEXT", "not_null": False, "default": None},
            "review_given_at": {"type": "INTEGER", "not_null": False, "default": None},
            "review_received_fame": {"type": "TEXT", "not_null": False, "default": None},
            "review_received_message": {"type": "TEXT", "not_null": False, "default": None},
            "review_received_at": {"type": "INTEGER", "not_null": False, "default": None},

            # 详情抓取记录。detail_fetch_failures 与待办预抓同一套路：连续失败到上限就
            # 退出候选集，否则一条永远打不开的取引页会拖住每一轮同步。
            "detail_synced_at": {"type": "INTEGER", "not_null": False, "default": None},
            "detail_fetch_failures": {"type": "INTEGER", "not_null": True, "default": 0},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            # 唯一键：一笔订单里的一件商品。**全表只能有这一个唯一索引**——
            # 见 CLAUDE.md「ON CONFLICT 的方言陷阱」，多一个 MySQL 上就会撞错键。
            {
                "name": "uk_purchase_items_order_item",
                "columns": ["order_id", "item_id"],
                "unique": True,
            },
            {"name": "idx_purchase_items_account", "columns": ["account_id"]},
            {"name": "idx_purchase_items_purchased", "columns": ["purchased_at"]},
            {"name": "idx_purchase_items_state", "columns": ["state"]},
        ]

    @classmethod
    def _build_filter(
        cls,
        keyword: Optional[str] = None,
        account_id: Optional[int] = None,
        state: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        sql = " FROM [purchase_items] t WHERE 1=1 "
        params: List[Any] = []
        if keyword is not None and str(keyword).strip():
            kw = f"%{str(keyword).strip()}%"
            sql += (
                " AND (IFNULL(t.item_name, '') LIKE ?"
                " OR IFNULL(t.item_id, '') LIKE ?"
                " OR IFNULL(t.order_id, '') LIKE ?)"
            )
            params.extend([kw, kw, kw])
        if account_id is not None:
            sql += " AND t.account_id = ?"
            params.append(int(account_id))
        if state is not None and str(state).strip():
            sql += " AND t.state = ?"
            params.append(str(state).strip())
        return sql, params

    @classmethod
    def find_list(
        cls,
        keyword: Optional[str] = None,
        account_id: Optional[int] = None,
        state: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql, params = cls._build_filter(
            keyword=keyword, account_id=account_id, state=state
        )
        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
        offset = (page - 1) * page_size
        keys = list(_PURCHASE_ITEM_LIST_KEYS)
        sel = f"""
            SELECT {', '.join('t.' + k for k in keys)}
            {base_sql}
            ORDER BY COALESCE(t.purchased_at, 0) DESC, t.id DESC
            LIMIT ? OFFSET ?
        """
        rows = db.execute_query(sel, tuple(params + [page_size, offset]))
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [dict(zip(keys, row)) for row in rows],
        }

    @classmethod
    def find_detail_candidates(
        cls,
        account_id: int,
        *,
        max_failures: int = 3,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """需要（重新）抓取取引详情的行。

        两类：**从未抓过**（``detail_synced_at`` 为空）与**尚未完成**（``state`` 不是
        ``STATE_COMPLETED``）——后者的状态、追踪号、评价都还会变。已完成且抓过的不再碰，
        所以稳态成本只随未完成笔数走，不随总笔数走。

        ``detail_fetch_failures`` 到上限即退出候选集：一条永远打不开的取引页
        （例如被取消后的拦截页）否则会拖住每一轮同步。手动单条抓取不受此限。
        """
        db = cls().db
        sql = (
            "SELECT [item_id], [order_id], [state], [detail_synced_at], [detail_fetch_failures] "
            "FROM [purchase_items] "
            "WHERE [account_id] = ? "
            "  AND COALESCE([detail_fetch_failures], 0) < ? "
            "  AND ([detail_synced_at] IS NULL "
            "       OR COALESCE([state], '') <> 'STATE_COMPLETED') "
            "ORDER BY COALESCE([purchased_at], 0) DESC, [id] DESC"
        )
        params: List[Any] = [int(account_id), int(max_failures)]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = db.execute_query(sql, tuple(params))
        keys = ("item_id", "order_id", "state", "detail_synced_at", "detail_fetch_failures")
        return [dict(zip(keys, r)) for r in rows]

    @classmethod
    def existing_order_ids(cls, account_id: int) -> set:
        """该账号已入库的订单号集合——翻页时用来判断「这一页全是旧数据，可以停了」。"""
        rows = cls().db.execute_query(
            "SELECT [order_id] FROM [purchase_items] WHERE [account_id] = ?",
            (int(account_id),),
        )
        return {str(r[0] or "").strip() for r in rows if str(r[0] or "").strip()}
