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

服务器需预装 **Node 20+** 与 **Python 3.10+**（脚本不再自动安装；依赖缺失时仅打印警告并跳过对应组件，不中断部署）。

全量部署（后端 + 前端 + systemd 服务 + Nginx 反代）：

```bash
sudo bash ./deploy_ubuntu.sh
```

也可按组件单独部署：

```bash
sudo bash ./deploy_ubuntu.sh backend    # 只更新后端并重启服务
sudo bash ./deploy_ubuntu.sh frontend   # 只重新构建前端产物（无需重启）
sudo bash ./deploy_ubuntu.sh service    # 只更新 systemd 单元并重启
sudo bash ./deploy_ubuntu.sh nginx      # 只更新 Nginx 配置并 reload
```

部署结构：

- 代码与运行环境：`/var/www/lab-tools`（backend/ 代码 + `.venv` 虚拟环境 + data 数据目录），以 `www-data` 用户运行 systemd 服务 `lab-tools`，内部端口 **8000**
- 反向代理：Nginx 将 `https://lab.sergget.qzz.io` 代理到 `127.0.0.1:8000`（配置见 `deploy/lab-tools.conf`，域名与 SSL 证书按需修改）

配置修改位置（直接编辑文件后重跑对应组件即可生效）：

- `deploy/lab-tools.service`：端口、OCR 节点地址（`LAB_TOOLS_OCR_NODE_URL`）、启用工具等 → `sudo bash ./deploy_ubuntu.sh service`
- `deploy/lab-tools.conf`：域名、SSL、上传大小限制等 → `sudo bash ./deploy_ubuntu.sh nginx`

服务管理：

```bash
systemctl status lab-tools
journalctl -u lab-tools -f
```

验证：

```bash
curl http://127.0.0.1:8000/api/health
curl https://lab.sergget.qzz.io/api/health
```

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