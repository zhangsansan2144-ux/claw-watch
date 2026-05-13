"""LibLibAI(www.liblib.art)通知中心「官方通知」。

需要登录;API 在 api2.liblib.art。
为了能在 Claude Code / 任何 Bash 后台可靠地弹出登录窗口,这里走 jimeng 路子:
  - subprocess 起系统真实 Chrome(带 --remote-debugging-port + --user-data-dir)
  - Playwright 通过 CDP attach
  - 登录态持久化在 auth/liblib_chrome_profile/(寿命比 storage_state 长得多)
  - 额外导出一份 storage_state 到 auth/liblib_auth.json,给 login_health 用

⚠️ 当前 fetch() 为「发现模式」:登录态加载 + dump 所有 api2 响应。
   定位「官方通知」接口后会替换成真正的提取逻辑。
"""

import json
import subprocess
import time
from datetime import datetime
from typing import Optional

from playwright.sync_api import sync_playwright

from .base import BaseSource, Item, FetchResult, LoginHealth
from .. import paths

HOME_URL = "https://www.liblib.art/"
NOTIFICATION_PAGE_URL = "https://www.liblib.art/message"  # 「通知」页,默认会触发 myTypeMsg(firstType=1=官方通知)
NOTIF_API_KEYWORD = "/community/myTypeMsg"
API_HOST = "api2.liblib.art"

# login 阶段顺手过一遍这几个 URL 触发各种 API,便于后续接口扩展
NOTIFICATION_URL_CANDIDATES = [
    NOTIFICATION_PAGE_URL,
    "https://www.liblib.art/userhome",
]


def _strip_html(html: str) -> str:
    """通知内容是富文本 HTML,飞书推送/控制台都需要纯文本。粗暴去标签 + 解 entity。"""
    import html as _html
    import re
    if not html:
        return ""
    # 块级元素转换行
    txt = re.sub(r"</(p|div|br|li|h[1-6])\s*>", "\n", html, flags=re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = _html.unescape(txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt

CDP_PORT = 9223  # 避开 jimeng 用的 9222
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

PROFILE_NAME = "liblib"   # → auth/liblib_chrome_profile/
AUTH_NAME = "liblib"      # → auth/liblib_auth.json

# 反追踪 cookie,不算登录信号
TRACKING_COOKIES = {
    "acw_tc", "webid", "webidExt", "_ga", "_gid", "_gat",
    "Hm_lvt", "Hm_lpvt", "SERVERID", "JSESSIONID",
    "sajssdk_2015_cross_new_user",
    "sensorsdata2015jssdkcross", "sensorsdata2015jssdkchannel",
}
TRACKING_COOKIE_PREFIXES = ("_ga_", "Hm_lvt_", "Hm_lpvt_")


def _is_tracking_cookie(name: str) -> bool:
    return name in TRACKING_COOKIES or name.startswith(TRACKING_COOKIE_PREFIXES)


def _start_chrome(headless: bool = False) -> None:
    """用 `open -na` 启动一个**全新** Chrome 实例(避免被现有 Chrome 单例转发吞掉)。

    返回 None —— `open` 命令本身瞬间退出,Chrome 进程独立运行,后续要靠 pkill
    by --user-data-dir 来识别和终止。
    """
    profile = paths.chrome_profile(PROFILE_NAME)
    profile.mkdir(exist_ok=True)
    args = [
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--window-size=1440,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")
    args.append(HOME_URL)
    subprocess.run(
        ["open", "-na", "Google Chrome", "--args"] + args,
        check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_for_cdp(port: int, timeout_s: int = 15) -> bool:
    """轮询 /json/version 直到 CDP 端口就绪。Chrome 启动可能要 4-8 秒。"""
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


def _stop_chrome() -> None:
    """按 --user-data-dir 路径精确 kill 我们启动的那个 Chrome,不动用户主 Chrome。"""
    profile = paths.chrome_profile(PROFILE_NAME)
    subprocess.run(
        ["pkill", "-f", f"user-data-dir={profile}"],
        check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _login_health() -> LoginHealth:
    """profile 存在就视为已登录;有 auth_file 时再看 cookie 寿命。"""
    profile = paths.chrome_profile(PROFILE_NAME)
    auth_path = paths.auth_file(AUTH_NAME)
    if not profile.exists():
        return LoginHealth(ok=False, note="未登录(Chrome profile 不存在)")
    if not auth_path.exists():
        return LoginHealth(ok=True, note="profile 存在但未导出 cookie 元信息")
    try:
        with open(auth_path) as f:
            state = json.load(f)
        # 找寿命最长的 liblib 鉴权 cookie
        best_exp = None
        best_name = None
        for c in state.get("cookies", []):
            if "liblib.art" not in c.get("domain", ""):
                continue
            if _is_tracking_cookie(c.get("name", "")):
                continue
            exp_ts = c.get("expires", -1)
            if exp_ts and exp_ts > 0 and (best_exp is None or exp_ts > best_exp):
                best_exp = exp_ts
                best_name = c.get("name")
        if best_exp is None:
            return LoginHealth(ok=True, note="找不到带过期时间的鉴权 cookie(session-only)")
        exp = datetime.fromtimestamp(best_exp)
        days = (exp - datetime.now()).days
        return LoginHealth(
            ok=days > 0,
            expires_at=exp,
            days_left=days,
            note=f"{best_name} {'已过期' if days <= 0 else f'{days} 天后过期'}",
        )
    except Exception as e:
        return LoginHealth(ok=True, note=f"读 cookie 异常: {e}(profile 仍可能有效)")


class LiblibSource(BaseSource):
    name = "liblib"
    requires_login = True

    def fetch(self) -> FetchResult:
        """抓取「官方通知」列表。

        实现:Playwright headless + storage_state → navigate 到 /message →
        拦截 myTypeMsg 响应。完全静默,不弹窗。
        """
        auth_path = paths.auth_file(AUTH_NAME)
        if not auth_path.exists():
            return FetchResult(
                source=self.name, ok=False,
                error="未登录,请先 `claw-watch login liblib`",
                login=_login_health(),
            )

        captured = {"data": None}

        def on_response(response):
            if NOTIF_API_KEYWORD in response.url:
                try:
                    captured["data"] = response.json()
                except Exception:
                    pass

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    storage_state=str(auth_path),
                    user_agent=UA,
                    locale="zh-CN",
                    viewport={"width": 1440, "height": 900},
                )
                page = context.new_page()
                page.on("response", on_response)
                page.goto(NOTIFICATION_PAGE_URL, wait_until="domcontentloaded", timeout=30000)
                # 通知接口在页面 mount 后异步触发,等几秒
                for _ in range(8):
                    if captured["data"] is not None:
                        break
                    page.wait_for_timeout(500)
                page.wait_for_timeout(1500)
                browser.close()
        except Exception as e:
            return FetchResult(source=self.name, ok=False,
                               error=f"浏览器异常: {e}", login=_login_health())

        raw = captured["data"]
        if raw is None:
            return FetchResult(source=self.name, ok=False,
                               error="没拦到 myTypeMsg 接口(可能登录态过期,跑 `claw-watch login liblib`)",
                               login=_login_health())

        if raw.get("code") not in (0, "0"):
            return FetchResult(source=self.name, ok=False,
                               error=f"API code={raw.get('code')}: {raw.get('msg')}",
                               login=_login_health())

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        items = []
        for n in ((raw.get("data") or {}).get("data") or []):
            ct = n.get("createTime") or ""
            date = ct[:10] if ct else None
            content_html = n.get("content") or ""
            content_text = _strip_html(content_html)
            items.append(Item(
                id=str(n.get("id", "")),
                title=n.get("title") or "(无标题)",
                source=self.name,
                date=date,
                content=content_text or None,
                url=None,  # 通知没有外链,content 里可能有
                extras={
                    "type": n.get("type"),
                    "first_type": n.get("firstType"),
                    "read_status": n.get("readStatus"),
                    "top_flag": n.get("topFlag"),
                    "uuid": n.get("uuid"),
                    "msg_desc_pic": n.get("msgDescPic") or None,
                },
            ))
        return FetchResult(source=self.name, ok=True, items=items, login=_login_health())

    def login_health(self) -> LoginHealth:
        return _login_health()

    def perform_login(self) -> None:
        """启动真实 Chrome 让用户登录,自动检测并保存。无需终端交互。

        检测策略:
        - cookie diff(主):匿名加载后记下 cookies,出现 liblib.art 域的新非追踪 cookie 即视为登录
        - getUserInfo(辅):接口返回 code==0 且 data 非空也算
        登录后自动:跑候选通知页 → 导出 storage_state → 关闭 Chrome
        """
        print("\n=== LibLib 登录 ===")
        print("即将启动 Chrome 浏览器(系统真实 Chrome,非 Playwright bundled)。")
        print("请在浏览器里完成登录,登录成功会自动检测、保存、关闭浏览器,无需回到终端。")
        print("超时:10 分钟。\n")

        _start_chrome(headless=False)
        if not _wait_for_cdp(CDP_PORT, timeout_s=15):
            _stop_chrome()
            print(f"[失败] Chrome CDP 端口 {CDP_PORT} 15s 内未就绪")
            return

        login_detected = {"ok": False, "via": None, "user_id": None}
        captured_apis: list[dict] = []
        initial_cookie_names: set[str] = set()

        def on_response(response):
            url = response.url
            if "/user/getUserInfo" in url:
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        code = body.get("code")
                        data = body.get("data")
                        if code in (0, "0", None) and data and isinstance(data, dict) and len(data) > 0:
                            if not login_detected["ok"]:
                                login_detected["ok"] = True
                                login_detected["via"] = "getUserInfo"
                                for k in ("uuid", "userUuid", "id", "uid", "userId"):
                                    if data.get(k):
                                        login_detected["user_id"] = data[k]
                                        break
                except Exception:
                    pass
            if API_HOST in url and "/log/" not in url and "/event/report" not in url:
                try:
                    captured_apis.append({
                        "url": url.split("?")[0],
                        "full_url": url,
                        "status": response.status,
                        "body": response.json(),
                    })
                except Exception:
                    pass

        def cookies_indicate_login(cookies: list) -> Optional[str]:
            for c in cookies:
                name = c.get("name", "")
                domain = c.get("domain", "")
                if "liblib.art" not in domain:
                    continue
                if name in initial_cookie_names or _is_tracking_cookie(name):
                    continue
                if not c.get("value"):
                    continue
                return f"{name}@{domain}"
            return None

        auth_path = paths.auth_file(AUTH_NAME)

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                for pg in context.pages:
                    pg.on("response", on_response)
                context.on("page", lambda p: p.on("response", on_response))

                page.wait_for_timeout(3000)
                try:
                    initial_cookie_names = {
                        c["name"] for c in context.cookies()
                        if "liblib.art" in c.get("domain", "")
                    }
                except Exception:
                    pass
                print(f"开始等登录(已记录 {len(initial_cookie_names)} 个匿名 cookies)")

                deadline = time.time() + 600
                last_status = time.time()
                while time.time() < deadline:
                    if not login_detected["ok"]:
                        try:
                            hit = cookies_indicate_login(context.cookies())
                            if hit:
                                login_detected["ok"] = True
                                login_detected["via"] = f"cookie:{hit}"
                        except Exception:
                            break
                    if login_detected["ok"]:
                        print(f"[OK] 检测到登录 (via {login_detected['via']})")
                        break
                    if time.time() - last_status > 30:
                        last_status = time.time()
                        elapsed = int(time.time() - (deadline - 600))
                        print(f"  ...还在等你登录 (已等 {elapsed}s / 600s)")
                    try:
                        page.wait_for_timeout(1500)
                    except Exception:
                        break

                # 兜底:即使没检测到,只要 liblib.art 域 cookie 有增长也试着保存
                if not login_detected["ok"]:
                    try:
                        cur = {c["name"] for c in context.cookies()
                               if "liblib.art" in c.get("domain", "")}
                        new = {
                            name for name in (cur - initial_cookie_names)
                            if not _is_tracking_cookie(name)
                        }
                        if new:
                            print(f"[兜底] cookie 增量 {new},尝试保存")
                            login_detected["ok"] = True
                            login_detected["via"] = "fallback-cookie-diff"
                    except Exception:
                        pass

                if not login_detected["ok"]:
                    print("[超时/失败] 没检测到登录,不保存")
                    return

                # 多停几秒让接口跑完
                try:
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

                # 顺路过一遍候选通知页
                for u in NOTIFICATION_URL_CANDIDATES:
                    try:
                        page.goto(u, wait_until="domcontentloaded", timeout=15000)
                        page.wait_for_timeout(2500)
                    except Exception:
                        pass

                try:
                    context.storage_state(path=str(auth_path))
                    print(f"[OK] 登录态(storage_state)已保存到 {auth_path}")
                except Exception as e:
                    print(f"[警告] 保存 storage_state 失败: {e}(Chrome profile 仍然有效)")
        finally:
            _stop_chrome()

        # 保存登录期抓到的 API 供分析
        login_dump = paths.raw_dump_file(self.name).with_name(f"{self.name}_login_capture.json")
        try:
            with open(login_dump, "w") as f:
                json.dump({"login_user_id": login_detected["user_id"],
                           "via": login_detected["via"],
                           "responses": captured_apis}, f, ensure_ascii=False, indent=2)
            print(f"[OK] 登录期间抓到的 {len(captured_apis)} 个 API 响应已存到 {login_dump}")
        except Exception as e:
            print(f"[警告] 保存 capture 失败: {e}")
        print(f"[OK] Chrome profile 已持久化在 {paths.chrome_profile(PROFILE_NAME)}")
