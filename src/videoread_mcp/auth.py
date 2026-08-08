"""B 站凭证管理 + 扫码登录。

- 凭证优先读环境变量（兼容旧 .mcp.json 配置），否则读本地 `auth.json`
- `qr_login()` 走 B 站官方 passport 扫码接口，终端打印二维码，手机 App 扫码即得 Cookie
- 不做自动续期：SESSDATA 过期后重跑 `videoread login` 重新扫码即可

凭证文件位置（Windows）：`%APPDATA%\\videoread\\auth.json`
凭证文件位置（Unix）：`~/.config/videoread/auth.json`
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 统一请求头（风控要求带 UA + Referer）
DEFAULT_HEADERS = {
    "Referer": "https://www.bilibili.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# 凭证文件字段
_FIELDS = (
    "sessdata",
    "bili_jct",
    "dedeuserid",
    "dedeuserid_ckmd5",
    "sid",
    "refresh_token",
    "mid",
    "uname",
    "updated_at",
)

# passport 扫码接口
URL_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
URL_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
URL_NAV = "https://api.bilibili.com/x/web-interface/nav"

# 轮询状态码（看 data.code，不是外层 code）
QR_NOT_SCANNED = 86101  # 未扫码，继续轮询
QR_SCANNED = 86090      # 已扫码未确认
QR_EXPIRED = 86038      # 二维码失效，需重新生成
QR_OK = 0               # 登录成功

# 轮询间隔 / 二维码有效期
POLL_INTERVAL = 2.0
QR_TIMEOUT = 175


class AuthError(Exception):
    """登录态缺失或失效。"""


@dataclass
class Credentials:
    """B 站登录凭证。字段与 auth.json 一一对应。"""

    sessdata: str = ""
    bili_jct: str = ""
    dedeuserid: str = ""
    dedeuserid_ckmd5: str = ""
    sid: str = ""
    refresh_token: str = ""
    mid: int = 0
    uname: str = ""
    updated_at: str = ""

    def cookie_str(self) -> str:
        parts = [f"SESSDATA={self.sessdata}"]
        if self.bili_jct:
            parts.append(f"bili_jct={self.bili_jct}")
        if self.dedeuserid:
            parts.append(f"DedeUserID={self.dedeuserid}")
        if self.dedeuserid_ckmd5:
            parts.append(f"DedeUserID__ckMd5={self.dedeuserid_ckmd5}")
        if self.sid:
            parts.append(f"sid={self.sid}")
        return "; ".join(parts)

    def is_valid(self) -> bool:
        return bool(self.sessdata and self.bili_jct)


def creds_path() -> Path:
    """凭证文件路径（Windows: %APPDATA%\\videoread\\auth.json）。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "videoread" / "auth.json"
    return Path.home() / ".config" / "videoread" / "auth.json"


# ---------------------------------------------------------------------------
# 加载 / 保存
# ---------------------------------------------------------------------------

def load_credentials(path: Path | None = None) -> Credentials | None:
    """从 auth.json 读取凭证，不存在或损坏返回 None。"""
    path = path or creds_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        creds = Credentials()
        for k in _FIELDS:
            if k in data:
                setattr(creds, k, data[k])
        if not creds.sessdata:
            return None
        return creds
    except (OSError, json.JSONDecodeError):
        return None


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    """写凭证文件；Unix 下 chmod 600。返回文件路径。"""
    path = path or creds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(creds, k) for k in _FIELDS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if os.name != "nt":
        path.chmod(0o600)
    return path


def delete_credentials(path: Path | None = None) -> bool:
    """删除凭证文件，返回是否存在被删除。"""
    path = path or creds_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# 环境变量覆盖（兼容旧 .mcp.json 的 BILIBILI_SESSDATA / BILIBILI_COOKIE）
# ---------------------------------------------------------------------------

def credentials_from_env() -> Credentials | None:
    """从环境变量构造凭证；未设置任何环境变量返回 None。"""
    cookie = os.getenv("BILIBILI_COOKIE", "").strip()
    sessdata = os.getenv("BILIBILI_SESSDATA", "").strip()
    bili_jct = os.getenv("BILIBILI_BILI_JCT", "").strip()
    if cookie:
        # 完整 Cookie 字符串：仅能当 cookie 串用，字段归零
        return Credentials(sessdata=cookie, bili_jct="__RAW_COOKIE__")
    if sessdata:
        return Credentials(sessdata=sessdata, bili_jct=bili_jct)
    return None


def get_credentials() -> Credentials | None:
    """获取有效凭证：环境变量优先，其次 auth.json。均无返回 None。"""
    env_creds = credentials_from_env()
    if env_creds:
        return env_creds
    return load_credentials()


def effective_cookie_str() -> str | None:
    """获取可直接放入 Cookie 头的字符串。"""
    creds = get_credentials()
    if not creds:
        return None
    if creds.bili_jct == "__RAW_COOKIE__":
        return creds.sessdata
    return creds.cookie_str()


# ---------------------------------------------------------------------------
# SESSDATA 过期解析
# ---------------------------------------------------------------------------

def sessdata_expiry(sessdata: str) -> float | None:
    """解析 SESSDATA 第二段（%2C 分隔）的过期 Unix 时间戳。解析失败返回 None。"""
    try:
        return float(sessdata.split("%2C")[1])
    except (IndexError, ValueError):
        return None


def creds_expiry(creds: Credentials) -> float | None:
    """凭证过期时间（Unix 秒）。raw cookie / 无法解析返回 None。"""
    if creds.bili_jct == "__RAW_COOKIE__":
        return None
    return sessdata_expiry(creds.sessdata)


# ---------------------------------------------------------------------------
# 登录态校验
# ---------------------------------------------------------------------------

def check_login(cookie_str: str, timeout: float = 15.0) -> tuple[bool, dict[str, Any]]:
    """调用 nav 接口校验登录态，返回 (是否登录, nav 的 data 字段)。"""
    headers = dict(DEFAULT_HEADERS)
    headers["Cookie"] = cookie_str
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(URL_NAV, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
    return bool(data.get("isLogin")), data


# ---------------------------------------------------------------------------
# 扫码登录
# ---------------------------------------------------------------------------

def _parse_set_cookie(cookie_strs: list[str]) -> dict[str, str]:
    """解析 Set-Cookie 头，取每个 cookie 的第一个 name=value。"""
    out: dict[str, str] = {}
    for raw in cookie_strs:
        first = raw.split(";", 1)[0].strip()
        if "=" in first:
            name, _, value = first.partition("=")
            out[name.strip()] = value.strip()
    return out


def _render_qr(url: str) -> None:
    """终端渲染二维码；失败或 segno 缺失时打印 URL 供手机扫码。"""
    print("请用 B 站手机 App「扫一扫」扫描下方二维码登录：")
    print()
    try:
        import segno

        qr = segno.make(url, error="m")
        # compact=True 用 Unicode 块元素渲染（非 ANSI），终端与纯文本输出均可扫描
        qr.terminal(compact=True, border=1)
    except Exception:
        pass  # 终端不支持，走 URL 兜底
    print()
    print("若二维码显示异常，手机 App 扫码或浏览器打开：")
    print(url)
    print()


async def qr_login(path: Path | None = None) -> Credentials:
    """执行扫码登录，成功返回 Credentials（并已写入 auth.json）。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        # 循环：二维码过期后自动重新生成
        while True:
            qrcode_key, qr_url = await _generate_qr(client)
            _render_qr(qr_url)
            print("等待扫码…（二维码 3 分钟内有效，按 Ctrl+C 取消）")
            start = time.time()
            while time.time() - start < QR_TIMEOUT:
                await asyncio.sleep(POLL_INTERVAL)
                status, body, set_cookies = await _poll_qr(client, qrcode_key)
                if status == QR_OK:
                    creds = _credentials_from_login(body, set_cookies)
                    ok, nav = check_login(creds.cookie_str())
                    if not ok:
                        raise AuthError("扫码成功但登录态校验失败，请重试")
                    creds.mid = nav.get("mid", 0)
                    creds.uname = nav.get("uname", "")
                    creds.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
                    save_credentials(creds, path)
                    return creds
                if status == QR_SCANNED:
                    print("✅ 已扫码，请在手机上确认登录…")
                elif status == QR_EXPIRED:
                    print("二维码已失效，正在重新生成…")
                    break
                # QR_NOT_SCANNED: 继续轮询
            else:
                # 循环正常结束（超时）→ 重新生成
                print("扫码超时，正在重新生成二维码…")
                continue
            continue


async def _generate_qr(client: httpx.AsyncClient) -> tuple[str, str]:
    """生成二维码，返回 (qrcode_key, url)。"""
    resp = await client.get(URL_QR_GENERATE, headers=DEFAULT_HEADERS)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    if not data.get("qrcode_key"):
        raise AuthError(f"生成二维码失败: {resp.json().get('message', '未知错误')}")
    return data["qrcode_key"], data.get("url", "")


async def _poll_qr(
    client: httpx.AsyncClient, qrcode_key: str
) -> tuple[int, dict[str, Any], list[str]]:
    """轮询扫码状态，返回 (data.code, 响应体, Set-Cookie 头列表)。"""
    resp = await client.get(
        URL_QR_POLL,
        params={"qrcode_key": qrcode_key, "source": "main-fe-header"},
        headers=DEFAULT_HEADERS,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") or {}
    set_cookies = resp.headers.get_list("set-cookie")
    return int(data.get("code", QR_NOT_SCANNED)), body, set_cookies


def _credentials_from_login(
    body: dict[str, Any], set_cookies: list[str]
) -> Credentials:
    """从 poll 成功响应构造凭证。Cookie 优先取 Set-Cookie 头，body 兜底。"""
    creds = Credentials()
    data = body.get("data") or {}

    # 1) Set-Cookie 头
    parsed = _parse_set_cookie(set_cookies)
    creds.sessdata = parsed.get("SESSDATA", "")
    creds.bili_jct = parsed.get("bili_jct", "")
    creds.dedeuserid = parsed.get("DedeUserID", "")
    creds.dedeuserid_ckmd5 = parsed.get("DedeUserID__ckMd5", "")
    creds.sid = parsed.get("sid", "")

    # 2) body 兜底（部分版本接口把 cookies 放 body）
    if not creds.sessdata:
        body_cookies = data.get("cookies") or {}
        creds.sessdata = body_cookies.get("SESSDATA", "")
        creds.bili_jct = body_cookies.get("bili_jct", "")
        creds.dedeuserid = body_cookies.get("DedeUserID", "")
        creds.dedeuserid_ckmd5 = body_cookies.get("DedeUserID__ckMd5", "")
        creds.sid = body_cookies.get("sid", "")

    creds.refresh_token = data.get("refresh_token", "")
    if not creds.sessdata:
        raise AuthError("扫码成功但未从响应中解析到 SESSDATA，请重试")
    return creds


def ensure_console_utf8() -> None:
    """Windows 控制台默认 GBK，中文/emoji 会 UnicodeEncodeError，重包为 utf-8。"""
    if os.name != "nt":
        return
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not stream.encoding:
            continue
        if stream.encoding.lower() not in ("utf-8", "utf8"):
            setattr(
                sys,
                stream_name,
                io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
            )
