# -*- coding: utf-8 -*-
"""单文件 exe 的解压目录：放在 exe 旁边、运行期间占住、启动时清掉上次的残留。

「FreeMarket Manager.exe」是 PyInstaller 的 onefile：每次启动由引导程序把 DLL、前端 webside、
Playwright 的 driver、mitm_addon.py、certifi 的 cacert.pem 等解压到 _MEIxxxx 再运行。默认解压在
%TEMP%，而存储感知 /「磁盘清理」的计划任务会删掉 %TEMP% 里放了 7 天左右的文件——程序挂着跑
一周，解压目录就被掏空：已加载的 DLL 被系统锁着删不掉，没锁的全没了。于是页面 500（index.html
不存在）、HTTPS 全挂（找不到 CA 证书包）、MITM 重启时找不到插件、晚加载的模块 import 失败，
进程却还活着，看起来就是「挂久了就死」。

所以分三层：

1. 解压到 exe 同目录的 runtime\\ 下（mercari.spec 的 runtime_tmpdir），和 system.db、data\\ 待在一起，
   系统清理不碰那里。写法是 %_PYI_ARCHIVE_FILE%\\..\\runtime：Windows 版引导程序会展开里面的
   环境变量，而它在算解压位置之前就把 exe 的完整路径放进了 _PYI_ARCHIVE_FILE，「exe 文件名\\..」
   经路径规范化折回 exe 所在目录。不能直接写相对路径 runtime：那是按当前工作目录算的（实测），
   restart.bat、开机自启、快捷方式改了起始位置就解到别处去了。
   _PYI_ARCHIVE_FILE 是 PyInstaller 内部用的变量，文档里没有。哪天升级后它没了，引导程序不会报错，
   只会悄悄解到「当前工作目录\\runtime」——所以有 bundle_in_place()，启动时对不上就在日志里报警告。
   代价是 exe 所在目录必须可写，放进 Program Files 这类目录会在启动时弹「无法创建临时目录」。
2. lock_bundle()：给每个文件开一个只读句柄持有到进程结束。Python 在 Windows 上开文件不带
   FILE_SHARE_DELETE，有这个句柄在，任何进程删它都是「另一个程序正在使用此文件」，读和执行都
   不受影响（Playwright 的 node.exe 照样能从这里起）。挡的是手动删 runtime 目录、第三方清理软件
   这类第 1 层管不到的东西，同时也是第 3 层判断「有没有人在用」的依据。
3. sweep_stale()：正常退出时引导程序会删掉自己的 _MEI，但被强杀、断电时来不及，不管的话
   每出一次事，程序目录里就多压一份上百 MB 的残留。

自调用充当 mitmdump 的子进程（MERCARI_RUN_MITMDUMP=1）不会另解压一份：PyInstaller 认出它是
同一个程序派生的，直接复用父进程的 _MEI（实测）。它也照样跑这两步，父进程意外先死时，
还活着的 mitmdump 不至于被引导程序的清理掏空。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time

# 持有到进程结束：列表里的对象一旦被回收，句柄就关了，文件又变回可删。
_handles: list = []
_swept = 0

# 与 mercari.spec 里 runtime_tmpdir 的最后一级同名，两边改要一起改。
_RUNTIME_DIR_NAME = "runtime"
# 最近有改动的目录可能是另一份正在解压、还没来得及占住文件的实例，留给下次再清。
_STALE_AFTER_SECONDS = 600


def _own_dir() -> str | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass or sys.platform != "win32":
        return None
    return os.path.normcase(os.path.abspath(meipass))


def _expected_parent() -> str:
    # onefile 的子进程里 sys.executable 就是 exe 本身，不是解压出来的什么东西。
    # 不用 app_paths.backend_root()：MERCARI_BACKEND_ROOT 能把它挪走，引导程序可不认这个变量。
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.normcase(os.path.join(exe_dir, _RUNTIME_DIR_NAME))


def bundle_in_place() -> bool:
    """解压目录是不是在 exe 旁边的 runtime\\ 里。开发态没有解压目录，算作是。"""
    own = _own_dir()
    return own is None or os.path.dirname(own) == _expected_parent()


def lock_bundle() -> int:
    """占住 sys._MEIPASS 下的全部文件，返回占住的个数。开发态没有解压目录，什么都不做。"""
    own = _own_dir()
    if own is None:
        return 0
    for dirpath, _dirnames, filenames in os.walk(own):
        for name in filenames:
            try:
                # buffering=0：要的只是句柄，别给上千个文件每个白占一块读缓冲。
                _handles.append(open(os.path.join(dirpath, name), "rb", buffering=0))
            except OSError:
                pass  # 个别文件打不开不影响其余的，大不了那一个回到原来的处境
    return len(_handles)


def sweep_stale() -> int:
    """删掉 runtime\\ 里上次没清掉的 _MEI*，返回删掉的个数。必须在 lock_bundle() 之后调。

    只在解压目录确实落在 exe 旁边时才动手：落到别处（见模块头第 1 条）时，那里的 _MEI* 可能是
    别的程序的，碰不得。

    「没人在用」靠先改名来判断：Windows 下目录里有文件开着就改不了名，而活着的实例都已经
    lock_bundle() 占住了自己的全部文件，所以改名成功的一定是死掉的那份。改名之后再删，
    删到一半出错也不会留下一个看着还完整、实际缺文件的目录。
    """
    global _swept
    own = _own_dir()
    if own is None or not bundle_in_place():
        return 0
    parent = os.path.dirname(own)
    removed = 0
    for name in os.listdir(parent):
        path = os.path.join(parent, name)
        if not name.startswith("_MEI") or os.path.normcase(path) == own or not os.path.isdir(path):
            continue
        # 已经是 .stale 的是上回改了名却没删干净的，直接删。
        doomed = path if name.endswith(".stale") else path + ".stale"
        try:
            if doomed != path:
                if time.time() - os.path.getmtime(path) < _STALE_AFTER_SECONDS:
                    continue
                os.rename(path, doomed)
        except OSError:
            continue  # 改不了名 = 还有实例在用
        shutil.rmtree(doomed, ignore_errors=True)
        if not os.path.exists(doomed):
            removed += 1
    _swept += removed
    return removed


def log_summary(log: logging.Logger) -> None:
    """把上面两步的结果打进日志。

    占住和清理必须在 main.py 最顶上做，那时 logging 还没配好（basicConfig 在 lifecycle 的启动
    事件里才跑，之前的 info 会被直接丢掉），所以结果先记在模块里，由 lifecycle 在日志就绪后调用。
    开发态什么都不打。
    """
    if _handles:
        log.info("已占住解压目录里的 %d 个文件，系统清理删不掉：%s", len(_handles), sys._MEIPASS)
    if not bundle_in_place():
        log.warning(
            "解压目录没落在 exe 旁边的 runtime 里，而是跟着当前工作目录跑了：%s"
            " —— 多半是升级 PyInstaller 后 _PYI_ARCHIVE_FILE 没了，见 src/meipass_lock.py",
            getattr(sys, "_MEIPASS", ""),
        )
    if _swept:
        log.info("已清掉 %d 份上次没退干净留下的解压目录", _swept)
