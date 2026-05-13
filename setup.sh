#!/usr/bin/env bash
# claw-watch 一键安装脚本(macOS)
# 用法: ./setup.sh
# 安全可重入:venv 已存在会复用,不会破坏已有登录态

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo
echo -e "${BOLD}=== claw-watch 安装 ===${NC}"
echo "目录: $PROJECT_DIR"
echo

# 1) 找一个 >= 3.11 的 Python
echo -e "${BOLD}[1/4]${NC} 检查 Python..."
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
        major=${ver%%.*}
        minor=${ver##*.}
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$candidate"
            echo -e "  ${GREEN}✓${NC} 用 $candidate (Python $ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "  ${RED}✗${NC} 没找到 Python 3.11+"
    echo
    echo "  最简单的装法:"
    echo "    brew install python@3.12"
    echo "  装完再跑 ./setup.sh"
    exit 1
fi

# 2) 创建 venv(已存在就复用)
echo -e "${BOLD}[2/4]${NC} 准备 venv..."
if [ -d ".venv" ]; then
    echo -e "  ${GREEN}✓${NC} .venv 已存在,复用"
else
    "$PYTHON" -m venv .venv
    echo -e "  ${GREEN}✓${NC} 已创建 .venv"
fi

# 3) 装依赖
echo -e "${BOLD}[3/4]${NC} 安装 claw-watch + 依赖..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e . --quiet
echo -e "  ${GREEN}✓${NC} pip install -e . 完成"

# 4) 装 chromium(playwright 用)
echo -e "${BOLD}[4/4]${NC} 安装 Playwright Chromium (~150MB,首次较慢)..."
if .venv/bin/playwright install chromium; then
    echo -e "  ${GREEN}✓${NC} Chromium 已就绪"
else
    echo -e "  ${YELLOW}⚠${NC}  playwright install 失败,可以稍后手动跑:"
    echo "      .venv/bin/playwright install chromium"
fi

echo
echo -e "${GREEN}${BOLD}✓ 安装完成${NC}"
echo
echo -e "${BOLD}下一步:${NC}"
echo
echo "  1. 把 claw-watch 加到 PATH(可选,不加就用全路径):"
echo "       export PATH=\"$PROJECT_DIR/.venv/bin:\$PATH\""
echo
echo "  2. 登录需要账号的源(vidu / jimeng / liblib):"
echo "       .venv/bin/claw-watch login"
echo "     向导会依次引导你登录 3 个源,每步可跳过"
echo
echo "  3. 跑一次试试:"
echo "       .venv/bin/claw-watch check"
echo
echo "  4. (可选)配飞书推送 + 定时:见 README"
echo
