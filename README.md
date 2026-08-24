# Lab Tools

自托管的办公文件处理工具箱：一个首页列出所有可用工具，通过 ZeroTrust 保护（无需自建登录）。

## 当前工具

| 工具 | 说明 |
| --- | --- |
| Excel 表格拆分 | 上传 .xlsx/.xls，预览各 sheet 内容，按表头值拆分，自定义输出文件名模板，选择保留列，支持多文件打包 zip 或合并为单工作簿 |
| 文档转换 | 上传文档/图片/PDF，转换为 Markdown、纯文本或 Word；图片与扫描件走 OCR 识别（含行级版面重建），支持区域裁剪 |

## 架构

- 后端：Python FastAPI，`backend/`
- 前端：Vue 3 + Vite + Element Plus，`frontend/`，构建产物由 FastAPI 直接托管（单进程部署）
- 文档转换的 OCR 有两种模式（见下文「部署模式」）：进程内本地 PaddleOCR，或独立 OCR 节点 `ocr_server/`（Flask + PaddleOCR）
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

## 部署模式（文档转换 OCR）

文档转换工具支持两种 OCR 部署模式，通过环境变量 `LAB_TOOLS_OCR_USE_LOCAL` 切换，改配置后重启服务即可切换，无需改代码。

### 模式 A：单机自包含（本地 OCR）

所有识别转换在同一台机器完成，无需独立 OCR 节点。适合只有一台服务器的场景。

systemd 服务（`deploy/lab-tools.service`）关键配置：

```ini
Environment=LAB_TOOLS_ENABLED=doc_convert        # 可选：只启用文档转换工具
Environment=LAB_TOOLS_OCR_USE_LOCAL=true          # 启用本地 OCR 模式
```

目标机额外依赖：

```bash
# 系统包（Debian / 统信 UOS / Ubuntu）
sudo apt install -y libglib2.0-0 libsm6 libxext6 libxrender1 \
    libgl1-mesa-glx libgomp1 pandoc poppler-utils

# Python 包（requirements.txt 已包含，部署脚本自动安装）
# paddlepaddle>=2.6,<3.0    # CPU 版
# paddleocr>=2.7,<3.0
```

说明：
- PaddleOCR 以 CPU 模式在 FastAPI 进程内运行，首次调用会自动下载模型到用户目录
- OCR 推理串行化（内部锁），内存占用约 1~2GB，低配机器建议限制并发
- `deploy_ubuntu.sh` 的 backend 组件会自动尝试安装上述系统依赖

### 模式 B：独立 OCR 节点（外部转发）

主服务与 OCR 节点分离：主服务负责办公文档与文本型 PDF，OCR 节点（`ocr_server/`，Flask + PaddleOCR，默认端口 8001）专门处理图片与扫描件。

systemd 服务关键配置：

```ini
Environment=LAB_TOOLS_OCR_USE_LOCAL=false              # 或不设（默认 false）
Environment=LAB_TOOLS_OCR_NODE_URL=http://<ocr主机>:8001
Environment=LAB_TOOLS_OCR_NODE_NAME=ocr-node           # 健康检查展示用
Environment=LAB_TOOLS_OCR_NODE_ROLE=heavy
```

OCR 节点部署见 `ocr_server/` 目录；节点不可达时自动降级为本地 OCR（若本机装有 paddleocr），完全未安装则返回 503。

两种模式对比：

| | 模式 A：本地 OCR | 模式 B：外部节点 |
| --- | --- | --- |
| 机器数量 | 单台即可 | 主机 + OCR 节点（可同机不同端口） |
| 依赖体积 | paddlepaddle + paddleocr 装在主服务 | 主服务可不装 paddle*，节点单独装 |
| 性能 | OCR 与 Web 同进程，CPU 密集时可能阻塞响应 | OCR 负载隔离，可独立扩容/升级 GPU |
| 切换方式 | `LAB_TOOLS_OCR_USE_LOCAL=true` | `LAB_TOOLS_OCR_USE_LOCAL=false` + 配置节点地址 |

## 部署（Ubuntu Server / Debian / 统信 UOS）

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
| LAB_TOOLS_ENABLED | 空（全部启用） | 启用的工具，逗号分隔，如 `doc_convert`；留空启用全部 |
| LAB_TOOLS_CONVERT_MAX_MB | 50 | 文档转换单文件大小上限 |
| LAB_TOOLS_OCR_USE_LOCAL | false | `true` 时 OCR 在本进程内运行（模式 A），无需外部节点 |
| LAB_TOOLS_OCR_NODE_URL | http://127.0.0.1:8001 | 外部 OCR 节点地址（模式 B） |
| LAB_TOOLS_OCR_TIMEOUT | 120 | 转发 OCR 节点的超时秒数 |
| LAB_TOOLS_PDF_TEXT_THRESHOLD | 50 | PDF 分类阈值：前 3 页可提取字符数低于此值判定为扫描件 |
| LAB_TOOLS_LAYOUT_RECONSTRUCTION | true | 是否启用基于 OCR 行级 bbox 的版面重建 |
| LAB_TOOLS_DOCX_REFERENCE_TEMPLATE | 空 | pandoc 转 docx 时的参考模板路径 |

## 安全

- 应用不做任何登录/鉴权，请务必置于 ZeroTrust（如 Cloudflare Access、Tailscale、自建 ZTNA）之后
- 生产环境建议在 ZeroTrust 网关终止 TLS（HTTP 即可），不要把 8000 直接暴露公网
- systemd 单元已启用 `NoNewPrivileges / ProtectSystem / ProtectHome`，数据写入仅限 data 目录

## 规划中的工具

- 待定（欢迎提 issue）