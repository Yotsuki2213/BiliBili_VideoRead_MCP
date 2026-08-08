"""Bilibili 评论提取 — `x/v2/reply` 接口（需登录 Cookie）。"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from videoread_mcp import auth

logger = logging.getLogger(__name__)

URL_REPLY = "https://api.bilibili.com/x/v2/reply"
_TIMEOUT = httpx.Timeout(30.0)

PAGE_SIZE = 20  # 接口每页上限 20

# sort: 0=时间序 1=热度序（本工具统一用 sort 参数）
_SORT_MAP = {"time": 0, "hot": 1}


class CommentError(Exception):
    """评论提取错误（登录失效、评论区关闭等）。"""


def fetch_comments(
    client: httpx.Client,
    aid: int,
    sort: str = "hot",
    max_comments: int = 50,
    include_replies: bool = False,
) -> list[dict[str, Any]]:
    """提取评论，返回 [{uname, content, like, ctime, level, replies}, ...]。

    Args:
        aid: 视频 aid
        sort: hot（按热度）| time（按时间）
        max_comments: 最多提取的根评论数
        include_replies: 是否附带每条根评论下的子回复
    """
    if sort not in _SORT_MAP:
        raise CommentError(f"不支持的排序方式: {sort}（可选 hot / time）")

    cookie = auth.effective_cookie_str()
    if not cookie:
        raise CommentError(
            "提取评论需要登录态。请先运行 `python -m videoread_mcp login` 扫码登录。"
        )
    headers = dict(auth.DEFAULT_HEADERS)
    headers["Cookie"] = cookie

    # 第一页：同时拿 hots（热评）与 replies（当前排序下的评论）
    first = _fetch_page(client, headers, aid, sort, pn=1)
    data = first.get("data") or {}
    total = (data.get("page") or {}).get("count", 0)
    hots = data.get("hots") or []
    replies = data.get("replies") or []

    # 热评优先（sort=hot 时 hots 与 replies 通常一致，去重）
    merged: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in hots + replies:
        rpid = item.get("rpid")
        if rpid in seen:
            continue
        seen.add(rpid)
        merged.append(_parse_item(item, include_replies))

    # 翻页补齐
    pn = 2
    while len(merged) < max_comments and pn * PAGE_SIZE < total:
        page = _fetch_page(client, headers, aid, sort, pn=pn)
        for item in (page.get("data") or {}).get("replies") or []:
            rpid = item.get("rpid")
            if rpid in seen:
                continue
            seen.add(rpid)
            merged.append(_parse_item(item, include_replies))
            if len(merged) >= max_comments:
                break
        pn += 1

    return merged[:max_comments]


def _fetch_page(
    client: httpx.Client, headers: dict[str, str], aid: int, sort: str, pn: int
) -> dict[str, Any]:
    resp = client.get(
        URL_REPLY,
        params={
            "type": 1,
            "oid": aid,
            "sort": _SORT_MAP[sort],
            "ps": PAGE_SIZE,
            "pn": pn,
        },
        headers=headers,
    )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("code", 0)
    if code == -101:
        raise CommentError(
            "B 站登录已失效，请运行 `python -m videoread_mcp login` 扫码重新登录。"
        )
    if code == 12002:
        raise CommentError("该视频评论区已关闭。")
    if code != 0:
        logger.warning("评论接口返回 code=%s: %s", code, body.get("message"))
        return {}
    return body


def _parse_item(item: dict[str, Any], include_replies: bool) -> dict[str, Any]:
    """解析单条评论。"""
    member = item.get("member") or {}
    content = (item.get("content") or {}).get("message", "")
    parsed = {
        "uname": member.get("uname", "匿名"),
        "mid": member.get("mid", 0),
        "content": content.strip(),
        "like": item.get("like", 0),
        "ctime": item.get("ctime", 0),
        "level": (member.get("level_info") or {}).get("current_level", 0),
        "rcount": item.get("rcount", 0),
        "replies": [],
    }
    if include_replies:
        for r in (item.get("replies") or [])[:5]:
            rmember = r.get("member") or {}
            rcontent = (r.get("content") or {}).get("message", "")
            parsed["replies"].append(
                {
                    "uname": rmember.get("uname", "匿名"),
                    "content": rcontent.strip(),
                    "like": r.get("like", 0),
                    "ctime": r.get("ctime", 0),
                }
            )
    return parsed


def format_ctime(ts: int) -> str:
    """Unix 时间戳 → YYYY-MM-DD HH:MM"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except (ValueError, OSError):
        return ""
