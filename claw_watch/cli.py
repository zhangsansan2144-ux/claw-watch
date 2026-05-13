"""claw-watch 命令行入口。

用法:
  claw-watch check                       检查所有 source
  claw-watch check --source kling,pai    只查指定的
  claw-watch check --output json         JSON 输出(给 agent 用)
  claw-watch check --output text         人类可读(默认)
  claw-watch status                      显示每个 source 的状态 + 登录健康
  claw-watch login                       登录向导(依次跑 vidu/jimeng/liblib,可跳过)
  claw-watch login vidu_notifications    只登录指定 source
  claw-watch sources                     列出所有可用 source
"""

import argparse
import json
import sys
from datetime import datetime

from .sources import SOURCES, get_source
from . import storage, notify


def _parse_sources(arg: str | None) -> list[str]:
    if not arg:
        return list(SOURCES)
    out = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [s for s in out if s not in SOURCES]
    if unknown:
        print(f"未知 source: {unknown},可选: {list(SOURCES)}", file=sys.stderr)
        sys.exit(2)
    return out


def cmd_check(args) -> int:
    selected = _parse_sources(args.source)
    overall = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "sources": {},
        "new_items": [],
        "warnings": [],
        "errors": [],
    }

    for name in selected:
        src = get_source(name)
        result = src.fetch()

        if not result.ok:
            overall["errors"].append({"source": name, "error": result.error})

        new_items = []
        if result.ok and result.items:
            new_items = storage.diff_new_items(name, result.items)
            storage.save_snapshot(name, result.items)

        for it in new_items:
            overall["new_items"].append(it.to_dict())

        overall["sources"][name] = {
            **result.to_dict(),
            "new_count": len(new_items),
        }

        # 登录态过期警告(3 天内)
        if result.login and result.login.days_left is not None and 0 < result.login.days_left <= 3:
            overall["warnings"].append({
                "source": name,
                "type": "login_expiring",
                "days_left": result.login.days_left,
                "message": f"{name} 登录态 {result.login.days_left} 天后过期,记得跑 `claw-watch login {name}`",
            })
        elif result.login and result.login.days_left is not None and result.login.days_left <= 0:
            overall["warnings"].append({
                "source": name,
                "type": "login_expired",
                "message": f"{name} 登录态已过期,跑 `claw-watch login {name}` 重新登录",
            })

    if args.output == "json":
        print(json.dumps(overall, ensure_ascii=False, indent=2))
    else:
        _print_text(overall)

    # 推送到飞书(如果开启)
    # --push 设置就一定推一条卡片,即便全平稳 —— 卡片里的"各源今日状态"反向证明
    # 监控真的跑过、各账号也没掉线。--dry-run 时只打印 JSON 不真发,用来调样式。
    if args.push:
        card = notify.build_card(overall)
        if args.dry_run:
            print("\n[dry-run] 飞书卡片 payload:")
            print(json.dumps({"msg_type": "interactive", "card": card},
                             ensure_ascii=False, indent=2))
        else:
            webhook = args.webhook or notify.get_webhook_url()
            if not webhook:
                print("[警告] --push 但没找到 webhook URL,设 FEISHU_WEBHOOK 环境变量或用 --webhook",
                      file=sys.stderr)
            else:
                ok, err = notify.feishu_card(webhook, card)
                if ok:
                    print("[推送] 已发送到飞书")
                else:
                    print(f"[推送] 失败: {err}", file=sys.stderr)

    # 任何 source 失败就 exit code != 0
    return 1 if overall["errors"] else 0


def _print_text(overall: dict) -> None:
    print(f"\n=== claw-watch · {overall['timestamp']} ===\n")

    for name, info in overall["sources"].items():
        status = "✅" if info["ok"] else "❌"
        total = info.get("total", 0)
        new = info.get("new_count", 0)
        line = f"{status} {name:25s} {total:3d} 条"
        if new > 0:
            line += f" · 🆕 {new} 条新增"
        if info.get("error"):
            line += f" · 错误: {info['error']}"
        if info.get("login"):
            login = info["login"]
            if login.get("days_left") is not None:
                line += f" · 登录还有 {login['days_left']} 天"
        print(line)

    if overall["new_items"]:
        print(f"\n--- 🆕 新增条目 ({len(overall['new_items'])} 条) ---")
        for it in overall["new_items"]:
            date = it.get("date") or "?"
            print(f"  · [{it['source']}] [{date}] {it['title']}")
            if it.get("content"):
                content = it["content"]
                if len(content) > 100:
                    content = content[:100] + "…"
                print(f"      {content}")

    if overall["warnings"]:
        print(f"\n--- ⚠️  警告 ({len(overall['warnings'])} 条) ---")
        for w in overall["warnings"]:
            print(f"  · {w['message']}")

    if overall["errors"]:
        print(f"\n--- ❌ 失败 ({len(overall['errors'])} 条) ---")
        for e in overall["errors"]:
            print(f"  · [{e['source']}] {e['error']}")
    print()


def cmd_status(args) -> int:
    """显示每个 source 当前的快照大小 + 登录态健康。"""
    print(f"\n=== claw-watch status · {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
    print(f"{'Source':<25} {'登录':<8} {'快照':<8} {'登录态':<30}")
    print("-" * 75)
    for name, src in SOURCES.items():
        snap_count = len(storage.load_snapshot(name))
        if src.requires_login:
            health = src.login_health()
            if health is None:
                login_str, status_str = "-", "-"
            else:
                login_str = "✅" if health.ok else "❌"
                if health.days_left is not None:
                    status_str = f"{health.days_left} 天后过期" if health.ok else "已过期"
                else:
                    status_str = health.note or ""
        else:
            login_str, status_str = "免", "—"
        print(f"{name:<25} {login_str:<8} {snap_count:<8} {status_str}")
    print()
    return 0


# 登录向导:无参 `claw-watch login` 时依次走这三个。
# (vidu_notifications 和 vidu_spotlights 共用同一份登录,所以只列一次)
_WIZARD_LOGINS = [
    ("vidu_notifications", "Vidu",   "vidu.cn  ·  覆盖通知 + 首页 Banner 两个源"),
    ("jimeng",             "即梦",   "jimeng.jianying.com  ·  会弹出真 Chrome,登录后自动检测"),
    ("liblib",             "LibLib", "liblib.art  ·  会弹出真 Chrome,登录后自动检测"),
]


def _login_feishu() -> str:
    """配置飞书 webhook URL,返回 'done' / 'skip' / 'quit'。"""
    print()
    print("  ── 飞书推送  (粘贴 webhook URL,以后定时推送用)")

    existing = notify.get_webhook_url()
    if existing:
        src_label = "环境变量 FEISHU_WEBHOOK" if notify.webhook_source() == "env" else "auth/feishu_webhook.txt"
        masked = existing[:55] + "…" if len(existing) > 60 else existing
        print(f"     当前状态: 已配置 ({src_label})")
        print(f"               {masked}")
        default_hint, default = "[s]", "s"
    else:
        print("     当前状态: 未配置")
        default_hint, default = "[l]", "l"

    while True:
        ans = input(f"     [l]配置 / [s]跳过 / [q]退出向导  {default_hint}: ").strip().lower()
        if not ans:
            ans = default
        if ans in ("s", "skip", "n", "no"):
            print("     [跳过]")
            return "skip"
        if ans in ("q", "quit", "exit"):
            return "quit"
        if ans in ("l", "login", "y", "yes", "c", "config"):
            break
        print("     无效输入,请输 l / s / q")

    print()
    print("     去飞书 App 拿 webhook:")
    print("       1) 找一个群(没有就新建一个,只有你自己也行)")
    print("       2) 群设置 → 群机器人 → 添加机器人 → 自定义机器人")
    print("       3) 起个名(如 claw-watch)→ 添加 → 复制弹出的 URL")
    print()

    while True:
        url = input("     粘贴 webhook URL(留空取消): ").strip()
        if not url:
            print("     [跳过]")
            return "skip"
        if not url.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"):
            print("     [警告] URL 不像飞书 webhook(应以 https://open.feishu.cn/open-apis/bot/v2/hook/ 开头)")
            confirm = input("     仍然使用? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                continue

        print("     [测试] 正在发送一张测试卡片...")
        ok, err = notify.feishu_card(url, notify.build_test_card())
        if not ok:
            print(f"     [失败] {err}")
            retry = input("     重新粘贴? [Y/n]: ").strip().lower()
            if retry in ("n", "no"):
                return "skip"
            continue
        notify.save_webhook_url(url)
        print("     [OK] 测试卡片已发送,去群里看一眼,应该收到 ✅ 绿色卡片")
        print(f"     [保存] webhook 已写入 {notify._WEBHOOK_FILE}")
        return "done"


def _login_one(src_name: str, display: str, hint: str) -> str:
    """走一个 source 的登录,返回 'done' / 'skip' / 'quit'。"""
    src = get_source(src_name)
    health = src.login_health()

    print()
    print(f"  ── {display}  ({hint})")
    if health and health.ok and health.days_left is not None:
        status = f"已登录,{health.days_left} 天后过期"
        default_hint = "[s]"
        default = "s"
    elif health and health.ok:
        status = "已登录"
        default_hint = "[s]"
        default = "s"
    else:
        status = (health.note if health else "未登录") or "未登录"
        default_hint = "[l]"
        default = "l"
    print(f"     当前状态: {status}")

    while True:
        ans = input(f"     [l]登录 / [s]跳过 / [q]退出向导  {default_hint}: ").strip().lower()
        if not ans:
            ans = default
        if ans in ("l", "login", "y", "yes"):
            try:
                src.perform_login()
            except Exception as e:
                print(f"     [失败] {e}")
            return "done"
        if ans in ("s", "skip", "n", "no"):
            print("     [跳过]")
            return "skip"
        if ans in ("q", "quit", "exit"):
            return "quit"
        print("     无效输入,请输 l / s / q")


def cmd_login(args) -> int:
    # 单个 source 模式
    if args.source:
        name = args.source
        if name not in SOURCES:
            print(f"未知 source '{name}',可选: {list(SOURCES)}", file=sys.stderr)
            return 2
        src = get_source(name)
        if not src.requires_login:
            print(f"{name} 不需要登录,直接 check 即可")
            return 0
        src.perform_login()
        return 0

    # 向导模式
    print("\n=== claw-watch 登录向导 ===")
    print("将依次引导你登录 3 个需要账号的源 + 1 个飞书 webhook。每一步都可以跳过。")
    for src_name, display, hint in _WIZARD_LOGINS:
        if _login_one(src_name, display, hint) == "quit":
            print("\n向导已退出。后续可随时跑 `claw-watch login` 继续。")
            return 0
    if _login_feishu() == "quit":
        print("\n向导已退出。后续可随时跑 `claw-watch login` 继续。")
        return 0
    print("\n=== 向导完成 ===")
    print("跑 `claw-watch status` 看登录态,或 `claw-watch check --push` 试一次抓取 + 推送。")
    return 0


def cmd_sources(args) -> int:
    for name, src in SOURCES.items():
        flag = "需登录" if src.requires_login else "免登录"
        print(f"  {name:<25} [{flag}]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claw-watch",
        description="AI 产品监控 —— 一行命令检查可灵/Vidu/拍我/即梦的最新动态",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="跑监控并对比快照")
    p_check.add_argument("--source", help="只检查指定的 source(逗号分隔)")
    p_check.add_argument("--output", choices=["text", "json"], default="text")
    p_check.add_argument(
        "--push",
        nargs="?",
        const="auto",
        choices=["auto", "always"],
        help="跑完后推送一张飞书卡片(每次都推,平稳日子是绿色'各源平稳'卡)。"
             "always 只是兼容旧用法,行为与不带参一致",
    )
    p_check.add_argument("--webhook", help="飞书 webhook URL(覆盖 FEISHU_WEBHOOK 环境变量)")
    p_check.add_argument(
        "--dry-run",
        action="store_true",
        help="--push 时只打印卡片 JSON 不真发,用来调样式",
    )
    p_check.set_defaults(func=cmd_check)

    p_status = sub.add_parser("status", help="显示各 source 状态 + 登录态健康")
    p_status.set_defaults(func=cmd_status)

    p_login = sub.add_parser(
        "login",
        help="登录需要账号的源。无参数=向导(依次走 vidu/jimeng/liblib)",
    )
    p_login.add_argument(
        "source",
        nargs="?",
        help="只登录指定 source(vidu_notifications / jimeng / liblib)。省略则进入向导",
    )
    p_login.set_defaults(func=cmd_login)

    p_sources = sub.add_parser("sources", help="列出所有 source")
    p_sources.set_defaults(func=cmd_sources)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
