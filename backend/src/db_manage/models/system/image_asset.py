# -*- coding: utf-8 -*-
"""图片资产映射表 [image_assets]：``/imges/<文件名>`` → 这张图实际存在哪儿。

**为什么是映射表而不是改写路径。**
商品图路径以 ``/imges/xxx.jpg`` 字符串的形式散落在 7 个业务列里
（``inventory.images_json`` / ``memos.images_json`` / ``transaction_messages.images_json``
三个还嵌在 JSON 数组中，另有 ``image_embeddings.image_path``、``todo_items.qr_image_path``、
``todo_items.ship_qr_photo_path``、``shop_accounts.avatar``），后端约二十处、前端五个页面都在用
``startswith('/imges/')`` 判断「这是不是本地图」。切到图床时若把这些值改写成图床绝对 URL，
等于要同时改动所有这些判断点，且一旦想切回本地就得再全部改回去——没有回滚路径。

所以 ``/imges/<文件名>`` 始终是**逻辑标识**，任何地方都不变；这张表只回答
「这个标识对应的字节现在放在哪」。切换存储后端 = 换一个解析结果，业务列一个字节都不动。

只有落在图床上的图片才在这里有行。查不到 = 本地文件，按老路径读盘。这带来一个重要性质：
迁移途中失败的那些图片没有行、继续走本地，页面不会因为迁移没跑完就出现一堆裂图。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class ImageAssetModel(BaseModel):
    """一行 = 一张已经放到图床上的图片。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "image_assets"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 逻辑标识：``/imges/xxx.jpg``，与业务列里存的值逐字节相同
            "rel_path": {
                "type": "TEXT",
                "not_null": True,
                "unique": True,
                "max_length": 500,
            },
            # 'remote' = 在图床上。留下这一列而不是「有行即远程」，是为了将来能再加别的后端，
            # 也方便用一条 UPDATE 把某批图片标回本地而不必删行（保留 sha256 等溯源信息）。
            "backend": {
                "type": "TEXT",
                "not_null": True,
                "default": "'remote'",
                "max_length": 20,
            },
            # 图床项目 slug + 图床给出的存储名。删除远程图片、重建 URL 都要用这两个。
            "remote_slug": {"type": "TEXT", "not_null": False, "default": None, "max_length": 120},
            "remote_name": {"type": "TEXT", "not_null": False, "default": None, "max_length": 200},
            # 完整公开 URL。缓存下来是为了读路径时不必每次拼接，也保留了「当时用的基地址」，
            # 万一图床换域名，能一眼看出哪些行是旧域名生成的。
            "remote_url": {"type": "TEXT", "not_null": False, "default": None, "max_length": 1000},
            "size": {"type": "INTEGER", "not_null": False, "default": 0},
            "sha256": {"type": "TEXT", "not_null": False, "default": None, "max_length": 64},
            "created_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": "CURRENT_TIMESTAMP",
            },
            "migrated_at": {"type": "DATETIME", "not_null": False, "default": None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_image_assets_rel_path", "columns": ["rel_path"], "unique": True},
            {"name": "idx_image_assets_backend", "columns": ["backend"], "unique": False},
        ]
