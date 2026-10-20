# -*- coding: utf-8 -*-
"""一次性：把拆分出来的商品并回同一个管理番号，供整体清点。

「拆分家族」= 顺着 ``inventory.split_parent_id`` 追到同一个源头的所有商品（含拆了又拆的）。
只处理源头番号 <= ``--max-root``（默认 1249）的家族；源头 <= 1249 而子件番号更大的也一起并。

每个家族（不分所有人）并进家族里**番号最新**的那件，走与「同条码合并」同一个
``inventory_barcode.merge.merge_into_newest``：批次搬过去、出库明细 / 在售台账 / 组合构成改指目标、
旧行软删除并记 ``merged_into_id``（旧标签、描述暗号、图片暗码仍能解析到目标），历史数据都在。
所有人不同时，``_merge_one`` 会把每个批次与每条历史出库明细的所有人落成显式值——同一番号下按
批次区分所有人，历史订单的结算归属不变。

跳过（打印清单，人工判断）：
- 与父件的商品条码 / 款式号 / 品相不一致的子件，连同它再往下拆出的子件（它们可能是别的商品）；
- 有未结清出品预扣减 / 出品任务仍占用的家族（``merge_blockers``，结清后重跑即可）。

幂等：已并掉的行是软删除，重跑只会处理还剩下的。

用法（在 backend 目录下，先停掉后端或至少确认没有同步任务在跑）：
    python -m tools.merge_split_families            # 只预览
    python -m tools.merge_split_families --apply    # 执行
只允许在测试库上执行；生产库需显式加 ``--allow-non-test``。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-root", type=int, default=1249, help="只处理源头番号 <= 此值的家族（默认 1249）")
    ap.add_argument("--apply", action="store_true", help="执行合并（默认只预览）")
    ap.add_argument("--allow-non-test", action="store_true", help="允许在非测试库上执行")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from src.db_manage.database import DatabaseManager
    from src.db_manage.db_settings import get_active_backend, get_mysql_config, is_test_database
    from src.db_manage.models.inventory.inventory_batch import InventoryBatchModel
    from src.db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
    from src.inventory_barcode.merge import merge_blockers, merge_into_newest

    backend = get_active_backend()
    db_name = get_mysql_config().get("database") if backend == "mysql" else "SQLite"
    print(f"数据库: {backend} / {db_name}")
    if args.apply and not is_test_database() and not args.allow_non_test:
        print("[错误] 当前不是测试库；确认要在这个库上执行请加 --allow-non-test。终止。")
        return 2

    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT i.[id], i.[split_parent_id], i.[owner_user_id], COALESCE(i.[is_delete], 0), "
        "i.[product_barcode], i.[variant_no], i.[grade], COALESCE(i.[is_combined], 0), "
        "COALESCE(i.[quantity], 0), i.[name], COALESCE(u.[display_name], u.[username]) "
        "FROM [inventory] i LEFT JOIN [users] u ON u.[id] = i.[owner_user_id]"
    ) or []
    inv = {int(r[0]): r for r in rows}

    def identity(r):
        return (r[4] or "", int(r[5] or 0), r[6] or "")

    def parent(i):
        p = inv[i][1]
        return int(p) if p is not None and int(p) in inv and int(p) != i else None

    def walk(i):
        """返回 (源头, 是否在链上跨过「与父件不一致」的边)。"""
        cut, seen = False, {i}
        while True:
            p = parent(i)
            if p is None or p in seen:
                return i, cut
            if identity(inv[i]) != identity(inv[p]):
                cut = True
            seen.add(p)
            i = p

    families = defaultdict(list)
    skipped = []
    for i, r in inv.items():
        if r[3] or r[7]:
            continue  # 已删除 / 已合并；组合商品不能拆分，不会出现在拆分家族里
        root, cut = walk(i)
        if root > args.max_root:
            continue
        if cut:
            skipped.append((i, root, "条码/款式/品相与父件不一致（或其上级不一致）"))
        else:
            families[root].append(i)

    def label(i):
        r = inv[i]
        return f"#{i}({r[10] or '无归属'} ×{int(r[8])})"

    plan = []
    for root in sorted(families):
        ids = sorted(families[root])
        if len(ids) < 2:
            continue
        blocker = merge_blockers(ids)
        if blocker:
            skipped.extend((i, root, blocker) for i in ids)
            continue
        plan.append((root, ids))

    owner_mixed = sum(1 for _r, ids in plan if len({inv[i][2] for i in ids}) > 1)
    print(f"\n待合并家族 {len(plan)} 个（其中跨所有人 {owner_mixed} 个），"
          f"并掉 {sum(len(ids) - 1 for _r, ids in plan)} 行：")
    for root, ids in plan:
        print(f"  源头 #{root}  →  保留 {label(ids[-1])}  ←  {', '.join(label(i) for i in ids[:-1])}"
              f"   [{inv[ids[-1]][9]}]")
    if skipped:
        print(f"\n跳过 {len(skipped)} 行（人工判断）：")
        for i, root, why in sorted(skipped):
            print(f"  #{i}（源头 #{root}）{inv[i][9]} —— {why}")

    if not args.apply:
        print("\n预览结束，未写入。确认无误后加 --apply 执行。")
        return 0

    # 所有人快照的两列由应用启动时自动补；后端还没用新代码重启过的话在这里补上
    InventoryBatchModel.ensure_table_exists()
    OrderOutboundLineModel.ensure_table_exists()

    done = failed = 0
    for root, ids in plan:
        try:
            merge_into_newest(ids)
            done += 1
        except Exception as e:  # noqa: BLE001 —— 单个家族失败（已整体回滚）不影响其它家族
            failed += 1
            print(f"  [失败] 源头 #{root} {ids}: {e}")
    print(f"\n完成：合并 {done} 个家族，失败 {failed} 个。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
