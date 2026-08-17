# Lab Tools

自托管的办公文件处理工具箱：一个首页列出所有可用工具，部署在单台 Ubuntu Server 上，通过 ZeroTrust 保护（无需自建登录）。

## 当前工具

| 工具 | 说明 |
| --- | --- |
| Excel 表格拆分 | 上传 .xlsx/.xls，预览各 sheet 内容，按表头值拆分，自定义输出文件名模板，选择保留列，支持多文件打包 zip 或合并为单工作簿 |
| Excel 表格比对 | 上传基准表与比对表，按指定键列匹配、可选值列，输出差异明细表，或在原表副本中高亮差异单元格（黄色=值差异、橙/绿=仅一侧有） |
| 文档转换 | 上传 office 文档 / 图片 / PDF，输出 Markdown / 纯文本 / Word；图片与扫描 PDF 走 OCR（独立 PaddleOCR 节点，可本地降级），支持区域裁剪与版面重建 |

## 架构

- 后端：Python FastAPI，`backend/`（pandas + openpyxl + MarkItDown + pdfplumber + PyMuPDF）
- 前端：Vue 3 + Vite + Element Plus，`frontend/`，构建产物由 FastAPI 直接托管（单进程部署）
- OCR 节点：独立 Flask 服务 `ocr_server/`（PaddleOCR，CPU 模式，默认 8001 端口），被文档转换工具经 HTTP 调用；节点离线时主服务自动降级
- 新增工具：在 `backend/app/tools/` 下新建工具包并在 `backend/app/tools/__init__.py` 注册，前端 `frontend/src/router/index.js` 加路由即可
- 详细文档：工具与依赖细节见 [docs/doc-convert.md](docs/doc-convert.md)、[docs/ocr-node.md](docs/ocr-node.md)

## 本地开发

Python 版本要求：**后端 3.10 – 3.13**（推荐 3.12；3.14 暂不支持，`pandas 2.x` / `pymupdf` 尚无对应 wheel）；**OCR 节点 3.11**（paddlepaddle 2.6.2 对应版本，详见 [docs/ocr-node.md](docs/ocr-node.md)）。

```bash
# 后端（Python 3.10 - 3.13）
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux 用 .venv/bin/activate
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:8000

# OCR 节点（可选，识别图片/扫描 PDF 用；依赖安装见 docs/ocr-node.md）
cd ocr_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_win11.txt   # Windows 实测清单
.venv\Scripts\python ocr_server.py --port 8001

# 前端（Node 20+）
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173，/api 代理到 8000
```

一键启动本地服务（后端 + OCR 节点，自动建 venv 装依赖）：

```bash
python run_local_servers.py --all
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

> 若某工具依赖缺失（例如未安装 OCR 相关依赖）导致导入失败，可用 `LAB_TOOLS_ENABLED` 只启用需要的工具再跑测试：
> `LAB_TOOLS_ENABLED="excel-split,excel-diff,doc-convert" .venv/bin/python -m pytest`（`backend/app/main.py` 已支持按工具惰性导入路由）。

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

### OCR 节点（可选组件）

图片 / 扫描 PDF 的识别依赖独立的 OCR 节点（`ocr_server/`，PaddleOCR）。Windows 部署为系统服务：

```powershell
# 前置：Python 3.11 + NSSM；先按 docs/ocr-node.md 建 venv 装依赖
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1            # 注册并启动（默认端口 8001）
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action status
```

接入主节点（把 `LAB_TOOLS_OCR_NODE_URL` 指向 OCR 节点 IP 后重载服务）：

```bash
sudo bash ./deploy_ubuntu.sh service
```

节点离线时主服务自动降级（本地 PaddleOCR → 文本型 PDF 退回 MarkItDown），不会影响其它工具。依赖版本约束与常见问题见 [docs/ocr-node.md](docs/ocr-node.md)。

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
| LAB_TOOLS_HOST / LAB_TOOLS_PORT | 0.0.0.0 / 8000 | 监听地址 |
| LAB_TOOLS_DATA_DIR | backend/data | 上传与产物存储目录 |
| LAB_TOOLS_TTL_HOURS | 2 | 临时文件保留时长，超时自动清理 |
| LAB_TOOLS_MAX_UPLOAD_MB | 100 | 上传大小限制 |
| LAB_TOOLS_STATIC_DIR | backend/app/static | 前端静态产物目录 |
| LAB_TOOLS_ENABLED | 空（全部） | 启用工具集合，逗号分隔（如 `excel-split,doc-convert`） |
| LAB_TOOLS_NODE_NAME / LAB_TOOLS_NODE_ROLE | 主机名 / main | 节点身份（健康检查展示） |
| **文档转换** | | |
| LAB_TOOLS_CONVERT_MAX_MB | 50 | 转换文件大小上限 |
| LAB_TOOLS_OCR_NODE_URL | http://127.0.0.1:8001 | OCR 节点地址（图片/扫描 PDF 识别） |
| LAB_TOOLS_OCR_TIMEOUT | 120 | 转发 OCR 节点的请求超时（秒） |
| LAB_TOOLS_OCR_NODE_NAME / LAB_TOOLS_OCR_NODE_ROLE | win11 / heavy | OCR 节点身份（展示用） |
| LAB_TOOLS_PDF_TEXT_THRESHOLD | 50 | PDF 文本/扫描分类的字符数阈值 |
| LAB_TOOLS_CROP_PDF_ZOOM | 2.0 | 扫描 PDF 裁剪渲染缩放倍率 |
| LAB_TOOLS_PANDOC_TIMEOUT | 30 | pandoc 转换超时（秒） |
| LAB_TOOLS_DOCX_REFERENCE_TEMPLATE | 空 | pandoc 参考模板路径（Markdown→docx 用） |
| LAB_TOOLS_LAYOUT_RECONSTRUCTION | true | OCR 版面重建开关 |
| LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO / LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO / LAB_TOOLS_LAYOUT_INDENT_RATIO | 1.3 / 1.4 / 0.5 | 版面重建几何阈值 |

OCR 节点侧环境变量（`NODE_NAME`、`PORT`、`OCR_MAX_FILE_MB`、`OCR_MAX_PDF_PAGES`、`OCR_TIMEOUT_SEC`、`OCR_PDF_DPI` 等）见 [docs/ocr-node.md](docs/ocr-node.md)。

## 安全

- 应用不做任何登录/鉴权，请务必置于 ZeroTrust（如 Cloudflare Access、Tailscale、自建 ZTNA）之后
- 生产环境建议在 ZeroTrust 网关终止 TLS（HTTP 即可），不要把 8000 直接暴露公网
- systemd 单元已启用 `NoNewPrivileges / ProtectSystem / ProtectHome`，数据写入仅限 data 目录

## 依赖速览

- **后端基础**：fastapi、uvicorn、python-multipart、pandas（`<3.0`）、openpyxl、xlrd
- **文档转换**：markitdown[all]（office/PDF 提取）、pdfplumber、pymupdf、python-docx、pillow、requests、psutil；可选 paddleocr（本地 OCR 降级）
- **OCR 节点**：flask、flask-cors、psutil、paddleocr==2.7.0.3、paddlepaddle==2.6.2（CPU）、numpy<2.0、opencv<=4.6.0.66、PyMuPDF>=1.25 —— 版本约束与踩坑详见 [docs/ocr-node.md](docs/ocr-node.md)
- **前端**：Vue 3、Vite、Element Plus、axios、cropperjs（区域裁剪）

## 规划中的工具

- 在线预览 / 表格编辑等交互式处理能力（当前各工具均为"上传 → 处理 → 下载"模式）