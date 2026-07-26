# -*- coding: utf-8 -*-
"""
任务队列表 [task_queue]：把「出品 / 订单更新 / 在售同步 / 改价 / 待办批量」等重型煤炉自动化
操作从 HTTP 请求内同步执行，改为提交任务 → 后台全局单 worker 串行执行。

状态流转（终态不可逆）：
    pending ──claim──> running ──> success | failed
       └──cancel──> canceled

防重复提交两把唯一索引：
  · ``client_token``     前端一次点击生成的 UUID。双击 / axios 重发 → 插入冲突 → 返回同一条任务。
  · ``active_dedup_key`` 语义去重键（如 ``orders.sync_new_data``），仅在非终态时有值；
    进入终态时置 NULL。SQLite 与 MySQL 的唯一索引均不比较 NULL，因此终态后同键可再次入队，
    无需 partial index，两端行为一致。
"""

import time
from typing import Any, Dict, List

from ...base_model import BaseModel

# 非终态：占用 active_dedup_key、参与「队列中是否还有出品任务」判断
PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
CANCELED = "canceled"

ACTIVE_STATUSES = (PENDING, RUNNING)
TERMINAL_STATUSES = (SUCCESS, FAILED, CANCELED)


class TaskQueueModel(BaseModel):
    """task_queue：一行一个后台任务。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "task_queue"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 任务类型，见 src/task_queue/registry.py，如 'inventory.listing'
            "task_type": {"type": "TEXT", "not_null": True, "default": None, "max_length": 64},
            # 中文展示名，如「出品：XXX（¥1200）」
            "title": {"type": "TEXT", "not_null": False, "default": None},
            "status": {"type": "TEXT", "not_null": True, "default": "'pending'", "max_length": 16},
            # handler 入参 JSON
            "payload": {"type": "TEXT", "not_null": False, "default": None},
            # 执行结果 JSON（原 HTTP 响应的 data）
            "result": {"type": "TEXT", "not_null": False, "default": None},
            # 失败原因
            "error": {"type": "TEXT", "not_null": False, "default": None},
            # 执行中的当前步骤（worker 写入，任务页轮询展示）
            "progress_step": {"type": "TEXT", "not_null": False, "default": None},
            "progress_label": {"type": "TEXT", "not_null": False, "default": None},
            # 关联煤炉账号（可空，用于筛选/展示）
            "account_id": {"type": "INTEGER", "not_null": False, "default": None},
            # 冗余账号名：账号删除后任务记录仍可展示
            "account_name": {"type": "TEXT", "not_null": False, "default": None},
            # 前端一次点击生成的 UUID（唯一，绝对幂等）
            "client_token": {"type": "TEXT", "not_null": False, "default": None, "max_length": 128},
            # 语义去重键：非终态时有值，终态置 NULL（唯一）
            "active_dedup_key": {"type": "TEXT", "not_null": False, "default": None, "max_length": 191},
            # 本任务当前仍占用的「可上架预扣减」件数（仅 inventory.listing 用）。
            # 入队时 = len(payload.inventory_ids)；被在售同步核销 / 失败释放 / TTL 兜底后归 0。
            # 详见 src/task_queue/reservations.py
            "reserved_qty": {"type": "INTEGER", "not_null": True, "default": 0},
            # 仍被占用的库存 id JSON 列表（与 reserved_qty 同步维护）：核销时移除对应 id，
            # 释放时按此精确归还。多商品出品任务部分核销后，靠 reserved_qty 数量切片会
            # 释放错库存（已核销的被再放一次、未核销的永久卡住）。NULL（历史行）时回退切片。
            "reserved_ids": {"type": "TEXT", "not_null": False, "default": None},
            # 提交者
            "user_id": {"type": "INTEGER", "not_null": False, "default": None},
            "username": {"type": "TEXT", "not_null": False, "default": None},
            # unix 秒
            "created_at": {"type": "INTEGER", "not_null": True, "default": 0},
            "started_at": {"type": "INTEGER", "not_null": False, "default": None},
            "finished_at": {"type": "INTEGER", "not_null": False, "default": None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_task_queue_status", "columns": ["status"]},
            {"name": "idx_task_queue_created_at", "columns": ["created_at"]},
            {"name": "idx_task_queue_task_type", "columns": ["task_type"]},
            {"name": "idx_task_queue_account_id", "columns": ["account_id"]},
            {"name": "idx_task_queue_reserved_qty", "columns": ["reserved_qty"]},
            {
                "name": "idx_task_queue_client_token",
                "columns": ["client_token"],
                "unique": True,
            },
            {
                "name": "idx_task_queue_active_dedup",
                "columns": ["active_dedup_key"],
                "unique": True,
            },
        ]


def now_ts() -> int:
    """统一的 unix 秒时间戳（与 system_logs.created_at 口径一致）。"""
    return int(time.time())
