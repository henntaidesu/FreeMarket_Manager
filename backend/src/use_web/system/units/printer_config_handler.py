# -*- coding: utf-8 -*-
"""二维码打印参数：标签尺寸 / 打印质量等，存业务库 [config] 表。

蓝牙设备绑定（serviceUuid / charUuid / deviceId / deviceName）**不在这里**——那记录的是
「这台机器上的这个浏览器授权过哪个设备」，换台设备就没有意义，仍留在前端 localStorage。

九个字段是一组、永远整体读写，所以存成一条 JSON 而不是九个键。
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
    headMm: float = Field(default=48, ge=20, le=110)
    dpi: int = Field(default=203, ge=100, le=600)
    chunk: int = Field(default=180, ge=20, le=512)
    threshold: int = Field(default=128, ge=10, le=245)
    density: int = Field(default=10, ge=1, le=31)
    feedMm: float = Field(default=15, ge=0, le=60)
    retractMm: float = Field(default=0, ge=0, le=60)
    # 定位方式：ff / gsff 交给打印机的间隔纸传感器自动走位（此时 feedMm、retractMm 都不生效）；
    # escK / escE / tspl 是打印前手动回缩。各家固件实现不同，需实测选
    # （德佟 P2 实测：escK 执行成了向前走纸）
    retractCmd: Literal["ff", "gsff", "escK", "escE", "tspl"] = "escK"


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
