# -*- coding: utf-8 -*-
"""待办事项 API 请求体（Pydantic）。"""
from typing import Literal, Optional

from pydantic import BaseModel as PydanticModel, Field


class SyncTodosRequest(PydanticModel):
    account_id: Optional[int] = None
    progress_job_id: Optional[str] = None


class SendTransactionMessageRequest(PydanticModel):
    text: str = Field(..., min_length=1, max_length=2000)
    progress_job_id: Optional[str] = None


class TranslateMessageRequest(PydanticModel):
    """按需翻译单条消息（旧数据「翻译」按钮）：译为中文并写回 text_zh。"""

    # 订单ID（= item_id），用于把译文写回对应消息行；缺失则只翻译不持久化
    order_no: str = ""
    # 煤炉消息 id（用于精确定位行；可空，空则按原文定位）
    msg_id: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=2000)


class ConfirmShippingSelectionRequest(PydanticModel):
    class_text: str = Field(..., min_length=1, max_length=200)
    # 仅对需要选择 facility 的 size 必填，与煤炉 radio value 一致：
    # 'POST_OFFICE' | 'LAWSON' | 'SEVEN_ELEVEN' | 'FAMILY_MART' | 'YAMATO_OFFICE' | 'PUDO' | None
    facility: Optional[str] = None
    # ゆうパケットポスト/mini：完了後そのまま「2次元コードを読み取る」を押して QR スキャナを開く
    scan_qr: bool = False
    # 需选发货地的方法（ゆうパケットポスト系以外）：完了後、返回交易ページ发行 发送用 QR/条形码（无需摄像头）
    generate_code: bool = False
    progress_job_id: Optional[str] = None


class ChangeShippingMethodRequest(PydanticModel):
    """完整修改配送方式：打开浏览器 → 点「発送方法を変更する」→ 按类别选中 → 点「変更する」。

    ``method_category`` 为前端图片类别（post=邮局 / yamato / other=其他），后端据此匹配
    实际 radio；``method_value``/``method_label`` 为回落（直接指定 radio）。
    """

    method_category: str = ""
    method_value: str = ""
    method_label: str = ""
    progress_job_id: Optional[str] = None


class CameraFrameRequest(PydanticModel):
    """客户端摄像头单帧（data URL）→ 推送到有头浏览器的虚拟摄像头。

    ``frame`` 为空时仅查询扫描状态（done/on_scanner），不写入画面。
    """

    frame: str = ""
    width: int = 0
    height: int = 0


class ShippingQrPhotoRequest(PydanticModel):
    """ゆうパケットポスト系 发货扫码：客户端拍的**一张**含二维码的照片（data URL）。

    提交后后端先用 zxingcpp 验一遍能否读出二维码，通过才落盘入队；
    之后喂图给煤炉扫描器、抓发货信息都在后台任务里做，页面不必等待。
    """

    photo: str = Field(..., min_length=1)
    #: 所选商品尺寸（ゆうパケットポスト / ゆうパケットポストmini）。
    #: 传了就由任务在后台完成「选尺寸 → 完了する → 进扫描页」，前台不再阻塞等待。
    class_text: Optional[str] = Field(default=None, max_length=120)
    #: 发货地点；ゆうパケットポスト系为 None（页面自动选好）
    facility: Optional[str] = Field(default=None, max_length=40)
    #: 喂图等待煤炉读出的超时秒数；留空用默认 90s
    timeout_sec: Optional[float] = None
    #: 虚拟发货：平台侧照常跑完（这条链路一步不改），但本地不收尾——行转「虚拟发货」
    #: 状态等实物投函。仅 ゆうパケットポスト / mini 可用，端点会校验 ``class_text``。
    virtual: bool = False
    #: 前端一次点击生成的幂等 token
    client_token: Optional[str] = Field(default=None, max_length=128)


class ShippingQrRetryRequest(PydanticModel):
    """用**已存的那张照片**重跑发货扫码，不必重拍。

    失败几乎从来不在识码上——照片入队时就已经解出二维码（``ship_qr_text``），
    断掉的是后面开浏览器、进扫描页、发通知那一段。让用户为此再拍一次没有意义。
    """

    #: 喂图等待煤炉读出的超时秒数；留空用默认 90s
    timeout_sec: Optional[float] = None
    #: 前端一次点击生成的幂等 token
    client_token: Optional[str] = Field(default=None, max_length=128)


class SubmitTransactionReviewRequest(PydanticModel):
    #: 评价正文。「良かった」时可留空——页面注脚写明コメントは任意；
    #: 「残念だった」需 10 字以上，由 ``submit_transaction_review`` 与页面同口径校验
    text: str = Field("", max_length=140)
    #: 取引評価单选，与页面 input[name="fame"] 的 value 一致
    rating: Literal["good", "bad"] = "good"
    progress_job_id: Optional[str] = None


class SubmitBuyerReceiptRequest(PydanticModel):
    """买家侧受取評価（「确认收货」）：文本 + rating，与卖家评价字段同构

    （买家/卖家共用同一套页面 input[name="fame"] 单选组件）。"""

    text: str = Field("", max_length=140)
    rating: Literal["good", "bad"] = "good"
    progress_job_id: Optional[str] = None


class BulkSubmitReviewsRequest(PydanticModel):
    """一键好评：对所有「評価をしてください」待办批量提交评价（不指定则全部启用账号）。"""

    text: str = Field("", max_length=140)
    progress_job_id: Optional[str] = None


class BulkFinalizePostShippingRequest(PydanticModel):
    """一键确认发送：对所有「已打包」待办批量执行发货通知（不指定则全部启用账号）。"""

    progress_job_id: Optional[str] = None


class TransactionActionRequest(PydanticModel):
    """无 body 的浏览器操作（拉详情/启动尺寸选择/修改发送方式）仍需透传 job_id。"""

    progress_job_id: Optional[str] = None
    # 确认发送时跳过「发送确认符号/追跡番号」核验（用户在核验不一致提示后确认仍要发送）。
    force: bool = False


class YahooShipRequest(PydanticModel):
    """雅虎发货：交易页上的三个必填项。

    ``size`` / ``location`` 必须是**该交易页当前真实提供的选项名**（由
    ``/yahoo/ship-state`` 返回），不做本地枚举——可选尺寸随配送会社变化。

    ``size`` 取 ゆうパケットポスト / mini 时改走 App API：这两项网页端不下发，``location``
    也就无从选起（投函型没有発送場所），因此对这两种设了默认值可以不传，但 ``material_code``
    变成必填（由后端校验，见 ``use_yahoo/app_api/ship.py``）。
    """

    # 品名：雅虎 maxlength=17，超出由后端截断
    item_name: str = Field(..., min_length=1, max_length=17)
    size: str = Field(..., min_length=1, max_length=60)
    location: str = ""
    # 专用箱 / 発送用シール / 専用封筒 上二维码的**照片**（data URL，仅投函型需要）。
    # 由后端解码并提取材料码——与煤炉一样「拍完即提交」，不让用户多按一次校验。
    material_image: str = ""
    # 只填表校验、不点「配送コードを表示する」
    dry_run: bool = False


class YahooShipQrRequest(PydanticModel):
    """雅虎投函型（ゆうパケットポスト / mini）发货：拍一张二维码照片就提交。

    与 ``YahooShipRequest`` 的区别只在**执行方式**：这条走任务队列，发行配送コード /
    発送通知 / 刷订单 / 软删待办都在后台跑，前台拍完即走。没有 ``location``——
    投函型没有発送場所可选；没有 ``dry_run``——排队的任务不做空跑。
    """

    # 品名：雅虎 maxlength=17，超出由后端截断
    item_name: str = Field(..., min_length=1, max_length=17)
    # 只接受 ゆうパケットポスト / ゆうパケットポストmini，端点会校验
    size: str = Field(..., min_length=1, max_length=60)
    # 専用箱 / 発送用シール / 専用封筒 上二维码的照片（data URL）
    photo: str = Field(..., min_length=1)
    # 虚拟发货：平台侧照常发行配送コード + 発送通知，本地转「虚拟发货」等实物投函。
    # 投函型本来就只有这两个尺寸，端点仍会再校验一次。
    virtual: bool = False
    # 前端一次点击生成的幂等 token
    client_token: Optional[str] = Field(default=None, max_length=128)


class YahooTradeMessageRequest(PydanticModel):
    """雅虎取引メッセージ（页面上限 1024 字）。"""

    text: str = Field(..., min_length=1, max_length=1024)
    dry_run: bool = False


class SendMessageReactionRequest(PydanticModel):
    """对买家某条消息发送 emoji 反应。

    ``reaction_index`` 必填：前端按 ``messages.filter(is_buyer=true).indexOf(target)`` 计算，
    后端用其在 DOM 上定位第 N 个 ``[data-testid="add-reaction-button"]``。
    """

    # 仅用于日志/审计；后端不会用它在 DOM 里查找
    message_id: Optional[str] = None
    reaction_index: int = Field(..., ge=0)
    # emoji 关键字（thumbsup/heart/smile/pray/cry/clap/sparkles/ok 等）
    reaction: str = Field(..., min_length=1, max_length=32)
    progress_job_id: Optional[str] = None
