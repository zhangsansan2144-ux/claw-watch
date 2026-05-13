"""统一的数据/认证文件路径。

默认在项目根目录下的 data/ 和 auth/,可以用环境变量 CLAW_WATCH_HOME 覆盖。
"""

import os
from pathlib import Path

# 项目根目录:默认是 pyproject.toml 所在的目录的父级
PROJECT_ROOT = Path(os.environ.get("CLAW_WATCH_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = PROJECT_ROOT / "data"
AUTH_DIR = PROJECT_ROOT / "auth"

DATA_DIR.mkdir(exist_ok=True)
AUTH_DIR.mkdir(exist_ok=True)


def snapshot_file(source_name: str) -> Path:
    return DATA_DIR / f"{source_name}_snapshot.json"


def raw_dump_file(source_name: str) -> Path:
    return DATA_DIR / f"{source_name}_raw.json"


def auth_file(source_name: str) -> Path:
    return AUTH_DIR / f"{source_name}_auth.json"


def chrome_profile(source_name: str) -> Path:
    return AUTH_DIR / f"{source_name}_chrome_profile"
