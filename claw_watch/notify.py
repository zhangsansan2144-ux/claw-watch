"""推送通知到飞书 webhook。

提供两种 msg_type:
- text:  feishu_text + format_summary,纯文本,用于回退或终端预览
- card:  feishu_card + build_card,interactive 卡片,日常推送用

webhook URL 查找顺序(get_webhook_url):
  1. FEISHU_WEBHOOK / CLAW_WATCH_WEBHOOK 环境变量
  2. auth/feishu_webhook.txt(由 `claw-watch login` 向导写入)
"""

import json
import os
import urllib.request
from datetime import datetime
from typing import Optional

from . import paths


# ─── 文本消息(回退用) ────────────────────────────────────────────────────

def feishu_text(webhook_url: str, text: str) -> tuple[bool, Optional[str]]:
    """给飞书自定义机器人 webhook 发一条纯文本。返回 (success, error_msg)。"""
    return _post(webhook_url, {"msg_type": "text", "content": {"text": text}})


def format_summary(overall: dict) -> str:
    """把 claw-watch check 的 JSON 结果格式化成纯文本。"""
    ts = overall.get("timestamp", "?")[:16].replace("T", " ")
    lines = [f"📰 AI 产品监控 · {ts}", ""]

    new_items = overall.get("new_items") or []
    if new_items:
        lines.append(f"🆕 共 {len(new_items)} 条新增:")
        by_source: dict[str, list] = {}
        for it in new_items:
            by_source.setdefault(it["source"], []).append(it)
        for src, its in by_source.items():
            lines.append(f"\n【{src}】")
            for it in its:
                date = it.get("date") or "?"
                lines.append(f"  · [{date}] {it['title']}")
                if it.get("content"):
                    c = it["content"]
                    if len(c) > 80:
                        c = c[:80] + "…"
                    lines.append(f"      {c}")
    else:
        lines.append("✅ 今日无新增")

    warnings = overall.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("⚠️ 警告:")
        for w in warnings:
            lines.append(f"  · {w.get('message', '')}")

    errors = overall.get("errors") or []
    if errors:
        lines.append("")
        lines.append("❌ 失败:")
        for e in errors:
            lines.append(f"  · [{e['source']}] {e.get('error', '')}")

    sources = overall.get("sources") or {}
    if sources:
        bits = []
        for name, info in sources.items():
            tag = "✅" if info.get("ok") else "❌"
            bits.append(f"{tag}{name}({info.get('total', 0)})")
        lines.append("")
        lines.append("各源状态: " + " ".join(bits))

    return "\n".join(lines)


# ─── 卡片消息(日常推送) ──────────────────────────────────────────────────

def feishu_card(webhook_url: str, card: dict) -> tuple[bool, Optional[str]]:
    """给飞书 webhook 发一张 interactive 卡片。返回 (success, error_msg)。"""
    return _post(webhook_url, {"msg_type": "interactive", "card": card})


def build_card(overall: dict) -> dict:
    """根据 check 结果构造飞书 interactive 卡片。

    Header 颜色按严重度切:errors > warnings > new > clean。
    Body 按"各源状态 → 新增详情 → 警告 → 错误"顺序展开,空段落跳过。
    """
    new_items = overall.get("new_items") or []
    warnings = overall.get("warnings") or []
    errors = overall.get("errors") or []
    sources = overall.get("sources") or {}

    # ── header ──
    ts_short = overall.get("timestamp", "")[5:16].replace("T", " ")  # MM-DD HH:MM
    if errors:
        template, head_emoji = "red", "❌"
        head_label = f"{len(errors)} 个失败"
    elif warnings and not new_items:
        template, head_emoji = "orange", "⚠️"
        head_label = f"{len(warnings)} 个警告"
    elif new_items:
        template, head_emoji = "blue", "🆕"
        head_label = f"{len(new_items)} 条新增"
    else:
        template, head_emoji = "green", "✅"
        head_label = "各源平稳"
    title = f"{head_emoji} AI 产品监控 · {head_label} · {ts_short}"

    # ── body: 各源今日状态(始终显示) ──
    elements: list[dict] = []
    overview_lines = ["**各源今日状态**"]
    for name, info in sources.items():
        new_count = info.get("new_count", 0)
        login = info.get("login") or {}
        days_left = login.get("days_left")
        if not info.get("ok"):
            err_msg = (info.get("error") or "未知错误")[:60]
            overview_lines.append(f"❌ `{name}` · 失败: {err_msg}")
        elif new_count > 0:
            overview_lines.append(f"🆕 `{name}` · {new_count} 条新增")
        elif days_left is not None and days_left <= 3:
            overview_lines.append(
                f"⚠️ `{name}` · 登录态 {'已过期' if days_left <= 0 else f'{days_left} 天后过期'}"
            )
        else:
            overview_lines.append(f"✅ `{name}` · 平稳无新增")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(overview_lines)}})

    # ── body: 新增详情(分组) ──
    if new_items:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🆕 新增详情({len(new_items)} 条)**"}})
        by_source: dict[str, list] = {}
        for it in new_items:
            by_source.setdefault(it["source"], []).append(it)
        for src, its in by_source.items():
            lines = [f"**【{src}】**"]
            for it in its:
                date = it.get("date") or "?"
                title_text = _md_escape(it.get("title") or "(无标题)")
                url = it.get("url")
                line = f"· `[{date}]` {title_text}"
                if url:
                    line += f"   [查看 →]({url})"
                lines.append(line)
                if it.get("content"):
                    c = _md_escape(it["content"])
                    if len(c) > 100:
                        c = c[:100] + "…"
                    lines.append(f"  {c}")
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

    # ── body: 警告 ──
    if warnings:
        elements.append({"tag": "hr"})
        warn_lines = [f"**⚠️ 警告({len(warnings)} 条)**"]
        for w in warnings:
            warn_lines.append(f"· {_md_escape(w.get('message', ''))}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(warn_lines)}})

    # ── body: 错误 ──
    if errors:
        elements.append({"tag": "hr"})
        err_lines = [f"**❌ 失败({len(errors)} 条)**"]
        for e in errors:
            err_lines.append(f"· `{e['source']}` —— {_md_escape(e.get('error', ''))}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(err_lines)}})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def _md_escape(s: str) -> str:
    """防止 source 标题里的方括号/星号干扰 lark_md 渲染。"""
    return s.replace("[", "\\[").replace("]", "\\]").replace("*", "\\*")


# ─── 公共 ────────────────────────────────────────────────────────────────

_WEBHOOK_FILE = paths.AUTH_DIR / "feishu_webhook.txt"


def get_webhook_url() -> Optional[str]:
    """按优先级返回 webhook URL:环境变量 > auth/feishu_webhook.txt。"""
    env = os.environ.get("FEISHU_WEBHOOK") or os.environ.get("CLAW_WATCH_WEBHOOK")
    if env:
        return env.strip()
    if _WEBHOOK_FILE.exists():
        try:
            url = _WEBHOOK_FILE.read_text().strip()
            return url or None
        except Exception:
            return None
    return None


def save_webhook_url(url: str) -> None:
    """把 webhook URL 写到 auth/feishu_webhook.txt(0600 权限,只允许自己读)。"""
    _WEBHOOK_FILE.write_text(url.strip() + "\n")
    try:
        _WEBHOOK_FILE.chmod(0o600)
    except OSError:
        pass


def webhook_source() -> Optional[str]:
    """告诉调用者 webhook 是从哪儿来的。返回 'env' / 'file' / None。"""
    if os.environ.get("FEISHU_WEBHOOK") or os.environ.get("CLAW_WATCH_WEBHOOK"):
        return "env"
    if _WEBHOOK_FILE.exists() and _WEBHOOK_FILE.read_text().strip():
        return "file"
    return None


def build_test_card() -> dict:
    """配置 webhook 时立即发的测试卡片,确认 URL 粘对了。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {
                "tag": "plain_text",
                "content": f"✅ claw-watch 配置成功 · 测试卡片 · {ts}",
            },
        },
        "elements": [{
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "如果你看到这条卡片,说明飞书 webhook **配置成功**。\n\n"
                    "之后每次跑 `claw-watch check --push`(或 cron 自动跑)"
                    "都会推一张实际监控卡片到这个群。"
                ),
            },
        }],
    }


def _post(webhook_url: str, payload: dict) -> tuple[bool, Optional[str]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.load(r)
        if resp.get("code") == 0 or resp.get("StatusCode") == 0:
            return True, None
        return False, f"飞书返回: {resp}"
    except Exception as e:
        return False, str(e)
