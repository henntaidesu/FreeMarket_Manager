# -*- coding: utf-8 -*-
"""出品向导页面的选择器 / URL / 超时等常量"""
from __future__ import annotations

import os
import urllib.request
from typing import Dict, Tuple


# ───────────────────────── Mercari 出品页 XPath ──────────────────────────── #

SELL_CREATE_URL = "https://jp.mercari.com/sell/create"

# 出品自动化超时（毫秒）
DEFAULT_ELEMENT_TIMEOUT_MS = 12_000

DEFAULT_PAGE_LOAD_TIMEOUT_MS = 12_000

SALE_ELEMENT_TIMEOUT_MS = 8_000


def _env_int_ms(name: str, default: int) -> int:
    """读取毫秒级超时环境变量，非法或缺省时回落 default。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return v if v > 0 else default


# 点击「出品する」后等待「出品が完了しました」成功文案的超时（毫秒）。
# 网络较慢时成功弹窗/跳转可能 >12s；独立放宽并可由 LISTING_SUBMIT_CONFIRM_TIMEOUT_MS 覆盖，
# 避免把「其实已上架、只是渲染慢」误判为失败而诱发重复上架。
SUBMIT_CONFIRM_TIMEOUT_MS = _env_int_ms("LISTING_SUBMIT_CONFIRM_TIMEOUT_MS", 30_000)

# 选类型/状态后可能进入 sell/wizard（煤炉中间向导页），用浏览器后退离开
SELL_WIZARD_URL_FRAGMENT = "sell/wizard"

SELL_WIZARD_BROWSER_BACK_TIMEOUT_MS = 12_000

# 选完商品类型后固定等待，应对煤炉延迟跳入 sell/wizard（秒）
SELL_WIZARD_POST_CATEGORY_WAIT_S = 5.0

SELL_WIZARD_POST_CATEGORY_POLL_S = 0.4

# go_back 失败时兜底：页面内「出品画面に戻る」或 XPath
SELL_WIZARD_BACK_TEXT = "出品画面に戻る"

SELL_WIZARD_BACK_BUTTON_TESTID = "back-to-listing-button"

# sell/wizard 返回出品表单：优先点此区域（用户提供的绝对 XPath）
SELL_WIZARD_BACK_BUTTON_XPATH = "/html/body/div[2]/div[2]/main/div[2]/div[2]"

SELL_WIZARD_XPATH_CLICK_TIMEOUT_MS = 5_000

# 写真ブロック内「写真を追加」按钮
PHOTO_ADD_BUTTON_XPATH = '//*[@id="main"]/form/section[1]/div/div[6]/div[2]/button'

# Switch 开关 input（需确保 aria-checked="false"）
SWITCH_INPUT_XPATH = (
    '//*[@id="main"]/form/section[1]/div/div[2]/label/div[2]/div/div/div/input'
)

# 商品名称 input
NAME_INPUT_XPATH = '//*[@id="main"]/form/section[2]/div[2]/div/div[1]/input'

# 商品说明 textarea
DESCRIPTION_TEXTAREA_XPATH = '//*[@id="main"]/form/div[1]/div/label/textarea[1]'

# カテゴリー 入口：按日文文案定位（不用 XPath）
CATEGORY_ENTRY_TEXTS: Tuple[str, ...] = ("カテゴリーを選択する", "カテゴリー")

# 类别页面各级列表项（a[x] 中 x 来自 DB position 字段）
CATEGORY_ITEM_XPATH_TPL = '//*[@id="main"]/a[{pos}]'

# 商品状態：入口与选项一律在 #main 内按日文文案定位（不用 XPath）
CONDITION_ENTRY_TEXTS: Tuple[str, ...] = ("商品の状態を選択する", "商品の状態")

# API status → メルカリ一覧表示文案
CONDITION_ITEM_JA: Dict[str, str] = {
    "new_unused": "新品、未使用",
    "almost_unused": "未使用に近い",
    "good": "目立った傷や汚れなし",
    "fair": "やや傷や汚れあり",
    "used": "傷や汚れあり",
}

# 快递費負担 select
SHIPPING_PAYER_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[2]/div/label/div/select'
)

# 位置 XPath 失败时的签名兜底：唯一同时含「送料込み」「着払い」两项的 select 即运费承担
# （某些类目会多插入品牌/尺码等 section，导致 section[4] 位置串位、位置 XPath 失效）。
SHIPPING_PAYER_SELECT_SIGNATURES: Tuple[str, ...] = ("送料込み", "着払い")

# select value 映射：seller(出品者負担)=2  buyer(購入者負担)=1
SHIPPING_PAYER_VALUE: Dict[str, str] = {
    "seller": "2",  # 送料込み(出品者負担)
    "buyer":  "1",  # 着払い(購入者負担)
}

# 配送方法：/sell/shipping_methods 页按文案定位
SHIPPING_METHODS_URL_FRAGMENT = "sell/shipping_methods"

SHIPPING_METHOD_ENTRY_TEXTS: Tuple[str, ...] = (
    "配送の方法を選択する",
    "配送の方法",
)

SHIPPING_METHOD_CONFIRM_TEXT = "更新する"

# 承运方式 radio：按 name+value 直接命中（与 DOM 顺序无关）。
# 此前用 //*[@id="main"]/div/div[N] 的位置 XPath，一旦出现配送活动 banner
# （shipping-campaign-bubble，div 计数 +1）就会串位，导致选「ゆうゆう」却选成「らくらく」。
# value 取自煤炉页面 input[name="selectedShippingMethod"]：らくらく=14 / ゆうゆう=17 / たのメル便=16
SHIPPING_METHOD_RADIO_NAME = "selectedShippingMethod"

SHIPPING_METHOD_RADIO_VALUE: Dict[str, str] = {
    "rakuraku": "14",
    "yuuyu": "17",
    "tanome": "16",
}

# 「未定」位于「その他」折叠区内，仍按 XPath 选；「普通郵便」走文案兜底
SHIPPING_METHOD_RADIO_XPATH: Dict[str, str] = {
    "undecided": "/html/body/div[2]/div[2]/main/div/div[4]/div[2]/fieldset[8]/input",
    "regular_mail": "",
}

# 「未定」需先展开折叠区再点 radio
SHIPPING_METHOD_UNDECIDED_EXPAND_XPATH = '//*[@id="main"]/div/div[4]/div'

SHIPPING_METHOD_ITEM_JA: Dict[str, str] = {
    "undecided": "未定",
    "rakuraku": "らくらくメルカリ便",
    "yuuyu": "ゆうゆうメルカリ便",
    "tanome": "梱包・発送たのメル便",
    "regular_mail": "普通郵便",
}

# 出品表单提交按钮（按文案）
SUBMIT_BUTTON_TEXTS: Tuple[str, ...] = ("出品する", "出品")

# 販売タイプ radio 的标签文案兜底：绝对 XPath 随类目多插 section 易串位失效时，
# 按 radio 关联标签文本命中（即購=定价直购 / オークション=拍卖）。
SALE_INSTANT_RADIO_LABELS: Tuple[str, ...] = ("即購入", "定価", "すぐ購入")

SALE_AUCTION_RADIO_LABELS: Tuple[str, ...] = ("オークション", "競り", "入札")

# 販売タイプ — 即購（定価）（body 下绝对路径，与煤炉当前 DOM 一致）
SALE_INSTANT_RADIO_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[2]/div[1]/label/input"
)

SALE_INSTANT_PRICE_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[2]/div[2]/div[1]/div/div/input"
)

# 販売タイプ — 拍卖（オークション）
SALE_AUCTION_RADIO_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[1]/label/input"
)

SALE_AUCTION_PRICE_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[3]/div/div/input"
)

# 拍卖时长：通常 / 三小时（与「通常」同级 div[1]/div[2]）
SALE_AUCTION_DURATION_NORMAL_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[1]/div/div/div[1]"
)

# 拍卖时长「三小时」：点击选项区内的 svg（煤炉用图标切换）
SALE_AUCTION_DURATION_3H_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[1]/div/div/div[2]/svg"
)

# 発送までの日数 select
SHIPPING_DAYS_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[5]/div/label/div/select'
)

# 位置 XPath 失败时的签名兜底：发货天数 select 的每个 option 文本均含「日で発送」。
SHIPPING_DAYS_SELECT_SIGNATURES: Tuple[str, ...] = ("日で発送",)

SHIPPING_DAYS_OPTION_INDEX: Dict[str, int] = {
    "1_2_days": 2,
    "2_3_days": 3,
    "4_7_days": 4,
}

# 発送元 select
SHIPPING_FROM_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[4]/div/label/div/select'
)

# 位置 XPath 失败时的签名兜底：唯一同时含「北海道」「東京都」两项的 select 即发货地。
SHIPPING_FROM_SELECT_SIGNATURES: Tuple[str, ...] = ("北海道", "東京都")
