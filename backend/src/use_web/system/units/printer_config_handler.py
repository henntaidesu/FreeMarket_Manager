# -*- coding: utf-8 -*-
"""二维码打印参数：标签尺寸 / 打印质量等，存业务库 [config] 表。

蓝牙设备绑定（serviceUuid / charUuid / deviceId / deviceName）**不在这里**——那记录的是
「这台机器上的这个浏览器授权过哪个设备」，换台设备就没有意义，仍留在前端 localStorage。

这几个字段是一组、永远整体读写，所以存成一条 JSON 而不是一个字段一个键。
"""

import json
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, ValidationError

from ....db_manage.models.system.config_entry import ConfigEntryModel

_K_PRINTER = "qr_printer_params"


class PrinterParams(BaseModel):
    """字段与前端 utils/btPrinter/config.js 的 DEFAULTS 对应（设备绑定字段除外）。

    取值范围与设置页的 el-input-number 上下限保持一致。
    """

    labelWmm: float = Field(default=30, ge=10, le=100)
    labelHmm: float = Field(default=30, ge=10, le=100)
    threshold: int = Field(default=128, ge=10, le=245)
    # 纸张类型（德佟 SDK LPA_GapType）：0 连续纸 / 2 间隙纸 / 3 黑标纸。标签对位由打印机按它定位，
    # 不再有手动走纸 / 回卷参数——旧版存的 feedMm / retractMm / retractCmd 等字段读取时直接忽略
    gapType: Literal[0, 2, 3] = 2
    # 打印浓度（LPA_PrintDarkness）：1~15，255 = 随打印机设置
    darkness: int = Field(default=255, ge=1, le=255)


def _read() -> PrinterParams:
    raw = ConfigEntryModel.get_value(_K_PRINTER)
    if not raw:
        return PrinterParams()
    try:
        data: Any = json.loads(raw)
    except (ValueError, TypeError):
        return PrinterParams()
    if not isinstance(data, dict):
        return PrinterParams()
    try:
        return PrinterParams(**data)
    except ValidationError:
        # 手工改坏了、或旧版本写入的值越界 —— 回默认值，别让设置页打不开
        return PrinterParams()


def get_printer_params() -> PrinterParams:
    return _read()


def put_printer_params(body: PrinterParams) -> PrinterParams:
    """整体替换：请求体缺的字段按默认值落库，前端始终提交完整对象。"""
    payload: Dict[str, Any] = body.model_dump()
    ConfigEntryModel.set_value(_K_PRINTER, json.dumps(payload, ensure_ascii=False))
    return body
