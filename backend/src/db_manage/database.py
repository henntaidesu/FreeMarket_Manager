# -*- coding: utf-8 -*-
"""
数据库管理核心类

后端无关：连接、事务、DDL、结构内省全部委托给方言层（dialects），
由环境变量 ``DB_BACKEND`` 选择 SQLite（默认）或 MySQL。上层调用点统一书写
SQLite 风格 SQL（``?`` 占位符、``[标识符]`` 方括号），由方言在执行时按需翻译。
"""

import os
import threading
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

from src.app_paths import backend_root_str
from .dialects import get_dialect
from . import archive_view


class DatabaseManager:
    """数据库管理器 - 单例模式"""

    _instance = None
    _lock = threading.Lock()
    _tlocal = threading.local()  # 每线程的活动事务连接（transaction() 内复用）

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            # mercariDB.db 放在 backend 根目录（冻结后与 exe 同目录）；MySQL 后端忽略此路径
            self.db_path = os.path.join(backend_root_str(), 'mercariDB.db')
            self.dialect = get_dialect(self.db_path)
            self.initialized = True
            self._setup_database()

    def _setup_database(self):
        """设置数据库配置（委托方言）"""
        self.dialect.setup()

    def _active_transaction_conn(self):
        """当前线程处于 transaction() 中时返回事务连接，否则 None"""
        return getattr(self._tlocal, 'conn', None)

    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器（处于事务中时复用事务连接，由 transaction() 统一提交/关闭）"""
        active = self._active_transaction_conn()
        if active is not None:
            yield active
            return
        conn = self.dialect.connect()
        try:
            yield archive_view.wrap(conn)
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """事务上下文：块内所有 execute_* 在同一连接上执行，结束时统一提交，异常时回滚。

        嵌套调用时直接加入外层事务。不使用 transaction() 的代码路径行为完全不变。
        """
        active = self._active_transaction_conn()
        if active is not None:
            # 嵌套事务：直接加入外层事务
            yield active
            return
        conn = self.dialect.connect()
        self.dialect.begin(conn)
        self._tlocal.conn = archive_view.wrap(conn)
        try:
            yield self._tlocal.conn
            self.dialect.commit(conn)
        except BaseException:
            try:
                self.dialect.rollback(conn)
            except Exception:
                pass
            raise
        finally:
            self._tlocal.conn = None
            conn.close()

    def execute_query(self, sql: str, params: tuple = ()) -> List[tuple]:
        """执行查询语句"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()

    def execute_update(self, sql: str, params: tuple = ()) -> int:
        """执行更新语句，返回受影响的行数"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.rowcount

    def execute_insert(self, sql: str, params: tuple = ()) -> Optional[int]:
        """执行插入语句，返回最后插入的行ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.lastrowid

    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """执行批量操作"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.rowcount

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        return self.dialect.table_exists(self, table_name)

    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表的列信息"""
        return self.dialect.get_table_columns(self, table_name)

    def create_table(self, table_name: str, columns: List[Dict[str, Any]],
                     indexes: List[Dict[str, Any]] = None) -> bool:
        """创建表"""
        return self.dialect.create_table(self, table_name, columns, indexes)

    def add_column(self, table_name: str, column_def: Dict[str, Any]) -> bool:
        """添加列到现有表"""
        return self.dialect.add_column(self, table_name, column_def)

    def drop_column(self, table_name: str, column_name: str) -> bool:
        """删除表中的列"""
        return self.dialect.drop_column(self, table_name, column_name)

    def get_all_tables(self) -> List[str]:
        """获取数据库中所有表名"""
        return self.dialect.get_all_tables(self)

    def drop_table(self, table_name: str) -> bool:
        """删除表"""
        return self.dialect.drop_table(self, table_name)

    def get_database_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        tables = self.get_all_tables()
        return {
            'db_path': self.db_path,
            'tables': [{'name': t, 'columns': self.get_table_columns(t)} for t in tables]
        }
