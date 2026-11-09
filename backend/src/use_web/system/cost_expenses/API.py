# -*- coding: utf-8 -*-
"""成本支出（包材/快递费）管理 API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/cost_expenses
- 完整 URL 示例: GET /mercariV2/src/use_web/cost_expenses/
"""

from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.cost_expenses_crud import (
    create_cost_expense,
    delete_cost_expense,
    list_cost_expenses,
    update_cost_expense,
)

router = APIRouter()

router.add_api_route("", list_cost_expenses, methods=["GET"])
# 订单 / 待办页记包材也走这里：订单页要有「包材」功能（口径见 src/page_access.py）
router.add_api_route(
    "", create_cost_expense, methods=["POST"],
    dependencies=[Depends(require_feature("orders:packaging", "todos:ship", "system/cost-expenses:create"))],
)
router.add_api_route(
    "/{cid}", update_cost_expense, methods=["PUT"],
    dependencies=[Depends(require_feature("system/cost-expenses:edit"))],
)
router.add_api_route(
    "/{cid}", delete_cost_expense, methods=["DELETE"],
    dependencies=[Depends(require_feature("system/cost-expenses:delete"))],
)
