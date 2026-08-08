"""MCP Server — 注册 3 个工具：字幕 / 弹幕 / 评论。

协议纪律：stdout 仅供 MCP JSON-RPC 通信，日志一律走 stderr。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from videoread_mcp import comments as comments_mod
from videoread_mcp import danmaku as danmaku_mod
from videoread_mcp import extractor, formatter

logger = logging.getLogger(__name__)

server = Server("videoread-mcp")

TOOL_VIDEO = "extract_bilibili_video"
TOOL_DANMAKU = "extract_bilibili_danmaku"
TOOL_COMMENTS = "extract_bilibili_comments"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=TOOL_VIDEO,
            description=(
                "提取 Bilibili 视频的元数据与字幕，整理为结构化 Markdown。"
                "支持多分 P 视频；不传 page 时提取前若干分 P 字幕。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Bilibili 视频链接，支持 BV 号、AV 号、完整 URL",
                    },
                    "include_timestamps": {
                        "type": "boolean",
                        "description": "是否在字幕中保留时间戳，默认 false",
                    },
                    "page": {
                        "type": "integer",
                        "description": "指定分 P（1 起）；不传则提取前 10 个分 P 字幕",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name=TOOL_DANMAKU,
            description=(
                "提取 Bilibili 视频的弹幕（完整弹幕，按时间排序，超限自动采样），"
                "输出为 Markdown 列表。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Bilibili 视频链接",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "最多返回的弹幕条数，超限均匀采样，默认 2000",
                    },
                    "page": {
                        "type": "integer",
                        "description": "指定分 P（1 起）；不传默认取第 1 个分 P",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name=TOOL_COMMENTS,
            description=(
                "提取 Bilibili 视频的评论（按热度或时间排序），输出为 Markdown。"
                "需要登录态。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Bilibili 视频链接",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["hot", "time"],
                        "description": "排序：hot=按热度（默认），time=按时间",
                    },
                    "max_comments": {
                        "type": "integer",
                        "description": "最多返回的根评论数，默认 50",
                    },
                    "include_replies": {
                        "type": "boolean",
                        "description": "是否附带每条评论下的子回复，默认 false",
                    },
                },
                "required": ["url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    url = arguments.get("url", "")
    try:
        if name == TOOL_VIDEO:
            data = await extractor.extract_video(
                url,
                page=arguments.get("page"),
            )
            markdown = formatter.format_video_markdown(
                data["meta"],
                data.get("subtitles", []),
                include_timestamps=bool(arguments.get("include_timestamps", False)),
            )
            return [TextContent(type="text", text=markdown)]

        if name == TOOL_DANMAKU:
            return await _handle_danmaku(arguments)

        if name == TOOL_COMMENTS:
            return await _handle_comments(arguments)

        raise ValueError(f"未知工具: {name}")
    except (extractor.ExtractionError, comments_mod.CommentError) as e:
        logger.error("%s 失败: %s", name, e)
        return [TextContent(type="text", text=f"❌ {e}")]
    except Exception as e:
        logger.exception("%s 异常", name)
        return [TextContent(type="text", text=f"❌ 提取失败: {e}")]


async def _handle_danmaku(arguments: dict[str, Any]) -> list[TextContent]:
    url = arguments.get("url", "")
    max_items = int(arguments.get("max_items", 2000))
    page = arguments.get("page")

    view = _resolve_view(url)
    pages = extractor._parse_pages(view)
    target = _pick_page(pages, page)
    meta = extractor.build_meta(view, url)

    items = await _fetch_danmaku_sync(view, target["cid"], max_items)
    return [TextContent(type="text", text=formatter.format_danmaku_markdown(items, meta))]


async def _handle_comments(arguments: dict[str, Any]) -> list[TextContent]:
    url = arguments.get("url", "")
    sort = arguments.get("sort", "hot")
    max_comments = int(arguments.get("max_comments", 50))
    include_replies = bool(arguments.get("include_replies", False))

    view = _resolve_view(url)
    aid = int(view.get("aid") or 0)
    meta = extractor.build_meta(view, url)

    items = await _fetch_comments_sync(aid, sort, max_comments, include_replies)
    return [TextContent(type="text", text=formatter.format_comments_markdown(items, meta))]


def _resolve_view(url: str) -> dict[str, Any]:
    """把任意链接解析为 view 数据。"""
    bvid = extractor._extract_bvid(extractor._build_url(url))
    if not bvid:
        raise extractor.ExtractionError(f"无法从链接中识别 BV 号: {url}")
    return extractor.fetch_view(bvid)


def _pick_page(pages: list[dict[str, Any]], page: int | None) -> dict[str, Any]:
    """按 page 参数选分 P；不传默认第 1 个。"""
    if page is None:
        return pages[0]
    if page < 1 or page > len(pages):
        raise extractor.ExtractionError(f"page={page} 超出范围（共 {len(pages)} 个分 P）")
    return pages[page - 1]


async def _fetch_danmaku_sync(
    view: dict[str, Any], cid: int, max_items: int
) -> list[dict[str, Any]]:
    """在线程池里跑弹幕抓取（阻塞网络）。"""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _fetch_danmaku_exec,
        view,
        cid,
        max_items,
    )


def _fetch_danmaku_exec(
    view: dict[str, Any], cid: int, max_items: int
) -> list[dict[str, Any]]:
    import httpx

    aid = view.get("aid")
    duration = int(view.get("duration") or 0)
    with httpx.Client(timeout=danmaku_mod._TIMEOUT) as client:
        return danmaku_mod.fetch_danmaku(client, aid, cid, duration, max_items)


async def _fetch_comments_sync(
    aid: int, sort: str, max_comments: int, include_replies: bool
) -> list[dict[str, Any]]:
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _fetch_comments_exec, aid, sort, max_comments, include_replies
    )


def _fetch_comments_exec(
    aid: int, sort: str, max_comments: int, include_replies: bool
) -> list[dict[str, Any]]:
    import httpx

    with httpx.Client(timeout=comments_mod._TIMEOUT) as client:
        return comments_mod.fetch_comments(
            client, aid, sort, max_comments, include_replies
        )


async def _run_server() -> None:
    """使用 stdio 传输启动 MCP 服务器。"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """命令行入口点（MCP stdio 服务）。"""
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
