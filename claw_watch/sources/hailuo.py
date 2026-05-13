"""海螺 AI(hailuoai.com)首页 banner + 运营弹窗。

完全公开 API,urllib 直接调,免登录免浏览器。

数据来自两个接口:
  1. `list_all_valid_popup_configs` —— 顶部横幅 + 弹窗类活动
     (文案走 i18n key,需要从同一份 response 的 starlingKeyMap 查)
  2. `common_config.video_banner_v2` —— 首页中部两个 banner 位
     - [0]: 左侧轮播(多张)
     - [1]: 右侧固定(单张)

两个接口的 id 都是小整数,容易碰撞,所以这里给 Item.id 加 source 前缀做去重。
"""

import json
import urllib.request
from datetime import datetime

from .base import BaseSource, Item, FetchResult
from .. import paths

POPUP_API = (
    "https://hailuoai.com/v2/api/operation/list_all_valid_popup_configs"
    "?device_platform=web&app_id=3001&version_code=22203&biz_id=0"
    "&lang=zh-Hans&os_name=Mac&browser_name=chrome"
)
COMMON_API = (
    "https://hailuoai.com/public/api/config/web/common_config"
    "?device_platform=web&app_id=3001&version_code=22203&biz_id=0"
    "&lang=zh-Hans&os_name=Mac&browser_name=chrome"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json", "Referer": "https://hailuoai.com/"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _resolve_title(cfg_json: dict, starling: dict, fallback: str) -> str:
    """从 configJson 里挖 title key,去 starlingKeyMap 查中文。挖不到就用 activityName。"""
    title_key = cfg_json.get("title") or cfg_json.get("h5Title")
    if not title_key:
        for member in ("normalMember", "vipMember"):
            block = cfg_json.get(member) or {}
            if isinstance(block, dict) and block.get("modalTitle"):
                title_key = block["modalTitle"]
                break
    if title_key and title_key in starling:
        return starling[title_key]
    return fallback


def _resolve_content(starling: dict) -> str | None:
    if not starling:
        return None
    longest = max(starling.values(), key=len, default="")
    return longest if len(longest) >= 8 else None


def _resolve_url(cfg_json: dict) -> str | None:
    btn = (cfg_json.get("btnInfo") or {}).get("action") or {}
    if btn.get("url"):
        return btn["url"]
    for member in ("normalMember", "vipMember"):
        block = cfg_json.get(member) or {}
        for a in (block.get("actions") or []):
            if isinstance(a, dict) and a.get("url"):
                return a["url"]
    return None


def _popup_items(raw: dict) -> list[Item]:
    out = []
    for c in (raw.get("data") or {}).get("configs", []):
        cfg_json_str = c.get("configJson") or "{}"
        try:
            cfg_json = json.loads(cfg_json_str)
        except Exception:
            cfg_json = {}
        starling = c.get("starlingKeyMap") or {}
        activity = c.get("activityName") or "(无名活动)"
        ts_ms = c.get("updatedAt") or c.get("createdAt")
        date = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d") if ts_ms else None

        out.append(Item(
            id=f"popup:{c.get('id', '')}",
            title=_resolve_title(cfg_json, starling, activity),
            source="hailuo",
            date=date,
            content=_resolve_content(starling),
            url=_resolve_url(cfg_json),
            extras={
                "kind": "popup",
                "activity_name": activity,
                "popup_type": c.get("popupType"),
                "start_time": c.get("startTime"),
                "end_time": c.get("endTime"),
                "updated_at": c.get("updatedAt"),
            },
        ))
    return out


def _banner_items(raw: dict) -> list[Item]:
    """common_config.video_banner_v2 是 [[轮播位...], [固定位...]] 的二维结构。"""
    data = raw.get("data") or {}
    groups = data.get("video_banner_v2") or []
    out = []
    slot_names = ["banner_carousel", "banner_fixed"]
    for idx, group in enumerate(groups):
        slot = slot_names[idx] if idx < len(slot_names) else f"banner_{idx}"
        if not isinstance(group, list):
            continue
        for b in group:
            if not isinstance(b, dict):
                continue
            title = (b.get("title") or "(无标题)").replace("\n", " ")
            out.append(Item(
                id=f"{slot}:{b.get('id', '')}",
                title=title,
                source="hailuo",
                date=None,  # banner 接口里没有时间字段
                content=b.get("desc") or None,
                url=b.get("link"),
                extras={
                    "kind": slot,
                    "image": b.get("image_url"),
                    "logo": b.get("logo"),
                },
            ))
    return out


class HailuoSource(BaseSource):
    name = "hailuo"
    requires_login = False

    def fetch(self) -> FetchResult:
        try:
            popup_raw = _http_get_json(POPUP_API)
            common_raw = _http_get_json(COMMON_API)
        except Exception as e:
            return FetchResult(source=self.name, ok=False, error=f"fetch 异常: {e}")

        for raw in (popup_raw, common_raw):
            status = raw.get("statusInfo") or {}
            if status.get("code") not in (0, None):
                return FetchResult(
                    source=self.name, ok=False,
                    error=f"API code={status.get('code')}: {status.get('message')}",
                )

        # 两份 raw 各存一份,便于排查
        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump({"popup": popup_raw, "common": common_raw}, f, ensure_ascii=False, indent=2)

        items = _popup_items(popup_raw) + _banner_items(common_raw)
        return FetchResult(source=self.name, ok=True, items=items)
