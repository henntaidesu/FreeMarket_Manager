# -*- coding: utf-8 -*-
"""
店铺账号表模型（煤炉 / 雅虎共用一张表，按 platform 列区分）。
HTTP 请求头以 JSON 形式存放在 value 列。
"""

import json
from typing import Dict, Any, List, Optional
from ...base_model import BaseModel


class ShopAccountModel(BaseModel):
    """店铺账号"""

    #: 改名前的表名。页面从「煤炉账号」改叫「店铺账号」后表也跟着改，
    #: 但**不自动改**（由使用者手动 RENAME），这里只留作启动自检的比对基准，
    #: 见 db_manager.initialize_database 里的 _assert_shop_accounts_renamed。
    LEGACY_TABLE_NAME = "mercari_accounts"

    @classmethod
    def get_table_name(cls) -> str:
        return "shop_accounts"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'account_name': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            # 所属市集平台：'mercari'（煤炉，默认）/ 'yahoo'（Yahoo!フリマ）。
            # 统一账号表按平台区分；历史数据经 ensure_table_exists 自动补列并回填 'mercari'。
            'platform': {
                'type': 'TEXT',
                'not_null': True,
                'default': "'mercari'",
            },
            'login_id': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'seller_id': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 卖家头像 URL（获取卖家 ID 时一并从出品一覧页解析）
            'avatar': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'login_password': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'status': {
                'type': 'TEXT',
                'not_null': True,
                'default': "'active'",
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'value': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 自动数据获取：0 关闭，1 开启
            'is_open': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 抓取间隔：15 / 30 / 60(1h) / 3h / 6h 等（见 mercari_accounts.ALLOWED_FETCH_INTERVALS）
            'fetch_interval': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 上次自动拉取成功时间（UTC ISO），供后台定时任务节流
            'auto_fetch_last_at': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 自动同步子任务（与订单页 / 在售页 / 待办页 / 通知页按钮对应）；总开关仍为 is_open + fetch_interval
            'auto_fetch_order_list': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'auto_fetch_on_sale': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 待办事项页「从煤炉同步」对应的自动开关
            'auto_fetch_todos': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 通知页「从煤炉同步」对应的自动开关
            'auto_fetch_notifications': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 每个同步项独立的抓取间隔（非空即视为开启该项；为空=关闭）。
            # 取值见 shop_accounts_models.normalize_interval：预设 15/30/60/3h/6h，或自定义 "<分钟>" / "<小时>h"。
            'auto_fetch_order_list_interval': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_on_sale_interval': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_todos_interval': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_notifications_interval': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 每个同步项独立的上次成功时间（UTC ISO），供后台定时任务按项节流
            'auto_fetch_order_list_last_at': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_on_sale_last_at': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_todos_last_at': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'auto_fetch_notifications_last_at': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 自动上架（售出即补挂）账号级开关：1=本账号售出订单触发补挂（需配合订单更新列表 + 商品单品开关）
            'auto_fetch_relist': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 不进行获取时间段（本地时间 24 小时制 "HH:MM"）；两个字段均非空时启用，
            # 当 start == end 表示无效（视为不暂停）；start > end 跨日（如 22:00 → 08:00）
            'pause_start_time': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'pause_end_time': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
        }

    @classmethod
    def ensure_table_exists(cls) -> bool:
        cls._migrate_legacy_meilu_table_name()
        ok = super().ensure_table_exists()
        if ok:
            cls._migrate_login_password_json_to_value()
            cls._migrate_auto_fetch_task_defaults()
            cls._migrate_per_task_intervals()
            if hasattr(cls, '_cached_table_columns'):
                delattr(cls, '_cached_table_columns')
        return ok

    @classmethod
    def _migrate_legacy_meilu_table_name(cls) -> None:
        """重命名旧表 meilu_accounts → mercari_accounts（仅在新表不存在且旧表存在时执行）。"""
        db = cls().db
        new_name = cls.get_table_name()
        legacy_name = 'meilu_accounts'
        if new_name == legacy_name:
            return
        try:
            if db.table_exists(new_name):
                return
            if not db.table_exists(legacy_name):
                return
            db.execute_update(f"ALTER TABLE [{legacy_name}] RENAME TO [{new_name}]", ())
            print(f"[mercari_accounts] 已将旧表 {legacy_name} 重命名为 {new_name}")
            for idx in cls.get_indexes():
                idx_name = idx.get('name')
                if not idx_name:
                    continue
                legacy_idx = idx_name.replace('mercari_accounts', 'meilu_accounts')
                if legacy_idx == idx_name:
                    continue
                try:
                    db.execute_update(f"DROP INDEX IF EXISTS [{legacy_idx}]", ())
                except Exception:
                    pass
        except Exception as e:
            print(f"[mercari_accounts] 旧表 meilu_accounts 迁移失败: {e}")

    @classmethod
    def _migrate_auto_fetch_task_defaults(cls) -> None:
        """旧数据 is_open=1 且子任务全 0 时，视为「订单列表 + 在售」默认开启（与升级前行为一致）。"""
        db = cls().db
        table = cls.get_table_name()
        if not db.table_exists(table):
            return
        names = {c['name'] for c in db.get_table_columns(table)}
        for col in ('auto_fetch_order_list', 'auto_fetch_on_sale'):
            if col not in names:
                return
        try:
            db.execute_update(
                f"""
                UPDATE [{table}]
                SET [auto_fetch_order_list] = 1,
                    [auto_fetch_on_sale] = 1
                WHERE [is_open] = 1
                  AND IFNULL([auto_fetch_order_list], 0) = 0
                  AND IFNULL([auto_fetch_on_sale], 0) = 0
                  AND IFNULL([auto_fetch_todos], 0) = 0
                  AND IFNULL([auto_fetch_notifications], 0) = 0
                """,
                (),
            )
        except Exception as e:
            print(f"[mercari_accounts] auto_fetch 子任务默认迁移跳过: {e}")

    @classmethod
    def _migrate_per_task_intervals(cls) -> None:
        """旧版「总开关 is_open + 单一 fetch_interval」迁移为「每项独立间隔」。

        对历史数据：is_open=1 且某子任务已开启(=1) 且 fetch_interval 非空时，
        把该共享间隔回填进对应的 *_interval 列（仅当目标列尚为空，幂等可重复执行）。
        """
        db = cls().db
        table = cls.get_table_name()
        if not db.table_exists(table):
            return
        names = {c['name'] for c in db.get_table_columns(table)}
        pairs = (
            ('auto_fetch_order_list', 'auto_fetch_order_list_interval'),
            ('auto_fetch_on_sale', 'auto_fetch_on_sale_interval'),
            ('auto_fetch_todos', 'auto_fetch_todos_interval'),
            ('auto_fetch_notifications', 'auto_fetch_notifications_interval'),
        )
        if 'fetch_interval' not in names or 'is_open' not in names:
            return
        for flag_col, iv_col in pairs:
            if flag_col not in names or iv_col not in names:
                continue
            try:
                db.execute_update(
                    f"""
                    UPDATE [{table}]
                    SET [{iv_col}] = [fetch_interval]
                    WHERE [is_open] = 1
                      AND IFNULL([{flag_col}], 0) = 1
                      AND [fetch_interval] IS NOT NULL AND TRIM([fetch_interval]) != ''
                      AND ([{iv_col}] IS NULL OR TRIM([{iv_col}]) = '')
                    """,
                    (),
                )
            except Exception as e:
                print(f"[mercari_accounts] 每项间隔迁移跳过({iv_col}): {e}")

    @classmethod
    def _migrate_login_password_json_to_value(cls) -> None:
        """旧版把请求头 JSON 存在 login_password；value 列为空时尝试迁移。"""
        db = cls().db
        table = cls.get_table_name()
        if not db.table_exists(table):
            return
        names = {c['name'] for c in db.get_table_columns(table)}
        if 'value' not in names or 'login_password' not in names:
            return
        try:
            db.execute_update(
                f"""
                UPDATE [{table}]
                SET [value] = [login_password]
                WHERE ([value] IS NULL OR TRIM([value]) = '')
                  AND [login_password] IS NOT NULL AND TRIM([login_password]) != ''
                  AND TRIM([login_password]) LIKE '{{%'
                """,
                (),
            )
        except Exception as e:
            print(f"[mercari_accounts] login_password -> value 迁移跳过: {e}")

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_mercari_accounts_name', 'columns': ['account_name']},
            {'name': 'idx_mercari_accounts_login', 'columns': ['login_id']},
            {'name': 'idx_mercari_accounts_seller_id', 'columns': ['seller_id']},
            {'name': 'idx_mercari_accounts_status', 'columns': ['status']},
            {'name': 'idx_mercari_accounts_platform', 'columns': ['platform']},
        ]

    @classmethod
    def find_detail_list(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql = f"FROM [{cls.get_table_name()}] m WHERE 1=1"
        params = []
        if keyword:
            base_sql += " AND (m.account_name LIKE ? OR m.login_id LIKE ?)"
            kw = f"%{keyword}%"
            params += [kw, kw]
        if status:
            base_sql += " AND m.status = ?"
            params.append(status)

        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
        select_sql = f"""
            SELECT m.id, m.account_name, m.platform, m.login_id, m.seller_id, m.avatar, m.login_password, m.status, m.remark, m.[value], m.is_open, m.fetch_interval, m.auto_fetch_last_at, m.auto_fetch_order_list, m.auto_fetch_on_sale, m.auto_fetch_todos, m.auto_fetch_notifications, m.auto_fetch_order_list_interval, m.auto_fetch_on_sale_interval, m.auto_fetch_todos_interval, m.auto_fetch_notifications_interval, m.auto_fetch_relist, m.pause_start_time, m.pause_end_time
            {base_sql}
            ORDER BY m.id ASC
            LIMIT ? OFFSET ?
        """
        keys = ['id', 'account_name', 'platform', 'login_id', 'seller_id', 'avatar', 'login_password', 'status', 'remark', 'value', 'is_open', 'fetch_interval', 'auto_fetch_last_at', 'auto_fetch_order_list', 'auto_fetch_on_sale', 'auto_fetch_todos', 'auto_fetch_notifications', 'auto_fetch_order_list_interval', 'auto_fetch_on_sale_interval', 'auto_fetch_todos_interval', 'auto_fetch_notifications_interval', 'auto_fetch_relist', 'pause_start_time', 'pause_end_time']
        rows = db.execute_query(select_sql, tuple(params + [page_size, (page - 1) * page_size]))
        # 各账号当前在售件数：与看板同口径（未软删 + status='on_sale'），
        # 按 (平台, 卖家ID) 归属——on_sale_items 没有 account_id 列，seller_id 才是账号锚点。
        on_sale_by_seller: Dict[tuple, int] = {}
        for pf, sid, cnt in db.execute_query(
            "SELECT COALESCE([platform], 'mercari'), [seller_id], COUNT(*) FROM [on_sale_items] "
            "WHERE COALESCE([is_delete], 0) = 0 AND [status] = 'on_sale' "
            "GROUP BY COALESCE([platform], 'mercari'), [seller_id]"
        ):
            on_sale_by_seller[(str(pf or 'mercari'), str(sid or '').strip())] = int(cnt or 0)
        items = []
        for row in rows:
            d = dict(zip(keys, row))
            d.pop('login_password', None)
            d['platform'] = (d.get('platform') or 'mercari')
            raw = d.pop('value', None)
            # 不向客户端返回请求头/令牌明文（Authorization、DPoP、Cookie 等），仅返回
            # 是否已配置的布尔标记（与 _item_api_dict 同款处理，防止令牌泄露被冒充卖家）
            _hv = cls._parse_value_json(raw) or {}
            d['value_set'] = bool(_hv)
            d['authorization_set'] = bool(str(_hv.get('authorization') or '').strip())
            d['dpop_set'] = bool(str(_hv.get('dpop_list') or _hv.get('dpop') or '').strip())
            d['is_open'] = 1 if d.get('is_open') else 0
            d['auto_fetch_order_list'] = 1 if d.get('auto_fetch_order_list') else 0
            d['auto_fetch_on_sale'] = 1 if d.get('auto_fetch_on_sale') else 0
            d['auto_fetch_todos'] = 1 if d.get('auto_fetch_todos') else 0
            d['auto_fetch_notifications'] = 1 if d.get('auto_fetch_notifications') else 0
            d['auto_fetch_order_list_interval'] = d.get('auto_fetch_order_list_interval') or None
            d['auto_fetch_on_sale_interval'] = d.get('auto_fetch_on_sale_interval') or None
            d['auto_fetch_todos_interval'] = d.get('auto_fetch_todos_interval') or None
            d['auto_fetch_notifications_interval'] = d.get('auto_fetch_notifications_interval') or None
            d['auto_fetch_relist'] = 1 if d.get('auto_fetch_relist') else 0
            d['pause_start_time'] = d.get('pause_start_time') or None
            d['pause_end_time'] = d.get('pause_end_time') or None
            _sid = str(d.get('seller_id') or '').strip()
            d['on_sale_count'] = on_sale_by_seller.get((d['platform'], _sid), 0) if _sid else 0
            items.append(d)
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': items,
        }

    @staticmethod
    def _parse_value_json(raw: Optional[str]) -> Dict[str, str]:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return {}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            return {k: ('' if v is None else str(v)) for k, v in data.items()}
        except Exception:
            return {}
