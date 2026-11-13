# -*- coding: utf-8 -*-
"""煤炉退货「返品先住所」的存取、规范化与校验（按店铺账号一套）。

保存与执行是两道口子：
- **保存**（账号表单实时保存）只做规范化、不拒绝——用户边打字边存，半截内容必须能落库；
- **执行**（填写 返品くん 表单前）用 ``validate`` 把关，缺项或格式不对就不开浏览器。
  返品くん 写明「匿名返品は再発送ができません」，填错的地址没有补救机会，所以宁可在本地拦下。
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Dict, List

from ..db_manage.models.shop_accounts.return_address import ShopAccountReturnAddressModel

FIELDS = ShopAccountReturnAddressModel.ADDRESS_FIELDS

#: 返品くん 表单「都道府県」下拉的全部选项（实测，顺序与页面一致）
PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県",
    "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府",
    "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
    "鹿児島県", "沖縄県",
)

_KANA_RE = re.compile(r"^[ァ-ヶー]+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OPTIONAL = ("address2",)

_LABELS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "セイ",
    "first_name_kana": "メイ",
    "tel": "电话号码",
    "email": "邮箱",
    "zipcode": "邮编",
    "prefecture": "都道府県",
    "city": "市区町村",
    "address1": "番地",
    "address2": "建物名",
}


def _to_katakana(text: str) -> str:
    # NFKC 把半角片假名并成全角；平假名整体平移 0x60 到片假名
    s = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def normalize(data: Dict[str, object]) -> Dict[str, str]:
    """把表单输入规范成 返品くん 要的格式（片假名全角、电话/邮编纯数字）。不做拒绝。"""
    out: Dict[str, str] = {}
    for name in FIELDS:
        v = str(data.get(name) or "").strip()
        if name in ("last_name_kana", "first_name_kana"):
            v = re.sub(r"\s+", "", _to_katakana(v))
        elif name in ("tel", "zipcode"):
            v = re.sub(r"\D", "", unicodedata.normalize("NFKC", v))
        elif name == "email":
            v = unicodedata.normalize("NFKC", v).strip()
        out[name] = v
    return out


def validate(addr: Dict[str, str]) -> List[str]:
    """执行前校验，返回问题列表（空 = 可以填写）。"""
    problems: List[str] = []
    for name in FIELDS:
        if name not in _OPTIONAL and not addr.get(name):
            problems.append(f"{_LABELS[name]}未填写")
    if problems:
        return problems
    for name in ("last_name_kana", "first_name_kana"):
        if not _KANA_RE.match(addr[name]):
            problems.append(f"{_LABELS[name]}须为全角片假名")
    if not re.fullmatch(r"\d{10,11}", addr["tel"]):
        problems.append("电话号码须为 10~11 位数字")
    if not _EMAIL_RE.match(addr["email"]):
        problems.append("邮箱格式不正确")
    if not re.fullmatch(r"\d{7}", addr["zipcode"]):
        problems.append("邮编须为 7 位数字")
    if addr["prefecture"] not in PREFECTURES:
        problems.append("都道府県不在可选范围内")
    return problems


def _find_row(account_id: int):
    rows = ShopAccountReturnAddressModel.find_all(
        where="[account_id] = ?", params=(int(account_id),), limit=1
    )
    return rows[0] if rows else None


def load(account_id: int) -> Dict[str, str]:
    """读出该账号的返品先住所；没有配置时各字段为空串。"""
    row = _find_row(account_id)
    return {name: str(getattr(row, name, "") or "") if row else "" for name in FIELDS}


def save(account_id: int, data: Dict[str, object]) -> Dict[str, str]:
    """规范化后整行写入（一账号一行）。返回落库后的值。"""
    addr = normalize(data)
    row = _find_row(account_id) or ShopAccountReturnAddressModel(account_id=int(account_id))
    for name, v in addr.items():
        setattr(row, name, v or None)
    row.updated_at = int(time.time() * 1000)
    row.save()
    return addr
