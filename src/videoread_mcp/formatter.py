"""Markdown 格式化器 — 视频/弹幕/评论 → AI 友好 Markdown。"""

from __future__ import annotations

from typing import Any

from videoread_mcp import comments as comments_mod


def _secs_to_hms(seconds: float) -> str:
    """秒数 → HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _format_count(n: int) -> str:
    """格式化数字（万、亿）。"""
    n = int(n or 0)
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def _format_date(date_str: str) -> str:
    """YYYYMMDD → YYYY-MM-DD（已是 YYYY-MM-DD 则原样返回）。"""
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _group_into_paragraphs(
    subtitles: list[dict[str, Any]], gap_threshold: float = 2.0
) -> list[list[dict[str, Any]]]:
    """按时间间隔将字幕分组为段落。"""
    if not subtitles:
        return []
    paragraphs: list[list[dict[str, Any]]] = []
    current = [subtitles[0]]
    for i in range(1, len(subtitles)):
        gap = subtitles[i]["from"] - subtitles[i - 1]["to"]
        if gap >= gap_threshold:
            paragraphs.append(current)
            current = [subtitles[i]]
        else:
            current.append(subtitles[i])
    if current:
        paragraphs.append(current)
    return paragraphs


def format_video_markdown(
    meta: dict[str, Any],
    subtitles: list[dict[str, Any]],
    include_timestamps: bool = False,
) -> str:
    """视频元数据 + 各分 P 字幕 → Markdown。

    subtitles 结构：[{page, part, items: [{from, to, content}]}, ...]
    """
    lines: list[str] = []
    lines.append(f"# {meta.get('title', '未知标题')}")
    lines.append("")

    # ── 元信息表 ──
    lines.append("## 📋 视频信息")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| UP 主 | {meta.get('uploader', '未知')} |")
    lines.append(f"| 时长 | {meta.get('duration_string') or _secs_to_hms(meta.get('duration', 0))} |")
    for label, key in (
        ("播放量", "view_count"),
        ("点赞数", "like_count"),
        ("硬币数", "coin_count"),
        ("收藏数", "favorite_count"),
        ("弹幕数", "danmaku_count"),
        ("评论数", "reply_count"),
    ):
        if meta.get(key):
            lines.append(f"| {label} | {_format_count(meta[key])} |")
    if meta.get("upload_date"):
        lines.append(f"| 发布日期 | {_format_date(meta['upload_date'])} |")
    if meta.get("url"):
        lines.append(f"| 链接 | {meta['url']} |")
    lines.append("")

    # ── 分 P 列表 ──
    pages = meta.get("pages") or []
    if len(pages) > 1:
        lines.append("## 📑 分 P 列表")
        lines.append("")
        lines.append("| P | 标题 | 时长 |")
        lines.append("|---|------|------|")
        for p in pages:
            lines.append(
                f"| P{p['page']} | {p.get('part', '')} | "
                f"{_secs_to_hms(p.get('duration', 0))} |"
            )
        lines.append("")

    # ── 描述 ──
    description = (meta.get("description") or "").strip()
    if description:
        lines.append("## 📝 视频简介")
        lines.append("")
        lines.append(description[:500])
        if len(description) > 500:
            lines.append("")
            lines.append("> …（简介过长，已截断）")
        lines.append("")

    # ── 字幕 ──
    lines.append("")
    _append_subtitles(lines, subtitles, include_timestamps)

    return "\n".join(lines).strip()


def _append_subtitles(
    lines: list[str], subtitles: list[dict[str, Any]], include_timestamps: bool
) -> None:
    """将各分 P 字幕追加到 lines。"""
    single = len(subtitles) == 1
    has_any = any(s.get("items") for s in subtitles)

    if not has_any:
        lines.append("## ⚠️ 字幕")
        lines.append("")
        lines.append("> 该视频暂无可用字幕（AI 字幕可能未开启或需要登录）。")
        return

    if single:
        lines.append("## 🎬 字幕内容")
    else:
        lines.append("## 🎬 字幕内容（按分 P）")

    for sub in subtitles:
        items = sub.get("items") or []
        if not items:
            continue
        if not single:
            lines.append("")
            lines.append(f"### P{sub['page']} {sub.get('part', '')}")
        lines.append("")
        for para in _group_into_paragraphs(items):
            if include_timestamps:
                lines.append(f"> **[{_secs_to_hms(para[0]['from'])}]**")
                lines.append(">")
            for line in para:
                lines.append(f"> {line['content']}" if include_timestamps else line["content"])
            lines.append("")


def format_danmaku_markdown(
    danmaku: list[dict[str, Any]], meta: dict[str, Any]
) -> str:
    """弹幕列表 → Markdown。danmaku: [{time, content}, ...]"""
    lines: list[str] = []
    lines.append(f"# 弹幕 · {meta.get('title', '未知标题')}")
    lines.append("")
    lines.append("> 按时间顺序，共提取 %d 条弹幕" % len(danmaku))
    lines.append("")
    if not danmaku:
        lines.append("该视频暂无弹幕。")
        return "\n".join(lines)

    for d in danmaku:
        ts = _secs_to_hms(d["time"])
        lines.append(f"- **[{ts}]** {d['content']}")
    return "\n".join(lines).strip()


def format_comments_markdown(
    comments: list[dict[str, Any]], meta: dict[str, Any]
) -> str:
    """评论列表 → Markdown。comments: [{uname, content, like, ctime, level, replies}, ...]"""
    lines: list[str] = []
    lines.append(f"# 评论 · {meta.get('title', '未知标题')}")
    lines.append("")
    lines.append("> 共提取 %d 条评论" % len(comments))
    lines.append("")
    if not comments:
        lines.append("该视频暂无评论。")
        return "\n".join(lines)

    for i, c in enumerate(comments, 1):
        date = comments_mod.format_ctime(c.get("ctime", 0))
        lines.append(f"### {i}. {c.get('uname', '匿名')}（Lv.{c.get('level', 0)}）")
        lines.append(f"> 点赞 {_format_count(c.get('like', 0))} · {date} · 回复 {c.get('rcount', 0)}")
        lines.append("")
        lines.append(c.get("content", ""))
        for r in c.get("replies", []):
            rdate = comments_mod.format_ctime(r.get("ctime", 0))
            lines.append("")
            lines.append(f"> ↳ **{r.get('uname', '匿名')}**（{rdate}）：{r.get('content', '')}")
        lines.append("")
    return "\n".join(lines).strip()
