#!/usr/bin/env bash
# claw-watch 一键安装脚本(macOS)
# 用法: ./setup.sh [--allow-protected]
# 安全可重入:venv 已存在会复用,不会破坏已有登录态

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# 解析 flag
ALLOW_PROTECTED=0
for arg in "$@"; do
    case "$arg" in
        --allow-protected) ALLOW_PROTECTED=1 ;;
        -h|--help)
            echo "用法: ./setup.sh [--allow-protected]"
            echo "  --allow-protected   跳过 ~/Desktop|Documents|Downloads 的位置检查"
            echo "                       (cron 默认无权读这些目录,定时会静默失败 — 知道风险才用)"
            exit 0 ;;
    esac
done

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# ─── 受保护目录检查 ────────────────────────────────────────────────
# macOS 默认不让 cron 读 ~/Desktop / ~/Documents / ~/Downloads,
# 装在这些位置定时任务会静默失败(没报错,没通知,只是不跑)。
# 写在最前面,fail fast。
case "$PROJECT_DIR" in
    "$HOME/Desktop"|"$HOME/Desktop"/*|\
    "$HOME/Documents"|"$HOME/Documents"/*|\
    "$HOME/Downloads"|"$HOME/Downloads"/*)
        if [ "$ALLOW_PROTECTED" -ne 1 ]; then
            BASENAME="$(basename "$PROJECT_DIR")"
            echo
            echo -e "${RED}${BOLD}✗ 项目在 macOS 受保护目录${NC}"
            echo
            echo "   当前位置: $PROJECT_DIR"
            echo
            echo "   问题: cron 默认无权读写 ~/Desktop / ~/Documents / ~/Downloads,"
            echo -e "         定时任务会${RED}静默失败${NC}(没报错也没通知,只是周二/周五啥都不跑)。"
            echo
            echo "   建议挪到非保护目录,例如直接放 \$HOME 下:"
            echo
            echo -e "     ${BOLD}cd .. && mv \"$BASENAME\" \"$HOME/$BASENAME\" && cd \"$HOME/$BASENAME\" && ./setup.sh${NC}"
            echo
            echo "   如果你确认不打算用 cron(只手动跑),可以跳过这个检查:"
            echo "     ./setup.sh --allow-protected"
            echo
            exit 1
        else
            echo -e "${YELLOW}⚠${NC}  在受保护目录但用 --allow-protected 跳过了检查;cron 装上后大概率不会跑"
        fi
        ;;
esac

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

mkdir -p data auth

CRON_LINE="0 11 * * 2,5 cd \"$PROJECT_DIR\" && .venv/bin/claw-watch check --push >> data/cron.log 2>&1"
# 用 PROJECT_DIR 作为 marker —— 它出现在 cron 行的 cd 部分,且包含完整路径,
# 不会跟同机其他 claw-watch 安装(如果未来有)冲突
CRON_MARKER="cd \"$PROJECT_DIR\""
LOGIN_STATUS="跳过"
CRON_STATUS="跳过"
FIRST_RUN_STATUS="跳过"

print_cron_fix_help() {
    local err="$1"

    if [ -n "$err" ]; then
        echo "    系统返回: $err"
    fi

    case "$err" in
        *"Operation not permitted"*|*"operation not permitted"*|*"Permission denied"*|*"permission denied"*)
            echo "    处理办法:"
            echo "      1) 打开 系统设置 → 隐私与安全性 → 完全磁盘访问权限"
            echo "      2) 给你正在用的 Terminal/iTerm 打开权限"
            echo "      3) 完全退出终端,重新打开,再回到这里重试"
            ;;
        *"bad minute"*|*"errors in crontab file"*|*"installing new crontab"*)
            echo "    处理办法:"
            echo "      1) 跑 crontab -e"
            echo "      2) 删除明显不完整/乱码/中文提示那几行"
            echo "      3) 保存退出后回到这里重试"
            ;;
        "")
            echo "    没拿到系统错误详情。通常重试一次即可;如果还失败,先跑 crontab -l 看是否正常。"
            ;;
        *)
            echo "    处理办法:"
            echo "      1) 先跑 crontab -l 看当前定时任务是否能正常读取"
            echo "      2) 如果有权限报错,按系统设置里的隐私权限处理"
            echo "      3) 如果有格式报错,跑 crontab -e 修掉坏行后重试"
            ;;
    esac
}

install_cron_with_guidance() {
    local err_file err ans

    while true; do
        EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
        err_file="$(mktemp -t claw-watch-cron.XXXXXX)"

        if (printf '%s\n' "$EXISTING_CRON"; echo "$CRON_LINE") | crontab - 2>"$err_file"; then
            rm -f "$err_file"
            if crontab -l 2>/dev/null | grep -Fq "$CRON_MARKER"; then
                echo -e "  ${GREEN}✓${NC} 已装"
                CRON_STATUS="已安装"
                echo "    · 看任务:    crontab -l"
                echo "    · 改时间:    crontab -e   (然后改带 claw-watch 的那一行)"
                echo "    · 删任务:    crontab -e   (删那一行)"
                echo "    · 看运行日志: tail -f $PROJECT_DIR/data/cron.log"
                return 0
            fi

            echo -e "  ${YELLOW}⚠${NC}  crontab 命令返回成功,但没查到任务。请重试一次。"
        else
            err="$(tr '\n' ' ' < "$err_file" | sed 's/[[:space:]]*$//')"
            rm -f "$err_file"
            echo -e "  ${YELLOW}⚠${NC}  crontab 写入失败,定时任务还没装上"
            print_cron_fix_help "$err"
        fi

        echo
        echo "    这一步只影响自动定时;登录和首次手动验证仍然可以继续。"
        read -r -p "    处理好后按 r 重试; 暂时不装按 s 跳过; 退出按 q: " ans
        ans=${ans:-r}
        case "$ans" in
            r|R|retry|Retry)
                echo "    好,重试安装定时任务..."
                ;;
            s|S|skip|Skip)
                CRON_STATUS="安装失败"
                echo "  已跳过定时任务。后面会继续做首次手动验证。"
                return 1
                ;;
            q|Q|quit|Quit|exit|Exit)
                CRON_STATUS="安装失败"
                echo "  已退出安装。后续可重新跑 ./setup.sh 继续。"
                exit 1
                ;;
            *)
                echo "    无效输入,默认重试。"
                ;;
        esac
    done
}

# 非交互模式(CI / 管道)直接打印手动提示退出
if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "下一步(交互式跑 ./setup.sh 会自动引导,这里手动版):"
    echo "  .venv/bin/claw-watch login    # 3 步向导:jimeng / liblib / 飞书 webhook"
    echo "  .venv/bin/claw-watch check --push"
    echo "  装定时任务: (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
    exit 0
fi

# ─── 询问 1:登录向导 ────────────────────────────────────────────────
echo -e "${BOLD}登录向导${NC}: 3 步 —— 即梦 / liblib + 飞书 webhook"
echo "  · 前 2 步会弹浏览器让你登录账号,每步可跳过"
echo "  · 第 3 步粘飞书 webhook URL,会立刻发一张测试卡片"
read -r -p "  现在开始? [Y/n]: " ans
ans=${ans:-Y}
if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo
    if .venv/bin/claw-watch login; then
        LOGIN_STATUS="完成"
    else
        LOGIN_STATUS="未完成"
        echo -e "  ${YELLOW}⚠${NC}  向导未完成。后续可手动跑 \`.venv/bin/claw-watch login\`"
    fi
fi
echo

# ─── 询问 2:装定时任务(crontab) ────────────────────────────────
echo -e "${BOLD}定时任务${NC}: 周二 + 周五 北京时间 11:00 自动跑 + 推飞书"
EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$EXISTING_CRON" | grep -Fq "$CRON_MARKER"; then
    echo -e "  ${GREEN}✓${NC} crontab 里已有这个 claw-watch 的任务,跳过"
    CRON_STATUS="已存在"
else
    read -r -p "  装吗? [Y/n]: " ans
    ans=${ans:-Y}
    if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        install_cron_with_guidance || true
    else
        CRON_STATUS="跳过"
        echo "  跳过。想之后装,跑这条:"
        echo "    (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
    fi
fi

echo

# ─── 询问 3:立刻手动跑一次 ─────────────────────────────────────────
echo -e "${BOLD}首次手动跑一次?${NC}"
echo "  作用:① 端到端验证(看一眼飞书群是否收到卡片)"
echo "        ② 触发 macOS 任何权限弹窗(Chrome 控制 / 自动化 等),你点'允许'"
echo "        ③ 给所有源建立第一份快照(下一次跑才能 diff 出新增)"
read -r -p "  跑吗?[Y/n]: " ans
ans=${ans:-Y}
if [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo
    if .venv/bin/claw-watch check --push; then
        FIRST_RUN_STATUS="完成"
    else
        FIRST_RUN_STATUS="有失败"
        echo -e "  ${YELLOW}⚠${NC}  抓取过程有失败,看上面输出排查"
    fi
fi

echo
echo -e "${GREEN}${BOLD}✓ 安装流程结束${NC}"
echo "结果:"
echo "  · 登录向导: $LOGIN_STATUS"
echo "  · 定时任务: $CRON_STATUS"
echo "  · 首次验证: $FIRST_RUN_STATUS"
echo
if [ "$CRON_STATUS" = "安装失败" ]; then
    echo -e "${YELLOW}下一步:${NC} 定时任务没装上,但你已经可以手动跑。想开启自动定时,稍后重试:"
    echo "  (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
    echo
fi
echo "随时手动跑:"
echo "  .venv/bin/claw-watch login          # 3 步登录向导"
echo "  .venv/bin/claw-watch check --push   # 抓取 + 推飞书"
echo "  .venv/bin/claw-watch status         # 看登录态健康"
echo
