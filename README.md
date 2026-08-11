# Lab Tools

自托管的办公文件处理工具箱：一个首页列出所有可用工具，部署在单台 Ubuntu Server 上，通过 ZeroTrust 保护（无需自建登录）。

## 当前工具

| 工具 | 说明 |
| --- | --- |
| Excel 表格拆分 | 上传 .xlsx/.xls，预览各 sheet 内容，按表头值拆分，自定义输出文件名模板，选择保留列，支持多文件打包 zip 或合并为单工作簿 |

## 架构

- 后端：Python FastAPI，`backend/`（pandas + openpyxl）
- 前端：Vue 3 + Vite + Element Plus，`frontend/`，构建产物由 FastAPI 直接托管（单进程部署）
- 新增工具：在 `backend/app/tools/` 下新建工具包并在 `backend/app/tools/__init__.py` 注册，前端 `frontend/src/router/index.js` 加路由即可

## 本地开发

```bash
# 后端（Python 3.9+）
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux 用 .venv/bin/activate
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:8000

# 前端（Node 20+）
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173，/api 代理到 8000
```

构建前端并交由后端托管：

```bash
cd frontend && npm run build
# 将 dist/ 内容复制到 backend/app/static/
```

## 测试

```bash
cd backend
.venv/bin/python -m pytest
```

## 部署（Ubuntu Server）

```bash
sudo bash ./deploy_ubuntu.sh
```

脚本会：安装 Node 20 / Python 依赖 → 构建前端 → 以 `labtools` 用户 + systemd 部署 `/opt/lab-tools`（默认端口 **8000**）→ 健康检查通过后提示完成。

服务管理：

```bash
systemctl status lab-tools
journalctl -u lab-tools -f
```

自定义端口：`LAB_TOOLS_PORT=9000 sudo bash ./deploy_ubuntu.sh`

## 环境变量（后端）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| LAB_TOOLS_HOST / PORT | 0.0.0.0 / 8000 | 监听地址 |
| LAB_TOOLS_DATA_DIR | backend/data | 上传与产物存储目录 |
| LAB_TOOLS_TTL_HOURS | 2 | 临时文件保留时长，超时自动清理 |
| LAB_TOOLS_MAX_UPLOAD_MB | 100 | 上传大小限制 |
| LAB_TOOLS_STATIC_DIR | backend/app/static | 前端静态产物目录 |

## 安全

- 应用不做任何登录/鉴权，请务必置于 ZeroTrust（如 Cloudflare Access、Tailscale、自建 ZTNA）之后
- 生产环境建议在 ZeroTrust 网关终止 TLS（HTTP 即可），不要把 8000 直接暴露公网
- systemd 单元已启用 `NoNewPrivileges / ProtectSystem / ProtectHome`，数据写入仅限 data 目录

## 规划中的工具

- Word / PPT / PDF 内容读取与转换（可复用 puremark-converter 的 MarkItDown 提取方案）