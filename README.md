# 🎬 BiliBili_VideoRead_MCP — B 站视频字幕 / 弹幕 / 评论 MCP

> 把 B 站视频喂给你的 AI：**扫码登录一次**，自动提取字幕、弹幕、评论和元数据，整理成结构化 Markdown 供 LLM 消化。
>
> GitHub: [Yotsuki2213/BiliBili_VideoRead_MCP](https://github.com/Yotsuki2213/BiliBili_VideoRead_MCP)

你的 AI 助手（Claude、ChatGPT、Cherry Studio…）不用再对 B 站链接干瞪眼。丢个 BV 号进去，自动拉取字幕、弹幕、评论、标题、UP 主、播放量——AI 读完就能给你总结、提炼、翻译、二次创作。**看视频的事交给 AI** ⚡

> **告别手动复制 Cookie**：B 站接口需要登录态，本项目用官方扫码登录，终端打印二维码，手机 App 扫一下即自动完成，无需 F12 复制，过期重新扫一次即可。

---

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 🔗 链接识别 | BV / AV 号、完整链接、短链接 `b23.tv` 通吃 |
| 📋 元数据 | 标题、UP 主、时长、播放量、点赞/硬币/收藏、发布日期、简介、封面 |
| 📑 多分 P | 元数据含全部分 P 列表，可提取全部或指定分 P 字幕 |
| 💬 字幕 | 优先中文 AI 字幕，自动回退语言；输出分段段落 |
| 🎯 弹幕 | 完整弹幕（分段接口，非实时池），按时间排序，超限自动均匀采样 |
| 💭 评论 | 按热度 / 时间排序，可选附带子回复 |
| 📄 Markdown | 全部结构化输出，AI 一眼看完直接开聊 |

---

## 🚀 快速开始

### 1. 安装

```bash
# 进入项目目录，用项目 venv 或你习惯的 Python 3.10+ 环境
pip install -e .
```

### 2. 扫码登录（一次性）

```bash
python -m videoread_mcp login
```

终端会打印二维码，**手机打开 B 站 App → 扫一扫**，几秒后自动保存登录态：

```
✅ 登录成功：你的昵称（mid=123456）
凭证已保存到 C:\Users\<你>\AppData\Roaming\videoread\auth.json
```

> - 凭证保存在用户级目录（Windows: `%APPDATA%\videoread\auth.json`，Unix: `~/.config/videoread/auth.json`），**不会**写进项目或 .mcp.json
> - SESSDATA 约 30 天过期，过期后重新跑一次 `login` 扫码即可
> - 常用命令：`videoread status` 查登录态与剩余天数，`videoread logout` 登出

### 3. 接入 MCP 客户端

以 Claude / Cherry Studio 为例，**无需任何环境变量**：

```json
{
  "mcpServers": {
    "videoread": {
      "command": "python",
      "args": ["-m", "videoread_mcp"]
    }
  }
}
```

> 本机用绝对路径指向项目 venv：`C:\...\VideoRead\.venv\Scripts\python.exe`

### 4. 开用

配置完成 → 重启客户端 → 对话里直接丢链接：

> 帮我总结下这个视频讲了啥：https://www.bilibili.com/video/BV1GJ411x7h7
> 顺便看看评论区都在说什么

AI 自动调 `extract_bilibili_video` / `extract_bilibili_comments`，秒出内容。

---

## 🛠️ MCP 工具

### `extract_bilibili_video`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `url` | string | ✅ | — | B 站视频链接（BV/AV/短链均可） |
| `include_timestamps` | boolean | ❌ | `false` | 字幕是否带 `[00:01]` 时间戳 |
| `page` | integer | ❌ | 全部 | 指定分 P（1 起）；不传提取前 10 个分 P 字幕 |

**返回**：视频信息表 + 分 P 列表 + 简介 + 字幕全文。

### `extract_bilibili_danmaku`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `url` | string | ✅ | — | B 站视频链接 |
| `max_items` | integer | ❌ | `2000` | 最多返回弹幕数，超限均匀采样 |
| `page` | integer | ❌ | 第 1 个分 P | 指定分 P |

**返回**：`[MM:SS] 内容` 弹幕列表（完整弹幕，按时间序）。

### `extract_bilibili_comments`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `url` | string | ✅ | — | B 站视频链接 |
| `sort` | string | ❌ | `hot` | `hot` 热度 / `time` 时间 |
| `max_comments` | integer | ❌ | `50` | 最多根评论数 |
| `include_replies` | boolean | ❌ | `false` | 是否附带子回复 |

**返回**：`昵称（Lv.X）｜点赞 · 时间 · 回复数｜内容` 评论列表。需要登录态。

---

## 🏗️ 项目结构

```
VideoRead/
├── pyproject.toml
├── src/videoread_mcp/
│   ├── __main__.py    # python -m videoread_mcp [login|status|logout|server]
│   ├── server.py      # MCP 工具注册与调度
│   ├── cli.py         # login/status/logout 子命令
│   ├── auth.py        # 扫码登录 + 凭证存取（env 覆盖优先）
│   ├── extractor.py   # 元数据 + 字幕（view → wbi/v2 → subtitle）
│   ├── danmaku.py     # 弹幕（seg.so 分段 + 零依赖 protobuf 解析）
│   ├── comments.py    # 评论（x/v2/reply）
│   ├── wbi.py         # WBI 签名
│   └── formatter.py   # Markdown 格式化
└── tests/             # 纯单元测试，无网络
```

## 🔧 技术栈

| 依赖 | 作用 |
|------|------|
| [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) | MCP 协议 stdio 通信 |
| [httpx](https://www.python-httpx.org/) | B 站 API 直连（登录 / 元数据 / 字幕 / 弹幕 / 评论） |
| [segno](https://pypi.org/project/segno/) | 终端二维码渲染 |
| Python ≥ 3.10 | 🐍 |

**零 yt-dlp、零 protobuf、零 cryptography** — 弹幕用零依赖手写 protobuf wire 解析，登录走 B 站官方 passport 接口，不依赖任何已关停的第三方库（bilibili-api / bilibili-API-collect）。

---

## 📌 注意事项

- **登录过期**：SESSDATA 约 30 天有效。过期后字幕/评论会提示重新登录，跑一次 `python -m videoread_mcp login` 扫码即可，无需重启 Claude 会话
- **凭证安全**：`SESSDATA` 是最高权限凭证，仅保存在你本机用户目录，严禁提交到 git
- 本工具**不下载视频**，纯文本提取，仅供学习交流，请遵守 B 站相关协议 🫡

---

## 📄 License

MIT
