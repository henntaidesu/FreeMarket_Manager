# -*- coding: utf-8 -*-
"""系统配置处理器：DeepSeek API 配置读写（对应前端「系统配置」页面）。

配置持久化到业务库 [config] 表（ConfigEntryModel），键名 / 默认值定义于
src/ai/deepseek_client.py，此处仅做接口层的读写与校验。
"""

from typing import Any, Optional

from pydantic import BaseModel, field_validator

from ....ai.deepseek_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    get_deepseek_settings,
    save_deepseek_settings,
)


class DeepSeekConfigOut(BaseModel):
    """系统配置回显。API Key 只回打码值（前缀 ••••+ 末 4 位），原样提交回来表示「不改」。"""

    api_key: str = ""
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL


class DeepSeekConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None

    @field_validator("api_key", "model", "base_url", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        if v is None:
            return None
        return str(v).strip()


_MASK_PREFIX = "••••"


def _mask(key: str) -> str:
    key = key or ""
    return f"{_MASK_PREFIX}{key[-4:]}" if key else ""


def _masked_out() -> DeepSeekConfigOut:
    cfg = dict(get_deepseek_settings())
    cfg["api_key"] = _mask(cfg.get("api_key") or "")
    return DeepSeekConfigOut(**cfg)


def get_deepseek_config() -> DeepSeekConfigOut:
    return _masked_out()


def put_deepseek_config(body: DeepSeekConfigUpdate) -> DeepSeekConfigOut:
    current = get_deepseek_settings().get("api_key") or ""
    api_key = body.api_key
    # 打码值原样回传 = 没改；None 同理
    if api_key is None or (api_key.startswith(_MASK_PREFIX) and api_key == _mask(current)):
        api_key = current or None
    save_deepseek_settings(
        api_key=api_key,
        model=body.model,
        base_url=body.base_url,
    )
    return _masked_out()
