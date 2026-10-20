# -*- coding: utf-8 -*-
"""历史库存视图：让「其他功能 → 历史数据」页复用整套库存页接口去读归档表。

带 ``X-Inventory-Archive: 1`` 请求头的请求，在本请求内：
  · SQL 里的 ``[inventory]`` / ``[inventory_batches]`` 改指 ``[inventory_old]`` /
    ``[inventory_batches_old]``（全仓 SQL 都用方括号写表名，所以按方括号替换即可）；
  · 任何写语句直接抛错——归档表只读，库存页里「读着读着顺手写一下」的路径也不能落库；
  · 只放行 GET/HEAD，其余方法由中间件 403。

开关是 contextvar，由中间件在请求开始时置位：同步端点跑在线程池里，Starlette 会把上下文
复制过去，所以端点及其调用的 DatabaseManager 都看得到；请求之外（后台线程、定时任务）恒为关。
"""

import re
from contextvars import ContextVar

ARCHIVE_HEADER = b"x-inventory-archive"
#: 角色里只勾了这一页的用户，只能以历史视图身份读库存相关接口（见 page_access.require_page）
ARCHIVE_PAGE = "system/inventory-history"

_active: ContextVar[bool] = ContextVar("inventory_archive_view", default=False)

_TABLE_RE = re.compile(r"\[(inventory|inventory_batches)\]")
_READ_RE = re.compile(r"^\s*(SELECT|WITH|PRAGMA|SHOW|DESCRIBE|EXPLAIN)\b", re.IGNORECASE)


class ArchiveReadOnlyError(RuntimeError):
    pass


def is_active() -> bool:
    return _active.get()


def _rewrite(sql: str) -> str:
    if not _READ_RE.match(sql or ""):
        raise ArchiveReadOnlyError("历史数据只读，不能写入")
    return _TABLE_RE.sub(lambda m: f"[{m.group(1)}_old]", sql)


class _Cursor:
    def __init__(self, raw):
        self._c = raw

    def execute(self, sql, params=None):
        sql = _rewrite(sql)
        return self._c.execute(sql) if params is None else self._c.execute(sql, params)

    def executemany(self, sql, params_list):
        raise ArchiveReadOnlyError("历史数据只读，不能写入")

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __iter__(self):
        return iter(self._c)


class _Connection:
    def __init__(self, raw):
        self._conn = raw

    def cursor(self, *a, **kw):
        return _Cursor(self._conn.cursor(*a, **kw))

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def wrap(conn):
    """历史视图开启时包一层只读 + 改表名的连接，否则原样返回。"""
    return _Connection(conn) if _active.get() else conn


class ArchiveViewMiddleware:
    """纯 ASGI 中间件（不用 BaseHTTPMiddleware，免得 contextvar 落在另一个 task 里）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not any(
            k == ARCHIVE_HEADER and v.strip() == b"1" for k, v in scope.get("headers") or ()
        ):
            return await self.app(scope, receive, send)
        if scope.get("method") not in ("GET", "HEAD"):
            body = '{"detail":"历史数据只读"}'.encode("utf-8")
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json; charset=utf-8")]})
            await send({"type": "http.response.body", "body": body})
            return
        token = _active.set(True)
        try:
            await self.app(scope, receive, send)
        finally:
            _active.reset(token)
