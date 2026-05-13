# 贡献指南

claw-watch 是一个 macOS-only 的小工具,设计目标是 5–10 个朋友各自本地装着用。

## 项目结构

```
claw-watch/
├── pyproject.toml
├── setup.sh                # 一键安装(macOS)
├── claw_watch/
│   ├── cli.py              # 命令行入口
│   ├── paths.py            # data/ 和 auth/ 路径
│   ├── storage.py          # 快照 / diff
│   ├── notify.py           # 飞书 webhook 推送
│   └── sources/
│       ├── base.py         # BaseSource + Item + FetchResult + LoginHealth
│       ├── kling.py        # 免登录,拦截前端 XHR
│       ├── pai.py          # 免登录,DOM 解析
│       ├── hailuo.py
│       ├── tapnow.py
│       ├── lovart.py       # Next.js 流式 chunk 抽 JSON
│       ├── runway.py       # Next.js + innerText 行解析
│       ├── vidu.py         # 首页 spotlights / banner(免登录)
│       ├── jimeng.py       # CDP attach 真实 Chrome(字节风控)
│       └── liblib.py       # 登录用真 Chrome(open -na),fetch 用 headless
├── data/                   # 运行时生成,*.json 不入库
└── auth/                   # ⚠️ 登录凭证,不入库
```

## 核心数据流

每次 `claw-watch check`:

1. 对每个 source 调 `fetch()` → 返回 `FetchResult { items: list[Item] }`
2. `storage.diff_new_items()` 按 `Item.id` 跟历史快照对比,只算新增
3. `storage.save_snapshot()` 覆盖快照
4. `cli._print_text` / `notify.format_summary` 输出
5. 退出码 = 是否有 source 失败

`Item` 是统一格式 ([base.py](claw_watch/sources/base.py)):

```python
@dataclass
class Item:
    id: str            # 用于 diff,必填
    title: str
    source: str        # 'kling' / 'vidu_spotlights' / ...
    date: str | None = None       # ISO YYYY-MM-DD
    content: str | None = None
    url: str | None = None
    extras: dict = field(default_factory=dict)
```

## 加一个新的监控源

1. 在 `claw_watch/sources/` 加 `<name>.py`,继承 `BaseSource`
2. 实现 `fetch() -> FetchResult`(必需)
3. 如果需要登录:实现 `login_health()` 和 `perform_login()`,设 `requires_login = True`
4. 在 [sources/__init__.py](claw_watch/sources/__init__.py) 的 `SOURCES` dict 里注册
5. 如果是需要登录的源,把它加到 [cli.py](claw_watch/cli.py) 的 `_WIZARD_LOGINS` 里

最简单的参考:[kling.py](claw_watch/sources/kling.py) —— headless 浏览器 + XHR 拦截。

需要登录的参考顺序(由易到难):
- [liblib.py](claw_watch/sources/liblib.py) —— 真 Chrome 登录 + headless fetch
- [jimeng.py](claw_watch/sources/jimeng.py) —— CDP attach 真 Chrome(最复杂)

## 反爬笔记

- **Vidu (spotlights)**: EdgeOne 指纹,headless 必须带 `--disable-blink-features=AutomationControlled` + UA + stealth init script(免登录,但反爬还是要绕)
- **即梦**: ByteDance 风控,**必须** CDP attach 真 Chrome(`/Applications/Google Chrome.app`)
- **LibLib**: 阿里 WAF + token-based,登录用真 Chrome,fetch 走带 token 的 headless
- **TapNow**: TLS 握手偶发超时,代码里有重试

## 测试

目前没有自动化测试。验证方式:

```bash
.venv/bin/claw-watch check --source <name> --output json
```

看 `data/<name>_raw.json` 确认拿到了原始接口数据,看 stdout 的 `items` 数组确认提取逻辑对。

## 发布

不发 PyPI。朋友通过 `git clone` + `./setup.sh` 安装。改完代码 push 到 main,他们 `git pull` + `./setup.sh` 重装即可(setup.sh 是幂等的)。
