# -*- coding: utf-8 -*-
"""商品图左下角管理暗码 → 库存 id：listing / 订单反查库存的**主方法**，说明文本暗号为兜底。

暗码由出品时 ``mgmt_image_cipher.embed_mgmt_code_in_file`` 写入每张上传图（与可见水印开关无关）。

- **单品只解首图**：同一 listing 的每张图嵌的都是同一个 id，多解无益；首图读不出时再试后面
  两张（说明里已不再写文本暗号，没有兜底了）。单品还读首图右下角的**件数码**（专用出品一条挂牌
  含 N 件），存成 id 重复 N 次，例如 ``[1534, 1534, 1534]``；``loads_ids`` 照旧去重，件数用
  ``loads_first_qty`` 取；
- **まとめ商品每张图一件**：组合 listing 是把各件原 listing 的图拼起来重新出品的，
  每张图带的是它原来那件的 id，所以逐张解、去重、保持顺序。判定见 ``is_photo_bundle``。

必须用**原图**（煤炉 items/get 的 ``photos``；雅虎公开商品页 ``__NEXT_DATA__`` 的 ``images``，
见 ``use_yahoo/item_photos.py``）：码区格长 ≈ 短边/70，订单 thumbnails 那种 300px
缩略图格长只剩 4px，实测一张都读不出来。

真实性边界与文本暗号相同：暗码可伪造，解出的 id 只在 ``_resolve_inventory_id`` 认得
（存在，或已合并则转到合并目标）时才采用；解码器本身另有三份副本一致性门槛压误报。

解码结果以 JSON 数组存进 ``on_sale_items.image_mgmt_ids`` / ``orders.image_mgmt_ids``：
出库行重建在事务里、跑得很频繁，不能每次都去下载图片。``"[]"`` 表示解过但没读到，
NULL 表示没解过——两者都让调用方回退到文本。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

#: 标题里出现即视为「每张图一件」的组合商品。雅虎多认一个「まとめ買い」——雅虎的まとめ买卖
#: listing 标题就带这几个字，说明里却不一定有「■ 商品内容」；煤炉标题里「まとめ買い歓迎 /
#: まとめ買い割引」是普通单品的常见宣传语，算进去会把单品当成组合、逐张图乱绑。
_PHOTO_BUNDLE_TITLE_MARKS = {
    "mercari": ("まとめ商品",),
    "yahoo": ("まとめ商品", "まとめ買い"),
}


def is_photo_bundle(title: Any, description: Any, platform: Any = None) -> bool:
    """这件 listing / 订单是否按「每张图一件」解码：标题带组合标记，或说明是まとめ格式。"""
    from .get_order.description_mgmt_ids import _is_bundle_order_description

    plat = str(platform or "").strip().lower() or "mercari"
    name = str(title or "")
    marks = _PHOTO_BUNDLE_TITLE_MARKS.get(plat, _PHOTO_BUNDLE_TITLE_MARKS["mercari"])
    return any(m in name for m in marks) or _is_bundle_order_description(description)


def _download(url: str) -> Optional[bytes]:
    u = str(url or "").strip()
    if not u:
        return None
    try:
        if u.startswith("/imges/"):
            from ..use_web.image_storage import read_image_bytes

            return read_image_bytes(u)
        from ..mercari_cdn_fetch import ALLOWED_HOST_SUFFIXES, fetch_image

        data, _ct = fetch_image(u, suffixes=ALLOWED_HOST_SUFFIXES + (".yimg.jp",))
        return data
    except Exception as exc:  # noqa: BLE001
        log.info("[image_mgmt_ids] 下载图片失败 %s: %s", u, exc)
        return None


#: 单品首图读不出 id 时最多再试几张（同一 listing 每张图嵌的是同一个 id）
_SINGLE_TRY_PHOTOS = 3


def _decode_one(url: str, *, with_qty: bool = False) -> Tuple[Optional[int], int]:
    """→ (库存 id, 件数)。件数只在 ``with_qty`` 且读出 id 时才解，读不到为 1。"""
    from .get_order.description_mgmt_ids import _resolve_inventory_id
    from .mgmt_image_cipher import decode_listing_qty_from_file, decode_mgmt_code_from_file

    data = _download(url)
    if not data:
        return None, 1
    fd, path = tempfile.mkstemp(suffix=".img")
    qty = 1
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        raw = decode_mgmt_code_from_file(
            path, validate=lambda i: _resolve_inventory_id(i) is not None
        )
        if raw is not None and with_qty:
            qty = decode_listing_qty_from_file(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return (_resolve_inventory_id(raw) if raw is not None else None), qty


def decode_photo_mgmt(photo_urls: Iterable[Any], *, bundle: bool) -> Tuple[List[int], int]:
    """逐张解码 → (去重后的库存 id（按图片顺序）, 件数)。阻塞 IO，异步调用方放线程里跑。

    まとめ：每张图一件，件数恒 1。单品：首图起最多试 ``_SINGLE_TRY_PHOTOS`` 张，第一张读出 id 的
    图同时读件数码。"""
    urls = [str(u).strip() for u in (photo_urls or []) if str(u or "").strip()]
    if not bundle:
        for u in urls[:_SINGLE_TRY_PHOTOS]:
            iid, qty = _decode_one(u, with_qty=True)
            if iid is not None:
                return [iid], max(1, int(qty))
        return [], 1
    out: List[int] = []
    for u in urls:
        iid, _qty = _decode_one(u)
        if iid is not None and iid not in out:
            out.append(iid)
    return out, 1


def decode_photo_inventory_ids(photo_urls: Iterable[Any], *, bundle: bool) -> List[int]:
    """只要 id 的旧口径（件数见 ``decode_photo_mgmt``）。"""
    return decode_photo_mgmt(photo_urls, bundle=bundle)[0]


def dumps_ids(ids: List[int], qty: int = 1) -> str:
    """单品件数 N>1 时存成 id 重复 N 次（まとめ的 ids 已去重，qty 恒 1）。"""
    vals = [int(i) for i in ids]
    if len(vals) == 1 and int(qty or 1) > 1:
        vals = vals * int(qty)
    return json.dumps(vals)


def loads_first_qty(raw: Any) -> int:
    """存储值里首个 id 连续重复的次数 = 单品件数（没有 / 解析失败为 1）。"""
    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return 1
    if not isinstance(vals, list) or not vals:
        return 1
    n = 0
    for v in vals:
        if v != vals[0]:
            break
        n += 1
    return max(1, n)


def loads_ids(raw: Any) -> List[int]:
    """存储值 → 仍然有效的库存 id（再过一遍 ``_resolve_inventory_id``：存进去之后可能被合并/删掉）。"""
    from .get_order.description_mgmt_ids import _resolve_inventory_id

    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    out: List[int] = []
    for v in vals if isinstance(vals, list) else []:
        try:
            rid = _resolve_inventory_id(int(v))
        except (TypeError, ValueError):
            continue
        if rid is not None and rid not in out:
            out.append(rid)
    return out


def listing_image_ids(item_id: str, photos: Any, *, bundle: bool) -> Tuple[List[int], Optional[str], int]:
    """items/get 的 ``photos`` → ``(库存 id, 要写回 on_sale_items.image_mgmt_ids 的值或 None, 件数)``。

    图片没变且解过 → 复用存储值，不重新下载；响应不带 ``photos``（雅虎伪响应 / 本地重关联）
    → 只读存储值。
    """
    from ..db_manage.database import DatabaseManager

    if not isinstance(photos, list):
        raw = _stored_on_sale_raw(item_id)
        return loads_ids(raw), None, loads_first_qty(raw)
    urls = [str(u).strip() for u in photos if isinstance(u, str) and str(u).strip()]
    iid = str(item_id or "").strip()
    rows = DatabaseManager().execute_query(
        "SELECT [photos_json], [image_mgmt_ids] FROM [on_sale_items] "
        "WHERE TRIM([item_id]) = ? ORDER BY COALESCE([is_delete], 0) ASC, [id] DESC LIMIT 1",
        (iid,),
    ) if iid else []
    if rows and rows[0][1] is not None:
        try:
            same = json.loads(rows[0][0] or "null") == urls
        except (TypeError, ValueError):
            same = False
        if same:
            return loads_ids(rows[0][1]), None, loads_first_qty(rows[0][1])
    ids, qty = decode_photo_mgmt(urls, bundle=bundle)
    return ids, dumps_ids(ids, qty), qty


def uncovered_bundle_titles(
    titles: List[str], image_ids: List[int], seller_id: Optional[str]
) -> List[str]:
    """まとめ商品：图片已认出的件之外，还要按「■ 商品内容」标题兜底的那几行。

    件数以说明里的标题数为准。某标题的候选库存里有一个图片已认出（且还没被别的同名标题认领）
    → 视为已覆盖；剩下的名额（标题数 − 图片件数）优先给**有候选库存**的标题：没有候选的标题
    本来就绑不上，它更可能正是某张已认出的图。没有图片结果时原样返回全部标题。
    """
    if not image_ids:
        return list(titles)
    from .get_order.description_mgmt_ids.inventory_resolve import _resolve_inventory_ids_by_bundle_title

    unclaimed = list(image_ids)
    rest: List[Tuple[str, bool]] = []
    for t in titles:
        cands = _resolve_inventory_ids_by_bundle_title(t, seller_id=seller_id)
        hit = next((c[0] for c in cands if c[0] in unclaimed), None)
        if hit is not None:
            unclaimed.remove(hit)
        else:
            rest.append((t, bool(cands)))
    left = max(0, len(titles) - len(image_ids))
    keep = {i for i, _ in sorted(enumerate(rest), key=lambda x: not x[1][1])[:left]}
    return [t for i, (t, _) in enumerate(rest) if i in keep]


def _stored_on_sale_raw(item_id: str) -> Optional[str]:
    from ..db_manage.database import DatabaseManager

    iid = str(item_id or "").strip()
    if not iid:
        return None
    rows = DatabaseManager().execute_query(
        "SELECT [image_mgmt_ids] FROM [on_sale_items] "
        "WHERE TRIM([item_id]) = ? AND [image_mgmt_ids] IS NOT NULL "
        "ORDER BY COALESCE([is_delete], 0) ASC, [id] DESC LIMIT 1",
        (iid,),
    )
    return rows[0][0] if rows else None


def stored_on_sale_image_ids(item_id: str) -> List[int]:
    return loads_ids(_stored_on_sale_raw(item_id))


def stored_order_image_mgmt(order_no: str) -> Tuple[List[int], int]:
    """订单的图片暗码 → (库存 id, 单品件数)：订单自己解过的优先（「获取商品说明」写入），
    否则用同一商品在售行的。"""
    from ..db_manage.database import DatabaseManager

    ono = str(order_no or "").strip()
    if not ono:
        return [], 1
    rows = DatabaseManager().execute_query(
        "SELECT [image_mgmt_ids] FROM [orders] WHERE [order_no] = ? LIMIT 1", (ono,)
    )
    if rows and rows[0][0] is not None:
        ids = loads_ids(rows[0][0])
        if ids:
            return ids, loads_first_qty(rows[0][0])
    raw = _stored_on_sale_raw(ono)
    return loads_ids(raw), loads_first_qty(raw)


def stored_order_image_ids(order_no: str) -> List[int]:
    return stored_order_image_mgmt(order_no)[0]
