# -*- coding: utf-8 -*-
"""控制台聚合端点：一次请求返回控制台整页所需的全部指标。

拆成多个端点的话前端得并发 5 个请求再各自处理 loading / 失败，而这几块数据本就该是
同一时刻的快照（区间一改全部要跟着变），所以合成一个。各分块自身在 units 下按主题分文件。
"""
import time
from typing import Any, Dict, Optional

from ._common import resolve_range
from .kpi import build_kpi, build_trend, earliest_purchase_ts
from .operations import build_operations, recent_orders
from .platforms import build_platforms
from .stock import build_stock

# 时区偏移合法范围（分钟）：UTC-12 ~ UTC+14，越界一律按 0 处理
_TZ_OFFSET_LIMIT_MIN = 14 * 60


def dashboard_summary(
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    today_start_ts: Optional[int] = None,
    today_end_ts: Optional[int] = None,
    tz_offset_min: int = 0,
    all_time: bool = False,
):
    """控制台整页数据。

    - ``start_ts`` / ``end_ts``：区间起止（Unix 秒），由前端按**本地自然日**边界换算，
      与订单页 dateRange 同一套 ``rollingLocalDayRangeTs``。缺省为最近 30 天。
    - ``all_time=True``（前端「全部」）：起点改用全库最早的购入时间，忽略传入的 ``start_ts``；
      环比区间因此落在有数据之前，各项会是 0——「全部」本来就没有可比的上一周期。
    - ``today_start_ts`` / ``today_end_ts``：本地「今天」起止，用于 KPI 的今日副指标。
    - ``tz_offset_min``：前端 ``-new Date().getTimezoneOffset()``，趋势按日分桶用。
      服务端与浏览器不一定同一时区，用服务端时区分桶会让曲线整体错位一天。

    统计一律按订单 ``purchase_time``（购入时间），与订单页 ``/orders/stats`` 的
    「最后更新优先」口径不同，详见 ``units/_common.py`` 顶部说明。
    """
    try:
        offset_min = int(tz_offset_min or 0)
    except (TypeError, ValueError):
        offset_min = 0
    if abs(offset_min) > _TZ_OFFSET_LIMIT_MIN:
        offset_min = 0
    tz_offset_sec = offset_min * 60

    now_ts = int(time.time())
    if all_time:
        # 无订单时 earliest 为 None，落回 resolve_range 的默认区间而不是从 1970 年开始
        start_ts = earliest_purchase_ts() or start_ts
    rng = resolve_range(start_ts, end_ts, now_ts)
    trend = build_trend(rng["start_ts"], rng["end_ts"], tz_offset_sec)

    payload: Dict[str, Any] = {
        "range": {**rng, "all_time": bool(all_time)},
        "generated_at": now_ts,
        "kpi": build_kpi(rng, today_start_ts, today_end_ts),
        "trend": trend["points"],
        "trend_granularity": trend["granularity"],
        "operations": build_operations(rng, now_ts),
        "stock": build_stock(),
        "platforms": build_platforms(rng),
        "recent_orders": recent_orders(),
    }
    return payload
