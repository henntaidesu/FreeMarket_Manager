# -*- coding: utf-8 -*-
"""控制台 API 路由（对应前端 /dashboard 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/dashboard
- 完整 URL 示例:
    GET /mercariV2/src/use_web/dashboard/summary
"""
from fastapi import APIRouter

from .units.summary import dashboard_summary

router = APIRouter()

router.add_api_route("/summary", dashboard_summary, methods=["GET"])
