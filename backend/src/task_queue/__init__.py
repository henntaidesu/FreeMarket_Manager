# -*- coding: utf-8 -*-
"""任务队列：把重型煤炉自动化操作从 HTTP 请求内同步执行，改为后台串行执行。

原来「出品 / 更新列表 / 更新状态 / 在售同步 / 全量更新 / 改价 / 一键好评 / 一键确认发送」
都在请求里跑到底，前端弹全屏遮罩等几分钟，关页面即失联。现在统一走这里：
提交任务立刻返回 → 全局单 worker 串行执行 → 前端在 /#/tasks 查看状态。

模块分工::

    store.py         task_queue 表的入队/占用/收尾/查询，两把唯一索引负责防重复提交
    registry.py      task_type → 处理器/展示名/去重键/标题
    handlers/        各操作的薄封装，只拆参数+桥接进度，业务实现仍在原处
    worker.py        全局单 worker 循环
    reservations.py  出品「可上架」预扣减台账
    progress.py      把既有内存进度桥接到任务行
    submit.py        统一入队入口（校验 task_type、补标题/账号、出品预扣减）

对外只用本文件导出的这些名字，不要直接 import 子模块的内部函数。
"""

from .registry import known_types
from .store import (
    TaskDuplicateError,
    cancel_pending,
    get_stats,
    get_task,
    has_active_tasks,
    list_tasks,
)
from .submit import submit_task
from .worker import start_worker, stop_worker


def has_pending_listing_tasks() -> bool:
    """队列中是否还有等待/正在执行的出品任务。

    自动同步循环用它决定是否让路：出品还没跑完就去同步在售，会把「预扣减尚未核销」的
    中间态当成最终态，也违背「刷新库存要等出品全部完成」的约定。
    """
    from .registry import INVENTORY_LISTING

    return has_active_tasks(INVENTORY_LISTING)


__all__ = [
    "TaskDuplicateError",
    "cancel_pending",
    "get_stats",
    "get_task",
    "has_active_tasks",
    "has_pending_listing_tasks",
    "known_types",
    "list_tasks",
    "start_worker",
    "stop_worker",
    "submit_task",
]
