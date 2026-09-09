# -*- coding: utf-8 -*-
"""图片搜索后台索引线程。

- 启动时全量对账：inventory 现存图片 vs 已索引向量，补算缺失、清理孤儿
- 库存增删改图片后通过 enqueue_inventory() 增量更新（只入队，不阻塞请求）
- 逐张低速处理（批间 sleep + 推理线程受限），不抢占弱机器 CPU
"""

from __future__ import annotations

import io
import json
import logging
import queue
import threading
import time
from typing import Dict, Optional

from PIL import Image

from ....db_manage.database import DatabaseManager
from ...image_storage import read_image_bytes
from . import index_store
from .embedder import embed_image, get_load_error

logger = logging.getLogger(__name__)

db = DatabaseManager()

_FULL_RECONCILE = -1  # 队列哨兵：全量对账

_queue: "queue.Queue[int]" = queue.Queue()
_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()

_status_lock = threading.Lock()
_status = {"state": "idle", "total": 0, "done": 0, "message": ""}


def _set_status(state: str, total: int = 0, done: int = 0, message: str = "") -> None:
    with _status_lock:
        _status.update({"state": state, "total": total, "done": done, "message": message})


def get_status() -> dict:
    with _status_lock:
        s = dict(_status)
    s["indexed_count"] = index_store.indexed_count()
    return s


def enqueue_inventory(inventory_id: int) -> None:
    """库存图片变更后调用：异步增量更新该商品的向量索引。"""
    try:
        _queue.put_nowait(int(inventory_id))
    except Exception:
        pass


def enqueue_full_reconcile() -> None:
    _queue.put_nowait(_FULL_RECONCILE)


def _paths_from_images_json(images_json) -> list:
    """与 inventory_helpers._inventory_paths_from_parsed_row 同口径，避免循环导入做了精简拷贝。"""
    if images_json and str(images_json).strip():
        try:
            data = json.loads(images_json)
            if isinstance(data, list):
                out = [str(x).strip() for x in data if x is not None and str(x).strip()]
                if out:
                    return out
        except Exception:
            pass
    return []


def _desired_paths(where_sql: str = "", params: tuple = ()) -> Dict[str, int]:
    """现存库存（未删除）应被索引的 {image_path: inventory_id}。"""
    rows = db.execute_query(
        "SELECT id, images_json FROM [inventory] "
        f"WHERE COALESCE(is_delete, 0) = 0 {where_sql}",
        params,
    )
    desired: Dict[str, int] = {}
    for pid, images_json in rows or []:
        for p in _paths_from_images_json(images_json):
            if p.startswith("/imges/"):
                desired[p] = int(pid)
    return desired


def _embed_path(path: str, inventory_id: int) -> bool:
    # read_image_bytes 本地/图床都能读：图片搬到图床后本地已经没有可 open() 的文件，
    # 但建索引必须真正看到像素，绕不开把字节取回来这一步。
    content = read_image_bytes(path)
    if content is None:
        return False
    try:
        with Image.open(io.BytesIO(content)) as img:
            vec = embed_image(img)
    except RuntimeError:
        raise  # 模型不可用，向上传递终止本轮
    except Exception as exc:
        logger.warning("[image_search] 图片向量化失败 %s: %s", path, exc)
        return False
    index_store.upsert_vector(inventory_id, path, vec)
    return True


def _process(task_pid: int) -> None:
    if task_pid == _FULL_RECONCILE:
        desired = _desired_paths()
        indexed = index_store.list_indexed_paths()
        index_store.delete_other_models()
    else:
        desired = _desired_paths(" AND id = ?", (task_pid,))
        indexed = {
            p: i for p, i in index_store.list_indexed_paths().items() if i == task_pid
        }

    stale = [p for p in indexed if p not in desired]
    if stale:
        index_store.delete_paths(stale)
    missing = [(p, pid) for p, pid in desired.items() if p not in indexed]
    if not missing:
        _set_status("idle")
        return

    total = len(missing)
    _set_status("indexing", total=total, done=0)
    logger.info("[image_search] 开始建立图片索引：%d 张", total)
    failed = 0
    for i, (path, pid) in enumerate(missing, 1):
        if not _embed_path(path, pid):
            failed += 1
        _set_status("indexing", total=total, done=i)
        time.sleep(0.02)  # 让出 CPU，弱机器上不影响正常请求
    _set_status("idle")
    # _embed_path 的返回值以前被丢弃，失败的图片既不留痕也不会退出候选集合——
    # 每次全量对账都会把同一批坏图重算一遍，而日志里只说「完成 N 张」。
    if failed:
        logger.warning(
            "[image_search] 图片索引完成：%d 张，其中 %d 张失败（文件缺失/无法解码），"
            "下次全量对账会再试一遍",
            total, failed,
        )
    else:
        logger.info("[image_search] 图片索引完成：%d 张", total)


def _worker() -> None:
    while True:
        task = _queue.get()
        try:
            _process(task)
        except RuntimeError as exc:
            # 模型下载/加载失败：标记错误，下次入队（或重新搜索）时重试
            _set_status("error", message=str(get_load_error() or exc))
            logger.warning("[image_search] 索引中止：%s", exc)
        except Exception:
            _set_status("error", message="索引过程出现未知错误")
            logger.exception("[image_search] 索引任务异常")
        finally:
            _queue.task_done()


def start_indexer() -> None:
    """启动后台索引线程（幂等），并触发一次全量对账。"""
    global _thread
    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="image-search-indexer", daemon=True)
            _thread.start()
    enqueue_full_reconcile()
