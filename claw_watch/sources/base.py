"""所有 source 的基类和数据结构。"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class Item:
    """统一的内容条目格式,所有 source 提取出来的数据都长这样。"""

    id: str
    title: str
    source: str                       # 'kling' / 'pai' / 'vidu_notifications' / ...
    date: str | None = None           # ISO 格式 YYYY-MM-DD,没有日期就 None
    content: str | None = None
    url: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)  # source 专属字段

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LoginHealth:
    """登录态健康状况(给需要登录的 source 用)。"""

    ok: bool                          # 当前是否还能用
    expires_at: datetime | None = None
    days_left: int | None = None
    note: str | None = None           # 人类可读说明


@dataclass
class FetchResult:
    """fetch 一次的结果。"""

    source: str
    ok: bool
    items: list[Item] = field(default_factory=list)
    error: str | None = None
    login: LoginHealth | None = None

    def to_dict(self) -> dict:
        d = {
            "source": self.source,
            "ok": self.ok,
            "items": [it.to_dict() for it in self.items],
            "total": len(self.items),
        }
        if self.error:
            d["error"] = self.error
        if self.login:
            d["login"] = {
                "ok": self.login.ok,
                "expires_at": self.login.expires_at.isoformat() if self.login.expires_at else None,
                "days_left": self.login.days_left,
                "note": self.login.note,
            }
        return d


class BaseSource:
    """每个站点 source 继承这个。

    最少要实现 name + fetch。需要登录的还要实现 login_health + perform_login。
    """

    name: str = ""
    requires_login: bool = False

    def fetch(self) -> FetchResult:
        raise NotImplementedError

    def login_health(self) -> LoginHealth | None:
        """对于不需要登录的 source,返回 None。"""
        return None

    def perform_login(self) -> None:
        """跑一次手动登录流程,把登录态持久化。"""
        raise NotImplementedError(f"{self.name} doesn't support login")
