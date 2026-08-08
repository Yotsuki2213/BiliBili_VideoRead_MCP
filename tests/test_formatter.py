"""formatter 模块测试：视频/弹幕/评论三种 Markdown 输出。"""

from videoread_mcp import formatter


def _meta(**overrides):
    base = {
        "title": "测试视频",
        "uploader": "测试UP主",
        "duration": 120,
        "duration_string": "02:00",
        "view_count": 10000,
        "like_count": 500,
        "coin_count": 10,
        "favorite_count": 20,
        "danmaku_count": 30,
        "reply_count": 5,
        "upload_date": "2024-07-01",
        "url": "https://www.bilibili.com/video/BV123/",
        "description": "这是一个测试视频的简介",
        "pages": [{"page": 1, "part": "P1", "duration": 120}],
    }
    base.update(overrides)
    return base


class TestFormatVideo:
    def test_single_page(self):
        subtitles = [{
            "page": 1,
            "part": "P1",
            "items": [
                {"from": 0.0, "to": 2.0, "content": "大家好"},
                {"from": 2.5, "to": 5.0, "content": "今天的内容"},
            ],
        }]
        md = formatter.format_video_markdown(_meta(), subtitles)
        assert "# 测试视频" in md
        assert "测试UP主" in md
        assert "1.0万" in md
        assert "大家好" in md
        assert "今天的内容" in md
        assert "暂无可用字幕" not in md
        assert "## 🎬 字幕内容" in md

    def test_no_subtitles(self):
        md = formatter.format_video_markdown(_meta(), [])
        assert "暂无可用字幕" in md

    def test_multi_page(self):
        subtitles = [
            {"page": 1, "part": "P1 第一章", "items": [{"from": 0.0, "to": 1.0, "content": "第一P"}]},
            {"page": 2, "part": "P2 第二章", "items": [{"from": 0.0, "to": 1.0, "content": "第二P"}]},
        ]
        meta = _meta(pages=[
            {"page": 1, "part": "P1 第一章", "duration": 60},
            {"page": 2, "part": "P2 第二章", "duration": 60},
        ])
        md = formatter.format_video_markdown(meta, subtitles)
        assert "## 📑 分 P 列表" in md
        assert "| P1 | P1 第一章 |" in md
        assert "### P1 P1 第一章" in md
        assert "### P2 P2 第二章" in md
        assert "第一P" in md
        assert "第二P" in md

    def test_with_timestamps(self):
        subtitles = [{
            "page": 1,
            "part": "P1",
            "items": [{"from": 0.0, "to": 2.0, "content": "你好"}],
        }]
        md = formatter.format_video_markdown(_meta(), subtitles, include_timestamps=True)
        assert "**[00:00]**" in md
        assert "> 你好" in md


class TestFormatDanmaku:
    def test_basic(self):
        danmaku = [{"time": 36.7, "content": "来了"}, {"time": 74.3, "content": "关注了"}]
        md = formatter.format_danmaku_markdown(danmaku, _meta())
        assert "弹幕" in md
        assert "- **[" in md
        assert "**来了**" not in md  # 内容不应被加粗
        assert "共提取 2 条弹幕" in md
        assert "[00:36]" in md
        assert "[01:14]" in md

    def test_empty(self):
        md = formatter.format_danmaku_markdown([], _meta())
        assert "暂无弹幕" in md


class TestFormatComments:
    def test_basic(self):
        comments = [
            {
                "uname": "张三",
                "content": "讲得真好",
                "like": 100,
                "ctime": 1700000000,
                "level": 4,
                "rcount": 2,
                "replies": [],
            }
        ]
        md = formatter.format_comments_markdown(comments, _meta())
        assert "共提取 1 条评论" in md
        assert "张三" in md
        assert "Lv.4" in md
        assert "讲得真好" in md
        assert "100" in md

    def test_with_replies(self):
        comments = [
            {
                "uname": "张三",
                "content": "正文",
                "like": 1,
                "ctime": 1700000000,
                "level": 1,
                "rcount": 1,
                "replies": [{"uname": "李四", "content": "回复内容", "like": 0, "ctime": 1700000001}],
            }
        ]
        md = formatter.format_comments_markdown(comments, _meta())
        assert "李四" in md
        assert "回复内容" in md
        assert "↳" in md

    def test_empty(self):
        md = formatter.format_comments_markdown([], _meta())
        assert "暂无评论" in md
