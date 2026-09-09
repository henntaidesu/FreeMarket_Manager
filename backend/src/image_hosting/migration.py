# -*- coding: utf-8 -*-
"""本地 ⇄ 图床的批量搬运作业。

**为什么切换是瞬时的，而搬运在后台慢慢跑。**
切换存储后端只是改一个配置键（新图片往哪写），和「几千张历史图片搬完了没有」是两件事。
所以流程是：先切后端 → 再在后台把积压的历史图片搬上去。这样

- 切换立即生效，不用等搬运，也不用重启（见 ``settings.reload``）；
- 搬运期间还没上去的图片没有映射行、继续走本地盘，页面上一张裂图都不会出现；
- 搬运途中新产生的图片直接写图床，不会漏掉。

**搬运是可重复的对账，不是一次性动作。** 判据是「本地还有文件、且没有映射行」，所以
中断后重跑只会处理剩下的；平时图床临时抽风导致留在本地的那些新图，再跑一次也会补上去。
图床侧用 ``external_key``（就是逻辑路径本身）保证幂等，重跑不会产生重复文件。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from . import assets, settings
from .client import ImageHostingClient, ImageHostingError

log = logging.getLogger(__name__)

#: 并发上传数。只有**网络上传**并发，映射行的写入始终回到主线程串行执行——
#: 业务库那边是一条 ``check_same_thread=False`` 的共享连接，多线程同时写它不安全。
_UPLOAD_WORKERS = 4

#: 错误列表上限。几千张图全失败时（比如 Token 填错），前端不需要几千条一模一样的信息。
_MAX_ERRORS = 100

_LOCK = threading.RLock()
_STATE: Dict[str, Any] = {
    "running": False,
    "direction": None,          # 'to_host' | 'to_local'
    "total": 0,
    "done": 0,
    "skipped": 0,
    "failed": 0,
    "current": "",
    "started_at": None,
    "finished_at": None,
    "cancelled": False,
    "message": "",
    "errors": [],
}


class MigrationBusyError(RuntimeError):
    """已有搬运作业在跑。"""


# ── 状态 ──────────────────────────────────────────────────────────────── #


def status() -> Dict[str, Any]:
    with _LOCK:
        state = dict(_STATE)
        state["errors"] = list(_STATE["errors"])
    total, done = state["total"], state["done"] + state["skipped"] + state["failed"]
    state["percent"] = round(done * 100 / total, 1) if total else (100.0 if state["finished_at"] else 0.0)
    return state


def _claim(direction: str) -> None:
    """占坑：**同步**把状态置为 running，然后才去开工作线程。

    两件事都靠它：
    - 防重复启动——「检查有没有在跑」和「标记成在跑」必须在同一个临界区里，分开做的话
      两个并发请求会双双通过检查；
    - 前端在 POST 返回后立刻开始轮询，此时工作线程可能还没跑起来。不先占坑的话，那一次
      轮询看到的是上一轮的 ``running: false``，前端当场停掉轮询，进度条再也不动。
    """
    with _LOCK:
        if _STATE["running"]:
            raise MigrationBusyError("已有图片搬运作业在进行中")
        _STATE.update(
            running=True, direction=direction, total=0, done=0, skipped=0,
            failed=0, current="", started_at=time.time(), finished_at=None,
            cancelled=False, message="正在统计待搬运的图片…", errors=[],
        )


def _release() -> None:
    """占坑之后、作业真正开始之前失败了，把坑让出来。"""
    with _LOCK:
        _STATE.update(running=False, finished_at=time.time())


def _begin(total: int) -> None:
    with _LOCK:
        _STATE["total"] = total
        _STATE["message"] = ""


def _note_error(rel_path: str, error: str) -> None:
    with _LOCK:
        _STATE["failed"] += 1
        if len(_STATE["errors"]) < _MAX_ERRORS:
            _STATE["errors"].append({"path": rel_path, "error": error})


def _finish(message: str) -> None:
    with _LOCK:
        _STATE.update(running=False, finished_at=time.time(), current="", message=message)


def request_cancel() -> bool:
    """请求停止。已经搬上去的部分保留（有映射行），不回滚——重跑会接着搬剩下的。"""
    with _LOCK:
        if not _STATE["running"]:
            return False
        _STATE["cancelled"] = True
        return True


def _cancelled() -> bool:
    with _LOCK:
        return _STATE["cancelled"]


# ── 工作集 ────────────────────────────────────────────────────────────── #


#: 不参与搬运的文件名前缀。``ship_qr_`` 是发货扫码那张照片——它是**短命的工作文件**，
#: 由 ``todos_sync/qr_photo.py`` 按绝对路径 open() 读取、任务跑完就删；搬上图床会让本地
#: 副本被删掉，那些 open() 当场失败。这也是它保存时带 ``local_only=True`` 的同一个理由。
_SKIP_PREFIXES = ("ship_qr_",)


def local_image_files() -> List[str]:
    """``imges/`` 下所有待搬运的图片，返回逻辑路径列表。

    只取顶层普通文件：``_thumbs/``（缩略图缓存）和 ``_mercari_cache/``（煤炉 CDN 图片缓存）
    是**按需重新生成的派生物**，把它们搬上图床既浪费带宽也毫无意义——本地删掉后下次访问
    会自动重建。

    这里按目录枚举而不是去七个业务列里把路径捞出来：目录是**超集**，包含所有被引用的图片
    加上一些孤儿文件。多传几张孤儿的代价，远小于漏掉某一列、让那批图片永远留在本地。
    """
    from ..use_web.image_storage import get_image_root

    root = get_image_root()
    if not os.path.isdir(root):
        return []
    names = []
    for name in os.listdir(root):
        if name.startswith((".", "_")) or name.startswith(_SKIP_PREFIXES):
            continue
        if os.path.isfile(os.path.join(root, name)):
            names.append(f"/imges/{name}")
    return sorted(names)


def pending_upload_paths() -> List[str]:
    """本地还有文件、但还没有映射行的那些——也就是「还没搬上去的」。"""
    candidates = local_image_files()
    already = assets.existing_rel_paths(candidates)
    return [path for path in candidates if path not in already]


def summary() -> Dict[str, Any]:
    """给设置页用的概览：本地多少张、图床上多少张、还差多少张没搬。"""
    local_files = local_image_files()
    already = assets.existing_rel_paths(local_files)
    total_bytes = 0
    from ..use_web.image_storage import get_image_root

    root = get_image_root()
    for path in local_files:
        if path in already:
            continue
        try:
            total_bytes += os.path.getsize(os.path.join(root, path.split("/imges/", 1)[1]))
        except OSError:
            continue
    return {
        "local_files": len(local_files),
        "remote_records": assets.remote_count(),
        "pending_upload": len(local_files) - len(already),
        "pending_bytes": total_bytes,
    }


# ── 上行：本地 → 图床 ─────────────────────────────────────────────────── #


def _upload_one(rel_path: str, root: str) -> Dict[str, Any]:
    """在工作线程里跑：只做读文件 + 上传，绝不碰数据库。"""
    filename = rel_path.split("/imges/", 1)[1]
    abs_path = os.path.join(root, filename)
    with open(abs_path, "rb") as f:
        content = f.read()
    from ..use_web.image_storage import content_type_for

    payload = ImageHostingClient().upload(
        filename=filename,
        content=content,
        content_type=content_type_for(filename),
        external_key=rel_path,
    )
    payload["_local_size"] = len(content)
    return payload


def _run_to_host() -> None:
    from ..use_web.image_storage import get_image_root

    root = get_image_root()
    targets = pending_upload_paths()
    _begin(len(targets))
    if not targets:
        _finish("没有需要搬运的图片，本地图片已全部在图床上。")
        return

    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        for start in range(0, len(targets), _UPLOAD_WORKERS):
            if _cancelled():
                break
            batch = targets[start:start + _UPLOAD_WORKERS]
            futures = [(path, pool.submit(_upload_one, path, root)) for path in batch]
            for rel_path, future in futures:
                with _LOCK:
                    _STATE["current"] = rel_path
                try:
                    payload = future.result()
                except FileNotFoundError:
                    # 搬运期间这张图被删了：不是错误，跳过即可
                    with _LOCK:
                        _STATE["skipped"] += 1
                    continue
                except (ImageHostingError, OSError) as exc:
                    _note_error(rel_path, str(exc))
                    continue
                # 回到主线程串行写映射 + 删本地副本（顺序不能反：先删本地再写行，
                # 中间崩一次就既没有本地文件也没有映射行，这张图彻底找不回来）
                try:
                    assets.record_remote(
                        rel_path,
                        slug=payload.get("project") or "",
                        stored_name=payload["stored_name"],
                        url=payload["url"],
                        size=payload.get("size") or payload["_local_size"],
                        sha256=payload.get("sha256"),
                    )
                except Exception as exc:  # noqa: BLE001
                    _note_error(rel_path, f"写映射失败：{exc}")
                    continue
                try:
                    os.remove(os.path.join(root, rel_path.split("/imges/", 1)[1]))
                except OSError as exc:
                    log.warning("已搬到图床但本地副本删除失败 %s：%s", rel_path, exc)
                with _LOCK:
                    _STATE["done"] += 1

    state = status()
    if state["cancelled"]:
        _finish(f"已停止。成功 {state['done']} 张，失败 {state['failed']} 张，剩余部分仍在本地。")
    elif state["failed"]:
        _finish(f"搬运完成，成功 {state['done']} 张，失败 {state['failed']} 张（失败的仍在本地，可再次运行）。")
    else:
        _finish(f"搬运完成，共 {state['done']} 张图片已迁移到图床。")


# ── 下行：图床 → 本地（回迁） ─────────────────────────────────────────── #


def _run_to_local(delete_remote: bool) -> None:
    from ..use_web.image_storage import get_image_root

    root = get_image_root()
    os.makedirs(root, exist_ok=True)
    rows = assets.all_remote_rows()
    _begin(len(rows))
    if not rows:
        _finish("图床上没有需要回迁的图片。")
        return

    client = ImageHostingClient()
    for row in rows:
        if _cancelled():
            break
        rel_path = row["rel_path"]
        with _LOCK:
            _STATE["current"] = rel_path
        filename = rel_path.split("/imges/", 1)[1]
        abs_path = os.path.join(root, filename)
        try:
            content = client.fetch_bytes(row["remote_url"])
        except ImageHostingError as exc:
            _note_error(rel_path, str(exc))
            continue
        try:
            # 先写临时文件再改名：中途断电不会留下一个半截的、看起来却像完整图片的文件
            temporary = f"{abs_path}.downloading"
            with open(temporary, "wb") as f:
                f.write(content)
            os.replace(temporary, abs_path)
        except OSError as exc:
            _note_error(rel_path, f"写本地文件失败：{exc}")
            continue
        # 本地文件到位之后才删映射行——此刻这张图两边都有，删行只是把读取切回本地
        assets.forget(rel_path)
        if delete_remote:
            try:
                client.delete(row["remote_name"])
            except ImageHostingError as exc:
                log.warning("回迁后删除图床副本失败 %s：%s", rel_path, exc)
        with _LOCK:
            _STATE["done"] += 1

    state = status()
    tail = "，图床副本已删除" if delete_remote else "，图床副本已保留"
    if state["cancelled"]:
        _finish(f"已停止。已回迁 {state['done']} 张，失败 {state['failed']} 张。")
    else:
        _finish(f"回迁完成，共 {state['done']} 张图片已回到本地{tail}。失败 {state['failed']} 张。")


# ── 对外入口 ──────────────────────────────────────────────────────────── #


def _spawn(target, *args) -> None:
    def runner():
        try:
            target(*args)
        except Exception as exc:  # noqa: BLE001
            log.exception("图片搬运作业异常终止")
            _finish(f"作业异常终止：{exc}")

    threading.Thread(target=runner, name="image-migration", daemon=True).start()


def start_to_host(activate: bool = True) -> Dict[str, Any]:
    """把本地历史图片搬到图床。``activate=True`` 时**先**把存储后端切到图床。

    先切后搬是有意的：切换只影响「新图片往哪写」，立刻生效且不需要重启；搬运期间产生的
    新图直接进图床，不会变成下一批积压。还没搬上去的老图没有映射行、继续走本地，全程可读。
    """
    if not settings.is_configured():
        raise ValueError("图床连接信息不完整，请先填写并测试连接")
    # 先探一次：连不上就别开始搬，否则用户看到的是几千条一模一样的失败。
    # 放在占坑之前——探测失败时状态还没被改动，不必回滚。
    ImageHostingClient().ping()
    _claim("to_host")
    try:
        if activate:
            settings.set_backend(settings.BACKEND_REMOTE)
            assets.clear_cache()
    except Exception:
        _release()
        raise
    _spawn(_run_to_host)
    return {"started": True, "backend": settings.active_backend()}


def start_to_local(delete_remote: bool = False, activate: bool = True) -> Dict[str, Any]:
    """把图床上的图片全部拉回本地。``activate=True`` 时先把存储后端切回本地。"""
    if not settings.is_configured():
        raise ValueError("图床连接信息不完整，无法回迁")
    ImageHostingClient().ping()
    _claim("to_local")
    try:
        if activate:
            settings.set_backend(settings.BACKEND_LOCAL)
            assets.clear_cache()
    except Exception:
        _release()
        raise
    _spawn(_run_to_local, delete_remote)
    return {"started": True, "backend": settings.active_backend()}
