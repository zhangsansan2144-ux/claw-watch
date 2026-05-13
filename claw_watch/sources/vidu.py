"""Vidu(vidu.cn) —— 同时提供"平台消息"和"首页 Banner"两个 source。

需要登录;EdgeOne 反爬,headless 下要带 stealth 装备。
一次浏览器会话 fetch 两次,共享底层 Playwright 开销 —— 通过模块级缓存实现。
"""

import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult, LoginHealth
from .. import paths

URL = "https://www.vidu.cn/home/reference"
NOTIF_API_KEYWORD = "/vidu/v1/system/notifications"
SPOT_API_KEYWORD = "/vpp/v1/spotlights"

# 共享同一份 auth 文件,两个 source 都用
AUTH_NAME = "vidu"

# 模块级缓存:同一次 CLI 调用里,如果 notifications 和 spotlights 都要 fetch,
# 共享一次浏览器启动结果
_cache: dict[str, dict | None] = {"notifications": None, "spotlights": None, "fetched_at": None}


def _fetch_both() -> tuple[Optional[dict], Optional[dict], Optional[str]]:
    """一次浏览器启动,同时拿 notifications 和 spotlights 的原始 JSON。"""
    auth_path = paths.auth_file(AUTH_NAME)
    if not auth_path.exists():
        return None, None, f"未找到登录态 {auth_path},请先 `claw-watch login vidu`"

    captured = {"notifications": None, "spotlights": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                storage_state=str(auth_path),
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
                url = response.url
                if NOTIF_API_KEYWORD in url and "unread-count" not in url:
                    try:
                        captured["notifications"] = response.json()
                    except Exception:
                        pass
                elif SPOT_API_KEYWORD in url:
                    try:
                        captured["spotlights"] = response.json()
                    except Exception:
                        pass

            page.on("response", on_response)

            page.goto(URL, wait_until="networkidle", timeout=45000)

            try:
                page.wait_for_function(
                    "() => document.body.innerText.includes('API开放平台')",
                    timeout=15000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1500)

            bell = page.evaluate(
                """
                () => {
                    const svgs = document.querySelectorAll('svg');
                    let best = null, maxX = 0;
                    svgs.forEach(svg => {
                        const r = svg.getBoundingClientRect();
                        if (r.top < 100 && r.height > 10 && r.height < 30
                            && r.width < 30 && r.left > maxX) {
                            maxX = r.left;
                            best = svg;
                        }
                    });
                    if (!best) return null;
                    let el = best;
                    for (let i = 0; i < 5 && el; i++) {
                        if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button'
                            || getComputedStyle(el).cursor === 'pointer') {
                            const r = el.getBoundingClientRect();
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                        el = el.parentElement;
                    }
                    const r = best.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                """
            )

            if bell:
                page.mouse.click(bell["x"], bell["y"])
            page.wait_for_timeout(3500)

            browser.close()
    except Exception as e:
        return None, None, f"浏览器异常: {e}"

    return captured["notifications"], captured["spotlights"], None


def _ensure_cache():
    """确保 _cache 里两个数据都已经 fetch 过。同一次 CLI 调用复用。"""
    # 30 秒内不重复 fetch
    now = time.time()
    fetched_at = _cache.get("fetched_at")
    if fetched_at and (now - fetched_at) < 30:
        return None  # 缓存还新鲜
    notif, spot, err = _fetch_both()
    if err:
        return err
    _cache["notifications"] = notif
    _cache["spotlights"] = spot
    _cache["fetched_at"] = now
    return None


def _read_jwt_exp() -> Optional[datetime]:
    """从 vidu_auth.json 里读 JWT cookie,解码 exp claim。"""
    auth_path = paths.auth_file(AUTH_NAME)
    if not auth_path.exists():
        return None
    try:
        with open(auth_path) as f:
            state = json.load(f)
        for c in state.get("cookies", []):
            if c.get("name") == "JWT":
                payload = c["value"].split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(payload))
                if "exp" in decoded:
                    return datetime.fromtimestamp(decoded["exp"])
    except Exception:
        pass
    return None


def _login_health() -> LoginHealth:
    exp = _read_jwt_exp()
    if exp is None:
        return LoginHealth(ok=False, note="未登录或 JWT 不可读")
    now = datetime.now()
    days = (exp - now).days
    return LoginHealth(
        ok=days > 0,
        expires_at=exp,
        days_left=days,
        note=f"{'已过期' if days <= 0 else f'{days} 天后过期'}",
    )


def _perform_login() -> None:
    """跑一次有人值守的登录流程,弹出可见浏览器让用户操作。"""
    auth_path = paths.auth_file(AUTH_NAME)
    signal_file = Path("vidu_login_done.signal")
    if signal_file.exists():
        signal_file.unlink()

    print(f"\n=== Vidu 登录 ===")
    print(f"即将弹出浏览器,请完成:")
    print(f"  1. 登录 Vidu 账号")
    print(f"  2. (可选)点🔔切到「平台消息」让接口先跑一次")
    print(f"完成后回到终端按 Enter")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        input("\n按 Enter 保存登录态... ")
        context.storage_state(path=str(auth_path))
        browser.close()
    print(f"[OK] 登录态已保存到 {auth_path}")


class ViduNotificationsSource(BaseSource):
    name = "vidu_notifications"
    requires_login = True

    def fetch(self) -> FetchResult:
        err = _ensure_cache()
        if err:
            return FetchResult(source=self.name, ok=False, error=err, login=_login_health())

        raw = _cache["notifications"]
        if raw is None:
            return FetchResult(source=self.name, ok=False,
                               error="没拦到 notifications 接口",
                               login=_login_health())

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        items = []
        for n in raw.get("notifications", []):
            nn = n.get("notification", {})
            pub = nn.get("publish_at")
            items.append(Item(
                id=str(nn.get("id", "")),
                title=nn.get("title") or "(无标题)",
                source=self.name,
                date=pub[:10] if pub else None,
                content=nn.get("content"),
                url=None,
                extras={"is_read": n.get("is_read")},
            ))
        return FetchResult(source=self.name, ok=True, items=items, login=_login_health())

    def login_health(self) -> LoginHealth:
        return _login_health()

    def perform_login(self) -> None:
        _perform_login()


class ViduSpotlightsSource(BaseSource):
    name = "vidu_spotlights"
    requires_login = True  # 跟 notifications 共用登录,所以也算需要

    def fetch(self) -> FetchResult:
        err = _ensure_cache()
        if err:
            return FetchResult(source=self.name, ok=False, error=err, login=_login_health())

        raw = _cache["spotlights"]
        if raw is None:
            return FetchResult(source=self.name, ok=False,
                               error="没拦到 spotlights 接口",
                               login=_login_health())

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
        return FetchResult(source=self.name, ok=True, items=items, login=_login_health())

    def login_health(self) -> LoginHealth:
        return _login_health()

    def perform_login(self) -> None:
        _perform_login()
