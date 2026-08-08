"""VideoRead CLI — 扫码登录 / 状态检查 / 登出。

用法：
    python -m videoread_mcp login     # 终端扫码登录
    python -m videoread_mcp status    # 检查登录态与剩余天数
    python -m videoread_mcp logout    # 删除本地凭证
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from videoread_mcp import auth


def _print(*args) -> None:
    print(*args)


def cmd_login(_args: argparse.Namespace) -> int:
    auth.ensure_console_utf8()
    try:
        creds = asyncio.run(auth.qr_login())
    except auth.AuthError as exc:
        print(f"❌ 登录失败: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已取消登录。")
        return 1
    print()
    print(f"✅ 登录成功：{creds.uname or creds.mid or '已登录'}（mid={creds.mid}）")
    print(f"凭证已保存到 {auth.creds_path()}")
    exp = auth.creds_expiry(creds)
    if exp:
        days = int((exp - time.time()) / 86400)
        print(f"SESSDATA 有效期约 {max(days, 0)} 天，过期后重新运行 `videoread login` 扫码即可。")
    print("重启后 MCP 工具即可使用字幕 / 弹幕 / 评论功能。")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    auth.ensure_console_utf8()
    creds = auth.get_credentials()
    if not creds:
        print("❌ 未找到登录凭证。请先运行 `python -m videoread_mcp login` 扫码登录。")
        return 1

    # 来源提示
    source = "环境变量" if auth.credentials_from_env() else f"文件 {auth.creds_path()}"
    exp = auth.creds_expiry(creds)
    if exp:
        days = int((exp - time.time()) / 86400)
        print(f"本地过期时间: {time.strftime('%Y-%m-%d', time.localtime(exp))}（约剩 {max(days, 0)} 天）")
        if days < 0:
            print("⚠️ 本地解析显示已过期，尝试线上校验…")

    cookie = auth.effective_cookie_str()
    if not cookie:
        print("❌ 无法构造 Cookie 串。")
        return 1
    try:
        ok, data = auth.check_login(cookie)
    except Exception as exc:
        print(f"❌ 网络请求失败: {exc}")
        return 1
    if ok:
        print(f"✅ 登录有效（来源: {source}）：mid={data.get('mid')}，昵称={data.get('uname')}")
        return 0
    print("❌ 登录已失效（Cookie 未被 B 站识别）。请运行 `python -m videoread_mcp login` 重新扫码。")
    return 1


def cmd_logout(_args: argparse.Namespace) -> int:
    auth.ensure_console_utf8()
    path = auth.creds_path()
    if auth.delete_credentials():
        print(f"✅ 已删除凭证文件 {path}")
    else:
        print(f"未找到凭证文件 {path}，无需登出。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="videoread", description="VideoRead B 站工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="终端扫码登录，自动保存凭证")
    sub.add_parser("status", help="检查登录态与剩余有效期")
    sub.add_parser("logout", help="删除本地登录凭证")
    args = parser.parse_args(argv)

    if args.command == "login":
        return cmd_login(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "logout":
        return cmd_logout(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    sys.exit(main())
