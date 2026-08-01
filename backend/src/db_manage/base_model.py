# -*- coding: utf-8 -*-
"""
数据库模型基础类
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from .database import DatabaseManager

log = logging.getLogger(__name__)


class BaseModel(ABC):
    """数据库模型基础类"""

    def __init__(self, **kwargs):
        self.db = DatabaseManager()
        self._data = {}
        self._original_data = {}

        for field_name, field_def in self.get_fields().items():
            value = kwargs.get(field_name, field_def.get('default'))
            if isinstance(value, str) and value.strip() == '':
                value = None
            self._data[field_name] = value
            self._original_data[field_name] = value

    @classmethod
    @abstractmethod
    def get_table_name(cls) -> str:
        """获取表名"""
        pass

    @classmethod
    @abstractmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        """获取字段定义"""
        pass

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        """获取索引定义"""
        return []

    def __getattr__(self, name: str):
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' 没有属性 '{name}'")

    def __setattr__(self, name: str, value):
        if name.startswith('_') or name in ['db']:
            super().__setattr__(name, value)
        elif hasattr(self, '_data') and name in self.get_fields():
            if isinstance(value, str) and value.strip() == '':
                value = None
            self._data[name] = value
        else:
            super().__setattr__(name, value)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self._data.copy()

    def save(self) -> bool:
        """保存到数据库（新增或更新）"""
        if self._is_new_record():
            return self._insert()
        return self._update()

    def delete(self) -> bool:
        """从数据库删除"""
        pks = self._get_primary_keys()
        if not pks:
            return False
        where = ' AND '.join([f'[{k}] = ?' for k in pks])
        params = tuple(self._data[k] for k in pks)
        try:
            return self.db.execute_update(
                f"DELETE FROM [{self.get_table_name()}] WHERE {where}", params
            ) > 0
        except Exception as e:
            print(f"删除记录失败: {e}")
            return False

    @classmethod
    def delete_all(cls, where_clause: str = None, params: tuple = None) -> int:
        """删除满足条件的所有记录"""
        db = DatabaseManager()
        sql = f"DELETE FROM [{cls.get_table_name()}]"
        if where_clause:
            sql += f" WHERE {where_clause}"
        try:
            return db.execute_update(sql, params or ())
        except Exception as e:
            print(f"批量删除失败: {e}")
            return 0

    def _is_new_record(self) -> bool:
        """判断是否为新记录"""
        pks = self._get_primary_keys()
        if not pks:
            return True
        for k in pks:
            if not self._data.get(k):
                return True
        where = ' AND '.join([f'[{k}] = ?' for k in pks])
        params = tuple(self._data[k] for k in pks)
        try:
            result = self.db.execute_query(
                f"SELECT 1 FROM [{self.get_table_name()}] WHERE {where} LIMIT 1", params
            )
            return len(result) == 0
        except Exception:
            return True

    # DB 侧默认关键字：值未被显式改动时交给数据库 DDL 默认，而不是把关键字当字面量插入
    _DB_DEFAULT_KEYWORDS = {'CURRENT_TIMESTAMP'}

    def _insert(self) -> bool:
        """插入新记录"""
        field_defs = self.get_fields()
        fields, placeholders, params = [], [], []
        for field_name, value in self._data.items():
            # created_at 等以 CURRENT_TIMESTAMP 为默认的列：值仍等于该默认时不插入，
            # 让数据库应用 DDL 默认（SQLite/MySQL 均生成真实时间戳）。
            default = field_defs.get(field_name, {}).get('default')
            if (isinstance(default, str)
                    and default.strip().strip("'\"").upper() in self._DB_DEFAULT_KEYWORDS
                    and value == default):
                continue
            if value is not None and not (isinstance(value, str) and value.strip() == ''):
                fields.append(field_name)
                placeholders.append('?')
                params.append(value)

        escaped = [f'[{f}]' for f in fields]
        sql = f"INSERT INTO [{self.get_table_name()}] ({', '.join(escaped)}) VALUES ({', '.join(placeholders)})"
        try:
            last_id = self.db.execute_insert(sql, tuple(params))
            # 回填 autoincrement 主键
            for field_name, field_def in self.get_fields().items():
                if field_def.get('primary_key') and field_def.get('autoincrement') and not self._data.get(field_name):
                    self._data[field_name] = last_id
            self._original_data = self._data.copy()
            return True
        except Exception as e:
            print(f"[错误] 插入失败 - 表: {self.get_table_name()}, 错误: {e}")
            return False

    def _update(self) -> bool:
        """更新现有记录"""
        pks = self._get_primary_keys()
        if not pks:
            return False
        changed, params = [], []
        for field_name, value in self._data.items():
            if field_name not in pks and value != self._original_data.get(field_name):
                changed.append(f'[{field_name}] = ?')
                params.append(None if isinstance(value, str) and value.strip() == '' else value)
        if not changed:
            return True

        where = ' AND '.join([f'[{k}] = ?' for k in pks])
        params.extend(self._original_data[k] for k in pks)
        sql = f"UPDATE [{self.get_table_name()}] SET {', '.join(changed)} WHERE {where}"
        try:
            affected = self.db.execute_update(sql, tuple(params))
            if affected > 0:
                self._original_data = self._data.copy()
                return True
            return False
        except Exception as e:
            print(f"更新记录失败: {e}")
            return False

    def _get_primary_keys(self) -> List[str]:
        return [k for k, v in self.get_fields().items() if v.get('primary_key')]

    @classmethod
    def find_by_id(cls, **primary_key_values):
        """根据主键查找记录"""
        instance = cls()
        pks = instance._get_primary_keys()
        if not pks or len(primary_key_values) != len(pks):
            return None
        where = ' AND '.join([f'[{k}] = ?' for k in pks])
        params = tuple(primary_key_values[k] for k in pks if k in primary_key_values)
        try:
            result = instance.db.execute_query(
                f"SELECT * FROM [{cls.get_table_name()}] WHERE {where} LIMIT 1", params
            )
            return cls._create_from_row(result[0]) if result else None
        except Exception as e:
            print(f"查找记录失败: {e}")
            return None

    @classmethod
    def find_all(cls, where: str = "", params: tuple = (),
                 limit: int = None, offset: int = None, order_by: str = None):
        """查找多条记录"""
        sql = f"SELECT * FROM [{cls.get_table_name()}]"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None and limit != "":
            # 安全：limit/offset 直接拼进 SQL，强制转 int 防止注入（order_by/where 仍要求调用方传常量）
            sql += f" LIMIT {int(limit)}"
            if offset:
                sql += f" OFFSET {int(offset)}"
        try:
            instance = cls()
            result = instance.db.execute_query(sql, params)
            return [cls._create_from_row(row) for row in result]
        except Exception as e:
            print(f"查找记录失败: {e}")
            return []

    @classmethod
    def count(cls, where: str = "", params: tuple = ()) -> int:
        """统计记录数"""
        sql = f"SELECT COUNT(*) FROM [{cls.get_table_name()}]"
        if where:
            sql += f" WHERE {where}"
        try:
            result = cls().db.execute_query(sql, params)
            return result[0][0] if result else 0
        except Exception as e:
            print(f"统计失败: {e}")
            return 0

    @classmethod
    def _get_table_column_names(cls) -> List[str]:
        cache_attr = '_cached_table_columns'
        if not hasattr(cls, cache_attr):
            columns = cls().db.get_table_columns(cls.get_table_name())
            setattr(cls, cache_attr, [col['name'] for col in columns])
        return getattr(cls, cache_attr)

    @classmethod
    def _create_from_row(cls, row: tuple):
        """从数据库行创建模型实例"""
        table_columns = cls._get_table_column_names()
        field_defs = cls.get_fields()
        kwargs = {}
        for idx, col_name in enumerate(table_columns):
            if idx >= len(row) or col_name not in field_defs:
                continue
            value = row[idx]
            if isinstance(value, str) and value.strip() == '':
                value = None
            kwargs[col_name] = value
        instance = cls(**kwargs)
        instance._original_data = instance._data.copy()
        return instance

    @classmethod
    def ensure_table_exists(cls) -> bool:
        """确保表存在，不存在则创建，存在则检查并同步结构"""
        db = DatabaseManager()
        if db.table_exists(cls.get_table_name()):
            return cls._check_and_update_table_structure()
        return cls._create_table()

    @classmethod
    def _create_table(cls) -> bool:
        db = DatabaseManager()
        columns = [
            {
                'name': fname,
                'type': fdef['type'],
                'primary_key': fdef.get('primary_key', False),
                'autoincrement': fdef.get('autoincrement', False),
                'not_null': fdef.get('not_null', False),
                'unique': fdef.get('unique', False),
                'default': fdef.get('default'),
                'max_length': fdef.get('max_length'),
                'mysql_type': fdef.get('mysql_type'),
            }
            for fname, fdef in cls.get_fields().items()
        ]
        return db.create_table(cls.get_table_name(), columns, cls.get_indexes())

    @classmethod
    def _check_and_update_table_structure(cls) -> bool:
        """检查并同步表结构（添加缺失字段；多余字段按闸门决定删或留）。

        删列走 ``schema_guard``：生产库一律跳过、测试库默认放行。跳过时留下的多余列是无害的
        （``get_fields()`` 不声明就永远不读它），而误删一列的数据不可恢复——两者不对等。
        """
        from .schema_guard import destructive_schema_allowed, note_executed_drop, note_skipped_drop

        db = DatabaseManager()
        table_name = cls.get_table_name()
        existing = {col['name']: col for col in db.get_table_columns(table_name)}
        defined = set(cls.get_fields().keys())

        for fname, fdef in cls.get_fields().items():
            if fname not in existing:
                log.info("表 %s 缺少字段 %s，正在添加...", table_name, fname)
                if not db.add_column(table_name, {
                    'name': fname, 'type': fdef['type'],
                    'not_null': fdef.get('not_null', False),
                    'default': fdef.get('default'),
                    'max_length': fdef.get('max_length'),
                    'mysql_type': fdef.get('mysql_type'),
                }):
                    return False

        extras = sorted(
            c for c in set(existing.keys()) - defined if not existing[c].get('pk')
        )
        if not extras:
            return True

        allowed, reason = destructive_schema_allowed()
        if not allowed:
            note_skipped_drop("column", reason, table_name, extras)
            return True

        # 逐列留痕，不要等整批删完再记：删到一半失败时提前 return，
        # 已经删掉的那几列的数据就没了，而 system_logs 里一个字都没有。
        for col_name in extras:
            if not db.drop_column(table_name, col_name):
                return False
            note_executed_drop("column", table_name, [col_name])
        return True
