"""B 站 WBI 接口签名。

B 站部分接口需要 WBI 签名（`w_rid`）。密钥从 nav 接口的 wbi_img 动态获取，
混淆表 `_MIXIN_KEY_ENC_TAB` 为固定常量（从 yt-dlp Bilibili 提取器移植）。
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

_KEY_CACHE: dict[str, Any] = {}


def _get_wbi_key(client: httpx.Client, headers: dict[str, str]) -> str:
    """获取 WBI 签名密钥（缓存 30 秒）。

    Args:
        client: 复用的 httpx.Client
        headers: 请求头（需含 UA/Referer）
    """
    now = time.time()
    if _KEY_CACHE.get("ts", 0) + 30 > now:
        return _KEY_CACHE["key"]

    resp = client.get("https://api.bilibili.com/x/web-interface/nav", headers=headers)
    resp.raise_for_status()
    nav = resp.json()

    img_url = nav["data"]["wbi_img"]["img_url"]
    sub_url = nav["data"]["wbi_img"]["sub_url"]
    # 取文件名（无扩展名）拼接
    img_key = img_url.rpartition("/")[2].partition(".")[0]
    sub_key = sub_url.rpartition("/")[2].partition(".")[0]
    lookup = img_key + sub_key

    key = "".join(lookup[i] for i in _MIXIN_KEY_ENC_TAB)[:32]
    _KEY_CACHE.update({"key": key, "ts": now})
    return key


def sign_wbi(
    params: dict[str, Any],
    client: httpx.Client,
    headers: dict[str, str],
) -> dict[str, Any]:
    """对请求参数做 WBI 签名，返回添加了 wts/w_rid 的参数字典。"""
    params = dict(params)
    params["wts"] = round(time.time())
    # 过滤特殊字符
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in sorted(params.items())
    }
    query = urllib.parse.urlencode(params)
    wbi_key = _get_wbi_key(client, headers)
    params["w_rid"] = hashlib.md5(f"{query}{wbi_key}".encode()).hexdigest()
    return params
