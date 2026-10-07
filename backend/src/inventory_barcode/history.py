# -*- coding: utf-8 -*-
"""条码识别 · 历史数据处理（系统配置页开关 → 任务队列 ``system.barcode_history``）。

一轮分两步，两步都**幂等**，中途失败或取消后再开一次开关只会处理剩下的：

1. 识别：``barcode_scan_status IS NULL`` 的商品逐个识别——
   · ``barcode`` 列里本来就是扫码录入的真实条码 → 直接采用，不看图；
   · 否则读全部商品图识别：识别到 1 个 → ``found``；一个都没有 → ``none``（条码保持 uuid，
     以后跳过）；多张图识别出不同条码 → ``conflict``（不自动处理，在系统配置页
     「处理冲突」里人工选定，见 conflicts.py）。
2. 合并：同产品条码 + 同归属人 的商品，全部并入其中管理番号最大的那个（见 merge.py）。
   有出品预扣减未结清的组本轮跳过，下一轮再并。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from ..db_manage.database import DatabaseManager
from ..db_manage.models.system.config_entry import ConfigEntryModel
from .decode import decode_inventory_images_detail, is_generated_barcode
from .merge import merge_blockers, merge_into

log = logging.getLogger(__name__)

#: [config] 开关键；"1" = 开启，键不存在 = 关闭
MODE_KEY = "barcode_history_mode"

Report = Optional[Callable[[str, str], None]]


def is_on() -> bool:
    try:
        return str(ConfigEntryModel.get_value(MODE_KEY) or "").strip() == "1"
    except Exception:  # noqa: BLE001
        log.exception("[barcode_history] 读取开关失败")
        return False


def set_on(on: bool) -> None:
    ConfigEntryModel.set_value(MODE_KEY, "1" if on else None)


def status() -> Dict[str, Any]:
    """开关 + 各识别状态的件数（仅未删除、非组合商品；merged 统计已并走的行）。"""
    rows = DatabaseManager().execute_query(
        """
        SELECT COALESCE([barcode_scan_status], ''), COUNT(1) FROM [inventory]
        WHERE COALESCE([is_combined], 0) = 0
          AND (COALESCE([is_delete], 0) = 0 OR [barcode_scan_status] = 'merged')
        GROUP BY COALESCE([barcode_scan_status], '')
        """
    ) or []
    c = {str(k): int(v) for k, v in rows}
    return {
        "enabled": is_on(),
        "pending_count": c.get("", 0),
        "found_count": c.get("found", 0),
        "none_count": c.get("none", 0),
        "conflict_count": c.get("conflict", 0),
        "merged_count": c.get("merged", 0),
    }


def _paths(images_json) -> List[str]:
    try:
        v = json.loads(images_json) if images_json else []
    except (TypeError, ValueError):
        return []
    return [str(x).strip() for x in v if x and str(x).strip()] if isinstance(v, list) else []


def scan_pending(report: Report = None, should_stop: Callable[[], bool] = lambda: False) -> Dict[str, int]:
    """第 1 步：识别所有未处理商品。"""
    db = DatabaseManager()
    rows = db.execute_query(
        """
        SELECT [id], [barcode], [product_barcode], [images_json] FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0 AND COALESCE([is_combined], 0) = 0
          AND [barcode_scan_status] IS NULL
        ORDER BY [id]
        """
    ) or []
    stats = {"total": len(rows), "found": 0, "none": 0, "conflict": 0}
    for i, (iid, barcode, product_barcode, images_json) in enumerate(rows, 1):
        if should_stop():
            break
        if report and (i == 1 or i % 10 == 0 or i == len(rows)):
            report("识别条码", f"{i}/{len(rows)}（识别到 {stats['found']}，无条码 {stats['none']}）")
        code: Optional[str] = None
        candidates: Optional[str] = None
        state = "none"
        if (product_barcode or "").strip():
            code, state = product_barcode.strip(), "found"
        elif (barcode or "").strip() and not is_generated_barcode(barcode):
            code, state = barcode.strip(), "found"
        else:
            found = decode_inventory_images_detail(_paths(images_json))
            if len(found) == 1:
                code, state = next(iter(found)), "found"
            elif len(found) > 1:
                # 记下每个条码出自哪几张图，人工处理弹窗（conflicts.py）据此展示
                state = "conflict"
                candidates = json.dumps(
                    [{"code": c, "images": imgs} for c, imgs in found.items()], ensure_ascii=False
                )
                log.info("[barcode_history] 商品 %s 识别出多个条码 %s，标记冲突", iid, list(found))
        db.execute_update(
            "UPDATE [inventory] SET [product_barcode] = ?, [barcode_scan_status] = ?, [barcode_candidates] = ? "
            "WHERE [id] = ? AND [barcode_scan_status] IS NULL",
            (code, state, candidates, int(iid)),
        )
        stats[state] += 1
    return stats


def merge_duplicates(report: Report = None, should_stop: Callable[[], bool] = lambda: False) -> Dict[str, int]:
    """第 2 步：同产品条码 + 同归属人 → 并入管理番号最大的商品。"""
    db = DatabaseManager()
    rows = db.execute_query(
        """
        SELECT [product_barcode], COALESCE([owner_user_id], 0), [id] FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0 AND COALESCE([is_combined], 0) = 0
          AND [product_barcode] IS NOT NULL AND TRIM([product_barcode]) <> ''
        ORDER BY [id]
        """
    ) or []
    groups: Dict[tuple, List[int]] = {}
    for code, owner, iid in rows:
        groups.setdefault((str(code).strip(), int(owner)), []).append(int(iid))
    dup = [ids for ids in groups.values() if len(ids) > 1]
    stats = {"groups": len(dup), "merged_items": 0, "deferred_groups": 0}
    for n, ids in enumerate(dup, 1):
        if should_stop():
            break
        target, sources = max(ids), [i for i in ids if i != max(ids)]
        if report:
            report("合并同条码商品", f"{n}/{len(dup)}：{sources} → {target}")
        reason = merge_blockers(sources)
        if reason:
            stats["deferred_groups"] += 1
            log.info("[barcode_history] 暂不合并 %s → %s：%s", sources, target, reason)
            continue
        stats["merged_items"] += len(merge_into(target, sources))
    return stats


def run(report: Report = None, should_stop: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    scan = scan_pending(report, should_stop)
    merge = merge_duplicates(report, should_stop)
    return {"scan": scan, "merge": merge}
