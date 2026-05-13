"""拍我 AI(pai.video / PixVerse)首页 Banner。

完全公开 API,urllib 直接调,不需要浏览器。
"""

import json
import urllib.request

from .base import BaseSource, Item, FetchResult
from .. import paths

API = "https://cn-app-api.pixverseai.cn/creative_platform/banners"


class PaiSource(BaseSource):
    name = "pai"
    requires_login = False

    def fetch(self) -> FetchResult:
        try:
            req = urllib.request.Request(
                API,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                    "Referer": "https://pai.video/",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = json.load(r)
        except Exception as e:
            return FetchResult(source=self.name, ok=False, error=f"fetch 异常: {e}")

        if raw.get("ErrCode") != 0:
            return FetchResult(source=self.name, ok=False,
                               error=f"API ErrCode={raw.get('ErrCode')}: {raw.get('ErrMsg')}")

        with open(paths.raw_dump_file(self.name), "w") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        items = []
        for b in raw.get("Resp", []):
            items.append(Item(
                id=str(b.get("id")),
                title=b.get("title") or "(无标题)",
                source=self.name,
                date=None,  # banner 没有日期字段
                content=b.get("content"),
                url=b.get("target_url") or b.get("target_path"),
                extras={
                    "image": b.get("img_url"),
                    # new_feature_guide 非空 ≈ 新功能 banner
                    "has_feature_guide": bool(b.get("new_feature_guide")),
                },
            ))
        return FetchResult(source=self.name, ok=True, items=items)
