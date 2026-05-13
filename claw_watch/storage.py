"""快照管理:保存/读取 + diff 出新增条目。"""

import json
from pathlib import Path

from .sources.base import Item
from . import paths


def load_snapshot(source_name: str) -> list[dict]:
    snap = paths.snapshot_file(source_name)
    if not snap.exists():
        return []
    try:
        with open(snap) as f:
            data = json.load(f)
        # 兼容老快照:id 可能是 int,统一转 string 再 diff
        for it in data:
            if "id" in it and it["id"] is not None and not isinstance(it["id"], str):
                it["id"] = str(it["id"])
        return data
    except Exception:
        return []


def save_snapshot(source_name: str, items: list[Item]) -> None:
    snap = paths.snapshot_file(source_name)
    with open(snap, "w") as f:
        json.dump([it.to_dict() for it in items], f, ensure_ascii=False, indent=2)


def diff_new_items(source_name: str, items: list[Item]) -> list[Item]:
    """根据 id 对比历史快照,返回新增条目。
    如果快照不存在,返回空(首次跑视为基线,不算"新增")。
    """
    snap = paths.snapshot_file(source_name)
    if not snap.exists():
        return []
    old = load_snapshot(source_name)
    old_ids = {it.get("id") for it in old if it.get("id")}
    return [it for it in items if it.id and it.id not in old_ids]
