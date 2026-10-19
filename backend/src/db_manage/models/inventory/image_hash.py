# -*- coding: utf-8 -*-
"""
商品图片内容哈希缓存（条码识别 · 疑似借用背面图 / 整套图片相同的判定）

每行对应一张图（``/imges/xxx`` 逻辑路径）。上传的文件名本身唯一、内容不会被改写，所以按路径缓存
的哈希永远有效。``barcodes`` 是这张图里识别出的条码（JSON 数组），NULL = 还没识别过——
只对被多件商品共用的图才识别，见 inventory_barcode/image_dupes.py。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class ImageHashModel(BaseModel):
    """图片内容哈希表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_image_hashes"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            # 商品图路径，如 /imges/xxx.jpg（与 inventory.images_json 中的值一致）
            'image_path': {
                'type': 'TEXT',
                'not_null': True,
                'max_length': 255,
            },
            # 文件内容 MD5（复制商品 / 重复上传同一张照片 → 字节相同）
            'md5': {
                'type': 'TEXT',
                'not_null': True,
                'max_length': 32,
            },
            # 图里识别出的条码 JSON 数组；NULL = 未识别
            'barcodes': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_image_hashes_path', 'columns': ['image_path'], 'unique': True},
            {'name': 'idx_inventory_image_hashes_md5', 'columns': ['md5']},
        ]
