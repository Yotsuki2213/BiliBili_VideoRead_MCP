"""Bilibili 视频提取器 — 纯 B 站 API 直连（无 yt-dlp）。

元数据：`x/web-interface/view`（一次拿全 title/owner/stat/pages）
字幕：WBI 签名后调 `x/player/wbi/v2`，再下载字幕 JSON。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from videoread_mcp import auth, wbi

logger = logging.getLogger(__name__)

URL_VIEW = "https://api.bilibili.com/x/web-interface/view"
URL_PLAYER_WBI = "https://api.bilibili.com/x/player/wbi/v2"

# 字幕语言优先级（支持 ai- 前缀）
_LANG_PRIORITY = {
    "zh-CN": 0, "zh": 1, "zh-Hans": 2, "ai-zh": 3,
    "zh-TW": 4, "ai-zh-TW": 5,
    "en": 10, "ai-en": 11,
    "ja": 20, "ai-ja": 21,
}

# 不指定 page 时默认最多提取前 N 个分 P 的字幕
DEFAULT_MAX_PAGES = 10

_TIMEOUT = httpx.Timeout(30.0)


class ExtractionError(Exception):
    """提取过程中的错误（无效 URL、视频不存在、无字幕、登录失效等）。"""


# ---------------------------------------------------------------------------
# URL 标准化
# ---------------------------------------------------------------------------

def _build_url(raw: str) -> str:
    """标准化输入为完整 Bilibili URL。"""
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.upper().startswith("BV"):
        return f"https://www.bilibili.com/video/{raw}"
    if raw.lower().startswith("av"):
        return f"https://www.bilibili.com/video/{raw}/"
    if raw.isdigit():
        return f"https://www.bilibili.com/video/av{raw}/"
    if "bilibili.com" in raw or "b23.tv" in raw:
        return raw if raw.startswith("http") else f"https://{raw}"
    return raw


def _extract_bvid(url: str) -> str:
    """从 URL 提取 BV 号。"""
    m = re.search(r"BV[a-zA-Z0-9]+", url)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# view 元数据
# ---------------------------------------------------------------------------

def _parse_pages(view: dict[str, Any]) -> list[dict[str, Any]]:
    """从 view 数据提取分 P 列表 [{page, cid, part, duration}, ...]。"""
    pages = view.get("pages") or []
    if pages:
        return [
            {
                "page": int(p.get("page", i + 1)),
                "cid": int(p["cid"]),
                "part": p.get("part", f"P{p.get('page', i + 1)}"),
                "duration": int(p.get("duration", 0)),
            }
            for i, p in enumerate(pages)
        ]
    # 单 P：无 pages 时用顶层 cid
    return [{
        "page": 1,
        "cid": int(view.get("cid", 0)),
        "part": view.get("title", "P1"),
        "duration": int(view.get("duration", 0)),
    }]


def fetch_view(bvid: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """获取视频 view 数据（无需登录）。"""
    resp = (client or httpx.Client(timeout=_TIMEOUT)).get(
        URL_VIEW, params={"bvid": bvid}, headers=auth.DEFAULT_HEADERS
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ExtractionError(f"视频不存在或已被删除: {data.get('message', '未知错误')}")
    return data.get("data") or {}


# ---------------------------------------------------------------------------
# 字幕（WBI 签名，需登录 Cookie）
# ---------------------------------------------------------------------------

def fetch_subtitles(
    client: httpx.Client,
    aid: int | None,
    bvid: str,
    cid: int,
    cookie: str | None,
) -> list[dict[str, Any]]:
    """通过 WBI 签名接口获取字幕列表，返回 [{from,to,content}, ...]。"""
    params: dict[str, Any] = {"cid": cid}
    params["aid"] = aid if aid else bvid

    signed = wbi.sign_wbi(params, client, auth.DEFAULT_HEADERS)
    headers = dict(auth.DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    resp = client.get(URL_PLAYER_WBI, params=signed, headers=headers)
    resp.raise_for_status()
    player = resp.json()
    code = player.get("code", 0)
    if code == -101 or player.get("data", {}).get("need_login_subtitle"):
        raise ExtractionError(_login_hint())

    sub_info = player.get("data", {}).get("subtitle", {}).get("subtitles", [])
    sub_info.sort(key=lambda s: _LANG_PRIORITY.get(s.get("lan", ""), 99))

    for sub in sub_info:
        sub_url = sub.get("subtitle_url")
        if not sub_url:
            continue
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url
        try:
            sub_resp = client.get(
                sub_url, headers={"User-Agent": auth.DEFAULT_HEADERS["User-Agent"]}
            )
            sub_resp.raise_for_status()
            items = [
                {
                    "from": float(e.get("from", 0)),
                    "to": float(e.get("to", 0)),
                    "content": e["content"].strip(),
                }
                for e in sub_resp.json().get("body", [])
                if e.get("content", "").strip()
            ]
            if items:
                logger.info("获取到 %d 条字幕 (lang=%s)", len(items), sub.get("lan"))
                return items
        except Exception as exc:
            logger.warning("下载字幕 URL 失败 (%s): %s", sub.get("lan"), exc)
            continue
    return []


def _login_hint() -> str:
    """登录失效的统一中文提示。"""
    return (
        "B 站字幕需要登录态，但当前登录已失效。"
        "请运行 `python -m videoread_mcp login` 扫码重新登录（约 30 秒），无需重启会话。"
    )


# ---------------------------------------------------------------------------
# 异步入口
# ---------------------------------------------------------------------------

async def extract_video(
    raw_url: str, page: int | None = None, max_pages: int = DEFAULT_MAX_PAGES
) -> dict[str, Any]:
    """异步提取视频元数据与字幕。

    Args:
        raw_url: BV 号 / AV 号 / 完整链接
        page: 指定分 P（1 起）；None 则提取前 max_pages 个分 P 的字幕
        max_pages: 不指定 page 时最多提取的分 P 数
    """
    url = _build_url(raw_url)
    bvid = _extract_bvid(url)
    if not bvid:
        raise ExtractionError(f"无法从链接中识别 BV 号: {url}")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract_sync, url, bvid, page, max_pages)


def build_meta(view: dict[str, Any], url: str) -> dict[str, Any]:
    """从 view 数据构建元数据字典（供视频/弹幕/评论工具共用）。"""
    pages = _parse_pages(view)
    stat = view.get("stat") or {}
    return {
        "title": view.get("title", "未知标题"),
        "url": url,
        "bvid": view.get("bvid", ""),
        "uploader": (view.get("owner") or {}).get("name", "未知"),
        "uploader_mid": (view.get("owner") or {}).get("mid", 0),
        "duration": int(view.get("duration", 0)),
        "duration_string": _secs_to_hms(view.get("duration", 0)),
        "view_count": stat.get("view", 0),
        "like_count": stat.get("like", 0),
        "coin_count": stat.get("coin", 0),
        "favorite_count": stat.get("favorite", 0),
        "danmaku_count": stat.get("danmaku", 0),
        "reply_count": stat.get("reply", 0),
        "upload_date": _ts_to_date(view.get("pubdate", 0)),
        "description": view.get("desc", "") or "",
        "thumbnail": view.get("pic", ""),
        "pages": pages,
    }


def _extract_sync(
    url: str, bvid: str, page: int | None, max_pages: int
) -> dict[str, Any]:
    view = fetch_view(bvid)
    pages = _parse_pages(view)
    if not pages:
        raise ExtractionError("未获取到视频分 P 信息")

    # 校验 page 参数
    if page is not None:
        if page < 1 or page > len(pages):
            raise ExtractionError(f"page={page} 超出范围（共 {len(pages)} 个分 P）")
        target_pages = [pages[page - 1]]
    else:
        target_pages = pages[:max_pages]

    meta = build_meta(view, url)

    # 逐分 P 抓字幕
    cookie = auth.effective_cookie_str()
    subtitles: list[dict[str, Any]] = []
    truncated = len(target_pages) < len(pages)

    with httpx.Client(timeout=_TIMEOUT) as client:
        for p in target_pages:
            items = []
            if p["cid"]:
                try:
                    items = fetch_subtitles(
                        client, view.get("aid"), bvid, p["cid"], cookie
                    )
                except ExtractionError:
                    raise
                except Exception as exc:
                    logger.warning("分 P%d 字幕提取失败: %s", p["page"], exc)
            subtitles.append(
                {"page": p["page"], "part": p["part"], "items": items}
            )

    return {"meta": meta, "subtitles": subtitles, "truncated": truncated}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _secs_to_hms(seconds: int) -> str:
    """秒数 → HH:MM:SS"""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _ts_to_date(ts: int) -> str:
    """Unix 时间戳 → YYYY-MM-DD。"""
    import datetime

    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""
