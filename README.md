# claw-watch

AI 视频/图片生成产品的更新监控 —— 一行命令检查可灵 / Vidu / 拍我 / 即梦的最新动态。

## 监控源

| Source | 站点 | 数据类型 | 是否登录 | 反爬难度 |
|---|---|---|---|---|
| `kling` | klingai.com | 官方更新公告 | ❌ | 无 |
| `pai` | pai.video (PixVerse) | 首页 Banner | ❌ | 无 |
| `hailuo` | hailuoai.com | 首页 Banner / 活动弹窗 | ❌ | 无 |
| `tapnow` | app.tapnow.ai | 首页 Banner 轮播 / 右下角广告卡 | ❌ | 无(TLS 握手偶发超时,内置重试) |
| `lovart` | www.lovart.ai | Changelog 「最新动态」 | ❌ | 无(Next.js 流式 chunk 抽 JSON,免登录公开页) |
| `runway` | runwayml.com | Changelog 产品更新 | ❌ | 无(Next.js,headless 直通,innerText 行解析) |
| `vidu_notifications` | vidu.cn | 通知中心「平台消息」 | ✅ | EdgeOne 指纹 |
| `vidu_spotlights` | vidu.cn | 首页 Banner / Spotlights | ✅ | (跟上面共用登录) |
| `jimeng` | jimeng.jianying.com | 通知中心「官方消息」 | ✅ | ByteDance 风控(需 CDP attach) |
| `liblib` | liblib.art | 通知中心「官方通知」 | ✅ | 阿里 WAF + token-based(需 CDP 登录) |

## 安装

需要 Python 3.11+ 和系统 Google Chrome(jimeng 监控用)。

```bash
cd /Users/edith/Desktop/aimon
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/playwright install chromium     # ~150MB
```

装完后 `claw-watch` 在 `.venv/bin/` 里。可以把它加到 PATH 或者用全路径。

## 用法

```bash
# 检查所有源,人类可读输出
claw-watch check

# 只检查指定源(逗号分隔)
claw-watch check --source kling,pai

# JSON 输出(给 agent / Claude Code 用)
claw-watch check --output json

# 检查 + 推送到飞书(有新增时才推)
claw-watch check --push

# 检查 + 每次必推
claw-watch check --push always

# 看各源状态 + 登录态健康
claw-watch status

# 重新登录 Vidu / 即梦(会弹浏览器)
claw-watch login vidu
claw-watch login jimeng

# 列出所有 source
claw-watch sources
```

## 首次配置

需要登录的源(`vidu` / `jimeng`)第一次要手动登录:

```bash
claw-watch login vidu      # 弹浏览器,扫码或账密登录,完成后回终端按 Enter
claw-watch login jimeng    # 同上
claw-watch login liblib    # 弹真 Chrome,登录后自动检测、保存、关闭,无需回终端
```

登录态会过期。`claw-watch status` 能看到剩余天数:
- Vidu JWT:约 2 周
- 即梦 sessionid:约 1 年
- LibLib usertoken:约 1 年(超长期 session)

过期后再跑一次 `claw-watch login <source>` 即可。

## 飞书推送

1. 飞书 App → 新建群聊(可以只有你自己)→ 群机器人 → 添加自定义机器人 → 复制 webhook URL
2. 设环境变量:
   ```bash
   export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx"
   ```
3. 跑 `claw-watch check --push` 就会推送

或者直接传 `--webhook URL`。

## 定时运行

macOS launchd / crontab 示例(每天早 9 点跑):

```cron
0 9 * * * cd /Users/edith/Desktop/aimon && .venv/bin/claw-watch check --push
```

⚠️ 注意:`jimeng` 监控**每次会短暂弹出 Chrome 窗口**(字节风控必需)。如果你不希望被打扰,可以排除即梦:
```bash
claw-watch check --source kling,pai,hailuo,vidu_notifications,vidu_spotlights --push
```

## Claude Code 集成

skill 已经装在 `~/.claude/skills/claw-watch/SKILL.md`。

在 Claude Code 里直接问:
- "今天可灵有啥新功能?"
- "看一下 AI 产品监控状态"
- "Vidu 登录态过期了,帮我重新登录"

Claude Code 会自动调用 `claw-watch` CLI 并把结果用自然语言总结给你。

## 项目结构

```
aimon/
├── pyproject.toml
├── claw_watch/
│   ├── cli.py              # 命令行入口
│   ├── paths.py            # data/ 和 auth/ 路径
│   ├── storage.py          # 快照 / diff
│   ├── notify.py           # 飞书 webhook 推送
│   └── sources/
│       ├── base.py         # BaseSource + Item + FetchResult
│       ├── kling.py
│       ├── pai.py
│       ├── hailuo.py
│       ├── vidu.py         # 一次 fetch 两个 source(notifications + spotlights)
│       ├── jimeng.py       # CDP attach 真实 Chrome
│       └── liblib.py       # 登录用真 Chrome(open -na),fetch 用 headless
├── data/                   # 快照 + 原始接口响应(可入 Git)
└── auth/                   # ⚠️ 登录凭证,不要入 Git
```

## 数据隐私

- `auth/vidu_auth.json` 含 JWT(账号凭证)
- `auth/jimeng_chrome_profile/` 含 Cookie 数据库(可登录你的字节账号)
- `auth/liblib_chrome_profile/` + `auth/liblib_auth.json` 含 usertoken(可登录你的 LibLib 账号)
- **千万别提交到公开仓库,千万别分享给任何人**

如果要给同事用,他们需要:
1. 复制本仓库代码(不带 `auth/` 和 `data/`)
2. 跑 `pip install -e .` + `playwright install chromium`
3. 自己跑 `claw-watch login vidu` / `claw-watch login jimeng` 登录他们自己的账号
4. 自己建飞书 webhook 并 `export FEISHU_WEBHOOK=...`

## 添加新的监控源

1. 在 `claw_watch/sources/` 加 `<name>.py`,继承 `BaseSource`
2. 实现 `fetch()` 返回 `FetchResult`(必需)
3. 如果需要登录:实现 `login_health()` 和 `perform_login()`,设 `requires_login = True`
4. 在 `sources/__init__.py` 的 `SOURCES` dict 里注册
