# -*- coding: utf-8 -*-
"""库存图片搜索（DINOv2 特征向量检索）。

公开 API：
- image_search / image_search_status：FastAPI 端点（注册见 inventory/API.py）
- start_indexer：后台索引线程（lifecycle 启动时调用）
- enqueue_inventory：库存图片变更钩子（CRUD 后调用，异步增量更新索引）
"""

from .indexer import start_indexer, enqueue_inventory
from .search_handler import image_search, image_search_status

__all__ = [
    "start_indexer",
    "enqueue_inventory",
    "image_search",
    "image_search_status",
]
