# AGENTS.md

BiliBili_VideoRead_MCP — Bilibili 视频字幕/弹幕/评论提取 MCP Server（Python ≥ 3.10，src layout，纯 B 站 API 直连）。

## 运行与调试

- 入口：
  - MCP server：`python -m videoread_mcp`（→ `server.main()`，`__main__.py` 无子命令参数时走 server）
  - CLI 登录：`python -m videoread_mcp login|status|logout`（→ `cli.main()`）
- 安装：`pip install -e .`；本机 venv 在 `.venv\Scripts\python.exe`
- 测试：`python -m pytest`（纯单元、无网络，respx mock httpx；`tests/fixtures/seg1.bin` 是 2026-08-08 实测的真实弹幕字节）
- 集成冒烟：`pytest -m integration`（默认跳过，需要真实网络+登录态）

## 登录 / 凭证（最重要）

**扫码登录**：`videoread login` → `auth.py` 的 `qr_login()`：
1. `GET passport.bilibili.com/x/passport-login/web/qrcode/generate` 拿 `qrcode_key`（180s 有效）
2. segno 终端渲染二维码（渲染失败降级打印 URL）
3. 每 2s 轮询 `GET /x/passport-login/web/qrcode/poll`，按 **data.code** 判断：`86101`未扫 / `86090`已扫待确认 / `86038`失效重生成 / `0`成功
4. 成功：从 **Set-Cookie 头**（`resp.headers.get_list('set-cookie')`）解析 SESSDATA/bili_jct/DedeUserID/DedeUserID__ckMd5/sid，body 存 `refresh_token`
5. 调 `x/web-interface/nav` 校验登录态，写 `auth.json`

**凭证存储**：Windows `%APPDATA%\videoread\auth.json`，Unix `~/.config/videoread/auth.json`（chmod 600）。**不写回 .mcp.json**（避免误提交 git / 改配置需重启）。

**读取优先级**：env（`BILIBILI_COOKIE` 或 `BILIBILI_SESSDATA`+`BILIBILI_BILI_JCT`）> auth.json。统一走 `auth.effective_cookie_str()`，**各模块禁止直接 os.getenv**。

**过期处理**：SESSDATA 是 `{payload}%2C{过期时间戳}` 格式，`auth.sessdata_expiry()` 解析；接口返回 -101 / `need_login_subtitle` 时抛带指引的中文错误"请运行 `python -m videoread_mcp login` 重新扫码"。**不做自动续期**（无 refresh_token 刷新链路，保持依赖最简）。

## 提取流程

1. **元数据**：`GET x/web-interface/view?bvid=`（无需登录）→ title/owner/stat/pages/desc/pic/pubdate。多分 P 用 `pages[]`（page/cid/part/duration）
2. **字幕**：WBI 签名后 `GET x/player/wbi/v2?cid=&aid=&wts=&w_rid=`（需登录 Cookie）→ `data.subtitle.subtitles[]`，取 `subtitle_url`（`//` 开头补 `https:`）下载字幕 JSON，`body[]` 的 from/to/content
3. **弹幕**：`GET x/v2/dm/web/seg.so?type=1&oid={cid}&pid={aid}&segment_index={n}`（6 分钟/包，每包 ≤6000 条）。响应是 **protobuf 字节**，用 `danmaku.py` 的**零依赖手写 wire 解析**（`_parse_dm_seg`），无 protobuf 依赖。过滤 `pool=2`（代码/BAS 弹幕），超 `max_items` 用 `_sample()` 均匀采样
4. **评论**：`GET x/v2/reply?type=1&oid={aid}&sort={0|1}&ps=20&pn={n}`（需登录 Cookie）。`data.hots` 热评 + `data.replies` 列表，错误码 `-101` 登录失效 / `12002` 评论区关闭

## 协议纪律

- stdout 仅供 MCP JSON-RPC 通信，**任何 print 到 stdout 都会破坏协议**。日志一律 stderr（`server.main()` 用 `logging.basicConfig(stream=sys.stderr)`）
- server.py 只定义一份 `_run_server()`/`main()`（曾产生过双份定义）
- 日志严禁打印 Cookie 明文（SESSDATA 是 HttpOnly 最高权限凭证）

## 环境变量

- `BILIBILI_SESSDATA` / `BILIBILI_BILI_JCT` / `BILIBILI_COOKIE`：仅作旧配置兼容覆盖，优先级高于 auth.json
- 注意：opencode 的 MCP 配置字段是 `environment` 不是 `env`

## Windows 调试陷阱

- PowerShell 控制台默认 GBK，Python print 中文/emoji 会 UnicodeEncodeError。CLI 入口调用 `auth.ensure_console_utf8()` 重包 stdout/stderr
- 验证提取逻辑可绕过 MCP：登录后 `python -c "import asyncio; from videoread_mcp.extractor import extract_video; print(asyncio.run(extract_video('BV1GJ411x7h7')))"`

## WBI 签名

- `wbi.py` 的 `_MIXIN_KEY_ENC_TAB` 固定表，密钥从 nav 接口 `wbi_img` 动态获取（缓存 30s）。某天所有字幕突然失效，先检查 wbi 密钥表是否被 B 站变更
- 字幕语言优先级：zh-CN > zh > zh-Hans > ai-zh > zh-TW > ai-zh-TW > en > ja

## 法律风险

- B 站 2026 年先后函告关停 bilibili-API-collect（1月）与 bilibili-api（7月）；本方案**裸调官方 passport 接口**，仅限个人学习用途，勿分发/商业化
