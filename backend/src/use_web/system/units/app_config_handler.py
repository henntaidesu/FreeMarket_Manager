# -*- coding: utf-8 -*-
"""应用配置处理器：出品默认值读写 + 自动出品总开关。"""

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from ....db_manage.models.system.config_entry import ConfigEntryModel

# 系统出品默认值：手动出品表单预填用（发货地/配送/快递费负担/发货天数）
# + 默认出品图片（1=有水印，0=无水印）。自动出品（补挂）不读这些默认，只用商品自身保存值。
_K_SHIP_FROM = "listing_defaults_shipping_from_area_id"
_K_SHIP_METHOD = "listing_defaults_shipping_method"
_K_SHIP_PAYER = "listing_defaults_shipping_payer"
_K_SHIP_DAYS = "listing_defaults_shipping_days"
_K_WATERMARK = "listing_defaults_watermark"

_ALLOWED_METHODS = frozenset({"undecided", "rakuraku", "yuuyu", "tanome", "regular_mail"})
_ALLOWED_PAYERS = frozenset({"seller", "buyer"})
_ALLOWED_DAYS = frozenset({"1_2_days", "2_3_days", "4_7_days"})


class ListingDefaultsOut(BaseModel):
    """手动出品表单默认值（发货地为煤炉 area id 字符串）+ 默认出品图片。"""

    shipping_from_area_id: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    # 默认出品图片：1=有水印，0=无水印
    watermark: int = 1


class ListingDefaultsUpdate(BaseModel):
    shipping_from_area_id: Optional[str] = Field(default=None, max_length=8)
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    watermark: Optional[int] = None

    @field_validator("shipping_from_area_id", mode="before")
    @classmethod
    def strip_area(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator(
        "shipping_method", "shipping_payer", "shipping_days",
        mode="before",
    )
    @classmethod
    def strip_opt(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


def _read_listing_defaults() -> Dict[str, Any]:
    raw_watermark = ConfigEntryModel.get_value(_K_WATERMARK)
    watermark = 1
    if raw_watermark is not None:
        try:
            watermark = 0 if int(str(raw_watermark).strip()) == 0 else 1
        except ValueError:
            watermark = 1
    return {
        "shipping_from_area_id": ConfigEntryModel.get_value(_K_SHIP_FROM),
        "shipping_method": ConfigEntryModel.get_value(_K_SHIP_METHOD),
        "shipping_payer": ConfigEntryModel.get_value(_K_SHIP_PAYER),
        "shipping_days": ConfigEntryModel.get_value(_K_SHIP_DAYS),
        "watermark": watermark,
    }


class MgmtCipherModeOut(BaseModel):
    """管理番号暗号编码模式：'binary'（二进制 ◇◆）/ 'base5'（五进制 -=~<>）。"""

    mode: str


class MgmtCipherModeUpdate(BaseModel):
    mode: str


def get_mgmt_cipher_mode():
    from ....use_mercari.mgmt_id_cipher import get_cipher_mode

    return MgmtCipherModeOut(mode=get_cipher_mode())


def put_mgmt_cipher_mode(body: MgmtCipherModeUpdate):
    mode = (body.mode or "").strip().lower()
    if mode not in ("binary", "base5"):
        raise HTTPException(status_code=400, detail=f"无效的 mode: {body.mode}")
    from ....use_mercari.mgmt_id_cipher import MGMT_CIPHER_MODE_KEY

    # base5 为默认：存空即删除该键；binary 显式写入
    ConfigEntryModel.set_value(MGMT_CIPHER_MODE_KEY, "binary" if mode == "binary" else None)
    return MgmtCipherModeOut(mode=mode)


def get_listing_defaults():
    return ListingDefaultsOut(**_read_listing_defaults())


def put_listing_defaults(body: ListingDefaultsUpdate):
    data = body.model_dump(exclude_unset=True)

    if "shipping_method" in data:
        v = data["shipping_method"]
        if v is not None and v not in _ALLOWED_METHODS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_method: {v}")

    if "shipping_payer" in data:
        v = data["shipping_payer"]
        if v is not None and v not in _ALLOWED_PAYERS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_payer: {v}")

    if "shipping_days" in data:
        v = data["shipping_days"]
        if v is not None and v not in _ALLOWED_DAYS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_days: {v}")

    if "watermark" in data:
        v = data["watermark"]
        if v is not None and int(v) not in (0, 1):
            raise HTTPException(status_code=400, detail=f"无效的 watermark: {v}")

    if "shipping_from_area_id" in data:
        ConfigEntryModel.set_value(_K_SHIP_FROM, data["shipping_from_area_id"])
    if "shipping_method" in data:
        ConfigEntryModel.set_value(_K_SHIP_METHOD, data["shipping_method"])
    if "shipping_payer" in data:
        ConfigEntryModel.set_value(_K_SHIP_PAYER, data["shipping_payer"])
    if "shipping_days" in data:
        ConfigEntryModel.set_value(_K_SHIP_DAYS, data["shipping_days"])
    if "watermark" in data:
        v = data["watermark"]
        ConfigEntryModel.set_value(
            _K_WATERMARK, None if v is None else str(0 if int(v) == 0 else 1)
        )

    return ListingDefaultsOut(**_read_listing_defaults())
