"""评论模块测试：解析 + 抓取（respx mock）。"""

import httpx
import pytest
import respx

from videoread_mcp import auth, comments

REPLY_URL = "https://api.bilibili.com/x/v2/reply"


def _reply_item(rpid, uname, message, like=0, ctime=1700000000, rcount=0, replies=None):
    return {
        "rpid": rpid,
        "like": like,
        "ctime": ctime,
        "rcount": rcount,
        "member": {"uname": uname, "mid": rpid, "level_info": {"current_level": 4}},
        "content": {"message": message},
        "replies": replies or [],
    }


class TestParseItem:
    def test_basic(self):
        item = _reply_item(1, "张三", "这个视频很棒", like=10, ctime=1700000000, rcount=2)
        parsed = comments._parse_item(item, include_replies=False)
        assert parsed["uname"] == "张三"
        assert parsed["content"] == "这个视频很棒"
        assert parsed["like"] == 10
        assert parsed["level"] == 4
        assert parsed["replies"] == []

    def test_include_replies(self):
        item = _reply_item(
            1, "张三", "正文",
            replies=[_reply_item(2, "李四", "同意", like=1, ctime=1700000001)],
        )
        parsed = comments._parse_item(item, include_replies=True)
        assert parsed["replies"][0]["uname"] == "李四"
        assert parsed["replies"][0]["content"] == "同意"


class TestFetchComments:
    def test_requires_cookie(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: None)
        with httpx.Client() as client:
            with pytest.raises(comments.CommentError):
                comments.fetch_comments(client, aid=123)

    def test_fetch_merged_hots(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: "SESSDATA=x; bili_jct=y")
        body = {
            "code": 0,
            "data": {
                "page": {"count": 30, "num": 1, "size": 20},
                "hots": [_reply_item(1, "热评用户", "热评内容", like=99)],
                "replies": [_reply_item(2, "时间用户", "时间序评论", like=5)],
            },
        }
        with respx.mock:
            respx.get(url__startswith=REPLY_URL).mock(
                return_value=httpx.Response(200, json=body)
            )
            with httpx.Client() as client:
                items = comments.fetch_comments(client, aid=123, sort="hot", max_comments=50)
        assert len(items) == 2
        assert items[0]["uname"] == "热评用户"
        assert items[1]["uname"] == "时间用户"

    def test_login_expired(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: "SESSDATA=x; bili_jct=y")
        with respx.mock:
            respx.get(url__startswith=REPLY_URL).mock(
                return_value=httpx.Response(200, json={"code": -101, "message": "未登录"})
            )
            with httpx.Client() as client:
                with pytest.raises(comments.CommentError):
                    comments.fetch_comments(client, aid=123)

    def test_closed(self, monkeypatch):
        monkeypatch.setattr(auth, "effective_cookie_str", lambda: "SESSDATA=x; bili_jct=y")
        with respx.mock:
            respx.get(url__startswith=REPLY_URL).mock(
                return_value=httpx.Response(200, json={"code": 12002, "message": "评论区已关闭"})
            )
            with httpx.Client() as client:
                with pytest.raises(comments.CommentError, match="关闭"):
                    comments.fetch_comments(client, aid=123)

    def test_invalid_sort(self, monkeypatch):
        with httpx.Client() as client:
            with pytest.raises(comments.CommentError, match="排序方式"):
                comments.fetch_comments(client, aid=123, sort="bogus")
