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
    """系统配置回显（API Key 明文回显，仅登录后可见）。"""

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


def get_deepseek_config() -> DeepSeekConfigOut:
    return DeepSeekConfigOut(**get_deepseek_settings())


def put_deepseek_config(body: DeepSeekConfigUpdate) -> DeepSeekConfigOut:
    save_deepseek_settings(
        api_key=body.api_key,
        model=body.model,
        base_url=body.base_url,
    )
    return DeepSeekConfigOut(**get_deepseek_settings())
