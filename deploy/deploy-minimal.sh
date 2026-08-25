#!/usr/bin/env bash
# ============================================================
# deploy-minimal.sh — Lab Tools 极简部署（仅 Excel 工具，模式 C）
#
# 适用于：仅需要 Excel 拆分/比对工具的极简部署
# 目标主机：任意 Linux（需 Python 3.10+）
# 部署路径：/var/www/lab-tools（被 systemd 服务引用）
#
# 部署模式：C（仅 Excel 工具，禁用文档转换）
#
# 用法：
#   sudo bash ./deploy-minimal.sh                  # 全量部署
#   sudo bash ./deploy-minimal.sh -h|--help        # 查看帮助
#
# 说明：
#   - 仅部署后端代码 + systemd 服务（无前端、无 Nginx、无 OCR）
#   - 依赖 Python 3.10+，脚本不再自动安装
#   - 配置：ENABLE_DOC_CONVERT=false，DEPLOY_MODE=C
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="lab-tools"
TARGET_DIR="/var/www/${APP_NAME}"
BACKEND_DIR="${TARGET_DIR}/backend"
SERVICE_NAME="lab-tools"
SERVICE_SRC="${ROOT_DIR}/deploy/lab-tools.service"
SYSTEMD_DEST="/etc/systemd/system/lab-tools.service"
SERVICE_USER="www-data"

usage() {
    sed -n '2,25p' "$0" | sed 's/^# \?//' | sed 's/^/  /'
}
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

# ---- 修复数据目录 ----
fix_up() {
    echo ">>> [fixup] 确保数据目录存在并归 www-data 属主"
    sudo install -d -o "www-data" -g "www-data" "/var/www/lab-tools/backend/data"
}

# ---- 重启服务 ----
restart_service() {
    if [ -f "/etc/systemd/system/lab-tools.service" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable --now lab-tools 2>/dev/null || true
        sudo systemctl restart lab-tools
        echo ">>> 已重启服务 lab-tools"
    else
        echo "Warning: 服务 lab-tools.service 尚未安装，跳过重启" >&2
    fi
}

# ============================================================
#  部署后端代码（仅 minimal 依赖）
# ============================================================
deploy_backend() {
    echo ">>> [backend] 部署后端代码 (模式 C: 仅 Excel 工具)"
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Warning: 未找到 python3，跳过 backend 组件（请先安装 Python 3.10+）" >&2
        return
    fi
    sudo install -d -o "www-data" -g "www-data" "/var/www/lab-tools/backend"
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --delete --exclude '.venv/' --exclude 'data/' \
            "${ROOT_DIR}/backend/" "/var/www/lab-tools/backend/"
    else
        if [ -d "/var/www/lab-tools/backend/.venv" ]; then
            sudo mv "/var/www/lab-tools/backend/.venv" "/var/www/lab-tools/backend/.venv.bak"
        fi
        sudo cp -a "${ROOT_DIR}/backend/." "/var/www/lab-tools/backend/"
        if [ -d "/var/www/lab-tools/backend/.venv.bak" ]; then
            sudo rm -rf "/var/www/lab-tools/backend/.venv"
            sudo mv "/var/www/lab-tools/backend/.venv.bak" "/var/www/lab-tools/backend/.venv"
        fi
    fi
    if [ ! -d "/var/www/lab-tools/backend/.venv" ]; then
        sudo python3 -m venv "/var/www/lab-tools/backend/.venv"
    fi
    sudo "/var/www/lab-tools/backend/.venv/bin/pip" install --quiet --upgrade pip
    if [ -f "/var/www/lab-tools/backend/requirements-minimal.txt" ]; then
        sudo "/var/www/lab-tools/backend/.venv/bin/pip" install --quiet -r "/var/www/lab-tools/backend/requirements-minimal.txt"
    else
        sudo "/var/www/lab-tools/backend/.venv/bin/pip" install --quiet -r "/var/www/lab-tools/backend/requirements.txt"
    fi
    sudo chown -R "www-data:www-data" "/var/www/lab-tools"
    restart_service
}

restart_service() {
    if [ -f "/etc/systemd/system/lab-tools.service" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable --now lab-tools 2>/dev/null || true
        sudo systemctl restart lab-tools
        echo ">>> 已重启服务 lab-tools"
    else
        echo "Warning: 服务 lab-tools.service 尚未安装，跳过重启" >&2
    fi
}

# ============================================================
#  主流程
# ============================================================
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 检查 systemd 服务文件是否存在
if [ ! -f "${ROOT_DIR}/deploy/lab-tools.service" ]; then
    echo "Error: service file not found: ${ROOT_DIR}/deploy/lab-tools.service" >&2
    exit 1
fi

echo ">>> [minimal] 部署模式 C：仅 Excel 工具"
sudo install -m 0644 "${ROOT_DIR}/deploy/lab-tools.service" "/etc/systemd/system/lab-tools.service"
sudo systemctl daemon-reload
sudo systemctl enable --now lab-tools 2>/dev/null || true

# 部署后端（使用 requirements-minimal.txt）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_backend

echo "===== Lab Tools 极简部署完成（模式 C）====="
printf '后端代码（run.py）：%s/run.py\n' "/var/www/lab-tools/backend"
printf 'systemd 服务：      /etc/systemd/system/lab-tools.service （已重启）\n'
printf '\n验证命令：\n'
printf '  systemctl status lab-tools\n'
printf '  curl http://127.0.0.1:8000/api/health\n'
printf '=====================================\n'