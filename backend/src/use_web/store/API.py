# -*- coding: utf-8 -*-
"""对外商城 API 模块（对应独立前端 /store）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/store
- 完整 URL 示例: GET /mercariV2/src/use_web/store/items

只导出 ``public_router``：商城是给未登录的访客看的，整组端点都在 require_auth 之外。
故意**没有** ``router``（需认证的那一半）—— 商城只读，没有任何需要登录才能做的事；
留一个空的 router 只会诱导后来者往里加需要鉴权的端点，而那类端点属于管理端页面。
"""
from fastapi import APIRouter

from .units.store_query import list_store_items, get_store_item, store_filters

public_router = APIRouter()

# 筛选项须在 /items/{pid} 之前注册（此处无冲突，但与站内其余路由保持同一写法）
public_router.add_api_route("/filters", store_filters, methods=["GET"])
public_router.add_api_route("/items", list_store_items, methods=["GET"])
public_router.add_api_route("/items/{pid}", get_store_item, methods=["GET"])
