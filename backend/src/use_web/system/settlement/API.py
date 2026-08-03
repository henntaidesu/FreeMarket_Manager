# -*- coding: utf-8 -*-
"""结算（按商品归属人分账）API。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/settlement
- 完整 URL 示例: GET /mercariV2/src/use_web/system/settlement/summary
"""

from fastapi import APIRouter

from .units.exchange_rate import get_exchange_rate
from .units.pending_items import (
    create_pending_item,
    delete_pending_item,
    list_pending_items,
)
from .units.settlement_handler import settlement_summary
from .units.settlement_records import (
    delete_settlement,
    list_settled_ranges,
    list_settlements,
    save_settlement,
)
from .units.settlement_resettle import resettle_settlement

router = APIRouter()

router.add_api_route("/summary", settlement_summary, methods=["GET"])
# 结算记录：保存快照 / 已结区间（禁选） / 列表 / 删除
router.add_api_route("/records", save_settlement, methods=["POST"])
router.add_api_route("/records", list_settlements, methods=["GET"])
router.add_api_route("/settled-ranges", list_settled_ranges, methods=["GET"])
router.add_api_route("/records/{rid}", delete_settlement, methods=["DELETE"])
# 重新结算：同区间用最新订单数据重算，与原结算并存并算差额
router.add_api_route("/records/{rid}/resettle", resettle_settlement, methods=["POST"])
# 待结算物品：随时登记，下次结算全部自动带入
router.add_api_route("/pending-items", list_pending_items, methods=["GET"])
router.add_api_route("/pending-items", create_pending_item, methods=["POST"])
router.add_api_route("/pending-items/{pid}", delete_pending_item, methods=["DELETE"])
# 汇率：Google Finance CNY→JPY
router.add_api_route("/exchange-rate", get_exchange_rate, methods=["GET"])
