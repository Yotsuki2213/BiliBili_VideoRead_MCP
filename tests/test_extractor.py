"""extractor 模块测试：view 元数据 + WBI 字幕全链路（respx mock，无网络）。"""

import httpx
import pytest
import respx

from videoread_mcp import extractor, wbi

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
PLAYER_URL = "https://api.bilibili.com/x/player/wbi/v2"
SUBTITLE_URL = "https://aisubtitle.hdslb.com/123.json"

BVID = "BV1xx411x7xx"


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


def _view_json() -> dict:
    return {
        "code": 0,
        "data": {
            "bvid": BVID,
            "aid": 123,
            "title": "测试视频",
            "duration": 100,
            "owner": {"name": "测试UP", "mid": 456},
            "pic": "https://pic.example/1.jpg",
            "pubdate": 1577835803,
            "desc": "这是简介内容",
            "cid": 999,
            "stat": {"view": 10000, "like": 500, "coin": 10, "favorite": 20, "danmaku": 30, "reply": 5},
            "pages": [
                {"page": 1, "cid": 999, "part": "P1 第一集", "duration": 100},
                {"page": 2, "cid": 1000, "part": "P2 第二集", "duration": 80},
            ],
        },
    }


def _player_json(cid: int) -> dict:
    return {
        "code": 0,
        "data": {
            "subtitle": {
                "subtitles": [
                    {"lan": "zh-CN", "subtitle_url": SUBTITLE_URL},
                ]
            }
        },
    }


def _subtitle_json() -> dict:
    return {
        "body": [
            {"from": 0.0, "to": 2.0, "content": "大家好"},
            {"from": 2.5, "to": 5.0, "content": "今天讲 WBI"},
        ]
    }


@pytest.fixture(autouse=True)
def _clear_wbi_cache():
    wbi._KEY_CACHE.clear()
    yield
    wbi._KEY_CACHE.clear()


class TestBuildUrl:
    def test_full_url(self):
        assert extractor._build_url("https://www.bilibili.com/video/BV1xx411x7xx/") == (
            "https://www.bilibili.com/video/BV1xx411x7xx/"
        )

    def test_bvid(self):
        assert "BV1xx411x7xx" in extractor._build_url("BV1xx411x7xx")

    def test_avid(self):
        assert "av123456" in extractor._build_url("av123456")

    def test_digits(self):
        assert "av123456" in extractor._build_url("123456")

    def test_short_link(self):
        url = extractor._build_url("b23.tv/abc")
        assert url.startswith("https://b23.tv/abc")


class TestExtractBvid:
    def test_from_url(self):
        assert extractor._extract_bvid("https://www.bilibili.com/video/BV1xx411x7xx") == "BV1xx411x7xx"

    def test_missing(self):
        assert extractor._extract_bvid("https://example.com") == ""


class TestParsePages:
    def test_multi(self):
        view = _view_json()["data"]
        pages = extractor._parse_pages(view)
        assert len(pages) == 2
        assert pages[0]["cid"] == 999
        assert pages[1]["part"] == "P2 第二集"

    def test_single_no_pages(self):
        view = {"cid": 5, "title": "单P", "duration": 30}
        pages = extractor._parse_pages(view)
        assert len(pages) == 1
        assert pages[0]["cid"] == 5


class TestBuildMeta:
    def test_fields(self):
        meta = extractor.build_meta(_view_json()["data"], "https://x/BV")
        assert meta["title"] == "测试视频"
        assert meta["uploader"] == "测试UP"
        assert meta["view_count"] == 10000
        assert meta["upload_date"] == "2020-01-01"
        assert len(meta["pages"]) == 2
        assert meta["duration_string"] == "01:40"


class TestExtractSync:
    def test_all_pages(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            respx.get(url__startswith=PLAYER_URL).mock(
                side_effect=[
                    httpx.Response(200, json=_player_json(999)),
                    httpx.Response(200, json=_player_json(1000)),
                ]
            )
            respx.get(SUBTITLE_URL).mock(
                return_value=httpx.Response(200, json=_subtitle_json())
            )

            result = extractor._extract_sync("https://x/BV1xx411x7xx", BVID, page=None, max_pages=10)

        assert result["meta"]["title"] == "测试视频"
        assert len(result["subtitles"]) == 2
        assert result["subtitles"][0]["page"] == 1
        assert result["subtitles"][0]["items"][0]["content"] == "大家好"
        assert result["subtitles"][1]["page"] == 2
        assert result["truncated"] is False

    def test_specific_page(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            respx.get(url__startswith=PLAYER_URL).mock(
                return_value=httpx.Response(200, json=_player_json(1000))
            )
            respx.get(SUBTITLE_URL).mock(
                return_value=httpx.Response(200, json=_subtitle_json())
            )

            result = extractor._extract_sync("https://x/BV1xx411x7xx", BVID, page=2, max_pages=10)

        assert len(result["subtitles"]) == 1
        assert result["subtitles"][0]["page"] == 2
        assert result["subtitles"][0]["part"] == "P2 第二集"

    def test_page_out_of_range(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            with pytest.raises(extractor.ExtractionError):
                extractor._extract_sync("https://x/BV1xx411x7xx", BVID, page=99, max_pages=10)

    def test_login_expired(self):
        """player 返回 -101 → 明确引导重新扫码。"""
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            respx.get(url__startswith=PLAYER_URL).mock(
                return_value=httpx.Response(
                    200, json={"code": -101, "message": "账号未登录"}
                )
            )
            with pytest.raises(extractor.ExtractionError) as exc:
                extractor._extract_sync("https://x/BV1xx411x7xx", BVID, page=1, max_pages=10)
        assert "login" in str(exc.value) or "重新扫码" in str(exc.value)

    def test_need_login_subtitle(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            respx.get(url__startswith=PLAYER_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"code": 0, "data": {"need_login_subtitle": True}},
                )
            )
            with pytest.raises(extractor.ExtractionError):
                extractor._extract_sync("https://x/BV1xx411x7xx", BVID, page=1, max_pages=10)


class TestExtractVideoAsync:
    @pytest.mark.asyncio
    async def test_async_entry(self):
        with respx.mock:
            respx.get(NAV_URL).mock(return_value=httpx.Response(200, json=_nav_json()))
            respx.get(VIEW_URL).mock(return_value=httpx.Response(200, json=_view_json()))
            respx.get(url__startswith=PLAYER_URL).mock(
                return_value=httpx.Response(200, json=_player_json(999))
            )
            respx.get(SUBTITLE_URL).mock(
                return_value=httpx.Response(200, json=_subtitle_json())
            )
            result = await extractor.extract_video(BVID, page=1)
        assert result["meta"]["bvid"] == BVID
        assert len(result["subtitles"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        with pytest.raises(extractor.ExtractionError):
            await extractor.extract_video("https://example.com/not-bilibili")
