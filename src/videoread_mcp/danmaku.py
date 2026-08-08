"""Bilibili 弹幕提取 — 分段 protobuf 接口，零依赖手写 wire 解析。

接口：`x/v2/dm/web/seg.so`（每包 6 分钟，完整弹幕）。
响应是 protobuf 字节（DmSegMobileReply），这里手写 wire-format 解析，
不引入 protobuf 依赖。仅提取普通弹幕（pool 0/1），过滤代码/BAS 弹幕。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from videoread_mcp import auth

logger = logging.getLogger(__name__)

URL_SEG = "https://api.bilibili.com/x/v2/dm/web/seg.so"
SEG_SECONDS = 360  # 每包 6 分钟
_TIMEOUT = httpx.Timeout(30.0)


# ---------------------------------------------------------------------------
# protobuf wire-format 解析（DmSegMobileReply / DanmakuElem）
# ---------------------------------------------------------------------------

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """读 varint，返回 (值, 新 pos)。"""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _parse_fields(data: bytes) -> dict[int, list[Any]]:
    """解析一条 protobuf 消息为 {field_number: [values]}。"""
    fields: dict[int, list[Any]] = {}
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        fnum, wtype = key >> 3, key & 7
        if wtype == 0:  # varint
            val, pos = _read_varint(data, pos)
            fields.setdefault(fnum, []).append(val)
        elif wtype == 1:  # fixed64
            fields.setdefault(fnum, []).append(data[pos : pos + 8])
            pos += 8
        elif wtype == 2:  # length-delimited
            ln, pos = _read_varint(data, pos)
            fields.setdefault(fnum, []).append(data[pos : pos + ln])
            pos += ln
        elif wtype == 5:  # fixed32
            fields.setdefault(fnum, []).append(data[pos : pos + 4])
            pos += 4
        else:
            raise ValueError(f"不支持的 protobuf wire type {wtype} (field {fnum})")
    return fields


def _parse_dm_seg(data: bytes) -> list[dict[str, Any]]:
    """解析 DmSegMobileReply，返回 [{time, content, ctime, mode, pool}, ...]。

    DmSegMobileReply.field1 = repeated DanmakuElem（每条即一个子消息）。
    DanmakuElem：1=id 2=progress(ms) 3=mode 5=color 6=midHash
                7=content 8=ctime 9=weight 11=pool 12=idStr 13=attr
    """
    reply = _parse_fields(data)
    items: list[dict[str, Any]] = []
    for raw in reply.get(1, []):
        if not isinstance(raw, bytes):
            continue
        e = _parse_fields(raw)
        content_bytes = e.get(7, [b""])[0]
        if not isinstance(content_bytes, bytes):
            continue
        content = content_bytes.decode("utf-8", "replace").strip()
        if not content:
            continue
        items.append(
            {
                "time": (e.get(2, [0])[0]) / 1000.0,  # ms → s
                "content": content,
                "ctime": e.get(8, [0])[0],
                "mode": e.get(3, [0])[0],
                "pool": e.get(11, [0])[0],
            }
        )
    return items


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

def fetch_danmaku(
    client: httpx.Client,
    aid: int | None,
    cid: int,
    duration: int,
    max_items: int = 2000,
) -> list[dict[str, Any]]:
    """按 6 分钟分段抓取全部弹幕，过滤 pool=2（代码/BAS），超限均匀采样。"""
    if not cid:
        return []
    seg_count = max(1, -(-duration // SEG_SECONDS))  # ceil
    all_items: list[dict[str, Any]] = []
    cookie = auth.effective_cookie_str()

    headers = dict(auth.DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    for idx in range(1, seg_count + 1):
        try:
            resp = client.get(
                URL_SEG,
                params={
                    "type": 1,
                    "oid": cid,
                    "pid": aid or "",
                    "segment_index": idx,
                },
                headers=headers,
            )
            if resp.status_code == 304:
                continue  # B 站对空分段/无新数据返回 304，视作该段无弹幕
            resp.raise_for_status()
            items = _parse_dm_seg(resp.content)
            all_items.extend(items)
            logger.info("弹幕分段 %d/%d: %d 条", idx, seg_count, len(items))
        except Exception as exc:
            logger.warning("弹幕分段 %d 获取失败: %s", idx, exc)

    if not all_items:
        return []

    # 过滤普通弹幕（pool 0/1），只保留内容与时间
    normal = [
        {"time": round(i["time"], 2), "content": i["content"]}
        for i in all_items
        if i["pool"] in (0, 1)
    ]
    return _sample(normal, max_items)


def _sample(items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    """超限时均匀采样（保留顺序，尽量包含首尾）。"""
    if len(items) <= max_items:
        return items
    if max_items <= 1:
        return [items[0]]
    step = (len(items) - 1) / (max_items - 1)
    idx = sorted({min(len(items) - 1, round(i * step)) for i in range(max_items)})
    # 极端情况下去重后不足，退化为整数步长采样
    if len(idx) < max_items:
        stride = len(items) / max_items
        idx = sorted({int(i * stride) for i in range(max_items)})
    return [items[i] for i in idx]
