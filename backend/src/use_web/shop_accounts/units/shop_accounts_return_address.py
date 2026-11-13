# -*- coding: utf-8 -*-
"""煤炉账号的「返品先住所」：账号编辑弹窗里配置，退货待办「填写返品先住所」时读取。

保存只规范化、不拒绝（编辑弹窗是改动即存，半截内容也要能落库）；返回里带上 ``problems``，
前端据此提示哪些项还不能用于填写。真正的拦截在执行前（``return_address_settings.validate``）。
"""

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....use_mercari import return_address_settings as ras


def _require_mercari_account(aid: int) -> ShopAccountModel:
    item = ShopAccountModel.find_by_id(id=int(aid))
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (getattr(item, "platform", "") or "mercari").strip().lower() != "mercari":
        raise HTTPException(status_code=400, detail="返品先住所仅用于煤炉账号")
    return item


def _response(addr: Dict[str, str]) -> Dict[str, Any]:
    return {
        "address": addr,
        "problems": ras.validate(addr),
        "prefectures": list(ras.PREFECTURES),
    }


def get_return_address(aid: int, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    """读取该账号的返品先住所（含可否用于填写的校验结果）。"""
    _require_mercari_account(aid)
    return _response(ras.load(int(aid)))


class ReturnAddressBody(PydanticModel):
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name_kana: Optional[str] = None
    first_name_kana: Optional[str] = None
    tel: Optional[str] = None
    email: Optional[str] = None
    zipcode: Optional[str] = None
    prefecture: Optional[str] = None
    city: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None


def save_return_address(
    aid: int, body: ReturnAddressBody, user: dict = Depends(require_auth)
) -> Dict[str, Any]:
    """整套写入该账号的返品先住所（规范化后落库）。"""
    _require_mercari_account(aid)
    return _response(ras.save(int(aid), body.model_dump()))
