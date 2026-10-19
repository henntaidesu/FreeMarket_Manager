# -*- coding: utf-8 -*-
"""同条码商品之间的「同一张图」：疑似借用背面图 / 整套图片相同。

拍背面图时有人直接拿了别的商品的背面照片，条码识别就把那件商品的条码记到了这件上。从数据看，
借用的图与原图**字节完全相同**（同一个文件被重复上传或随复制带过来），所以按文件内容 MD5 判定：

  · **疑似借用条码**：这件商品的某张图与同条码下另一件商品的某张图是同一个文件，两件的**主图却不同**，
    而且这张图里识别得出该条码——条码可能只属于其中一件。系统**只标出来**（两边都标，谁借了谁
    数据上分不出），由人逐件确认：「条码不属于此商品」清条码（图片保留）/「条码正确」（系列共用条码，
    以后不再提示，``inventory.barcode_confirmed``）。
  · **整套图片相同**：两件商品的图片集合完全一样——多半是复制出来的同一商品，只提示，不自动归类。

哈希按图片路径缓存在 ``inventory_image_hashes``（上传的文件名唯一、内容不会被改写，缓存永久有效）。
读图在图床后端下是网络请求，所以统计 / 待合并计数只用缓存；缓存由条码识别任务（``refresh_all``）
与待合并列表（只补当页那几组）补齐。被共用的图才识别条码，同样缓存。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..db_manage.database import DatabaseManager

log = logging.getLogger(__name__)

#: path → (md5, barcodes 或 None=未识别)
Cache = Dict[str, Tuple[str, Optional[List[str]]]]


def load_cache(paths: Iterable[str]) -> Cache:
    paths = sorted({p for p in paths if p})
    out: Cache = {}
    db = DatabaseManager()
    for i in range(0, len(paths), 500):
        chunk = paths[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for path, md5, codes in db.execute_query(
            f"SELECT [image_path], [md5], [barcodes] FROM [inventory_image_hashes] WHERE [image_path] IN ({ph})",
            tuple(chunk),
        ) or []:
            try:
                parsed = json.loads(codes) if codes is not None else None
            except (TypeError, ValueError):
                parsed = None
            out[path] = (md5, parsed if isinstance(parsed, list) else None)
    return out


def ensure_hashes(paths: Iterable[str], should_stop: Callable[[], bool] = lambda: False) -> int:
    """补齐缺失的哈希，返回新算了几张。取不到图的跳过（下次再试）。"""
    from ..use_web.image_storage import read_image_bytes

    paths = sorted({p for p in paths if p})
    have = load_cache(paths)
    db = DatabaseManager()
    n = 0
    for p in paths:
        if p in have:
            continue
        if should_stop():
            break
        try:
            data = read_image_bytes(p)
        except Exception:  # noqa: BLE001 —— 一张图读不到不该挡住其它的
            log.warning("[image_dupes] 读取图片失败 %s", p, exc_info=True)
            continue
        if not data:
            continue
        try:
            db.execute_update(
                "INSERT INTO [inventory_image_hashes] ([image_path], [md5]) VALUES (?, ?)",
                (p, hashlib.md5(data).hexdigest()),
            )
            n += 1
        except Exception:  # noqa: BLE001 —— 并发补同一张图撞唯一索引，另一边已写入
            pass
    return n


def ensure_barcodes(paths: Iterable[str]) -> int:
    """给缓存里还没识别过的图识别条码，返回识别了几张。"""
    from ..use_web.image_storage import read_image_bytes
    from .decode import decode_image_bytes

    cache = load_cache(paths)
    db = DatabaseManager()
    n = 0
    for p, (_md5, codes) in cache.items():
        if codes is not None:
            continue
        try:
            data = read_image_bytes(p)
            found = sorted(set(decode_image_bytes(data))) if data else None
        except Exception:  # noqa: BLE001
            log.warning("[image_dupes] 识别条码失败 %s", p, exc_info=True)
            continue
        if found is None:
            continue
        db.execute_update(
            "UPDATE [inventory_image_hashes] SET [barcodes] = ? WHERE [image_path] = ?",
            (json.dumps(found), p),
        )
        n += 1
    return n


def family_flags(barcode: str, items: List[Dict[str, Any]], cache: Cache) -> Dict[int, Dict[str, Any]]:
    """同一条码下（跨归属人）的商品之间比对。``items`` = [{id, images, confirmed}]。

    返回 {id: {"same_set": [ids], "borrowed": [{"image", "peers"}]}}；只列出有标记的商品。"""
    md5s: Dict[int, List[str]] = {}
    for it in items:
        md5s[it["id"]] = [cache[p][0] for p in it["images"] if p in cache]
    main = {it["id"]: (cache[it["images"][0]][0] if it["images"] and it["images"][0] in cache else None)
            for it in items}
    out: Dict[int, Dict[str, Any]] = {}
    for it in items:
        iid = it["id"]
        mine = md5s[iid]
        if not mine:
            continue
        flags: Dict[str, Any] = {}
        # 整套相同：图片都算过哈希、集合一致
        if len(mine) == len(it["images"]):
            same = [o["id"] for o in items if o["id"] != iid and len(md5s[o["id"]]) == len(o["images"])
                    and set(md5s[o["id"]]) == set(mine)]
            if same:
                flags["same_set"] = same
        if not it.get("confirmed"):
            borrowed = []
            for p in it["images"]:
                if p not in cache:
                    continue
                m, codes = cache[p]
                peers = [o["id"] for o in items if o["id"] != iid and m in md5s[o["id"]]
                         and main[o["id"]] != main[iid]]
                # 这张图里识别得出该条码才算（未识别过的保守地算上，等识别补齐再收窄）
                if peers and (codes is None or barcode in codes):
                    borrowed.append({"image": p, "peers": peers})
            if borrowed:
                flags["borrowed"] = borrowed
        if flags:
            out[iid] = flags
    return out


def shared_images(items: List[Dict[str, Any]], cache: Cache) -> List[str]:
    """被同条码下多件商品共用的图（需要识别条码来判定借用的那些）。"""
    owners: Dict[str, set] = {}
    for it in items:
        for p in it["images"]:
            if p in cache:
                owners.setdefault(cache[p][0], set()).add(it["id"])
    return [p for it in items for p in it["images"] if p in cache and len(owners[cache[p][0]]) > 1]


def _families() -> Dict[str, List[Dict[str, Any]]]:
    rows = DatabaseManager().execute_query(
        "SELECT [id], TRIM([product_barcode]), [images_json], COALESCE([barcode_confirmed], 0) FROM [inventory] "
        "WHERE COALESCE([is_delete], 0) = 0 AND COALESCE([is_combined], 0) = 0 "
        "AND [product_barcode] IS NOT NULL AND TRIM([product_barcode]) <> ''"
    ) or []
    fam: Dict[str, List[Dict[str, Any]]] = {}
    for iid, code, images_json, confirmed in rows:
        try:
            imgs = json.loads(images_json) if images_json else []
        except (TypeError, ValueError):
            imgs = []
        fam.setdefault(code, []).append({
            "id": int(iid), "images": [str(x) for x in imgs if x] if isinstance(imgs, list) else [],
            "confirmed": int(confirmed),
        })
    return fam


def refresh_all(report=None, should_stop: Callable[[], bool] = lambda: False) -> Dict[str, int]:
    """条码识别任务里跑：给所有有条码、且同条码下不止一件的商品补齐图片哈希，再识别被共用的图。"""
    fam = {c: its for c, its in _families().items() if len(its) > 1}
    paths = [p for its in fam.values() for it in its for p in it["images"]]
    if report:
        report("比对重复图片", f"{len(paths)} 张图")
    hashed = ensure_hashes(paths, should_stop)
    cache = load_cache(paths)
    shared = [p for its in fam.values() for p in shared_images(its, cache)]
    decoded = 0 if should_stop() else ensure_barcodes(shared)
    return {"hashed": hashed, "decoded": decoded}
