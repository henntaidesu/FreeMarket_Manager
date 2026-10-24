# -*- coding: utf-8 -*-
"""
成本记录表模型
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from ...base_model import BaseModel
from .warehouse import WarehouseModel


def parse_ship_sizes(raw) -> List[str]:
    """ship_sizes 列（JSON 数组字符串）→ 去空去重后的尺寸名列表；坏值按未关联处理。"""
    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    if not isinstance(vals, list):
        return []
    out: List[str] = []
    for v in vals:
        name = str(v or '').strip()
        if name and name not in out:
            out.append(name)
    return out


class CostRecordModel(BaseModel):
    """成本记录表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "cost_records"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'cost_date': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'item_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'item_image': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'amount': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 1,
            },
            'warehouse_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 关联的发货尺寸名（JSON 数组，如 ["ゆうパケットポストmini"]）。发货向导选定尺寸后
            # 只列出关联了该尺寸的包材；某尺寸只关联一种包材时直接选定、跳过包材页。
            'ship_sizes': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'operator': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'管理员'",
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
            {'name': 'idx_cost_records_date', 'columns': ['cost_date']},
            {'name': 'idx_cost_records_type', 'columns': ['type']},
            {'name': 'idx_cost_records_warehouse', 'columns': ['warehouse_id']},
            # 包材按名称取最新行（_find_packaging_item_latest）：type+item_name 过滤 + cost_date 排序
            {'name': 'idx_cost_records_type_item_date', 'columns': ['type', 'item_name', 'cost_date']},
        ]

    @classmethod
    def find_detail_list(
        cls,
        cost_type: Optional[str] = None,
        warehouse_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql = """
            FROM [cost_records] c
            LEFT JOIN [warehouses] w ON w.id = c.warehouse_id
            WHERE 1=1
        """
        params = []

        if cost_type:
            base_sql += " AND c.type = ?"
            params.append(cost_type)
        if warehouse_id:
            base_sql += " AND c.warehouse_id = ?"
            params.append(warehouse_id)
        if start_date:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, tzinfo=timezone.utc
            )
            base_sql += " AND c.cost_date >= ?"
            params.append(int(dt_start.timestamp()))
        if end_date:
            dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            base_sql += " AND c.cost_date <= ?"
            params.append(int(dt_end.timestamp()))

        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]

        wh_l = WarehouseModel.sql_display_label("w")
        select_sql = f"""
            SELECT c.id, c.cost_date, c.type, c.item_name, c.item_image, c.amount, c.quantity, c.warehouse_id, {wh_l} as warehouse_name,
                   c.ship_sizes, c.remark, c.operator, c.created_at
            {base_sql}
            ORDER BY c.cost_date DESC, c.id DESC
            LIMIT ? OFFSET ?
        """
        query_params = params + [page_size, (page - 1) * page_size]
        rows = db.execute_query(select_sql, tuple(query_params))

        keys = ['id', 'cost_date', 'type', 'item_name', 'item_image', 'amount', 'quantity', 'warehouse_id', 'warehouse_name', 'ship_sizes', 'remark', 'operator', 'created_at']
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [
                {**d, 'ship_sizes': parse_ship_sizes(d.get('ship_sizes'))}
                for d in (dict(zip(keys, row)) for row in rows)
            ],
        }
