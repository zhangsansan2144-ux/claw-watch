"""可灵(klingai.com)更新公告。

接口完全公开,但需要浏览器拦截 —— 接口签名只有 Vidu/Kling 自己前端 JS 知道。
"""

import json
from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult
from .. import paths

URL = "https://klingai.com/release-note/release-history"
API_KEYWORD = "releaseNotesDataConfirmed"


class KlingSource(BaseSource):
    name = "kling"
    requires_login = False

    def fetch(self) -> FetchResult:
        captured = {"data": None}

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                )
                page = context.new_page()

                def on_response(response):
                    if API_KEYWORD in response.url:
                        try:
                            captured["data"] = response.json()
                        except Exception:
                            pass

                page.on("response", on_response)
                page.goto(URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                browser.close()
        except Exception as e:
            return FetchResult(source=self.name, ok=False, error=f"fetch 异常: {e}")

        if captured["data"] is None:
            return FetchResult(source=self.name, ok=False, error="没拦到目标接口")

        # 保存 raw
        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(captured["data"], f, ensure_ascii=False, indent=2)

        items = self._extract(captured["data"])
        return FetchResult(source=self.name, ok=True, items=items)

    def _extract(self, raw: dict) -> list[Item]:
        # 可灵的数据在 data.zh 数组里
        zh_items = (raw.get("data") or {}).get("zh") or []
        out = []
        for it in zh_items:
            if not isinstance(it, dict):
                continue
            out.append(Item(
                id=str(it.get("id", "")),
                title=it.get("title") or "(无标题)",
                source=self.name,
                date=it.get("date"),
                content=it.get("content"),
                url=(it.get("operation") or {}).get("webUrl"),
                extras={
                    "major": it.get("major", False),
                    "feature": it.get("feature"),
                },
            ))
        return out
