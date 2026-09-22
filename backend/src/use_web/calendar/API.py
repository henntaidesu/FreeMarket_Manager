# -*- coding: utf-8 -*-
"""日历 API 路由（对应前端 /system/calendar 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/calendar
- 完整 URL 示例:
    GET    /mercariV2/src/use_web/calendar/events?start=...&end=...
    GET    /mercariV2/src/use_web/calendar/pending-count
    POST   /mercariV2/src/use_web/calendar/events
    PUT    /mercariV2/src/use_web/calendar/events/{eid}
    DELETE /mercariV2/src/use_web/calendar/events/{eid}
"""

from fastapi import APIRouter

from .units.calendar_handler import (
    create_event,
    delete_event,
    list_events,
    pending_count,
    update_event,
)

router = APIRouter()

router.add_api_route("/events", list_events, methods=["GET"])
router.add_api_route("/pending-count", pending_count, methods=["GET"])
router.add_api_route("/events", create_event, methods=["POST"])
router.add_api_route("/events/{eid}", update_event, methods=["PUT"])
router.add_api_route("/events/{eid}", delete_event, methods=["DELETE"])
