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

CRON_LINE="0 11 * * 2,5 cd \"$PROJECT_DIR\" && .venv/bin/claw-watch check --push >> data/cron.log 2>&1"
# 用 PROJECT_DIR 作为 marker —— 它出现在 cron 行的 cd 部分,且包含完整路径,
# 不会跟同机其他 claw-watch 安装(如果未来有)冲突
CRON_MARKER="cd \"$PROJECT_DIR\""

# 非交互模式(CI / 管道)直接打印手动提示退出
if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "下一步(交互式跑 ./setup.sh 会自动引导,这里手动版):"
    echo "  .venv/bin/claw-watch login    # 4 步向导:vidu / jimeng / liblib / 飞书 webhook"
    echo "  .venv/bin/claw-watch check --push"
    echo "  装定时任务: (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
    exit 0
fi

# ─── 询问 1:登录向导 ────────────────────────────────────────────────
echo -e "${BOLD}登录向导${NC}: 4 步 —— vidu / 即梦 / liblib + 飞书 webhook"
echo "  · 前 3 步会弹浏览器让你登录账号,每步可跳过"
echo "  · 第 4 步粘飞书 webhook URL,会立刻发一张测试卡片"
read -r -p "  现在开始? [Y/n]: " ans
ans=${ans:-Y}
if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo
    .venv/bin/claw-watch login || echo -e "  ${YELLOW}⚠${NC}  向导未完成。后续可手动跑 \`.venv/bin/claw-watch login\`"
fi
echo

# ─── 询问 2:装定时任务(crontab) ────────────────────────────────
echo -e "${BOLD}定时任务${NC}: 周二 + 周五 北京时间 11:00 自动跑 + 推飞书"
if crontab -l 2>/dev/null | grep -Fq "$CRON_MARKER"; then
    echo -e "  ${GREEN}✓${NC} crontab 里已有这个 claw-watch 的任务,跳过"
else
    read -r -p "  装吗? [Y/n]: " ans
    ans=${ans:-Y}
    if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo -e "  ${GREEN}✓${NC} 已装"
        echo "    · 看任务:    crontab -l"
        echo "    · 改时间:    crontab -e   (然后改带 claw-watch 的那一行)"
        echo "    · 删任务:    crontab -e   (删那一行)"
        echo "    · 看运行日志: tail -f $PROJECT_DIR/data/cron.log"
    else
        echo "  跳过。想之后装,跑这条:"
        echo "    (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
    fi
fi

echo
echo -e "${GREEN}${BOLD}✓ 全部完成${NC}"
echo "随时手动跑:"
echo "  .venv/bin/claw-watch login          # 4 步登录向导"
echo "  .venv/bin/claw-watch check --push   # 抓取 + 推飞书"
echo "  .venv/bin/claw-watch status         # 看登录态健康"
echo
