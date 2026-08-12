#!/usr/bin/env bash
# ============================================================
# deploy_ubuntu.sh — Lab Tools（Ubuntu）「可选组件」部署脚本
#
# 适用于：自托管办公文件处理工具箱的单台 Ubuntu Server 部署
# 目标主机：J3455（4GB 内存，Ubuntu Server 20.04，预装 Node 20+ / Python 3.10+）
# 部署路径：/var/www/lab-tools（被 systemd 服务与 Nginx 反代引用）
#
# 部署组件（可单独或组合指定，不传参数时默认部署全部 all）：
#   backend   后端代码（backend/ 下所有内容：run.py、app/、requirements.txt 等）
#             自动创建 .venv 并安装依赖，部署完成后重启服务
#   frontend  前端静态产物（frontend/ 构建后放置到 backend/app/static/）
#   service   systemd 服务单元 lab-tools.service（部署后会自动重启服务）
#   nginx     Nginx 反向代理配置 lab-tools.conf
#   all       以上全部
#
# 用法：
#   sudo bash ./deploy_ubuntu.sh                  # 全量部署（等价于 ./deploy_ubuntu.sh all）
#   sudo bash ./deploy_ubuntu.sh backend          # 只更新后端代码并重启服务（改后端时最常用）
#   sudo bash ./deploy_ubuntu.sh frontend         # 只更新前端页面（静态产物无需重启服务）
#   sudo bash ./deploy_ubuntu.sh service          # 只更新 systemd 单元并重启服务
#   sudo bash ./deploy_ubuntu.sh nginx            # 只更新 Nginx 配置并 reload
#   sudo bash ./deploy_ubuntu.sh backend frontend # 组合：同时更新后端 + 前端
#   sudo bash ./deploy_ubuntu.sh -h|--help        # 查看本帮助
#
# 示例：
#   # 修改了后端代码（或 requirements.txt）后，只部署后端并重启：
#   sudo bash ./deploy_ubuntu.sh backend
#   # 修改了前端代码后，重新构建并放置静态产物：
#   sudo bash ./deploy_ubuntu.sh frontend
#   # 修改了部署配置（lab-tools.service / lab-tools.conf）后：
#   sudo bash ./deploy_ubuntu.sh service nginx
#
# 说明：
#   - 本脚本不安装 Node / Python，服务器需预装 Node 20+ 与 Python 3.10+；
#     依赖缺失时仅打印警告并跳过对应组件，不会中断部署。
#   - backend / service 组件部署完成后会自动 restart 服务，使改动立即生效；
#   - frontend / nginx 组件为静态产物/代理配置，不影响运行中的进程，不触发重启；
#   - 配置（OCR 节点地址、端口、工具开关等）直接编辑 deploy/lab-tools.service；
#     域名与 SSL 证书见 deploy/lab-tools.conf，部署后按需修改。
#   - nginx 的 lab-tools.conf 若不存在，仅打印警告，不中断部署。
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="lab-tools"
TARGET_DIR="/var/www/${APP_NAME}"           # 部署目标根目录（systemd 与 nginx 均引用此路径）
BACKEND_DIR="${TARGET_DIR}/backend"         # 后端代码目录（run.py / app/ / .venv / data）
STATIC_DIR="${BACKEND_DIR}/app/static"      # 前端静态产物目录（FastAPI 直接托管）
SERVICE_NAME="${APP_NAME}"                  # systemd 服务名，与 lab-tools.service 的 [Unit] 对应
SERVICE_SRC="${ROOT_DIR}/deploy/lab-tools.service"
NGINX_CONF_SRC="${ROOT_DIR}/deploy/lab-tools.conf"
SYSTEMD_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_AVAILABLE="/etc/nginx/sites-available/${SERVICE_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${SERVICE_NAME}"
SERVICE_USER="www-data"

KNOWN_PARTS="backend frontend service nginx all"
PART_COUNT="$#"

# ---- 帮助 / 用法 ----
usage() {
    sed -n '2,42p' "$0" | sed 's/^# \?//' | sed 's/^/  /'
}
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

# ---- 解析要部署的组件 ----
# 不传参数 = all；传了参数则只部署列出的组件（重复项自动忽略）
declare -A PARTS
if [ "$PART_COUNT" -eq 0 ]; then
    PARTS[all]=1
else
    for p in "$@"; do
        case " $KNOWN_PARTS " in
            *" $p "*) PARTS["$p"]=1 ;;
            *)
                echo "Error: unknown component '$p'" >&2
                echo "Usage: $0 [backend] [frontend] [service] [nginx] [all]" >&2
                exit 1
                ;;
        esac
    done
fi

# need <name>：判断某组件是否需要部署（all 模式下全部为真）
need() { [ -n "${PARTS[all]:-}" ] || [ -n "${PARTS[$1]:-}" ]; }

# ---- 重启服务（backend / service 部署后调用，使改动生效）----
restart_service() {
    if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
        sudo systemctl daemon-reload
        sudo systemctl enable --now "$SERVICE_NAME" 2>/dev/null || true
        sudo systemctl restart "$SERVICE_NAME"
        echo ">>> 已重启服务 ${SERVICE_NAME}"
    else
        echo "Warning: 服务 ${SERVICE_NAME}.service 尚未安装，跳过重启" >&2
    fi
}

# ============================================================
#  组件 1：后端代码（backend/）
# ============================================================
deploy_backend() {
    echo ">>> [backend] 部署后端代码 backend/ -> ${BACKEND_DIR}"
    # 依赖检查：需要 python3（脚本不再自动安装，缺失时仅警告并跳过）
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Warning: 未找到 python3，跳过 backend 组件（请先安装 Python 3.10+）" >&2
        return
    fi
    # install -d 同时设置 www-data 属主，确保 run.py 运行时对目录有写权限
    # （www-data 也是 lab-tools.service 的 User 字段指定的用户）
    sudo install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${BACKEND_DIR}"
    # 同步 backend/ 下所有内容（run.py、app/、requirements.txt 等）
    # 排除 .venv（虚拟环境由脚本管理）与 data/（运行数据，避免被 --delete 清除）
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --delete --exclude '.venv/' --exclude 'data/' \
            "${ROOT_DIR}/backend/" "${BACKEND_DIR}/"
    else
        # 无 rsync 时用 cp 兜底：先移开服务器端 .venv，同步后再恢复，
        # 避免仓库中的开发机 .venv 覆盖服务器端已安装的虚拟环境
        if [ -d "${BACKEND_DIR}/.venv" ]; then
            sudo mv "${BACKEND_DIR}/.venv" "${BACKEND_DIR}/.venv.bak"
        fi
        sudo cp -a "${ROOT_DIR}/backend/." "${BACKEND_DIR}/"
        if [ -d "${BACKEND_DIR}/.venv.bak" ]; then
            sudo rm -rf "${BACKEND_DIR}/.venv"
            sudo mv "${BACKEND_DIR}/.venv.bak" "${BACKEND_DIR}/.venv"
        fi
    fi
    # 虚拟环境不存在时创建（已存在则复用，加快增量部署）
    if [ ! -d "${BACKEND_DIR}/.venv" ]; then
        sudo python3 -m venv "${BACKEND_DIR}/.venv"
    fi
    # 安装/更新 Python 依赖（pip 安装保留：依赖仍然需要安装）
    sudo "${BACKEND_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    sudo "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r "${BACKEND_DIR}/requirements.txt"
    # 统一归 www-data，保证服务进程可读写 data 目录
    sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET_DIR}"
    # 代码更新后必须重启服务，否则运行中的进程仍是旧代码
    restart_service
}

# ============================================================
#  组件 2：前端静态产物（frontend/）
# ============================================================
deploy_frontend() {
    echo ">>> [frontend] 构建前端并放置静态产物"
    # 依赖检查：需要 node + npm（脚本不再自动安装，缺失时仅警告并跳过）
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "Warning: 未找到 node 或 npm，跳过 frontend 组件（请先安装 Node 20+）" >&2
        return
    fi
    if [ ! -d "${ROOT_DIR}/frontend" ]; then
        echo "Warning: 未找到 frontend 目录，跳过前端构建" >&2
        return
    fi
    # 在临时目录构建，避免污染仓库（node_modules / dist）
    FRONTEND_TMP="$(mktemp -d)"
    cp -r "${ROOT_DIR}/frontend/." "${FRONTEND_TMP}/"
    (
        cd "${FRONTEND_TMP}"
        npm install --no-fund --no-audit >/dev/null 2>&1
        npm run build
    )
    # 先删旧产物再放置新产物（FastAPI 单进程托管静态文件，目录结构需干净）
    sudo rm -rf "${STATIC_DIR}"
    sudo install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "$(dirname "${STATIC_DIR}")"
    sudo cp -r "${FRONTEND_TMP}/dist" "${STATIC_DIR}"
    sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATIC_DIR}"
    rm -rf "${FRONTEND_TMP}"
    # 前端为静态文件，由 FastAPI 每次请求读取，无需重启服务
}

# ============================================================
#  组件 3：systemd 服务单元
# ============================================================
deploy_service() {
    echo ">>> [service] 安装 systemd 服务单元"
    # lab-tools.service 定义了 User/WorkingDirectory/Environment 等配置
    # （OCR 节点地址、端口、工具开关等），配置修改后重跑本组件即可生效
    if [ -f "${SERVICE_SRC}" ]; then
        sudo install -m 0644 "${SERVICE_SRC}" "${SYSTEMD_DEST}"
    else
        echo "Warning: service file not found: ${SERVICE_SRC}" >&2
    fi
    # 单元文件变化后必须 daemon-reload，再重启服务生效
    restart_service
}
# --- 修复数据目录权限问题（部署完成后统一创建 data 目录并设置属主） ---
fix_up() {
    echo ">>> [fixup] 确保数据目录存在并归 ${SERVICE_USER} 属主"
    sudo install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${BACKEND_DIR}/data"
}

# ============================================================
#  组件 4：Nginx 反向代理配置
# ============================================================
deploy_nginx() {
    echo ">>> [nginx] 安装 Nginx 反向代理配置"
    # lab-tools.conf 将 lab.sergget.qzz.io 的 HTTPS 流量代理到 127.0.0.1:8000
    # （后端监听的内部端口，由 lab-tools.service 的 LAB_TOOLS_PORT 环境变量决定）
    # SSL 证书位于 /etc/nginx/snippets/ssl-sergget.conf（需独立维护）
    if [ -f "${NGINX_CONF_SRC}" ]; then
        sudo install -m 0644 "${NGINX_CONF_SRC}" "${NGINX_AVAILABLE}"
        sudo ln -sf "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
        if command -v nginx >/dev/null 2>&1; then
            # 验证配置语法，失败不中断后续流程
            sudo nginx -t >/dev/null 2>&1 || true
            # 优先 reload（不中断现有连接），失败时 fallback 到 restart
            if systemctl list-unit-files 2>/dev/null | grep -q '^nginx.service'; then
                sudo systemctl reload nginx 2>/dev/null || sudo systemctl restart nginx 2>/dev/null || true
            fi
        fi
    else
        echo "Warning: nginx config not found: ${NGINX_CONF_SRC}" >&2
    fi
}

# ============================================================
#  按需执行各组件
# ============================================================
if need backend; then
    deploy_backend
fi
if need frontend; then
    deploy_frontend
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
printf '===== Lab Tools Ubuntu 部署完成 =====\n'
printf '本次部署组件：'
if [ -n "${PARTS[all]:-}" ]; then
    printf 'all\n'
else
    printf '%s\n' "$*"
fi
printf '后端代码（run.py）：%s\n' "${BACKEND_DIR}/run.py"
printf '前端静态产物：      %s\n' "${STATIC_DIR}"
printf 'Nginx 配置文件：    %s\n' "${NGINX_AVAILABLE}"
printf 'systemd 服务：      %s （已重启）\n' "${SYSTEMD_DEST}"
printf '\n验证命令：\n'
printf '  systemctl status %s\n' "${SERVICE_NAME}"
printf '  curl http://127.0.0.1:8000/api/health\n'
printf '  curl https://lab.sergget.qzz.io/api/health\n'
printf '=====================================\n'
