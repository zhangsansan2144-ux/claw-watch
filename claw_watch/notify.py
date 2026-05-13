"""推送通知到飞书 webhook(或其它兼容渠道)。

最小实现:发文本消息(纯 text)。后续可以扩展富文本卡片(interactive card)。
"""

import json
import os
import urllib.request
from typing import Optional


def feishu_text(webhook_url: str, text: str) -> tuple[bool, Optional[str]]:
    """给飞书自定义机器人 webhook 发一条纯文本。返回 (success, error_msg)。"""
    payload = {"msg_type": "text", "content": {"text": text}}
    data = json.dumps(payload).encode("utf-8")
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


def format_summary(overall: dict) -> str:
    """把 claw-watch check 的 JSON 结果格式化成飞书消息文本。"""
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

    # 总览一行
    sources = overall.get("sources") or {}
    if sources:
        bits = []
        for name, info in sources.items():
            tag = "✅" if info.get("ok") else "❌"
            bits.append(f"{tag}{name}({info.get('total', 0)})")
        lines.append("")
        lines.append("各源状态: " + " ".join(bits))

    return "\n".join(lines)


def get_webhook_url() -> Optional[str]:
    """从环境变量读 webhook URL。也可以扩展成读配置文件。"""
    return os.environ.get("FEISHU_WEBHOOK") or os.environ.get("CLAW_WATCH_WEBHOOK")
