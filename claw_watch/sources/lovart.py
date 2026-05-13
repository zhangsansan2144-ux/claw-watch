"""Lovart(www.lovart.ai)产品更新日志「最新动态」/ Changelog。

公开页面 `/zh/changelog`,免登录。数据不在 DOM 里,而是嵌在 Next.js App Router
的流式 chunk `self.__next_f.push([1, "<escaped json>"])` 里。把所有 chunk 拼起来
后,每个 changelog 条目都是一个独立 JSON 对象,字段长这样:

  {
    "updateTime": "2026-04-22T00:00:00+08:00",
    "pic": "https://...",
    "link": "/canvas?...",
    "mediaType": "" | "video",
    "needLogin": true,
    "i18n": {
      "zh": {"title": "...", "desc": "...", "btnText": "...", "tag": "更新"},
      "en": {"title": "...", "desc": "...", "btnText": "...", "tag": "Updates"}
    }
  }

直接 grep `"updateTime":"..."` 然后 bracket-match 抽对象,比依赖 DOM 渲染稳。
Lovart 站点对第三方加载等待较多(Google FedCM 等),所以用 `domcontentloaded`
而不是 `networkidle`,免得 30s 等不到。
"""

import json
import re
from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult
from .. import paths

URL = "https://www.lovart.ai/zh/changelog"

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[\d+,\s*"((?:[^"\\]|\\.)*)"\]\)')


def _decode_next_chunks(html: str) -> str:
    """把页面上所有 __next_f.push 流式 chunk 拼成一整个 decoded 字符串。"""
    parts = []
    for m in _PUSH_RE.finditer(html):
        try:
            parts.append(json.loads('"' + m.group(1) + '"'))
        except Exception:
            continue
    return "".join(parts)


def _bracket_match_object(s: str, key_pos: int) -> str | None:
    """从 key_pos 往左找最近的未配对 '{',然后 bracket-match 抽到 '}'。
    string 内的 { } 不参与计数。"""
    # 反向找开 {
    depth = 0
    start = None
    for i in range(key_pos, -1, -1):
        c = s[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                start = i
                break
            depth -= 1
    if start is None:
        return None
    # 正向 bracket-match
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if esc:
            esc = False
            continue
        if c == '\\':
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _extract_entries(html: str) -> list[dict]:
    big = _decode_next_chunks(html)
    seen = set()
    entries = []
    for m in re.finditer(r'"updateTime"\s*:\s*"', big):
        obj_str = _bracket_match_object(big, m.start())
        if obj_str is None or obj_str in seen:
            continue
        seen.add(obj_str)
        try:
            parsed = json.loads(obj_str)
        except Exception:
            continue
        if isinstance(parsed, dict) and "i18n" in parsed and "updateTime" in parsed:
            entries.append(parsed)
    return entries


def _fetch_html() -> tuple[str | None, str | None]:
    """加载页面拿 HTML。Lovart 抖动有点多,做 2 次重试。"""
    last_err = None
    for attempt in range(2):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    locale="zh-CN",
                    viewport={"width": 1440, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                # 等流式 chunk 全部到位:同时让客户端 JS 跑一会儿
                page.wait_for_timeout(3500)
                html = page.content()
                browser.close()
                return html, None
        except Exception as e:
            last_err = e
    return None, f"加载页面失败: {last_err}"


class LovartSource(BaseSource):
    name = "lovart"
    requires_login = False

    def fetch(self) -> FetchResult:
        html, err = _fetch_html()
        if err:
            return FetchResult(source=self.name, ok=False, error=err)

        entries = _extract_entries(html)
        if not entries:
            return FetchResult(
                source=self.name, ok=False,
                error="没在 __next_f 流里抽到 changelog 条目(页面结构可能变了)",
            )

        # 把原始 entries dump 出来供排查
        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

        items = []
        for e in entries:
            zh = (e.get("i18n") or {}).get("zh") or {}
            en = (e.get("i18n") or {}).get("en") or {}
            title = zh.get("title") or en.get("title") or "(无标题)"
            update_time = e.get("updateTime") or ""
            date = update_time[:10] if update_time else None
            # id 用 (date, title);两者已确认全局唯一,且语义稳定。
            # title 截断防止极长标题让 id 难看,但保留足够区分度。
            id_title = title[:60]
            items.append(Item(
                id=f"{date}:{id_title}",
                title=title,
                source=self.name,
                date=date,
                content=zh.get("desc") or en.get("desc"),
                url=URL,  # 单页 changelog 没有锚点,统一指首页
                extras={
                    "tag": zh.get("tag") or en.get("tag"),
                    "media_type": e.get("mediaType") or None,
                    "pic": e.get("pic") or None,
                    "need_login": e.get("needLogin"),
                    "title_en": en.get("title"),
                    "desc_en": en.get("desc"),
                    "btn_text": zh.get("btnText"),
                    "update_time": update_time,  # 完整带时区时间戳
                },
            ))
        return FetchResult(source=self.name, ok=True, items=items)
