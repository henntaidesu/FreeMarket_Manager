# -*- coding: utf-8 -*-
"""Yahoo!フリマ 出品页的 URL / 选择器 / 枚举映射。

与煤炉的差异（决定了本包为什么不能复用 post_to_macket）：
- 出品表单在另一个域名 ``paypayfleamarket-sec.yahoo.co.jp``，DOM 类名全部是构建期哈希
  （``sc-xxxx``），没有 id / data-testid，只能靠**标签文案 + 结构**定位；
- 分类是逐级下钻的底部弹层（2～4 级不等，点到叶子才关闭），不是煤炉的固定 3 级 + 位置索引；
- 没有「送料負担」「販売形式（拍卖）」——Yahoo!フリマ 一律出品者負担、一律定价即购。
"""
from __future__ import annotations

from typing import Dict, Tuple

# 出品表单页（/sell 页「出品する」按钮的目标；/sell/create 是 404）
ITEM_ADD_URL = "https://paypayfleamarket-sec.yahoo.co.jp/item/add?from=sellTop"

#: 从账号主 profile 克隆登录态时要带上的 Cookie 域名（默认只克隆煤炉域）
YAHOO_COOKIE_DOMAINS: Tuple[str, ...] = ("yahoo", "paypay")
YAHOO_LOGIN_HINT = "paypayfleamarket.yahoo.co.jp"

DEFAULT_PAGE_LOAD_TIMEOUT_MS = 60_000
DEFAULT_ELEMENT_TIMEOUT_MS = 20_000
# 提交后等待结果的宽限（与煤炉一致：宁可判「不确定」也不误判失败）
SUBMIT_CONFIRM_TIMEOUT_MS = 60_000

# ── 表单字段（按 label 文案定位，见 _fields.field_trigger） ── #
NAME_INPUT_PLACEHOLDER = "商品名を入力してください（必須）"
NAME_MAX_LEN = 65
#: 商品説明 textarea 的 placeholder 首段（页面上还有别的 textarea，靠它区分）
DESCRIPTION_PLACEHOLDER_MARK = "（任意）"
DESCRIPTION_MAX_LEN = 1000
IMAGE_MAX_COUNT = 20
ADD_IMAGE_BUTTON_TEXT = "画像を追加する"
#: 点「画像を追加する」后才挂到 DOM 上的隐藏 input（#album 相册 / #photo 拍照）
IMAGE_FILE_INPUT_ID = "album"
IMAGE_DIALOG_CLOSE_TEXT = "閉じる"

LABEL_CATEGORY = "カテゴリ"
LABEL_CONDITION = "商品の状態"
LABEL_SHIPPING_METHOD = "配送方法"

#: 未选择时触发块显示的占位文案——用它判断某个字段是否已选好
UNSELECTED_PLACEHOLDER = "選択してください（必須）"

# 商品状態：API status → Yahoo!フリマ 选项首行文案
#（煤炉的 new_unused 是「新品、未使用」，雅虎只写「未使用」）
CONDITION_ITEM_JA: Dict[str, str] = {
    "new_unused": "未使用",
    "almost_unused": "未使用に近い",
    "good": "目立った傷や汚れなし",
    "fair": "やや傷や汚れあり",
    "used": "傷や汚れあり",
}

# 配送方法：煤炉配送方式 → 雅虎「おてがる配送」承运商。
# 雅虎只有雅玛多 / 日本邮便两家；煤炉侧的 未定 / 普通郵便 / たのメル便 无对应项，
# 置 None 表示「保持雅虎页面默认（おてがる配送（日本郵便））」。
SHIPPING_METHOD_JA: Dict[str, str] = {
    "rakuraku": "おてがる配送（ヤマト運輸）",
    "yuuyu": "おてがる配送（日本郵便）",
    "tanome": "",
    "regular_mail": "",
    "undecided": "",
}

# 発送までの日数 select[name=timeToShip] 的 option value
SHIPPING_DAYS_SELECT_NAME = "timeToShip"
SHIPPING_DAYS_VALUE: Dict[str, str] = {
    "1_2_days": "ONE_TO_TWO_DAYS",
    "2_3_days": "TWO_TO_THREE_DAYS",
    # 煤炉的 4~7 日对应雅虎的 3~7 日（雅虎没有 4~7 档）
    "4_7_days": "THREE_TO_SEVEN_DAYS",
}

# 発送元の地域 select[name=prefectures]：按 option 文案选（比 enum value 稳）
SHIPPING_FROM_SELECT_NAME = "prefectures"

#: 煤炉 area_id（1～47，JIS 顺序）→ 都道府県名。99（未定）雅虎不支持。
PREFECTURE_BY_AREA_ID: Dict[str, str] = {
    "1": "北海道", "2": "青森県", "3": "岩手県", "4": "宮城県", "5": "秋田県",
    "6": "山形県", "7": "福島県", "8": "茨城県", "9": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県", "15": "新潟県",
    "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県",
    "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県", "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県",
}

# 販売価格
PRICE_INPUT_PLACEHOLDER = "0"
PRICE_MIN = 300
PRICE_MAX = 9_999_999

# 提交
SUBMIT_BUTTON_TEXT = "出品する"
DRAFT_BUTTON_TEXT = "下書きに保存する"
#: 提交成功的判定文案（任一命中即认为已挂牌）
SUBMIT_SUCCESS_TEXTS: Tuple[str, ...] = ("出品しました", "出品が完了", "商品を出品しました")

#: 填了商品名后，分类弹层先给「カテゴリはこちらですか」推荐列表，
#: 要点这个按钮才回到可逐级下钻的全量分类树。
CATEGORY_MORE_BUTTON_TEXT = "他のカテゴリから選ぶ"
