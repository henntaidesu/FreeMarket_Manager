# -*- coding: utf-8 -*-
"""
管理番号暗号（低位在前），两种编码：
- 五进制（默认）：字符集 ``-=~<>`` 对应 0–4。
- 二进制：菱形 ``◇◆`` 对应 0–1（◇=0，◆=1）。

当前编码模式记录在 config 表键 ``mgmt_cipher_mode``（'binary' / 'base5'，默认 base5），
由隐藏页 /x9 切换。**编码与解析都严格按当前模式**：选了五进制就只按五进制解析，
反之亦然（非兼容解析）。出品时写在商品说明最末行，无「管理番号：」前缀。

⚠️ 安全声明：这是**混淆（obfuscation），不是加密（cryptography）**。
无密钥、无机密性、无完整性/真实性保证——任何人只要知道字符表即可自行编/解码、伪造任意 id。
因此**下游绝不能仅凭解码结果就信任某个 id**：解出的 inventory.id 必须独立校验其确实
属于预期的账号 / 卖家 / 组合(bundle)范围（存在性检查 + 账号隔离），再用于库存/出库记账。
⚠️ 注意：编码线格式（encode 输出）已写入真实在售商品说明，**不可更改**（否则已上架商品无法解码）。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

MGMT_CIPHER_ALPHABET = "-=~<>"   # 五进制 0–4
MGMT_BINARY_ALPHABET = "◇◆"      # 二进制 0–1（◇=0，◆=1）
MGMT_CIPHER_MODE_KEY = "mgmt_cipher_mode"

_BASE5_SET = set(MGMT_CIPHER_ALPHABET)
_BINARY_SET = set(MGMT_BINARY_ALPHABET)
# 各模式各自的 token 正则（'-' 置于字符类开头表示字面量）
_BASE5_TOKEN_RE = re.compile(r"^([-=~<>]+)(?:\s*[*xX×]\s*(\d+))?$", re.UNICODE)
_BINARY_TOKEN_RE = re.compile(r"^([◇◆]+)(?:\s*[*xX×]\s*(\d+))?$", re.UNICODE)


def get_cipher_mode() -> str:
    """读取当前编码模式：'binary' 或 'base5'（默认 base5）。"""
    try:
        from ..db_manage.models.system.config_entry import ConfigEntryModel

        v = (ConfigEntryModel.get_value(MGMT_CIPHER_MODE_KEY) or "").strip().lower()
    except Exception:  # noqa: BLE001
        v = ""
    return "binary" if v == "binary" else "base5"


def _mode_spec(mode: Optional[str] = None):
    """返回 (alphabet, base, charset, token_re)；mode 省略时取当前配置模式。"""
    m = mode or get_cipher_mode()
    if m == "binary":
        return MGMT_BINARY_ALPHABET, 2, _BINARY_SET, _BINARY_TOKEN_RE
    return MGMT_CIPHER_ALPHABET, 5, _BASE5_SET, _BASE5_TOKEN_RE


def encode_mgmt_id(value: int, mode: Optional[str] = None) -> str:
    """将正整数 inventory.id 编码为暗号串（mode 省略时取当前配置模式）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid management id") from None
    if n < 0:
        raise ValueError("invalid management id")
    alphabet, base, _set, _re = _mode_spec(mode)
    if n == 0:
        return alphabet[0]
    chars: List[str] = []
    while n > 0:
        chars.append(alphabet[n % base])
        n //= base
    return "".join(chars)


def decode_mgmt_id_cipher(token: str, mode: Optional[str] = None) -> Optional[int]:
    """解码单个暗号 token；严格按当前(或指定)模式的字符集解析，非法返回 None。"""
    s = (token or "").strip()
    if not s:
        return None
    alphabet, base, charset, _re = _mode_spec(mode)
    if not all(c in charset for c in s):
        return None
    n = 0
    mult = 1
    for c in s:
        n += alphabet.index(c) * mult
        mult *= base
    return n if n > 0 else None


def encode_mgmt_ids(ids: List[int], sep: str = "、") -> str:
    mode = get_cipher_mode()  # 一次读取，避免逐个查库
    parts: List[str] = []
    for raw in ids:
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            parts.append(encode_mgmt_id(n, mode=mode))
    return sep.join(parts)


def _split_cipher_chunks(segment: str) -> List[str]:
    parts: List[str] = []
    for part in re.split(r"[,，、\s]+", segment or ""):
        p = (part or "").strip()
        if p:
            parts.append(p)
    return parts


def _cipher_token_base_and_qty(token: str, mode: Optional[str] = None) -> Tuple[str, int]:
    t = (token or "").strip()
    if not t:
        return "", 1
    _a, _b, _set, token_re = _mode_spec(mode)
    m = token_re.match(t)
    if not m:
        return "", 1
    base = (m.group(1) or "").strip()
    qraw = (m.group(2) or "").strip()
    if not qraw:
        return base, 1
    try:
        q = int(qraw)
    except (TypeError, ValueError):
        q = 1
    return base, max(1, q)


def is_cipher_mgmt_line(line: str, mode: Optional[str] = None) -> bool:
    """整行是否仅由「当前模式」的暗号 token（及分隔符）组成。"""
    s = (line or "").strip()
    if not s:
        return False
    if re.search(r"管理\s*(?:ID|番号)\s*[:：]", s, re.IGNORECASE):
        return False
    if re.search(r"バーコード\s*[:：]", s, re.IGNORECASE):
        return False
    m = mode or get_cipher_mode()
    _a, _b, charset, _re = _mode_spec(m)
    has_token = False
    for part in _split_cipher_chunks(s):
        base, _qty = _cipher_token_base_and_qty(part, mode=m)
        if not base or not all(c in charset for c in base):
            return False
        has_token = True
    return has_token


def parse_trailing_cipher_mgmt_tokens(text: Optional[str]) -> List[Tuple[int, int]]:
    """
    从说明**最末非空行**解析暗号管理番号（严格按当前模式）。
    返回 [(inventory_id, quantity), ...]
    """
    if text is None:
        return []
    s = str(text).strip()
    if not s:
        return []

    mode = get_cipher_mode()  # 一次读取，整次解析保持一致
    lines = s.splitlines()
    last_line = ""
    for raw in reversed(lines):
        t = str(raw or "").strip()
        if t:
            last_line = t
            break
    if not last_line or not is_cipher_mgmt_line(last_line, mode=mode):
        return []

    out: List[Tuple[int, int]] = []
    for part in _split_cipher_chunks(last_line):
        base, qty = _cipher_token_base_and_qty(part, mode=mode)
        if not base:
            continue
        mid = decode_mgmt_id_cipher(base, mode=mode)
        if mid is None:
            continue
        out.append((mid, qty))
    return out
