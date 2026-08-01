# -*- coding: utf-8 -*-
"""EdgeWebDriveManager 生命周期/启动配置：锁 / Playwright / 缓存清理 / shutdown"""
from __future__ import annotations

import asyncio
import os
import shutil
import threading
from contextlib import asynccontextmanager
from typing import Any, List
from ..interactive_tab_state import save_snapshot_from_context
from ._config import _DriveThreadState


class _LifecycleMixin:

    @classmethod
    def _outer_lock_for_profile(cls, account_key: str) -> threading.Lock:
        with cls._profile_outer_locks_guard:
            if account_key not in cls._profile_outer_locks:
                cls._profile_outer_locks[account_key] = threading.Lock()
            return cls._profile_outer_locks[account_key]


    @staticmethod
    def _profile_release_delay_sec() -> float:
        try:
            return float((os.environ.get("WEB_DRIVE_PROFILE_RELEASE_DELAY_SEC") or "0.45").strip())
        except ValueError:
            return 0.45


    @staticmethod
    def _interactive_no_viewport() -> bool:
        """有头交互会话：不固定 viewport，窗口可最大化并随用户拖拽改变大小。"""
        v = (os.environ.get("WEB_DRIVE_INTERACTIVE_NO_VIEWPORT") or "1").strip().lower()
        return v not in ("0", "false", "no", "off")


    @staticmethod
    def _interactive_launch_args() -> List[str]:
        return [
            "--start-maximized",
            "--disable-features=RestoreSession",
        ]


    @staticmethod
    async def _apply_image_block_route(context: Any, *, block_images: bool) -> None:
        """按需为 context 注册「图片资源 abort」路由（减轻带宽与页面渲染耗时）。

        与 ``--blink-settings=imagesEnabled=false`` 启动参数配合：启动参数让 Chromium 不再
        发起图片请求，路由 abort 兜底拦截那些通过 fetch/xhr 等非 ``<img>`` 路径的图片资源。
        """
        if not block_images:
            return

        async def _block(route: Any) -> None:
            if route.request.resource_type == "image":
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _block)


    @staticmethod
    def _launch_retry_delays_sec() -> List[float]:
        raw = (os.environ.get("WEB_DRIVE_LAUNCH_RETRY_DELAYS_SEC") or "0,0.7,1.4").strip()
        out: List[float] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError:
                pass
        return out if out else [0.0, 0.7, 1.4]


    @asynccontextmanager
    async def _serialize_profile(self, account_key: str):
        """按 profile 串行化。在线程里抢 ``threading.Lock``，避免阻塞事件循环。

        ⚠️ 这里必须能扛住**取消**。原写法是 ``await asyncio.to_thread(lock.acquire)``：
        取消只会取消那个 future，**工作线程仍在跑 ``lock.acquire()``**，随后拿到锁并返回——
        而 ``try/finally`` 压根没开始，没有任何人会 release。结果是这个账号的 profile
        永久死锁，之后所有针对它的浏览器操作（同步/出品/待办）全部无限等待，只能重启进程。
        取消在本项目里是常态：关停 worker、用户中断执行中的任务、``wait_for`` 超时都会取消。

        改法：带超时地轮询抢锁，并且**在线程内**把「抢到了」记进 ``holder``——这样即便取消
        恰好落在线程返回与赋值之间，下面的 CancelledError 分支也能凭 holder 把锁还回去。
        """
        lock = self._outer_lock_for_profile(account_key)
        holder: list = []

        def _try_acquire() -> bool:
            # 先记录再返回：holder 的写入发生在线程内，不受协程被取消的影响
            if lock.acquire(True, 0.2):
                holder.append(True)
                return True
            return False

        try:
            while not holder:
                await asyncio.to_thread(_try_acquire)
        except BaseException:
            if holder:
                lock.release()
                holder.clear()
            raise

        try:
            yield
        finally:
            if holder:
                holder.clear()
                lock.release()


    def _ts(self) -> _DriveThreadState:
        s = getattr(self._tls, "state", None)
        if s is None:
            s = _DriveThreadState()
            self._tls.state = s
        return s


    def _prepare_async(self) -> _DriveThreadState:
        """在 async 方法开头调用：确保本线程有 asyncio.Lock（绑定当前运行中的 loop）。"""
        s = self._ts()
        if s.lock is None:
            s.lock = asyncio.Lock()
        return s


    @staticmethod
    def _drop_stale_playwright(s: _DriveThreadState, running: asyncio.AbstractEventLoop) -> None:
        """本线程内：当前 loop 与创建 Playwright 时不一致则丢弃缓存（常见于连续多次 asyncio.run）。"""
        if s.playwright is None:
            s.playwright_loop = None
            return
        if s.playwright_loop is running:
            return
        s.playwright = None
        s.playwright_loop = None


    async def _ensure_playwright(self, s: _DriveThreadState) -> Any:
        running = asyncio.get_running_loop()
        self._drop_stale_playwright(s, running)

        if s.playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 playwright，请在 backend 目录执行: pip install playwright && playwright install msedge"
                ) from exc
            s.playwright = await async_playwright().start()
            s.playwright_loop = running

        return s.playwright


    @staticmethod
    def _purge_non_auth_cache(user_data_dir: str) -> None:
        """清理浏览器运行期缓存，尽量保留登录态相关数据（cookies/local storage/indexeddb）。"""
        if not user_data_dir or not os.path.isdir(user_data_dir):
            return

        targets = [
            os.path.join(user_data_dir, "Default", "Cache"),
            os.path.join(user_data_dir, "Default", "Code Cache"),
            os.path.join(user_data_dir, "Default", "GPUCache"),
            os.path.join(user_data_dir, "Default", "DawnCache"),
            os.path.join(user_data_dir, "Default", "DawnGraphiteCache"),
            os.path.join(user_data_dir, "Default", "DawnWebGPUCache"),
            os.path.join(user_data_dir, "Default", "Service Worker", "CacheStorage"),
            os.path.join(user_data_dir, "Default", "Media Cache"),
            os.path.join(user_data_dir, "GrShaderCache"),
            os.path.join(user_data_dir, "ShaderCache"),
        ]
        for p in targets:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                # 清理失败不影响浏览器启动
                pass

        # 这类文件不影响登录态，但可减少站点缓存/状态噪音
        files = [
            os.path.join(user_data_dir, "Default", "Network Action Predictor"),
            os.path.join(user_data_dir, "Default", "Network Action Predictor-journal"),
        ]
        for f in files:
            try:
                if os.path.isfile(f):
                    os.remove(f)
            except Exception:
                pass


    async def shutdown(self) -> None:
        """关闭当前线程内的所有会话与 Playwright（仅影响调用方所在线程）。"""
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            for key in list(s.contexts.keys()):
                ctx = s.contexts.get(key)
                meta = self._session_meta(s, key)
                if (
                    ctx is not None
                    and meta.get("interactive")
                    and self._is_context_alive(ctx)
                ):
                    try:
                        await save_snapshot_from_context(key, ctx)
                    except Exception:
                        pass
            for key in list(s.contexts.keys()):
                ctx = s.contexts.pop(key, None)
                if ctx is not None:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
            s.session_meta.clear()
            if s.playwright is not None:
                try:
                    await s.playwright.stop()
                except Exception:
                    pass
                s.playwright = None
                s.playwright_loop = None
            s.lock = None
