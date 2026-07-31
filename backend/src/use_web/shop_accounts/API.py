# -*- coding: utf-8 -*-
"""店铺账号管理 API 模块（煤炉 / 雅虎共用）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/shop-accounts
- 完整 URL 示例: GET /mercariV2/src/use_web/shop-accounts/
"""
from fastapi import APIRouter

from .units.shop_accounts_crud import (
    create_shop_account,
    delete_shop_account,
    list_shop_accounts,
    update_shop_account,
)
from .units.shop_accounts_mitm import (
    fetch_seller_id_via_mitm,
)
from .units.shop_accounts_sync import sync_account_all_data
from .units.shop_accounts_yahoo import fetch_yahoo_basic_info_endpoint

router = APIRouter()

router.add_api_route("", list_shop_accounts, methods=["GET"])
router.add_api_route("", create_shop_account, methods=["POST"])
router.add_api_route("/{aid}", update_shop_account, methods=["PUT"])
router.add_api_route("/fetch-seller-id-via-mitm", fetch_seller_id_via_mitm, methods=["POST"])
# 雅虎的「获取基础信息」：卖家ID 在 /my 的 DOM 里，不需要 MITM，故与煤炉分开成独立端点
router.add_api_route("/fetch-yahoo-basic-info", fetch_yahoo_basic_info_endpoint, methods=["POST"])
router.add_api_route("/{aid}/sync-data", sync_account_all_data, methods=["POST"])
router.add_api_route("/{aid}", delete_shop_account, methods=["DELETE"])
