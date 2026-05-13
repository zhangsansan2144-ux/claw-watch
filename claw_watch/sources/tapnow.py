"""TapNow(app.tapnow.ai)首页 banner 轮播 + 右下角广告弹窗。

完全公开 API,urllib 直接调,免登录免浏览器。两个接口:
  1. `/api/community/carousel/active/home` —— 首页顶部 banner 轮播
     (整数 id + created_at,字段干净)
  2. `/api/bff/platform/config?keys=GLOBAL_BOTTOM_RIGHT_AD_CARD`
     —— 右下角广告卡。value 是 JSON 字符串,里面才是真数据。
     id 是字符串("11" / "minimax2.6" / ...),没有时间戳。

两接口 id 取值域不同(int vs 字符串),理论上不撞,但保险起见给 Item.id
加 kind 前缀做去重。
"""

import json
import time
import urllib.request

from .base import BaseSource, Item, FetchResult
from .. import paths

CAROUSEL_API = "https://app.tapnow.ai/api/community/carousel/active/home?limit=50&language=zh-CN"
# 只关心右下角广告卡这一个 key,但接口 keys 参数本身得带至少一个值
CONFIG_API = "https://app.tapnow.ai/api/bff/platform/config?keys=GLOBAL_BOTTOM_RIGHT_AD_CARD"
POPUP_KEY = "GLOBAL_BOTTOM_RIGHT_AD_CARD"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _http_get_json(url: str) -> dict:
    # TapNow 的 TLS 握手偶发性超时(观测到 ~50% 失败率),做 3 次重试 + 退避
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Referer": "https://app.tapnow.ai/",
                },
            )
            with urllib.request.urlopen(req, timeout=20 + attempt * 5) as r:
                return json.load(r)
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _pick_zh(field) -> str | None:
    """title/description 字段在 popup 里是 {lang: text} dict,在 carousel 顶层是裸 str。
    优先 zh-CN,退化到任何能找到的。"""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("zh-CN") or field.get("en-US") or next(iter(field.values()), None)
    return None


def _carousel_items(raw: dict) -> list[Item]:
    out = []
    for c in raw.get("data") or []:
        if not isinstance(c, dict):
            continue
        if c.get("enabled") is False:
            continue
        cid = c.get("id")
        if cid is None:
            continue
        created = c.get("created_at") or c.get("updated_at") or ""
        out.append(Item(
            id=f"carousel:{cid}",
            title=c.get("title") or "(无标题)",
            source="tapnow",
            date=created[:10] if created else None,
            content=c.get("description") or c.get("subtitle") or None,
            url=c.get("link_url"),
            extras={
                "kind": "carousel",
                "subtitle": c.get("subtitle"),
                "button_text": c.get("button_text"),
                "sort_order": c.get("sort_order"),
                "media_url": c.get("media_url"),
                "cover_image_url": c.get("cover_image_url"),
                "view_count": c.get("view_count"),
                "updated_at": c.get("updated_at"),
                "localized_meta": c.get("localized_meta"),
            },
        ))
    return out


def _popup_items(raw: dict) -> list[Item]:
    entries = raw.get("data") or []
    target = next((e for e in entries if isinstance(e, dict) and e.get("key") == POPUP_KEY), None)
    if not target:
        return []
    val = target.get("value")
    if isinstance(val, str):
        try:
            cards = json.loads(val)
        except Exception:
            return []
    elif isinstance(val, list):
        cards = val
    else:
        return []

    out = []
    for p in cards:
        if not isinstance(p, dict):
            continue
        if p.get("enable") is False:
            continue
        pid = p.get("id")
        if pid is None:
            continue
        # url:NAVIGATE → 站内 route,其他 action 不一定有外链
        url = None
        action = p.get("action")
        data = p.get("data") or {}
        if action == "NAVIGATE" and data.get("route"):
            url = data["route"]
        elif action == "OPEN_URL" and data.get("url"):
            url = data["url"]
        out.append(Item(
            id=f"popup:{pid}",
            title=_pick_zh(p.get("title")) or "(无标题)",
            source="tapnow",
            date=None,  # popup 配置没带时间戳
            content=_pick_zh(p.get("description")),
            url=url,
            extras={
                "kind": "popup",
                "action": action,
                "visible_type": p.get("visible_type"),
                "image": p.get("src"),
                "data": data,
                "title_localized": p.get("title") if isinstance(p.get("title"), dict) else None,
                "description_localized": p.get("description") if isinstance(p.get("description"), dict) else None,
            },
        ))
    return out


class TapNowSource(BaseSource):
    name = "tapnow"
    requires_login = False

    def fetch(self) -> FetchResult:
        try:
            carousel_raw = _http_get_json(CAROUSEL_API)
            config_raw = _http_get_json(CONFIG_API)
        except Exception as e:
            return FetchResult(source=self.name, ok=False, error=f"fetch 异常: {e}")

        # 两接口都用 {"code": 200, ...} 做成功标记;0 是 canvas 系老接口用的,这俩不会出
        for label, raw in (("carousel", carousel_raw), ("config", config_raw)):
            if raw.get("code") not in (200, 0):
                return FetchResult(
                    source=self.name, ok=False,
                    error=f"{label} API code={raw.get('code')}: {raw.get('message')}",
                )

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump({"carousel": carousel_raw, "config": config_raw}, f, ensure_ascii=False, indent=2)

        items = _carousel_items(carousel_raw) + _popup_items(config_raw)
        return FetchResult(source=self.name, ok=True, items=items)
