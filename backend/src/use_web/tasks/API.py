# -*- coding: utf-8 -*-
"""任务队列 API 路由（对应前端 /tasks 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/tasks
- 完整 URL 示例:
    GET  /mercariV2/src/use_web/tasks
    GET  /mercariV2/src/use_web/tasks/stats
    POST /mercariV2/src/use_web/tasks/submit
"""
from fastapi import APIRouter

from .units.tasks_handler import (
    cancel_task,
    get_task_detail,
    list_task_types,
    list_tasks_endpoint,
    retry_task,
    submit_task_endpoint,
    task_stats,
)

router = APIRouter()

router.add_api_route("", list_tasks_endpoint, methods=["GET"])
router.add_api_route("/stats", task_stats, methods=["GET"])
router.add_api_route("/types", list_task_types, methods=["GET"])
router.add_api_route("/submit", submit_task_endpoint, methods=["POST"])
router.add_api_route("/{task_id}", get_task_detail, methods=["GET"])
router.add_api_route("/{task_id}/cancel", cancel_task, methods=["POST"])
router.add_api_route("/{task_id}/retry", retry_task, methods=["POST"])
