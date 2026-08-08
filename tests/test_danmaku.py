"""弹幕模块测试：零依赖 protobuf 解析器 + seg.so 抓取 + 采样。"""

from pathlib import Path

import httpx
import pytest
import respx

from videoread_mcp import auth, danmaku

FIXTURE = Path(__file__).parent / "fixtures" / "seg1.bin"


def _varint(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _make_elem(progress_ms: int, content: str, pool: int = 0) -> bytes:
    """构造一条 DanmakuElem：field2=progress(ms) field7=content field11=pool。"""
    body = b""
    body += _varint(2 << 3 | 0) + _varint(progress_ms)
    content_bytes = content.encode("utf-8")
    body += _varint(7 << 3 | 2) + _varint(len(content_bytes)) + content_bytes
    body += _varint(11 << 3 | 0) + _varint(pool)
    return _varint(1 << 3 | 2) + _varint(len(body)) + body


class TestWireParser:
    def test_parse_real_fixture(self):
        """用 2026-08-08 抓取的真实 seg.so 字节验证解析器。"""
        items = danmaku._parse_dm_seg(FIXTURE.read_bytes())
        assert len(items) > 100
        assert all("content" in i and "time" in i for i in items)
        assert items[0]["time"] == pytest.approx(36.716, abs=0.01)
        assert items[0]["content"]

    def test_parse_handcrafted(self):
        reply = _make_elem(10000, "你好世界") + _make_elem(20000, "第二条", pool=1) + _make_elem(30000, "代码弹幕", pool=2)
        items = danmaku._parse_dm_seg(reply)
        assert len(items) == 3
        assert items[0]["time"] == 10.0
        assert items[0]["content"] == "你好世界"
        assert items[1]["pool"] == 1
        assert items[2]["pool"] == 2

    def test_empty(self):
        assert danmaku._parse_dm_seg(b"") == []


class TestFetchDanmaku:
    def test_fetch_filters_and_sorts(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: None)
        fixture = FIXTURE.read_bytes()
        with respx.mock:
            respx.get(url__startswith=danmaku.URL_SEG).mock(
                return_value=httpx.Response(200, content=fixture)
            )
            with httpx.Client() as client:
                items = danmaku.fetch_danmaku(client, aid=1, cid=2, duration=400, max_items=2000)
        # duration=400 → 2 个分段，每条都返回 fixture
        assert len(items) > 300
        assert all("pool" not in i for i in items)  # 已过滤 pool 字段
        assert all("content" in i and "time" in i for i in items)

    def test_no_cid(self, monkeypatch):
        with httpx.Client() as client:
            assert danmaku.fetch_danmaku(client, aid=1, cid=0, duration=100) == []

    def test_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: None)
        with respx.mock:
            respx.get(url__startswith=danmaku.URL_SEG).mock(
                return_value=httpx.Response(500)
            )
            with httpx.Client() as client:
                assert danmaku.fetch_danmaku(client, aid=1, cid=2, duration=100) == []

    def test_304_treated_as_empty_segment(self, monkeypatch):
        """B 站对空分段返回 304，应视作无弹幕继续，而非报错。"""
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: None)
        with respx.mock:
            respx.get(url__startswith=danmaku.URL_SEG).mock(
                return_value=httpx.Response(304)
            )
            with httpx.Client() as client:
                assert danmaku.fetch_danmaku(client, aid=1, cid=2, duration=400) == []


class TestSampling:
    def test_no_sampling_when_within_limit(self):
        items = [{"time": i, "content": str(i)} for i in range(10)]
        assert danmaku._sample(items, 20) == items

    def test_uniform_sampling(self):
        items = [{"time": i, "content": str(i)} for i in range(100)]
        sampled = danmaku._sample(items, 10)
        assert len(sampled) == 10
        assert sampled[0] == items[0]
        assert sampled[-1] == items[-1]
        # 采样保持相对顺序
        times = [s["time"] for s in sampled]
        assert times == sorted(times)

    def test_sample_more_than_len(self):
        items = [{"time": i, "content": str(i)} for i in range(5)]
        sampled = danmaku._sample(items, 10)
        assert sampled == items
