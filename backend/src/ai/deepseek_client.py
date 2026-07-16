# -*- coding: utf-8 -*-
"""DeepSeek（OpenAI 兼容）客户端：出品标题 / 出品说明的 AI 生成。

- 配置（API Key / 模型 / API 地址）保存在业务库的 [config] 表（ConfigEntryModel）。
- 出品标题与出品说明按需求以【日语】生成（面向 Mercari Japan）。
- 主图按 OpenAI 兼容的多模态格式（image_url + base64 data URL）随请求发送；
  DeepSeek 标准 deepseek-chat 为纯文本模型，若带图需在系统配置里改用支持视觉的模型 / 地址。
"""

import json
import re
from typing import Any, Dict, Optional

import requests
from fastapi import HTTPException

from ..db_manage.models.system.config_entry import ConfigEntryModel

# ===== [config] 表键名 =====
K_DEEPSEEK_API_KEY = "deepseek_api_key"
K_DEEPSEEK_MODEL = "deepseek_model"
K_DEEPSEEK_BASE_URL = "deepseek_base_url"

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"

# 出品标题 / 出品说明的长度上限（与前端库存表单字段一致：标题 40、说明 900）
_MAX_TITLE = 40
_MAX_BODY = 900

_SYSTEM_PROMPT = (
    "あなたはメルカリ（Mercari Japan）の出品文作成アシスタントです。"
    "与えられた商品情報（主題＝商品名、カテゴリ、価格、商品画像など）をもとに、"
    "購入意欲を高める自然で丁寧な【日本語】の出品タイトルと出品説明を作成してください。"
    f"出品タイトルは全角{_MAX_TITLE}文字以内、出品説明は{_MAX_BODY}文字以内にしてください。"
    "誇大表現や虚偽の情報は避け、商品情報から読み取れる範囲で作成してください。"
    "必ず次のJSON形式【のみ】で出力してください（前後に説明文やコードブロック記号```を付けないこと）："
    '{"title": "出品タイトル", "body": "出品説明"}'
)


def get_deepseek_settings() -> Dict[str, str]:
    """读取 DeepSeek 配置（含默认值）。api_key 可能为空字符串。"""
    return {
        "api_key": ConfigEntryModel.get_value(K_DEEPSEEK_API_KEY) or "",
        "model": ConfigEntryModel.get_value(K_DEEPSEEK_MODEL) or DEFAULT_MODEL,
        "base_url": ConfigEntryModel.get_value(K_DEEPSEEK_BASE_URL) or DEFAULT_BASE_URL,
    }


def save_deepseek_settings(
    api_key: Optional[str], model: Optional[str], base_url: Optional[str]
) -> None:
    """写入 DeepSeek 配置。空值删除该键（回落默认）。"""
    ConfigEntryModel.set_value(K_DEEPSEEK_API_KEY, api_key)
    # 模型 / 地址：与默认值相同时不必落库（存空即删除）
    m = (model or "").strip()
    ConfigEntryModel.set_value(K_DEEPSEEK_MODEL, None if not m or m == DEFAULT_MODEL else m)
    b = (base_url or "").strip().rstrip("/")
    ConfigEntryModel.set_value(
        K_DEEPSEEK_BASE_URL, None if not b or b == DEFAULT_BASE_URL else b
    )


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出里尽量解析出 {title, body}：容忍 ```json 包裹或前后杂文。"""
    s = (text or "").strip()
    if not s:
        return None
    # 去掉可能的 ```json ... ``` 代码块包裹
    fence = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # 退化：截取第一个 { 到最后一个 } 之间的片段再试
    l, r = s.find("{"), s.rfind("}")
    if 0 <= l < r:
        try:
            obj = json.loads(s[l : r + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _build_user_content(
    theme: str,
    category: Optional[str],
    price: Optional[float],
    image_data_url: Optional[str],
):
    """构造 user 消息内容：文本 + （可选）主图（OpenAI 兼容多模态格式）。"""
    lines = [f"主題（商品名）: {theme}"]
    if category:
        lines.append(f"カテゴリ: {category}")
    if price is not None:
        try:
            lines.append(f"価格: ¥{int(round(float(price)))}")
        except (TypeError, ValueError):
            pass
    lines.append("上記の商品について、日本語の出品タイトルと出品説明をJSONで作成してください。")
    text = "\n".join(lines)

    if not image_data_url:
        # 纯文本：直接返回字符串内容
        return text
    # 多模态：文本 + 图片
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]


def generate_listing(
    theme: str,
    category: Optional[str] = None,
    price: Optional[float] = None,
    image_data_url: Optional[str] = None,
) -> Dict[str, str]:
    """调用 DeepSeek 生成出品标题与出品说明（日语），返回 {title, body}。

    失败时抛 HTTPException（由 FastAPI 转成对应状态码，前端弹出 detail）。
    """
    settings = get_deepseek_settings()
    api_key = settings["api_key"]
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="尚未配置 DeepSeek API Key，请先到「系统配置」页面填写并保存。",
        )

    theme = (theme or "").strip()
    if not theme:
        raise HTTPException(status_code=400, detail="商品名（主題）为空，无法生成出品文案。")

    url = settings["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_content(theme, category, price, image_data_url),
            },
        ],
        "temperature": 1.0,
        "max_tokens": 1200,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="调用 DeepSeek 超时，请稍后重试。")
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"无法连接 DeepSeek：{e}")

    if resp.status_code != 200:
        detail = resp.text or ""
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek 返回错误（{resp.status_code}）：{detail[:300]}",
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="DeepSeek 返回内容无法解析。")

    obj = _extract_json_obj(content)
    if obj is not None:
        title = str(obj.get("title", "") or "").strip()
        body = str(obj.get("body", "") or "").strip()
    else:
        # 未按 JSON 返回：整体作为说明，首行作为标题兜底
        text = str(content or "").strip()
        first_line = text.splitlines()[0].strip() if text else ""
        title, body = first_line, text

    return {"title": title[:_MAX_TITLE], "body": body[:_MAX_BODY]}
