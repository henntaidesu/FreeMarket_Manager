# -*- coding: utf-8 -*-
"""出品图暗码设置（隐藏页 /x9）：管理番号码、件数码各自「有码 / 无码」+ 嵌在哪个角。

存在 config 表键 ``mgmt_image_code_settings``（JSON），缺省 = 两个码都嵌、
管理番号码左下角、件数码右下角（即引入本设置之前的固定行为）。

- 只影响**新出品**往哪里嵌、嵌不嵌；解码永远四个角都找（当前设置的角优先），
  所以改位置后，旧位置上的已上架图片照样认得回来。
- 两个码都开时不能放同一个角：码区完全重叠，后嵌的会把先嵌的抹掉。
- 管理番号码选「无码」= 新挂牌不再带 inventory.id，在售 / 订单**无法自动关联库存**。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

CORNERS = ("tl", "tr", "bl", "br")
_KEY = "mgmt_image_code_settings"
_DEFAULTS: Dict[str, Dict] = {
    "id": {"enabled": True, "corner": "bl"},
    "qty": {"enabled": True, "corner": "br"},
}


def _normalize(raw: Optional[dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for kind, dflt in _DEFAULTS.items():
        v = (raw or {}).get(kind) if isinstance(raw, dict) else None
        v = v if isinstance(v, dict) else {}
        corner = str(v.get("corner") or "").strip().lower()
        out[kind] = {
            "enabled": bool(v.get("enabled", dflt["enabled"])),
            "corner": corner if corner in CORNERS else dflt["corner"],
        }
    return out


def get_settings() -> Dict[str, Dict]:
    try:
        from ..db_manage.models.system.config_entry import ConfigEntryModel

        s = ConfigEntryModel.get_value(_KEY)
        return _normalize(json.loads(s) if s else None)
    except Exception:  # noqa: BLE001
        return _normalize(None)


def save_settings(raw: dict) -> Dict[str, Dict]:
    """校验并保存；不合法抛 ValueError。"""
    for kind in _DEFAULTS:
        corner = str(((raw or {}).get(kind) or {}).get("corner") or "").strip().lower()
        if corner not in CORNERS:
            raise ValueError(f"无效的位置: {corner or '(空)'}")
    s = _normalize(raw)
    if s["id"]["enabled"] and s["qty"]["enabled"] and s["id"]["corner"] == s["qty"]["corner"]:
        raise ValueError("管理番号码与件数码不能放在同一个角")
    from ..db_manage.models.system.config_entry import ConfigEntryModel

    ConfigEntryModel.set_value(_KEY, None if s == _DEFAULTS else json.dumps(s))
    return s


def decode_corners(kind: str) -> List[str]:
    """解码时找角的顺序：当前设置的角 → 缺省角（历史图片都在那里）→ 其余。"""
    s = get_settings()
    order = [s[kind]["corner"], _DEFAULTS[kind]["corner"], *CORNERS]
    return list(dict.fromkeys(order))
