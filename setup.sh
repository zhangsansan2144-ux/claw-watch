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

# 非交互模式(CI / 管道)直接打印手动提示退出
if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "下一步:"
    echo "  export PATH=\"$PROJECT_DIR/.venv/bin:\$PATH\""
    echo "  .venv/bin/claw-watch login    # 4 步向导:vidu / jimeng / liblib / 飞书 webhook"
    echo "  .venv/bin/claw-watch check --push"
    exit 0
fi

# ─── 询问 1:加 PATH ──────────────────────────────────────────────
SHELL_NAME="$(basename "${SHELL:-zsh}")"
case "$SHELL_NAME" in
    zsh)  RC_FILE="$HOME/.zshrc" ;;
    bash) RC_FILE="$HOME/.bash_profile" ;;
    *)    RC_FILE="$HOME/.${SHELL_NAME}rc" ;;
esac
EXPORT_LINE="export PATH=\"$PROJECT_DIR/.venv/bin:\$PATH\""

if [ -f "$RC_FILE" ] && grep -Fq "$PROJECT_DIR/.venv/bin" "$RC_FILE"; then
    echo -e "${GREEN}✓${NC} PATH 已经在 $RC_FILE 里了,跳过这一步"
    PATH_ADDED=1
else
    echo -e "${BOLD}加 PATH${NC}: 把 claw-watch 加到 $RC_FILE,以后直接敲 \`claw-watch ...\`,不用全路径"
    read -r -p "  加吗? [Y/n]: " ans
    ans=${ans:-Y}
    if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        echo "" >> "$RC_FILE"
        echo "# Added by claw-watch setup.sh" >> "$RC_FILE"
        echo "$EXPORT_LINE" >> "$RC_FILE"
        echo -e "  ${GREEN}✓${NC} 已写入 $RC_FILE"
        echo -e "  ${YELLOW}↻${NC} 当前终端要让它生效:运行 \`source $RC_FILE\`(新开终端会自动生效)"
        PATH_ADDED=1
    else
        echo "  跳过。后续用 \`.venv/bin/claw-watch\` 全路径即可"
        PATH_ADDED=0
    fi
fi
echo

# ─── 询问 2:立刻进登录向导 ────────────────────────────────────────
echo -e "${BOLD}登录向导${NC}: 4 步 —— vidu / 即梦 / liblib + 飞书 webhook"
echo "  · 前 3 步会弹浏览器让你登录账号,每步可跳过"
echo "  · 第 4 步粘飞书 webhook URL,会立刻发一张测试卡片"
read -r -p "  现在开始? [Y/n]: " ans
ans=${ans:-Y}
if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo
    exec .venv/bin/claw-watch login
fi

echo
echo "随时可以手动跑:"
echo "  .venv/bin/claw-watch login          # 4 步登录向导"
echo "  .venv/bin/claw-watch check --push   # 抓取 + 推飞书"
echo "  .venv/bin/claw-watch status         # 看登录态健康"
echo
