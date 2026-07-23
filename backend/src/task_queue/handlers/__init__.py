# -*- coding: utf-8 -*-
"""任务处理器：每个 ``task_type`` 一个 ``async def handle_xxx(task: dict) -> Any``。

处理器只做三件事：拆 payload、桥接进度、调用**既有**业务函数。真正的自动化实现
（浏览器、MITM、字段填写）一行都没有搬过来，仍在 use_mercari / use_web / web_drive 下。

由 ``registry.resolve_handler`` 懒加载，避免与业务模块循环依赖。
"""
