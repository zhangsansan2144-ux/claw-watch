"""所有 source 在这里登记。"""

from .base import BaseSource, Item, FetchResult, LoginHealth
from . import kling, pai, vidu, jimeng, hailuo, liblib, tapnow, lovart, runway


SOURCES: dict[str, BaseSource] = {
    "kling": kling.KlingSource(),
    "pai": pai.PaiSource(),
    "vidu_notifications": vidu.ViduNotificationsSource(),
    "vidu_spotlights": vidu.ViduSpotlightsSource(),
    "jimeng": jimeng.JimengSource(),
    "hailuo": hailuo.HailuoSource(),
    "liblib": liblib.LiblibSource(),
    "tapnow": tapnow.TapNowSource(),
    "lovart": lovart.LovartSource(),
    "runway": runway.RunwaySource(),
}


def get_source(name: str) -> BaseSource:
    if name not in SOURCES:
        raise KeyError(f"未知 source '{name}',可选: {list(SOURCES)}")
    return SOURCES[name]


__all__ = ["BaseSource", "Item", "FetchResult", "LoginHealth", "SOURCES", "get_source"]
