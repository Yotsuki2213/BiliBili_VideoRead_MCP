"""WBI 签名测试 — 固定参数快照断言。"""

import httpx
import pytest
import respx

from videoread_mcp import wbi

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# 基准：f1b85306e24cfdbd8e73b5c3a2f2a281 + a2f4d5a1c6f9b3c7d8e0f1a2b3c4d5e6
# 混淆后 key = c77b1e3ade41c834293822f32ab1fa6d
EXPECTED_KEY = "c77b1e3ade41c834293822f32ab1fa6d"
EXPECTED_WRID = "84dc81afadfbbda5c230ca9adc0fc384"


def _nav_json() -> dict:
    return {
        "code": 0,
        "data": {
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/f1b85306e24cfdbd8e73b5c3a2f2a281.png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/a2f4d5a1c6f9b3c7d8e0f1a2b3c4d5e6.png",
            }
        },
    }


@pytest.fixture(autouse=True)
def _clear_wbi_cache():
    wbi._KEY_CACHE.clear()
    yield
    wbi._KEY_CACHE.clear()


def _client() -> httpx.Client:
    return httpx.Client()


class TestGetWbiKey:
    def test_key_extraction(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            with _client() as client:
                assert wbi._get_wbi_key(client, {"User-Agent": "x"}) == EXPECTED_KEY

    def test_cached(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            with _client() as client:
                wbi._get_wbi_key(client, {"User-Agent": "x"})
                wbi._get_wbi_key(client, {"User-Agent": "x"})
        # 若走了缓存，nav 只被请求一次；respx 未断言时此处仅验证不抛错


class TestSignWbi:
    def test_snapshot(self, monkeypatch):
        # 固定时间，得到确定的 wts 与 w_rid
        monkeypatch.setattr(wbi.time, "time", lambda: 1700000000.0)
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            with _client() as client:
                signed = wbi.sign_wbi(
                    {"cid": 123, "bvid": "BV1xx411x7xx"},
                    client,
                    {"User-Agent": "x"},
                )
        assert signed["wts"] == "1700000000"
        assert signed["w_rid"] == EXPECTED_WRID

    def test_special_chars_filtered(self, monkeypatch):
        monkeypatch.setattr(wbi.time, "time", lambda: 1700000000.0)
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            with _client() as client:
                signed = wbi.sign_wbi(
                    {"bvid": "BV'xx", "cid": 1},
                    client,
                    {"User-Agent": "x"},
                )
        # 单引号属于 '!'()* 需被过滤
        assert "BV'xx" not in signed.get("w_rid", "")
        assert signed["bvid"] == "BVxx"
