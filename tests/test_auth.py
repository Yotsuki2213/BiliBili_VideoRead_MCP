"""auth 模块测试：凭证读写、环境变量覆盖、SESSDATA 过期解析、扫码状态机。"""

import httpx
import pytest
import respx

from videoread_mcp import auth

URL_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
URL_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
URL_NAV = "https://api.bilibili.com/x/web-interface/nav"


async def _noop_sleep(_x) -> None:
    pass


class TestSessdataExpiry:
    def test_basic(self):
        assert auth.sessdata_expiry("abc%2C1801306292") == 1801306292.0

    def test_invalid(self):
        assert auth.sessdata_expiry("abc") is None
        assert auth.sessdata_expiry("") is None
        assert auth.sessdata_expiry("a%2Cnotanumber") is None


class TestCredentialRoundtrip:
    def test_save_load(self, tmp_path):
        path = tmp_path / "auth.json"
        creds = auth.Credentials(
            sessdata="sess",
            bili_jct="jct",
            dedeuserid="123",
            refresh_token="rt",
            uname="测试用户",
            mid=456,
        )
        auth.save_credentials(creds, path)
        loaded = auth.load_credentials(path)
        assert loaded.sessdata == "sess"
        assert loaded.bili_jct == "jct"
        assert loaded.dedeuserid == "123"
        assert loaded.refresh_token == "rt"
        assert loaded.uname == "测试用户"
        assert loaded.mid == 456

    def test_load_missing(self, tmp_path):
        assert auth.load_credentials(tmp_path / "nope.json") is None

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "auth.json"
        path.write_text("{invalid json", encoding="utf-8")
        assert auth.load_credentials(path) is None

    def test_delete(self, tmp_path):
        path = tmp_path / "auth.json"
        auth.save_credentials(auth.Credentials(sessdata="s"), path)
        assert auth.delete_credentials(path) is True
        assert auth.delete_credentials(path) is False

    def test_cookie_str(self):
        c = auth.Credentials(sessdata="s", bili_jct="j", dedeuserid="1")
        assert "SESSDATA=s" in c.cookie_str()
        assert "bili_jct=j" in c.cookie_str()
        assert "DedeUserID=1" in c.cookie_str()


class TestEnvOverride:
    def test_full_cookie(self, monkeypatch):
        monkeypatch.setenv("BILIBILI_COOKIE", "SESSDATA=x; bili_jct=y")
        creds = auth.get_credentials()
        assert creds is not None
        assert creds.bili_jct == "__RAW_COOKIE__"
        assert auth.effective_cookie_str() == "SESSDATA=x; bili_jct=y"

    def test_sessdata_jct(self, monkeypatch):
        monkeypatch.delenv("BILIBILI_COOKIE", raising=False)
        monkeypatch.setenv("BILIBILI_SESSDATA", "sess")
        monkeypatch.setenv("BILIBILI_BILI_JCT", "jct")
        assert auth.effective_cookie_str() == "SESSDATA=sess; bili_jct=jct"

    def test_file_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("BILIBILI_COOKIE", raising=False)
        monkeypatch.delenv("BILIBILI_SESSDATA", raising=False)
        monkeypatch.delenv("BILIBILI_BILI_JCT", raising=False)
        path = tmp_path / "auth.json"
        auth.save_credentials(auth.Credentials(sessdata="fsess", bili_jct="fjct"), path)
        monkeypatch.setattr(auth, "creds_path", lambda: path)
        assert auth.effective_cookie_str() == "SESSDATA=fsess; bili_jct=fjct"

    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("BILIBILI_COOKIE", raising=False)
        monkeypatch.delenv("BILIBILI_SESSDATA", raising=False)
        monkeypatch.delenv("BILIBILI_BILI_JCT", raising=False)
        monkeypatch.setattr(auth, "load_credentials", lambda path=None: None)
        assert auth.get_credentials() is None
        assert auth.effective_cookie_str() is None


class TestParseSetCookie:
    def test_parse(self):
        cookies = auth._parse_set_cookie(
            [
                "SESSDATA=abc%2C123; Path=/; Domain=.bilibili.com; HttpOnly",
                "bili_jct=jvalue; Path=/",
                "DedeUserID=42; Path=/",
            ]
        )
        assert cookies == {"SESSDATA": "abc%2C123", "bili_jct": "jvalue", "DedeUserID": "42"}


def _success_poll_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "data": {
                "url": "",
                "refresh_token": "refresh_token_value",
                "timestamp": 1700000000000,
                "code": 0,
            },
        },
        headers=httpx.Headers(
            [
                ("set-cookie", "SESSDATA=sessdata_value; Path=/; HttpOnly"),
                ("set-cookie", "bili_jct=bili_jct_value; Path=/"),
                ("set-cookie", "DedeUserID=12345; Path=/"),
                ("set-cookie", "DedeUserID__ckMd5=md5val; Path=/"),
                ("set-cookie", "sid=sidval; Path=/"),
            ]
        ),
    )


class TestQrLogin:
    @pytest.mark.asyncio
    async def test_full_flow(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth, "_render_qr", lambda url: None)
        monkeypatch.setattr(auth.asyncio, "sleep", _noop_sleep)
        path = tmp_path / "auth.json"
        monkeypatch.setattr(auth, "creds_path", lambda: path)

        with respx.mock:
            respx.get(URL_GENERATE).mock(
                return_value=httpx.Response(
                    200,
                    json={"code": 0, "data": {"url": "https://bilibili.com/qr", "qrcode_key": "k123"}},
                )
            )
            respx.get(url__startswith=URL_POLL).mock(
                side_effect=[
                    httpx.Response(200, json={"code": 0, "data": {"code": 86101}}),
                    httpx.Response(200, json={"code": 0, "data": {"code": 86090}}),
                    _success_poll_response(),
                ]
            )
            respx.get(URL_NAV).mock(
                return_value=httpx.Response(
                    200,
                    json={"code": 0, "data": {"isLogin": True, "mid": 12345, "uname": "扫码用户"}},
                )
            )

            creds = await auth.qr_login()

        assert creds.sessdata == "sessdata_value"
        assert creds.bili_jct == "bili_jct_value"
        assert creds.dedeuserid == "12345"
        assert creds.refresh_token == "refresh_token_value"
        assert creds.mid == 12345
        assert creds.uname == "扫码用户"
        assert path.exists()

    @pytest.mark.asyncio
    async def test_expired_regenerates(self, tmp_path, monkeypatch):
        """86038 失效后应重新生成二维码（generate 被调用两次）。"""
        monkeypatch.setattr(auth, "_render_qr", lambda url: None)
        monkeypatch.setattr(auth.asyncio, "sleep", _noop_sleep)
        path = tmp_path / "auth.json"
        monkeypatch.setattr(auth, "creds_path", lambda: path)

        generate_calls = []

        def _generate_handler(request: httpx.Request) -> httpx.Response:
            generate_calls.append(1)
            return httpx.Response(
                200,
                json={"code": 0, "data": {"url": f"https://bilibili.com/qr{len(generate_calls)}", "qrcode_key": f"key{len(generate_calls)}"}},
            )

        with respx.mock:
            respx.get(URL_GENERATE).mock(side_effect=_generate_handler)
            respx.get(url__startswith=URL_POLL).mock(
                side_effect=[
                    httpx.Response(200, json={"code": 0, "data": {"code": 86038}}),
                    httpx.Response(200, json={"code": 0, "data": {"code": 86101}}),
                    _success_poll_response(),
                ]
            )
            respx.get(URL_NAV).mock(
                return_value=httpx.Response(200, json={"code": 0, "data": {"isLogin": True}})
            )
            creds = await auth.qr_login()

        assert len(generate_calls) == 2
        assert creds.sessdata == "sessdata_value"
