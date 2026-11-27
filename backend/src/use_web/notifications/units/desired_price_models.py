# -*- coding: utf-8 -*-
"""降价请求(値下げ依頼 / DesiredPriceOfferCreated)相关 API 请求体(Pydantic)。"""
from typing import Optional

from pydantic import BaseModel as PydanticModel


class DesiredPriceSyncRequest(PydanticModel):
    item_id: str
    account_id: Optional[int] = None
    notification_id: Optional[int] = None
    progress_job_id: Optional[str] = None


class DesiredPriceDecideRequest(PydanticModel):
    """同意 / 拒绝降价请求。

    - ``action='accept'`` 时点击页面「売る」按钮(同意报价 → 以该价格出售)
    - ``action='reject'`` 时点击页面「売らない」按钮(拒绝报价)
    """

    action: str
    account_id: Optional[int] = None
    #: 处理哪一条（多个买家同时请求时必传），= 详情 offers[].key
    offer_key: Optional[str] = None
    progress_job_id: Optional[str] = None


class DesiredPriceCloseRequest(PydanticModel):
    account_id: Optional[int] = None
