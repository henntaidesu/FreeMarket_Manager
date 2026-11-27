# -*- coding: utf-8 -*-
"""煤炉「已打包」待办的「更改发送」：作废已发行的发货码，按新的尺寸 / 发货地重新出码。

就是把处理弹窗里原来要分两次点的两步串成一条任务：
``revise_shipping_after_qr``（「商品サイズや発送方法を修正する」→「変更する」，清掉本地码）
→ ``confirm_shipping_selection``（选尺寸 → 选发货地 → 完了 → 发行新码）。

只接受要选发货地的尺寸：ゆうパケットポスト 系发完是扫专用箱二维码，那要现场拍照，
不是一条能在后台跑完的任务。第二步失败时旧码已经作废、本地码已清，这一行会回到
「待发货」——报错里写明，让人在处理弹窗里重新发货。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .....db_manage.models.todos.todo_item import TodoItemModel
from .change_method import revise_shipping_after_qr
from .shipping_select import confirm_shipping_selection


async def change_shipping_after_qr(
    todo_id: int,
    class_text: str,
    facility: str,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    class_text = (class_text or "").strip()
    facility = (facility or "").strip()
    if not class_text or not facility:
        raise ValueError("更改发送需要指定尺寸与发货地")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    if not (getattr(todo, "qr_image_path", "") or "").strip():
        raise ValueError("该待办还没有发行发货码（不是「已打包」），不能更改发送")

    await revise_shipping_after_qr(int(todo_id), progress_job_id=progress_job_id)
    try:
        result = await confirm_shipping_selection(
            int(todo_id),
            class_text,
            facility,
            generate_code=True,
            progress_job_id=progress_job_id,
        )
    except Exception as exc:
        raise RuntimeError(
            f"原发货码已作废，但重新出码失败：{exc}。该待办已回到待发货，请在处理弹窗里重新发货"
        ) from exc
    if not result.get("qr_image_url"):
        raise RuntimeError(
            "原发货码已作废，已选好新的尺寸与发货地，但没读到新的发货码。请打开处理弹窗刷新抓取确认"
        )
    return result
