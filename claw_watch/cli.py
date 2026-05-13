"""claw-watch 命令行入口。

用法:
  claw-watch check                       检查所有 source
  claw-watch check --source kling,pai    只查指定的
  claw-watch check --output json         JSON 输出(给 agent 用)
  claw-watch check --output text         人类可读(默认)
  claw-watch status                      显示每个 source 的状态 + 登录健康
  claw-watch login vidu                  跑一次手动登录流程
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
    if args.push:
        webhook = args.webhook or notify.get_webhook_url()
        if not webhook:
            print("[警告] --push 但没找到 webhook URL,设 FEISHU_WEBHOOK 环境变量或用 --webhook", file=sys.stderr)
        else:
            # 只在有新增 / 警告 / 错误时推(避免每天推空消息),除非 --push always
            should_push = (
                args.push == "always"
                or overall["new_items"]
                or overall["warnings"]
                or overall["errors"]
            )
            if should_push:
                text = notify.format_summary(overall)
                ok, err = notify.feishu_text(webhook, text)
                if ok:
                    print("[推送] 已发送到飞书")
                else:
                    print(f"[推送] 失败: {err}", file=sys.stderr)
            else:
                print("[推送] 无新增/警告,跳过(用 --push always 强制推)")

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


def cmd_login(args) -> int:
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
        help="跑完后推送到飞书 webhook。auto=只在有新增/警告时推,always=每次必推",
    )
    p_check.add_argument("--webhook", help="飞书 webhook URL(覆盖 FEISHU_WEBHOOK 环境变量)")
    p_check.set_defaults(func=cmd_check)

    p_status = sub.add_parser("status", help="显示各 source 状态 + 登录态健康")
    p_status.set_defaults(func=cmd_status)

    p_login = sub.add_parser("login", help="重新登录某个 source")
    p_login.add_argument("source", help="source 名(vidu / jimeng)")
    p_login.set_defaults(func=cmd_login)

    p_sources = sub.add_parser("sources", help="列出所有 source")
    p_sources.set_defaults(func=cmd_sources)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
