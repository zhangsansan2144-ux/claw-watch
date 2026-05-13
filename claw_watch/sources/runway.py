"""Runway(runwayml.com/changelog)产品更新日志。

公开页面,无 Cloudflare 拦截(headless Playwright 直接通过)。
数据是 Next.js App Router 的 React Server Components 序列化树,
不是平铺 JSON,所以不能像 Lovart 那样按 key 抽对象。改用 innerText 解析。

视觉/文本结构非常规整:从 "Latest updates" 标题之后开始,每条 4 行:
  Apr 7, 2026         ← 日期
  Paid Plans          ← 计划层级(也可能是 "API" / "Enterprise" 等)
  Seedance 2.0        ← 标题
  Use anything... 描述

遇到不符合日期格式(`MMM d, yyyy`)的行就视为列表结束(footer 的 "Product" 等)。
"""

import json
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult
from .. import paths

URL = "https://runwayml.com/changelog"
START_MARKER = "Latest updates"
DATE_RE = re.compile(r'^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}$')

# innerText 里的日期用 "Apr 7, 2026" 这种格式,strptime "%b %d, %Y"


def _next_nonempty(lines: list[str], i: int) -> tuple[int, str | None]:
    while i < len(lines) and not lines[i]:
        i += 1
    if i >= len(lines):
        return i, None
    return i, lines[i]


def _parse_entries(text: str) -> list[Item]:
    lines = [l.strip() for l in text.split("\n")]
    # 找 "Latest updates" 起点
    start = next((i + 1 for i, l in enumerate(lines) if l == START_MARKER), None)
    if start is None:
        return []

    items: list[Item] = []
    i = start
    while i < len(lines):
        i, date_line = _next_nonempty(lines, i)
        if date_line is None or not DATE_RE.match(date_line):
            break
        # 4 个非空行 = (date, plan, title, desc)
        i_plan = i + 1
        i_plan, plan_line = _next_nonempty(lines, i_plan)
        i_title = i_plan + 1
        i_title, title_line = _next_nonempty(lines, i_title)
        i_desc = i_title + 1
        i_desc, desc_line = _next_nonempty(lines, i_desc)
        if title_line is None:
            break

        try:
            date_iso = datetime.strptime(date_line, "%b %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            # 解析失败原样保留,不让一条坏数据卡死整条流水线
            date_iso = None

        items.append(Item(
            id=f"{date_iso or date_line}:{title_line[:60]}",
            title=title_line,
            source="runway",
            date=date_iso,
            content=desc_line,
            url=URL,
            extras={
                "plan_tier": plan_line,
                "date_raw": date_line,
            },
        ))
        i = i_desc + 1
    return items


def _fetch_text() -> tuple[str | None, str | None]:
    """Playwright headless 跑一次,返回 page.evaluate body innerText。
    Runway 偶尔会卡在第三方脚本,做 2 次重试。"""
    last_err = None
    for attempt in range(2):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    locale="en-US",
                    viewport={"width": 1440, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                txt = page.evaluate("() => document.body.innerText")
                browser.close()
                return txt, None
        except Exception as e:
            last_err = e
    return None, f"加载页面失败: {last_err}"


class RunwaySource(BaseSource):
    name = "runway"
    requires_login = False

    def fetch(self) -> FetchResult:
        txt, err = _fetch_text()
        if err:
            return FetchResult(source=self.name, ok=False, error=err)

        items = _parse_entries(txt)
        if not items:
            return FetchResult(
                source=self.name, ok=False,
                error=f"没解析到 changelog 条目(找不到 '{START_MARKER}' 或日期模式)",
            )

        # 把解析出的全量条目 dump 出来供排查
        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump([it.to_dict() for it in items], f, ensure_ascii=False, indent=2)

        return FetchResult(source=self.name, ok=True, items=items)
