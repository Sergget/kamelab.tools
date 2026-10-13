#!/usr/bin/env bash
# ============================================================
# deploy-sugon.sh — Lab Tools（sugon 龙芯 mips64el）部署脚本
#
# 适用于：龙架构（mips64el）服务器，如 LoongArch / 龙芯 3A/3C 系列
#
# sugan 环境特殊之处：
#   - 无 paddleocr / rapidocr 本地 OCR 引擎（缺无对应 wheel）
#   - PDF 能力由系统包 poppler-utils 提供（pdftotext / pdftoppm / pdfinfo）
#   - numpy / pandas / pydantic-core 等需源码编译，依赖 GCC >= 8.4
#   - 文档转换走外部 OCR 节点（模式 A）：DEPLOY_MODE=A + OCR_NODE_URL
#
# 用法：
#   sudo bash ./deploy-sugon.sh            # 全量部署
#   sudo bash ./deploy-sugon.sh backend    # 仅后端
#   sudo bash ./deploy-sugon.sh service    # 仅 systemd 单元
#   sudo bash ./deploy-sugon.sh service nginx # 组合
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="lab-tools"
TARGET_DIR="/var/www/${APP_NAME}"
BACKEND_DIR="${TARGET_DIR}/backend"
STATIC_DIR="${BACKEND_DIR}/app/static"
SERVICE_NAME="${APP_NAME}"
SERVICE_SRC="${ROOT_DIR}/deploy/lab-tools-sugon.service"
NGINX_CONF_SRC="${ROOT_DIR}/deploy/lab-tools.conf"
SYSTEMD_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_AVAILABLE="/etc/nginx/sites-available/${SERVICE_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${SERVICE_NAME}"
SERVICE_USER="www-data"

# ---- 帮助 ----
usage() {
    sed -n '2,28p' "$0" | sed 's/^# \?//' | sed 's/^/  /'
}
[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { usage; exit 0; }

# ---- 解析组件 ----
KNOWN_PARTS="backend service nginx all"
declare -A PARTS
if [ "$#" -eq 0 ]; then
    PARTS[all]=1
else
    for p in "$@"; do
        case " $KNOWN_PARTS " in
            *" $p "*) PARTS["$p"]=1 ;;
            *) echo "Error: unknown component '$p'" >&2; exit 1 ;;
        esac
    done
fi
need() { [ -n "${PARTS[all]:-}" ] || [ -n "${PARTS[$1]:-}" ]; }

# ---- 修复数据目录 ----
fix_up() {
    echo ">>> [fixup] 确保数据目录存在并归 ${SERVICE_USER} 属主"
    sudo install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${BACKEND_DIR}/data"
}

# ---- 重启服务 ----
restart_service() {
    fix_up
    if [ -f "${SYSTEMD_DEST}" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable --now "$SERVICE_NAME" 2>/dev/null || true
        sudo systemctl restart "$SERVICE_NAME"
        echo ">>> 已重启服务 ${SERVICE_NAME}"
    else
        echo "Warning: 服务 ${SERVICE_NAME}.service 尚未安装，跳过重启" >&2
    fi
}

# ============================================================
#  组件 1：后端代码（sugon 版）
# ============================================================
deploy_backend() {
    echo ">>> [backend] 部署后端代码到 ${BACKEND_DIR}"

    if ! command -v python3 >/dev/null 2>&1; then
        echo "Warning: 未找到 python3，跳过 backend 组件（请先安装 Python 3.10+）" >&2
        return
    fi

    # 安装 poppler-utils（PDF 提取与渲染，mips64el 系统包提供）
    if command -v apt-get >/dev/null 2>&1; then
        echo ">>> [backend] 安装 poppler-utils..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq poppler-utils || true
    fi

    # 同步代码
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --delete --exclude '.venv/' --exclude 'data/' \
            "${ROOT_DIR}/backend/" "${BACKEND_DIR}/"
    else
        if [ -d "${BACKEND_DIR}/.venv" ]; then
            sudo mv "${BACKEND_DIR}/.venv" "${BACKEND_DIR}/.venv.bak"
        fi
        sudo cp -a "${ROOT_DIR}/backend/." "${BACKEND_DIR}/"
        if [ -d "${BACKEND_DIR}/.venv.bak" ]; then
            sudo rm -rf "${BACKEND_DIR}/.venv"
            sudo mv "${BACKEND_DIR}/.venv.bak" "${BACKEND_DIR}/.venv"
        fi
    fi

    # 虚拟环境
    if [ ! -d "${BACKEND_DIR}/.venv" ]; then
        sudo python3 -m venv "${BACKEND_DIR}/.venv"
    fi

    # sugon 专用：导出 GCC 路径以支持 numpy / pandas / pydantic-core 源码编译
    # 龙芯系统通常将高版本 GCC 安装在 /opt/gcc12 或 /usr/local/gcc/bin
    export CC=gcc
    export CXX=g++
    # 优先使用 /opt/gcc12（如存在）
    if [ -d "/opt/gcc12/bin" ]; then
        export PATH="/opt/gcc12/bin:${PATH}"
        export CC=/opt/gcc12/bin/gcc
        export CXX=/opt/gcc12/bin/g++
    fi

    # 安装 sugon 专用依赖（requirements-sugon.txt）
    sudo "${BACKEND_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    sudo "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r "${BACKEND_DIR}/requirements-sugon.txt"

    sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET_DIR}"
    restart_service
}

# ============================================================
#  组件 2：Systemd 服务单元
# ============================================================
deploy_service() {
    echo ">>> [service] 安装 sugon 专用 systemd 服务单元"
    if [ -f "${SERVICE_SRC}" ]; then
        sudo install -m 0644 "${SERVICE_SRC}" "${SYSTEMD_DEST}"
    else
        echo "Warning: service file not found: ${SERVICE_SRC}" >&2
    fi
    restart_service
}

# ============================================================
#  组件 3：Nginx 反向代理
# ============================================================
deploy_nginx() {
    echo ">>> [nginx] 安装 Nginx 反向代理配置"
    if [ -f "${NGINX_CONF_SRC}" ]; then
        sudo install -m 0644 "${NGINX_CONF_SRC}" "${NGINX_AVAILABLE}"
        sudo ln -sf "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
        if command -v nginx >/dev/null 2>&1; then
            sudo nginx -t >/dev/null 2>&1 || true
            if systemctl list-unit-files 2>/dev/null | grep -q '^nginx.service'; then
                sudo systemctl reload nginx 2>/dev/null || sudo systemctl restart nginx 2>/dev/null || true
            fi
        fi
    else
        echo "Warning: nginx config not found: ${NGINX_CONF_SRC}" >&2
    fi
}

# ============================================================
#  按需执行
# ============================================================
if need backend; then
    deploy_backend
fi
if need service; then
    deploy_service
fi
if need nginx; then
    deploy_nginx
fi

# ============================================================
#  部署摘要
# ============================================================
printf '===== Lab Tools sugon 部署完成 =====\n'
printf '部署目标：sugon (mips64el)\n'
printf '后端代码：%s\n' "${BACKEND_DIR}/run.py"
printf '依赖文件：%s\n' "${BACKEND_DIR}/requirements-sugon.txt"
printf 'OCR 模式：远程节点 (DEPLOY_MODE=A)\n'
printf 'systemd 服务：%s\n' "${SYSTEMD_DEST}"
printf '验证命令：\n'
printf '  systemctl status %s\n' "${SERVICE_NAME}"
printf '  curl http://127.0.0.1:8000/api/health\n'
printf '=====================================\n'
