# -*- coding: utf-8 -*-
"""煤炉退货的「返品先住所」，按店铺账号一行。

买家取消申请被同意后，煤炉要求卖家 24 小时内在外部服务「返品くん」里填写返品先信息
（见 ``use_mercari/get_to_du_list/transaction_detail/return_address.py``）。这里存的就是
要填进那张表单的内容，字段与表单一一对应。

单独建表而不是塞进 ``shop_accounts.value``：那一列由 ``_norm_headers_dict`` 按白名单重写，
任何一次账号编辑都会把不在白名单里的键丢掉。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


def _text() -> Dict[str, Any]:
    return {"type": "TEXT", "not_null": False, "default": None}


class ShopAccountReturnAddressModel(BaseModel):
    """店铺账号的返品先住所"""

    #: 可写字段（与 返品くん 表单一一对应），API 与自动化共用这一份清单
    ADDRESS_FIELDS = (
        "last_name",
        "first_name",
        "last_name_kana",
        "first_name_kana",
        "tel",
        "email",
        "zipcode",
        "prefecture",
        "city",
        "address1",
        "address2",
    )

    @classmethod
    def get_table_name(cls) -> str:
        return "shop_account_return_addresses"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        fields: Dict[str, Dict[str, Any]] = {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "account_id": {
                "type": "INTEGER",
                "not_null": True,
                "default": None,
            },
        }
        for name in cls.ADDRESS_FIELDS:
            fields[name] = _text()
        fields["updated_at"] = {"type": "INTEGER", "not_null": False, "default": 0}
        return fields

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "idx_shop_account_return_addresses_account",
                "columns": ["account_id"],
                "unique": True,
            },
        ]
