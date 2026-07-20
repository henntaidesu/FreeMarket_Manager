# -*- coding: utf-8 -*-
"""从订单描述解析出库 token 与管理 ID"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple
from ...mgmt_id_cipher import parse_trailing_cipher_mgmt_tokens
from ._common import OutboundToken, _BARCODE_PATTERN, _MGMT_BANGO_PATTERN, _MGMT_ID_PATTERN, _split_chunks, _value_and_quantity


def parse_order_description_outbound_tokens_with_quantity(
    text: Optional[str],
) -> List[Tuple[str, Any, int]]:
    """
    按说明文中出现顺序，解析出 (line_kind, value, quantity) 列表。
    line_kind: ``mgmt_id`` | ``barcode``
    """
    if text is None:
        return []
    s = str(text).strip()
    if not s:
        return []

    spans: List[Tuple[int, str, str]] = []
    for m in _MGMT_ID_PATTERN.finditer(s):
        spans.append((m.start(), "mgmt", m.group(1) or ""))
    for m in _MGMT_BANGO_PATTERN.finditer(s):
        spans.append((m.start(), "mgmt", m.group(1) or ""))
    for m in _BARCODE_PATTERN.finditer(s):
        spans.append((m.start(), "barcode", m.group(1) or ""))
    # ⚠️ 暗号是混淆、非加密、可伪造（见 mgmt_id_cipher.py 安全声明）。这里只做「解析」，
    # 不做「信任」：解出的 mgmt_id 交给下游 outbound_sync 时会再经 _inventory_id_exists
    # 存在性校验后才落库存/出库行（真实性边界在 inventory_resolve/outbound_sync 处）。
    cipher_pos = len(s)
    strip_lines = s.splitlines()
    for raw_ln in reversed(strip_lines):
        if str(raw_ln or "").strip():
            pos = s.rfind(raw_ln)
            if pos >= 0:
                cipher_pos = pos
            break
    for mid, qty in parse_trailing_cipher_mgmt_tokens(s):
        chunk = f"{mid}*{qty}" if qty > 1 else str(mid)
        spans.append((cipher_pos, "mgmt", chunk))

    spans.sort(key=lambda x: x[0])

    out: List[Tuple[str, Any, int]] = []
    for _, kind, chunk in spans:
        for part in _split_chunks(chunk):
            base, qty = _value_and_quantity(part)
            if not base:
                continue
            if kind == "mgmt":
                try:
                    n = int(base)
                except (TypeError, ValueError):
                    continue
                out.append(("mgmt_id", n, qty))
            else:
                bc = base.strip()
                if not bc:
                    continue
                out.append(("barcode", bc, qty))
    return out

def parse_order_description_outbound_tokens(text: Optional[str]) -> List[OutboundToken]:
    """
    按说明文中出现顺序，解析出 (line_kind, value) 列表。
    line_kind: ``mgmt_id`` | ``barcode``
    """
    if text is None:
        return []
    s = str(text).strip()
    if not s:
        return []

    out: List[OutboundToken] = []
    for kind, value, qty in parse_order_description_outbound_tokens_with_quantity(s):
        repeat = max(1, int(qty or 1))
        out.extend([(kind, value)] * repeat)
    return out

def parse_management_ids_from_description(text: Optional[str]) -> List[int]:
    """
    仅从说明中解析管理 ID 序列（兼容旧调用；新逻辑见 parse_order_description_outbound_tokens）。
    """
    return [v for k, v in parse_order_description_outbound_tokens(text) if k == "mgmt_id"]
