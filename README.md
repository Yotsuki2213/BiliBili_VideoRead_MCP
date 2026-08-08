# 🎬 BiliBili_VideoRead_MCP

> ~~让 AI 也能看 B 站~~ 把 B 站视频**嚼碎了喂**给你的 AI：字幕、弹幕、评论、元数据一键萃取，输出结构化 Markdown 供 LLM 消化。

你的 AI 助手（Claude、ChatGPT、Cherry Studio…）不用再对 B 站链接干瞪眼了。丢个 BV 号进去，字幕、弹幕、评论、标题、UP 主、播放量自动到位，AI 读完就能给你总结、提炼、翻译、二次创作——**投币的事交给人类，看视频的事交给 AI** ⚡

> 🚫 **告别 F12 手抄 Cookie**：本项目用 B 站官方扫码登录，终端打码、手机一扫即自动登录；约 30 天过期后重扫一次，全程免维护、无需重启会话。

请给个 ⭐ Star 支持一下，作者会更有动力更新和维护！
---

## ✨ 功能介绍

| 功能 | 简介 |
|------|------|
| 🔗 链接识别 | BV / AV 号、完整链接、短链接 `b23.tv` 通吃 |
| 📋 元数据 | 标题、UP 主、时长、播放量、点赞/硬币/收藏、发布日期、简介、封面 |
| 📑 多分 P | 元数据含全部分 P 列表，可提取全部或指定分 P 字幕 |
| 💬 字幕 | 优先中文 AI 字幕，自动回退语言；按语义分段输出 |
| 🎯 弹幕 | **完整弹幕**（分段接口，非实时池），按时间排序，超限自动均匀采样 |
| 💭 评论 | 按热度 / 时间排序，可选附带子回复 |
| 📄 Markdown | 全部结构化输出，AI 一眼看完直接开聊 |

---

## 🚀 快速开始

### 1. 安装

```bash
pip install -e .
# 或者用 uv：
uv pip install -e .
```

### 2. 扫码登录（一次性，10 秒搞定）

```bash
python -m videoread_mcp login
```

终端会打印二维码，**手机打开 B 站 App → 右上角扫一扫**，几秒后自动保存登录态：

```
✅ 登录成功：你的昵称（mid=123456）
凭证已保存到 C:\Users\<你>\AppData\Roaming\videoread\auth.json
```

> - 凭证存在**你本机的用户目录**（Windows: `%APPDATA%\videoread\auth.json`，Unix: `~/.config/videoread/auth.json`），不会写进项目或 `.mcp.json`
> - SESSDATA 约 30 天过期，过期后重新跑一次 `login` 扫码即可
> - 常用命令：`python -m videoread_mcp status` 查登录态与剩余天数，`logout` 登出

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

> 💡 本机建议用绝对路径指向项目 venv：`C:\...\BiliBili_VideoRead_MCP\.venv\Scripts\python.exe`

### 4. 开用

配置完成 → 重启客户端 → 对话里直接丢链接：

> 帮我总结下这个视频讲了啥：[https://www.bilibili.com/video/BV1GJ411x7h7]
> 顺便看看评论区都在说啥

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
BiliBili_VideoRead_MCP/
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

**零 yt-dlp、零 protobuf、零 cryptography** — 弹幕用零依赖手写 protobuf wire 解析，登录走 B 站官方 passport 接口，不依赖任何已关停的第三方库。

---

## 🛡️ 免责声明（叠甲区，认真看）

> 本项目作者深知"工具无罪、乱用有责"，以下免责声明**有多层就叠几层**，请逐条阅读：

1. **非官方出品**：本项目与哔哩哔哩（B 站）官方**没有任何关系**，非官方发布，B 站不背书、不负责。所有商标、名称归其各自所有者所有。
2. **仅限个人学习交流**：本项目仅供学习 HTTP / MCP / 数据处理等技术的**个人学习用途**。**禁止**任何形式的商业用途、牟利行为、大规模批量爬取、攻击或滥用 B 站服务。
3. **法律风险自负**：B 站接口及服务条款可能随时变更，且 B 站已对同类逆向项目（如 bilibili-api）采取过法律行动。本项目基于公开接口实现，**不保证长期可用**，因使用本项目导致的任何纠纷、封号、法律责任均由使用者自行承担。
4. **账号安全**：`SESSDATA` 是 B 站账号的**最高权限凭证**，本项目仅将其保存在你本机用户目录。**严禁**公开分享扫码二维码截图、auth.json 或 Cookie 内容，泄露等于把账号交给别人。
5. **内容版权**：提取的字幕、弹幕、评论等内容的版权归原作者与 B 站所有，仅限个人阅读学习，**请勿**转载、二次分发、商用。
6. **稳定性与可用性**：本项目按"现状"提供，不提供任何明示或默示的保证。B 站改版、风控、网络环境等因素都可能使其失效；接口失效时按 README 指引重新扫码或自行修复，**作者不承诺修复时间**。
7. **不构成建议**：本项目产出的任何内容均不构成投资、理财、法律或其他专业建议；引用他人内容不代表赞同其观点。
8. **风险自担条款**：使用即视为同意以上全部条款。如果你所在地区或你的使用场景不允许此类工具，请**立即停止使用并删除本项目**。

**看视频一时爽，一直看一直爽 🫡**

---

## 📄 License

MIT
