#!/usr/bin/env bash
# Lab Tools 一键部署脚本（Ubuntu Server）
# 用法：sudo bash ./deploy_ubuntu.sh
set -euo pipefail

APP_NAME="lab-tools"
APP_DIR="/opt/${APP_NAME}"
SERVICE_USER="labtools"
PORT="${LAB_TOOLS_PORT:-8000}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/6] 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 python3-venv python3-pip >/dev/null

if ! command -v node >/dev/null 2>&1 || [ "$(node --version | sed 's/v\([0-9]*\).*/\1/')" -lt 20 ]; then
  echo "==> 安装 Node.js 20（用于构建前端）"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
  apt-get install -y -qq nodejs >/dev/null
fi

echo "==> [2/6] 创建运行用户与目录"
id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
mkdir -p "${APP_DIR}/backend/data"
rsync -a --delete "${SRC_DIR}/backend/" "${APP_DIR}/backend/" 2>/dev/null || cp -r "${SRC_DIR}/backend/." "${APP_DIR}/backend/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

echo "==> [3/6] 安装 Python 依赖"
python3 -m venv "${APP_DIR}/backend/.venv"
"${APP_DIR}/backend/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/backend/.venv/bin/pip" install --quiet -r "${APP_DIR}/backend/requirements.txt"

echo "==> [4/6] 构建前端并放置静态产物"
if [ -d "${SRC_DIR}/frontend" ]; then
  FRONTEND_DIR="$(mktemp -d)"
  cp -r "${SRC_DIR}/frontend/." "${FRONTEND_DIR}/"
  cd "${FRONTEND_DIR}"
  npm install --no-fund --no-audit >/dev/null 2>&1
  npm run build
  rm -rf "${APP_DIR}/backend/app/static"
  cp -r dist "${APP_DIR}/backend/app/static"
  cd /
  rm -rf "${FRONTEND_DIR}"
else
  echo "警告：未找到 frontend 目录，跳过前端构建（使用已有 static 产物）"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/backend"

echo "==> [5/6] 安装 systemd 服务（端口 ${PORT}）"
sed "s/^Environment=LAB_TOOLS_PORT=.*/Environment=LAB_TOOLS_PORT=${PORT}/" \
  "${SRC_DIR}/deploy/lab-tools.service" > "/etc/systemd/system/${APP_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${APP_NAME}"

echo "==> [6/6] 等待服务就绪"
for i in $(seq 1 15); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo "部署完成：http://<服务器IP>:${PORT}"
    echo "提示：请在 ZeroTrust 代理 / 防火墙中将 ${PORT} 端口对公网开放，并确保 8000 不直接暴露。"
    exit 0
  fi
  sleep 1
done

echo "错误：服务启动失败，请查看日志：journalctl -u ${APP_NAME} -n 50"
exit 1