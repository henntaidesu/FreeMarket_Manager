# -*- coding: utf-8 -*-
"""购入商品列表 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/purchases
- 完整 URL 示例: GET /mercariV2/src/use_web/purchases

同步与单条「获取详情」都没有 HTTP 端点：页面按钮提交任务队列的 ``purchases.sync`` /
``purchases.refresh_one``（见 task_queue/registry.py）——两者都是浏览器自动化。

代购结算（``/stats`` 与 ``/settlement``）是纯本地读写，不碰浏览器，所以走普通 HTTP。
它与「出售结算」``use_web/system/settlement`` 是两套账，互不引用。

``/{item_id}/tracking`` 同理走普通 HTTP：它直连黑猫 / 邮局的**公开**查询页，
一次 ``requests`` 就完事，既不需要登录态也不需要浏览器（见 ``src/delivery_tracking``）。
"""
from fastapi import APIRouter

from .units.purchases_query import (
    get_purchase_messages,
    list_purchase_items,
    list_purchase_states,
    purchase_stats,
)
from .units.purchases_settlement import (
    update_purchase_settlement,
    update_purchase_settlement_by_filter,
)
from .units.purchases_tracking import get_purchase_tracking

router = APIRouter()

router.add_api_route("", list_purchase_items, methods=["GET"])
# 代购结算汇总：跟随列表的筛选条件，不受分页影响（口径见 purchases_query.purchase_stats）
router.add_api_route("/stats", purchase_stats, methods=["GET"])
router.add_api_route("/states", list_purchase_states, methods=["GET"])
# 代购结算：批量（含单条）标记结算状态 / 归属人
router.add_api_route("/settlement", update_purchase_settlement, methods=["POST"])
# 同一件事的另一种选行方式：按筛选条件整批改（购入结算页的「标记已结算」）
router.add_api_route(
    "/settlement/by-filter", update_purchase_settlement_by_filter, methods=["POST"]
)
router.add_api_route("/{item_id}/messages", get_purchase_messages, methods=["GET"])
# 配送履历：直连黑猫 / 邮局的公开查询页，不开浏览器也不入队，所以走普通 HTTP
# （见 units/purchases_tracking.py 与 src/delivery_tracking/）
router.add_api_route("/{item_id}/tracking", get_purchase_tracking, methods=["GET"])
