"""即梦(jimeng.jianying.com)官方消息。

字节系反爬,必须用 subprocess 启动真实 Chrome + CDP attach。
登录态在 chrome profile 目录里持久化,sessionid 寿命 ~1 年。
"""

import json
import subprocess
import time
from datetime import datetime
from typing import Optional

from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult, LoginHealth
from .. import paths

URL = "https://jimeng.jianying.com/ai-tool/home"
API_KEYWORD = "/mweb/v1/get_notice_list"
CDP_PORT = 9222
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PROFILE_NAME = "jimeng"     # → auth/jimeng_chrome_profile/
AUTH_NAME = "jimeng"        # → auth/jimeng_auth.json(健康检查用)


def _profile_alive() -> bool:
    """是否还有 Chrome 进程占着我们的 profile。"""
    profile = paths.chrome_profile(PROFILE_NAME)
    return subprocess.run(
        ["pgrep", "-f", f"user-data-dir={profile}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def _start_chrome(extra_args: Optional[list[str]] = None) -> None:
    """用 `open -na` 启一个全新 Chrome 实例。

    直接执行 Chrome 二进制在 macOS 上会被「应用单例」机制吞掉 —— 如果用户主 Chrome
    已经运行,新调用会被转发给主 Chrome,我们这边的 --remote-debugging-port 不会生效。
    `open -na` 的 `-n` 强制开新实例。

    返回 None —— `open` 自身瞬间退出,Chrome 在后台独立运行。后续靠 _stop_chrome
    按 --user-data-dir 路径 pkill。

    启动前先确认上一次的 Chrome 真死透了 —— 否则 profile 还被锁着,新 Chrome 会
    fallback 到一份临时空白 profile,登录态全丢。
    """
    profile = paths.chrome_profile(PROFILE_NAME)
    profile.mkdir(exist_ok=True)

    # 兜底:上一次 _stop_chrome 没等够 / 没被调用,这次先把 profile 释放出来
    if _profile_alive():
        deadline = time.time() + 8
        while time.time() < deadline and _profile_alive():
            time.sleep(0.3)
        if _profile_alive():
            subprocess.run(
                ["pkill", "-9", "-f", f"user-data-dir={profile}"],
                check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1)

    args = [
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--window-size=1440,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if extra_args:
        args.extend(extra_args)
    args.append(URL)
    subprocess.run(
        ["open", "-na", "Google Chrome", "--args"] + args,
        check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_for_cdp(port: int, timeout_s: int = 15) -> bool:
    """轮询 /json/version 直到 CDP 端口就绪。Chrome 启动一般要 4-8 秒。"""
    import urllib.request
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop_chrome(wait_s: int = 10) -> None:
    """按 --user-data-dir 路径精确 kill 我们启动的那个 Chrome,绝不动用户主 Chrome。

    发完 SIGTERM 必须**等 Chrome 真的退出**,不能立刻返回 —— 因为 Chrome 收到
    SIGTERM 后要 2-5 秒做收尾:把 RAM 里的 cookie / IndexedDB / 网络状态
    flush 到 profile 的 SQLite,释放 profile 锁。

    如果不等就接着调 _start_chrome,新 Chrome 看到 profile 还被锁 → fallback 成
    临时空白 profile → 登录态全丢。这是一个真实踩过的 bug。
    """
    profile = paths.chrome_profile(PROFILE_NAME)
    pattern = f"user-data-dir={profile}"
    subprocess.run(
        ["pkill", "-f", pattern],
        check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if not _profile_alive():
            time.sleep(0.5)  # 多等 0.5s 让 SQLite WAL checkpoint 完成
            return
        time.sleep(0.2)
    # 超时仍未死,SIGKILL 兜底
    subprocess.run(
        ["pkill", "-9", "-f", pattern],
        check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def _login_health() -> LoginHealth:
    """查看 jimeng_chrome_profile 是否还在 + sessionid cookie 是否还活着。"""
    profile = paths.chrome_profile(PROFILE_NAME)
    auth_path = paths.auth_file(AUTH_NAME)
    if not profile.exists():
        return LoginHealth(ok=False, note="未登录(profile 不存在)")
    if not auth_path.exists():
        return LoginHealth(ok=True, note="profile 存在但未导出 cookie 元信息")
    try:
        with open(auth_path) as f:
            state = json.load(f)
        for c in state.get("cookies", []):
            if c.get("name") == "sessionid":
                exp_ts = c.get("expires", -1)
                if exp_ts <= 0:
                    return LoginHealth(ok=True, note="session cookie(浏览器关闭即失效,长期看会过期)")
                exp = datetime.fromtimestamp(exp_ts)
                days = (exp - datetime.now()).days
                return LoginHealth(
                    ok=days > 0,
                    expires_at=exp,
                    days_left=days,
                    note=f"{'已过期' if days <= 0 else f'{days} 天后过期'}",
                )
    except Exception as e:
        return LoginHealth(ok=True, note=f"读 cookie 异常: {e}(profile 仍可能有效)")
    return LoginHealth(ok=True, note="找不到 sessionid cookie")


class JimengSource(BaseSource):
    name = "jimeng"
    requires_login = True

    def fetch(self) -> FetchResult:
        profile = paths.chrome_profile(PROFILE_NAME)
        if not profile.exists():
            return FetchResult(source=self.name, ok=False,
                               error=f"未登录,请先 `claw-watch login jimeng`",
                               login=_login_health())

        captured: dict[str, dict | None] = {"data": None}
        _start_chrome()
        if not _wait_for_cdp(CDP_PORT, timeout_s=15):
            _stop_chrome()
            return FetchResult(source=self.name, ok=False,
                               error=f"Chrome CDP 端口 {CDP_PORT} 15s 内未就绪",
                               login=_login_health())

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                def on_response(response):
                    if API_KEYWORD not in response.url:
                        return
                    try:
                        body = response.json()
                        data = body.get("data") or {}
                        if data.get("notice_type") != 1:
                            return
                        notices = data.get("notice_list") or []
                        prev = captured["data"]
                        prev_count = len((prev or {}).get("data", {}).get("notice_list") or [])
                        if prev is None or len(notices) > prev_count:
                            captured["data"] = body
                    except Exception:
                        pass

                for pg in context.pages:
                    pg.on("response", on_response)
                context.on("page", lambda p: p.on("response", on_response))

                # 等侧栏「通知」菜单项渲染出来 —— 这个 id 是稳定的,而且只要它在了,bell 一定也在了
                # 之前用 "≥2 个 20x20 SVG" 作为等待条件,bell(顶上的那个)因带未读红点
                # 渲染稍慢,刚好踩在 2 个的临界点 → 取错下面的「应用下载」当 bell
                try:
                    page.wait_for_selector("#SiderMenuNotification", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)

                bell = page.evaluate(
                    """
                    () => {
                        const H = window.innerHeight;
                        const all = [];
                        document.querySelectorAll('svg').forEach(svg => {
                            const r = svg.getBoundingClientRect();
                            if (r.left < 100 && r.top > H * 0.5
                                && r.width === 20 && r.height === 20) {
                                all.push({top: r.top,
                                          x: r.left + r.width / 2,
                                          y: r.top + r.height / 2});
                            }
                        });
                        all.sort((a, b) => a.top - b.top);
                        return all.length ? all[0] : null;
                    }
                    """
                )

                if not bell:
                    return FetchResult(source=self.name, ok=False,
                                       error="没找到左下角🔔",
                                       login=_login_health())

                page.mouse.click(bell["x"], bell["y"])
                page.wait_for_timeout(1500)

                try:
                    page.get_by_text("官方消息", exact=True).first.click(timeout=5000)
                except Exception:
                    pass

                # 等响应,最多 10 秒
                for _ in range(20):
                    page.wait_for_timeout(500)
                    if captured["data"] is not None:
                        page.wait_for_timeout(2000)
                        break
        except Exception as e:
            return FetchResult(source=self.name, ok=False, error=f"浏览器异常: {e}",
                               login=_login_health())
        finally:
            _stop_chrome()

        raw = captured["data"]
        if raw is None:
            return FetchResult(source=self.name, ok=False,
                               error="没拦到 get_notice_list(notice_type=1)",
                               login=_login_health())

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        items = []
        for n in (raw.get("data") or {}).get("notice_list", []):
            ct = n.get("created_time")
            date = datetime.fromtimestamp(ct).strftime("%Y-%m-%d") if ct else None
            items.append(Item(
                id=str(n.get("id", "")),
                title=n.get("title") or "(无标题)",
                source=self.name,
                date=date,
                content=n.get("content"),
                url=n.get("url") or None,
            ))
        return FetchResult(source=self.name, ok=True, items=items, login=_login_health())

    def login_health(self) -> LoginHealth:
        return _login_health()

    def perform_login(self) -> None:
        """启动可视化 Chrome 让用户登录,完成后导出 cookies 到 auth/jimeng_auth.json
        用于后续健康检查(profile 自身已自动持久化)。"""
        print(f"\n=== 即梦 登录 ===")
        print(f"即将弹出 Chrome,请完成:")
        print(f"  1. 登录账号")
        print(f"  2. 点左下角🔔,切到「官方消息」,等消息列表加载出来")
        print(f"完成后再回到终端按 Enter")

        _start_chrome()
        if not _wait_for_cdp(CDP_PORT, timeout_s=15):
            _stop_chrome()
            print(f"[失败] Chrome CDP 端口 {CDP_PORT} 15s 内未就绪")
            return

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                context = browser.contexts[0]

                input("\n登录完成后按 Enter 保存登录态... ")

                # 导出 cookies + storage 元信息(健康检查要看 sessionid 过期时间)
                try:
                    context.storage_state(path=str(paths.auth_file(AUTH_NAME)))
                    print(f"[OK] cookie 元信息已保存到 {paths.auth_file(AUTH_NAME)}")
                except Exception as e:
                    print(f"[警告] 保存 cookie 元信息失败(profile 仍然有效): {e}")
        finally:
            _stop_chrome()
        print(f"[OK] Chrome profile 持久化在 {paths.chrome_profile(PROFILE_NAME)}")
