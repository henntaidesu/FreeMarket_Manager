# -*- coding: utf-8 -*-
"""购入商品列表 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/purchases
- 完整 URL 示例: GET /mercariV2/src/use_web/purchases

同步与单条「获取详情」都没有 HTTP 端点：页面按钮提交任务队列的 ``purchases.sync`` /
``purchases.refresh_one``（见 task_queue/registry.py）——两者都是浏览器自动化。
"""
from fastapi import APIRouter

from .units.purchases_query import (
    get_purchase_messages,
    list_purchase_items,
    list_purchase_states,
)

router = APIRouter()

router.add_api_route("", list_purchase_items, methods=["GET"])
router.add_api_route("/states", list_purchase_states, methods=["GET"])
router.add_api_route("/{item_id}/messages", get_purchase_messages, methods=["GET"])
