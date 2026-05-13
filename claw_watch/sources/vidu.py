"""Vidu(vidu.cn)首页 Spotlights / Banner。

完全免登录:Spotlights 接口对未登录用户也开放。
EdgeOne 反爬,headless 下要带 stealth 装备避免被识破。

(早先版本还做过「平台消息通知中心」这一源,但消息中心几乎没有功能更新通知,
价值低、维护成本高 [需要登录 + 解 JWT + 周期性重新登录],已下线。)
"""

import json

from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult
from .. import paths

URL = "https://www.vidu.cn/home/reference"
SPOT_API_KEYWORD = "/vpp/v1/spotlights"


def _fetch_spotlights() -> tuple[dict | None, str | None]:
    """启 headless Chromium,加载首页,拦 spotlights 接口的 JSON 响应。"""
    captured: dict[str, dict | None] = {"spotlights": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                locale="zh-CN",
                viewport={"width": 1920, "height": 1080},
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

            def on_response(response):
                if SPOT_API_KEYWORD in response.url:
                    try:
                        captured["spotlights"] = response.json()
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)
            browser.close()
    except Exception as e:
        return None, f"浏览器异常: {e}"

    return captured["spotlights"], None


class ViduSpotlightsSource(BaseSource):
    name = "vidu_spotlights"
    requires_login = False

    def fetch(self) -> FetchResult:
        raw, err = _fetch_spotlights()
        if err:
            return FetchResult(source=self.name, ok=False, error=err)
        if raw is None:
            return FetchResult(source=self.name, ok=False,
                               error="没拦到 spotlights 接口")

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        items = []
        for s in raw.get("spotlights", []):
            t = s.get("type")
            data = s.get(t) if t else None
            if not isinstance(data, dict):
                continue
            link = data.get("link")
            if isinstance(link, dict):
                link = link.get("uri")
            real_id = data.get("id")
            items.append(Item(
                id=str(real_id) if real_id and real_id != "0" else f"{t}:{data.get('title', '')}",
                title=data.get("title") or "(无标题)",
                source=self.name,
                date=(data.get("start_time") or "")[:10] or None,
                content=data.get("subtitle"),
                url=link,
                extras={
                    "type": t,
                    "phase": data.get("phase"),
                    "end_time": data.get("end_time"),
                    "cover": data.get("cover_uri"),
                },
            ))
        return FetchResult(source=self.name, ok=True, items=items)
