# claw-watch

AI 视频/图片生成产品的更新监控 —— 一行命令检查可灵 / Vidu / 即梦 / 海螺 / LibLib / TapNow / Lovart / Runway / 拍我的最新动态,可推送到飞书。

需要登录的源(Vidu / 即梦 / LibLib)用你**自己的账号**抓你**自己**的通知,所以每人都得各装各的。

---

## 装一遍

> 前置:macOS、Python 3.11+(没装的话:`brew install python@3.12`)

**全程一行命令**:

```bash
git clone https://github.com/zhangsansan2144-ux/claw-watch.git && cd claw-watch && ./setup.sh
```

`setup.sh` 会:
1. 创建 venv,装依赖,装 Chromium(~150MB)
2. 问你 **要不要把 `claw-watch` 加到 PATH**(写到 `~/.zshrc`),回车 = 同意
3. 问你 **要不要立刻进登录向导**,回车 = 同意 → 自动 `exec claw-watch login`

---

## 登录向导 (4 步,每步可跳过)

`claw-watch login` 启动向导,依次问你:

1. **Vidu** —— 自动弹无头浏览器到登录页,你扫码/输密码,回终端按 Enter 保存。覆盖 Vidu 通知 + 首页 Banner 两个源。
2. **即梦** —— 自动弹**真 Chrome 窗口**(字节风控必需),登录后自动检测、保存、关闭。
3. **LibLib** —— 同上,弹真 Chrome,登录后自动检测。
4. **飞书 webhook** —— 提示你在飞书 App 里建机器人拿 URL,粘贴到终端 → 立刻发一张测试卡片到群里 → 保存到 `auth/feishu_webhook.txt`。

每一步开头会显示当前状态(已登录还剩 X 天 / 已配置 / 未配置),已经搞定的默认 [s]跳过,没搞定的默认 [l]登录。

想单独再做某一步:

```bash
claw-watch login vidu_notifications
claw-watch login jimeng
claw-watch login liblib
claw-watch login                     # 重新走完整向导(配过的会默认跳)
```

登录态会过期,跑 `claw-watch status` 看剩余天数:

| 源 | 凭证 | 大约有效期 |
|---|---|---|
| Vidu | JWT | ~2 周 |
| 即梦 | sessionid | ~1 年 |
| LibLib | usertoken | ~1 年 |
| 飞书 webhook | URL | 不过期(除非你在飞书里删机器人) |

---

## 定时跑 (1 步)

每周二 + 周五 北京时间 11:00 跑一次,加到 crontab:

```cron
0 11 * * 2,5 cd /path/to/claw-watch && .venv/bin/claw-watch check --push
```

> cron 时间字段:`分 时 日 月 星期`。`2,5` = 周二 + 周五(0=周日, 1=周一, ..., 6=周六)。
> 改成每天就把 `2,5` 换成 `*`;只想周一三五就 `1,3,5`。

(`--push` 需要先配飞书 webhook,见下面。)

⚠️ **即梦每次会短暂弹 Chrome 窗口**(字节风控必需)。如果不希望被打扰,定时任务里排除即梦:

```bash
.venv/bin/claw-watch check --source kling,pai,hailuo,vidu_notifications,vidu_spotlights,liblib,tapnow,lovart,runway --push
```

---

## 飞书推送

**最简单的配法**:跑 `claw-watch login`,走到第 4 步,粘 webhook URL 即可(向导会发测试卡片确认 + 保存到 `auth/feishu_webhook.txt`)。

**手动配 webhook**(不想走向导):

1. 飞书 App → 新建群聊(可以只有你自己)→ 群机器人 → 添加自定义机器人 → 复制 webhook URL
2. 任选一种方式存 URL:
   - **写文件**(推荐,cron 也能读):
     ```bash
     echo "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx" > auth/feishu_webhook.txt
     ```
   - **设环境变量**(只对当前 shell):
     ```bash
     export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx"
     ```
3. `claw-watch check --push` 就会推送一张富文本卡片
   - **每次都推一条**,即便所有源都平稳无新增 —— 反向证明监控真的跑过、各账号还没掉线。卡片 header 颜色:🟢 平稳 / 🔵 有新增 / 🟠 有警告 / 🔴 有失败
   - 卡片包含「各源今日状态」段落,逐一列出每个源是新增、平稳、警告还是失败;再下面才是新增详情、警告、失败的展开
   - `--webhook URL` 临时覆盖以上两种存储

> 查找顺序:`--webhook` flag > 环境变量 `FEISHU_WEBHOOK` > 文件 `auth/feishu_webhook.txt`

### 调样式 / 不真发

```bash
claw-watch check --push --dry-run
```

`--dry-run` 模式下只把卡片 JSON 打到 stdout,不真推。改 `notify.py` 里的样式时拿这个对着调,免得反复 spam 群。

---

## 监控源一览

| Source | 站点 | 数据类型 | 是否登录 |
|---|---|---|---|
| `kling` | klingai.com | 官方更新公告 | ❌ |
| `pai` | pai.video | 首页 Banner | ❌ |
| `hailuo` | hailuoai.com | 首页 Banner / 活动弹窗 | ❌ |
| `tapnow` | app.tapnow.ai | 首页 Banner / 广告卡 | ❌ |
| `lovart` | www.lovart.ai | Changelog 最新动态 | ❌ |
| `runway` | runwayml.com | Changelog 产品更新 | ❌ |
| `vidu_notifications` | vidu.cn | 通知中心 平台消息 | ✅ |
| `vidu_spotlights` | vidu.cn | 首页 Banner / Spotlights | ✅(共用 Vidu 登录) |
| `jimeng` | jimeng.jianying.com | 通知中心 官方消息 | ✅ |
| `liblib` | liblib.art | 通知中心 官方通知 | ✅ |

---

## 常用命令

```bash
claw-watch check                       # 检查全部
claw-watch check --source kling,pai    # 只查指定的
claw-watch check --output json         # JSON 输出(给 agent 用)
claw-watch check --push                # 检查 + 飞书推送(每次都推一张卡片)
claw-watch check --push --dry-run      # 不真发,只打印卡片 JSON 调样式用
claw-watch status                      # 看各源状态 + 登录态健康
claw-watch login                       # 登录向导
claw-watch login <source>              # 单独登录某个源
claw-watch sources                     # 列出所有源
```

---

## Claude Code 集成

skill 装在 `~/.claude/skills/claw-watch/SKILL.md`(本仓库不带,需要单独部署)。装上之后在 Claude Code 里直接问:

- "今天可灵有啥新功能?"
- "看一下 AI 产品监控状态"
- "Vidu 登录态过期了,帮我重新登录"

Claude Code 会自动调 `claw-watch` CLI 并把结果总结给你。

---

## 数据隐私 ⚠️

- `auth/vidu_auth.json` —— 含 JWT,可登录你的 Vidu 账号
- `auth/jimeng_chrome_profile/` —— 含 Cookie,可登录你的字节账号
- `auth/liblib_chrome_profile/` + `auth/liblib_auth.json` —— 含 usertoken,可登录你的 LibLib 账号

**`auth/` 已加到 `.gitignore`,千万别绕过、千万别分享。**

`data/*.json`(快照 + 原始接口响应)也不入仓 —— 每个用户本地各跑各的,数据不共享。

---

## 排错

| 现象 | 处理 |
|---|---|
| `setup.sh` 报 "没找到 Python 3.11+" | `brew install python@3.12` 后重跑 |
| `playwright install chromium` 失败 | 网络问题,重跑 `.venv/bin/playwright install chromium` |
| `claw-watch check` 某个源 `登录态已过期` | 跑 `claw-watch login <source>` 重新登录 |
| 即梦 fetch 报错 / 拿不到数据 | 字节风控变化,可能需要重新跑 `claw-watch login jimeng` |
| 想看某次抓到的原始数据 | 看 `data/<source>_raw.json` |

---

## 给开发者

想加新的监控源、了解架构、看项目布局,见 [CONTRIBUTING.md](CONTRIBUTING.md)。
