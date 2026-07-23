# -*- coding: utf-8 -*-
"""任务队列页处理器。"""

from .tasks_handler import (
    cancel_task,
    get_task_detail,
    list_task_types,
    list_tasks_endpoint,
    retry_task,
    submit_task_endpoint,
    task_stats,
)

__all__ = [
    "cancel_task",
    "get_task_detail",
    "list_task_types",
    "list_tasks_endpoint",
    "retry_task",
    "submit_task_endpoint",
    "task_stats",
]
