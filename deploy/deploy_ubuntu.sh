#!/usr/bin/env bash
# ============================================================
# deploy_ubuntu.sh — Lab Tools（Ubuntu）「可选组件」部署脚本
#
# 部署组件（可单独或组合指定，不传参数时默认全部 all）：
#   backend    部署后端代码 + 安装 Python 依赖
#   frontend   构建前端并放置静态产物
#   service    安装 systemd 服务单元 lab-tools.service（自动重启服务）
#   all        以上全部
#
# 选项（部署时可覆盖服务配置）：
#   --tools <id1,id2>   仅启用指定工具（如 doc-convert,excel-split；缺省=全部）
#   --ocr-url <URL>     Windows OCR 节点地址（如 http://192.168.0.81:8101）
#   --ocr-name <名称>   OCR 节点名称（缺省 win11）
#   --ocr-role <角色>   OCR 节点角色（缺省 heavy）
#   --node-name <名称>  本节点名称（缺省服务器主机名）
#   --node-role <角色>  本节点角色（缺省 main）
#   --port <端口>       监听端口（缺省 8000）
#
# 用法：
#   sudo bash ./deploy_ubuntu.sh                          # 全量部署
#   sudo bash ./deploy_ubuntu.sh backend                  # 只更新后端代码并重启
#   sudo bash ./deploy_ubuntu.sh frontend                 # 只构建部署前端
#   sudo bash ./deploy_ubuntu.sh service --port 9000      # 只改服务端口
#   sudo bash ./deploy_ubuntu.sh all --tools doc-convert \
#       --ocr-url http://192.168.0.81:8101 --ocr-name win11 --ocr-role heavy
#   sudo bash ./deploy_ubuntu.sh -h|--help                # 查看本帮助
#
# 说明：
#   - backend / service 组件部署完成后会自动重启服务，使改动立即生效；
#   - frontend 为静态产物，放置后由 FastAPI 直接托管，无需重启；
#   - --tools / --ocr-* / --node-* / --port 会写入 systemd 单元，
#     仅当 service 或 backend 组件被部署（或服务已安装）时才会生效。
# ============================================================
set -euo pipefail

APP_NAME="lab-tools"
APP_DIR="/opt/${APP_NAME}"
SERVICE_USER="labtools"
SERVICE_UNIT="/etc/systemd/system/${APP_NAME}.service"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- 默认参数 ----
PORT="${LAB_TOOLS_PORT:-8000}"
TOOLS="${LAB_TOOLS_ENABLED:-}"
OCR_URL="${LAB_TOOLS_OCR_NODE_URL:-http://127.0.0.1:8001}"
OCR_NAME="${LAB_TOOLS_OCR_NODE_NAME:-win11}"
OCR_ROLE="${LAB_TOOLS_OCR_NODE_ROLE:-heavy}"
NODE_NAME_VAL="${LAB_TOOLS_NODE_NAME:-}"
NODE_ROLE_VAL="${LAB_TOOLS_NODE_ROLE:-main}"

KNOWN_PARTS="backend frontend service all"
PARTS=""
CONFIG_CHANGED=0

usage() {
    sed -n '3,30p' "$0" | sed 's/^# \?//' | sed 's/^/  /'
}

need() {
    echo " ${PARTS} " | grep -qE " all | $1 "
}

opt_used() {
    CONFIG_CHANGED=1
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help) usage; exit 0 ;;
            --tools) TOOLS="${2:-}"; opt_used; shift 2 ;;
            --ocr-url) OCR_URL="${2:-}"; opt_used; shift 2 ;;
            --ocr-name) OCR_NAME="${2:-}"; opt_used; shift 2 ;;
            --ocr-role) OCR_ROLE="${2:-}"; opt_used; shift 2 ;;
            --node-name) NODE_NAME_VAL="${2:-}"; opt_used; shift 2 ;;
            --node-role) NODE_ROLE_VAL="${2:-}"; opt_used; shift 2 ;;
            --port) PORT="${2:-}"; opt_used; shift 2 ;;
            all|backend|frontend|service) PARTS="${PARTS} ${1}"; shift ;;
            *)
                echo "Error: unknown argument '$1'" >&2
                echo "Usage: $0 [backend] [frontend] [service] [all] [options...]" >&2
                exit 1
                ;;
        esac
    done
    [ -n "${PARTS}" ] || PARTS="all"
}

service_installed() {
    systemctl list-unit-files 2>/dev/null | grep -q "^${APP_NAME}.service"
}

restart_service() {
    if service_installed; then
        systemctl daemon-reload
        systemctl enable --now "${APP_NAME}" 2>/dev/null || true
        systemctl restart "${APP_NAME}"
        echo ">>> 已重启服务 ${APP_NAME}"
    else
        echo "Warning: 服务 ${APP_NAME}.service 尚未安装，跳过重启" >&2
    fi
}

# ---- 生成 systemd 单元（按本次参数替换环境变量） ----
build_service_unit() {
    local tmp
    tmp="$(mktemp)"
    sed "s/^Environment=LAB_TOOLS_PORT=.*/Environment=LAB_TOOLS_PORT=${PORT}/" \
        "${SRC_DIR}/deploy/lab-tools.service" > "${tmp}"
    sed -i "s|^Environment=LAB_TOOLS_OCR_NODE_URL=.*|Environment=LAB_TOOLS_OCR_NODE_URL=${OCR_URL}|" "${tmp}"
    sed -i "s/^Environment=LAB_TOOLS_OCR_NODE_NAME=.*/Environment=LAB_TOOLS_OCR_NODE_NAME=${OCR_NAME}/" "${tmp}"
    sed -i "s/^Environment=LAB_TOOLS_OCR_NODE_ROLE=.*/Environment=LAB_TOOLS_OCR_NODE_ROLE=${OCR_ROLE}/" "${tmp}"
    sed -i "s/^Environment=LAB_TOOLS_NODE_ROLE=.*/Environment=LAB_TOOLS_NODE_ROLE=${NODE_ROLE_VAL}/" "${tmp}"
    if [ -n "${NODE_NAME_VAL}" ]; then
        sed -i "s/^Environment=LAB_TOOLS_NODE_NAME=.*/Environment=LAB_TOOLS_NODE_NAME=${NODE_NAME_VAL}/" "${tmp}"
    fi
    sed -i "s/^Environment=LAB_TOOLS_ENABLED=.*/Environment=LAB_TOOLS_ENABLED=${TOOLS}/" "${tmp}"
    cat "${tmp}"
    rm -f "${tmp}"
}

# ============================================================
#  组件 1：backend
# ============================================================
deploy_backend() {
    echo ">>> [backend] 部署后端代码 + 安装依赖"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || true
    apt-get install -y -qq curl ca-certificates python3 python3-venv python3-pip rsync >/dev/null 2>&1 || true

    id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
    mkdir -p "${APP_DIR}/backend/data"
    rsync -a --delete "${SRC_DIR}/backend/" "${APP_DIR}/backend/" 2>/dev/null || cp -r "${SRC_DIR}/backend/." "${APP_DIR}/backend/"

    if [ ! -d "${APP_DIR}/backend/.venv" ]; then
        python3 -m venv "${APP_DIR}/backend/.venv"
    fi
    "${APP_DIR}/backend/.venv/bin/pip" install --quiet --upgrade pip
    "${APP_DIR}/backend/.venv/bin/pip" install --quiet -r "${APP_DIR}/backend/requirements.txt"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
    restart_service
}

# ============================================================
#  组件 2：frontend
# ============================================================
deploy_frontend() {
    if [ ! -d "${SRC_DIR}/frontend" ]; then
        echo "Warning: 未找到 frontend 目录，跳过前端构建" >&2
        return
    fi
    echo ">>> [frontend] 构建前端并放置静态产物"
    export DEBIAN_FRONTEND=noninteractive
    if ! command -v node >/dev/null 2>&1 || [ "$(node --version | sed 's/v\([0-9]*\).*/\1/')" -lt 20 ]; then
        echo "==> 安装 Node.js 20（用于构建前端）"
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1 || true
        apt-get install -y -qq nodejs >/dev/null 2>&1 || true
    fi

    FRONTEND_DIR="$(mktemp -d)"
    cp -r "${SRC_DIR}/frontend/." "${FRONTEND_DIR}/"
    (cd "${FRONTEND_DIR}" && npm install --no-fund --no-audit >/dev/null 2>&1 && npm run build)
    rm -rf "${APP_DIR}/backend/app/static"
    cp -r "${FRONTEND_DIR}/dist" "${APP_DIR}/backend/app/static"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/backend"
    rm -rf "${FRONTEND_DIR}"
}

# ============================================================
#  组件 3：service
# ============================================================
deploy_service() {
    echo ">>> [service] 安装 systemd 服务单元"
    build_service_unit > "${SERVICE_UNIT}"
    restart_service
}

# ============================================================
#  主流程
# ============================================================
parse_args "$@"

echo "===== Lab Tools Ubuntu 部署 ====="
echo "本机: ${HOSTNAME} 端口: ${PORT}"
echo "OCR 节点: ${OCR_NAME}(${OCR_ROLE}) -> ${OCR_URL}"
[ -n "${TOOLS}" ] && echo "启用工具: ${TOOLS}" || echo "启用工具: 全部"
echo "部署组件:${PARTS}"
echo "================================"

if need backend; then deploy_backend; fi
if need frontend; then deploy_frontend; fi
if need service; then deploy_service; fi

# 仅部署 frontend 时若服务已安装，把配置参数写入单元并重启
if ! need service && ! need backend && service_installed && [ "${CONFIG_CHANGED}" = "1" ]; then
    echo ">>> 检测到配置参数变化，重新写入 systemd 单元并重启"
    build_service_unit > "${SERVICE_UNIT}"
    restart_service
fi

printf '\n===== Lab Tools Ubuntu 部署完成 =====\n'
printf '部署组件：%s\n' "${PARTS}"
printf '后端代码：%s\n' "${APP_DIR}/backend"
printf '前端页面：%s/app/static\n' "${APP_DIR}/backend"
printf 'systemd 服务：%s（已重启）\n' "${SERVICE_UNIT}"
printf '\n验证命令：\n'
printf '  systemctl status %s\n' "${APP_NAME}"
printf '  curl http://127.0.0.1:%s/api/health\n' "${PORT}"
printf '  curl http://127.0.0.1:%s/api/tools\n' "${PORT}"
printf '=====================================\n'