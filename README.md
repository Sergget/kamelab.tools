# Lab Tools

自托管的办公文件处理工具箱：一个首页列出所有可用工具，部署在单台服务器上，通过 ZeroTrust 保护（无需自建登录）。

## 当前工具

| 工具 | 说明 |
| --- | --- |
| Excel 表格拆分 | 上传 .xlsx/.xls，预览各 sheet 内容，按表头值拆分，自定义输出文件名模板，选择保留列，支持多文件打包 zip 或合并为单工作簿 |
| Excel 表格比对 | 上传基准表与比对表，按指定键列匹配、可选值列，输出差异明细表，或在原表副本中高亮差异单元格（黄色=值差异、橙/绿=仅一侧有） |
| 文档转换 | 上传 office 文档 / 图片 / PDF，输出 Markdown / 纯文本 / Word；图片与扫描 PDF 走 OCR（支持远程节点与本地引擎），支持区域裁剪与版面重建 |
| 通讯录归档与管理 | 上传不同日期的通讯录 Excel，自动识别表头并映射字段，按版本增量归档；支持任意时点查询、可视化增删改查、导出 Excel；项目以密码保护，删除前强制先导出数据库备份（`.cmdb`） |

## 架构

- 后端：Python FastAPI，`backend/`（pandas + openpyxl；文档转换用纯 Python 提取 + 系统 poppler，OCR 引擎可选）
- 前端：Vue 3 + Vite + Element Plus，`frontend/`，构建产物由 FastAPI 直接托管（单进程部署）
- OCR 节点：独立 Flask 服务 `ocr_server/`（支持 RapidOCR/ONNXRuntime CPU 版与 PaddleOCR GPU 版），被文档转换工具经 HTTP 调用；节点离线时主服务自动降级
- 新增工具：在 `backend/app/tools/` 下新建工具包并在 `backend/app/tools/__init__.py` 注册，前端 `frontend/src/router/index.js` 加路由即可
- 详细文档：工具与依赖细节见 [docs/doc-convert.md](docs/doc-convert.md)、[docs/doc-compile.md](docs/doc-compile.md)、[docs/ocr-node.md](docs/ocr-node.md)、[docs/contact-manager.md](docs/contact-manager.md)

## 部署模式

文档转换工具（doc-convert）支持四种部署模式，**仅通过环境变量切换，无需改代码**：

| 模式 | 主服务器 | OCR节点 | 文档转换 | 适用场景 |
|------|----------|---------|----------|----------|
| **A** | 任意（mips64el/ARM/x86） | 独立节点 | 远程 OCR | 异构集群、弱主机 |
| **B** | Ubuntu x86_64 | 远程 GPU 节点 | 远程 GPU OCR | 本地异构、GPU 加速 |
| **C** | 任意 | — | 禁用 | 仅 Excel 工具、极简部署 |
| **D** | Ubuntu x86_64 | 本地 GPU | 本地 GPU OCR | 单机全功能、GPU 加速 |

### 核心环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEPLOY_MODE` | `A` | 部署模式：`A` \| `B` \| `C` \| `D` |
| `OCR_NODE_URL` | 空 | OCR 节点地址，如 `http://ocr-node:8001` |
| `OCR_NODE_TIMEOUT` | `5` | OCR 节点探活超时（秒） |
| `OCR_ENGINE` | `auto` | 本地引擎：`rapidocr` \| `paddleocr` \| `auto` |
| `OCR_USE_GPU` | `false` | 是否启用 GPU 加速（需 NVIDIA GPU CC 6.1+） |
| `ENABLE_DOC_CONVERT` | `true` | 文档转换总开关（模式 C 设为 `false`） |
| `OCR_USE_LOCAL` | `false` | 本地 OCR 回退开关（节点不可达时） |
| `OCR_IDLE_UNLOAD_SEC` | `900` | 空闲自动卸载模型秒数（0=永不卸载） |
| `OCR_NODE_NAME` | `ocr-node` | OCR 节点显示名称 |
| `OCR_NODE_ROLE` | `heavy` | OCR 节点角色标识 |

### 模式示例

**模式 A：主服务器 + 远程 OCR 节点**
```bash
# 主服务器（任意架构）
DEPLOY_MODE=A
OCR_NODE_URL=http://ocr-node:8001

# OCR 节点（RapidOCR CPU 版）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-cpu.ps1
```

**模式 B：Ubuntu 主服务 + 远程 GPU OCR 节点**
```bash
# OCR 节点（PaddleOCR GPU）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-gpu.ps1 -OcrUseGpu true

# Ubuntu 主服务
DEPLOY_MODE=B
OCR_NODE_URL=http://<ocr节点IP>:8001
sudo bash ./deploy_ubuntu.sh
```

**模式 C：仅 Excel 工具（极简）**
```bash
DEPLOY_MODE=C
sudo bash ./deploy-minimal.sh
```

**模式 D：Ubuntu 单机全功能（本地 GPU OCR）**
```bash
DEPLOY_MODE=D
OCR_ENGINE=paddleocr
OCR_USE_GPU=true
sudo bash ./deploy_ubuntu.sh
```

---

## 本地开发

Python 版本要求：**后端 3.10 – 3.13**（推荐 3.11；3.14 暂不支持，`pandas 2.x` / `pymupdf` 尚无对应 wheel）；**OCR 节点 3.11**（paddlepaddle 2.6.2 对应版本）。

```bash
# 后端（Python 3.10 - 3.13）
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux 用 .venv/bin/activate
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:8000

# OCR 节点 CPU 版（RapidOCR）
cd ocr_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ocr-cpu.txt
.venv\Scripts\python ocr_server.py --port 8001

# OCR 节点 GPU 版（需 NVIDIA GPU CC 6.1+）
cd ocr_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ocr-gpu.txt
.venv\Scripts\python ocr_server.py --port 8001

# 前端（Node 20+）
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173，/api 代理到 8000
```

一键启动本地服务（支持按需组合或全量启动，自动管理虚拟环境与依赖）：

```bash
python run_local_servers.py --all            # 启动全部（后端 + 前端开发服务 + OCR 节点）
python run_local_servers.py --backend        # 仅启动后端服务
python run_local_servers.py --frontend       # 仅启动前端 Vite 开发服务
python run_local_servers.py --ocr            # 仅启动 OCR 节点服务
python run_local_servers.py --backend --frontend --port 8000
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

单独跑某个工具的测试：

```bash
.venv/bin/python -m pytest tests/test_excel_split.py -v
.venv/bin/python -m pytest tests/test_excel_diff.py -v
.venv/bin/python -m pytest tests/test_doc_convert.py -v
.venv/bin/python -m pytest tests/test_contact_manager.py -v
```

> 若某工具依赖缺失（例如未安装 OCR 相关依赖）导致导入失败，可用 `LAB_TOOLS_ENABLED` 只启用需要的工具再跑测试：
> `LAB_TOOLS_ENABLED="excel-split,excel-diff,doc-convert" .venv/bin/python -m pytest`（`backend/app/main.py` 已支持按工具惰性导入路由）。

---

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
- 反向代理：Nginx 将域名的 HTTPS 流量代理到 `127.0.0.1:8000`（配置见 `deploy/lab-tools.conf`，域名与 SSL 证书按需修改）

### OCR 节点（可选组件）

图片 / 扫描 PDF 的识别依赖独立的 OCR 节点（`ocr_server/`）。支持两种部署方式：

**CPU 版（RapidOCR，无需 AVX/GPU）：**
```powershell
# Windows 部署为系统服务（NSSM）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-cpu.ps1        # 注册并启动（默认端口 8001）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-cpu.ps1 -Action status
```

**GPU 版（PaddleOCR + GPU，需 NVIDIA GPU CC 6.1+）：**
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-gpu.ps1 -OcrUseGpu true
```

接入主节点（设置 `OCR_NODE_URL` 指向 OCR 节点 IP 后重载服务）：

```bash
sudo bash ./deploy_ubuntu.sh service
```

节点离线时主服务自动降级（本地 OCR 引擎 → pdftotext），不会影响其它工具。依赖版本约束与常见问题见 [docs/ocr-node.md](docs/ocr-node.md)。

### 极简部署（仅 Excel 工具，模式 C）

```bash
DEPLOY_MODE=C
sudo bash ./deploy-minimal.sh
```

配置修改位置（直接编辑文件后重跑对应组件即可生效）：

- `deploy/lab-tools.service`：端口、OCR 节点地址（`OCR_NODE_URL`）、启用工具等 → `sudo bash ./deploy_ubuntu.sh service`
- `deploy/lab-tools.conf`：域名、SSL、上传大小限制等 → `sudo bash ./deploy_ubuntu.sh nginx`

服务管理：

```bash
systemctl status lab-tools
journalctl -u lab-tools -f
```

验证：

```bash
curl http://127.0.0.1:8000/api/health
curl https://your-domain.com/api/health
```

---

### sugon（龙芯 mips64el）部署

sugon 架构（如龙芯 3A/3C 系列）**不支持本地 OCR 引擎**（paddleocr/rapidocr 无对应 wheel），
因此文档转换走**远程 OCR 节点**（模式 A）。PDF 能力由系统包 `poppler-utils` 提供，
`numpy`/`pandas`/`pydantic-core` 等依赖通过 GCC 源码编译（需 `GCC >= 8.4`，如 `/opt/gcc12`）。

```bash
sudo bash ./deploy-sugon.sh            # 全量部署（后端 + 服务 + Nginx）
sudo bash ./deploy-sugon.sh backend    # 仅后端（代码更新时使用）
sudo bash ./deploy-sugon.sh service    # 仅 systemd 单元（配置修改时使用）
sudo bash ./deploy-sugon.sh service nginx # 组合
```

配置文件：
- `deploy/lab-tools-sugon.service` — sugon 专用 systemd 单元，预设 `DEPLOY_MODE=A`、`OCR_USE_LOCAL=false`
  - 修改方法：编辑 `deploy/lab-tools-sugon.service` 中的 `LAB_TOOLS_OCR_NODE_URL` 为实际 OCR 节点 IP，
    然后运行 `sudo bash ./deploy-sugon.sh service`

验证：
```bash
systemctl status lab-tools
curl http://127.0.0.1:8000/api/health
```

---

## OCR 节点（Windows 部署）

前置：Python 3.11 + NSSM（加入 PATH）；先在 `ocr_server` 目录创建虚拟环境并安装依赖：

```powershell
# CPU 版（RapidOCR，无需 AVX/GPU）
cd ocr_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ocr-cpu.txt

# GPU 版（需 NVIDIA GPU CC 6.1+，如 GTX 1060+）
cd ocr_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ocr-gpu.txt
```

部署为系统服务（NSSM）：

```powershell
# CPU 版
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-cpu.ps1            # 注册并启动（默认端口 8001）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-cpu.ps1 -Action status

# GPU 版（需 NVIDIA GPU CC 6.1+，如 GTX 1060+）
powershell -ExecutionPolicy Bypass -File .\deploy-ocr-gpu.ps1 -OcrUseGpu true
```

接入主节点（设置 `OCR_NODE_URL` 指向 OCR 节点 IP 后重载服务）：

```bash
sudo bash ./deploy_ubuntu.sh service
```

节点离线时主服务自动降级（本地 OCR 引擎 → pdftotext），不会影响其它工具。依赖版本约束与常见问题见 [docs/ocr-node.md](docs/ocr-node.md)。

### 极简部署（仅 Excel 工具，模式 C）

```bash
DEPLOY_MODE=C
sudo bash ./deploy-minimal.sh
```

---

## 环境变量（后端）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DEPLOY_MODE | A | 部署模式：A/B/C/D |
| OCR_NODE_URL | 空 | OCR 节点地址（模式 A/B 生效） |
| OCR_NODE_TIMEOUT | 5 | OCR 节点探活超时（秒） |
| OCR_ENGINE | auto | 本地引擎：rapidocr \| paddleocr \| auto |
| OCR_USE_GPU | false | GPU 加速开关（需 NVIDIA GPU CC 6.1+） |
| ENABLE_DOC_CONVERT | true | 文档转换总开关（模式 C 设 false） |
| OCR_USE_LOCAL | false | 本地 OCR 回退（节点不可达时） |
| OCR_IDLE_UNLOAD_SEC | 900 | 空闲自动卸载模型秒数（0=永不卸载） |
| OCR_NODE_NAME | ocr-node | OCR 节点显示名称 |
| OCR_NODE_ROLE | heavy | OCR 节点角色标识 |
| LAB_TOOLS_HOST / LAB_TOOLS_PORT | 0.0.0.0 / 8000 | 监听地址 |
| LAB_TOOLS_DATA_DIR | backend/data | 上传与产物存储目录 |
| LAB_TOOLS_TTL_HOURS | 2 | 临时文件保留时长，超时自动清理 |
| LAB_TOOLS_MAX_UPLOAD_MB | 100 | 上传大小限制 |
| LAB_TOOLS_STATIC_DIR | backend/app/static | 前端静态产物目录 |
| LAB_TOOLS_ENABLED | 空（全部） | 启用工具集合，逗号分隔 |
| LAB_TOOLS_NODE_NAME / LAB_TOOLS_NODE_ROLE | 主机名 / main | 节点身份（健康检查展示） |
| LAB_TOOLS_CONVERT_MAX_MB | 50 | 转换文件大小上限 |
| LAB_TOOLS_OCR_TIMEOUT | 120 | 转发 OCR 节点的请求超时（秒） |
| LAB_TOOLS_PDF_TEXT_THRESHOLD | 50 | PDF 分类阈值：前 3 页字符数 ≥ 此值为文本型 |
| LAB_TOOLS_CROP_PDF_ZOOM | 2.0 | 扫描 PDF 裁剪渲染缩放倍率 |
| LAB_TOOLS_PANDOC_TIMEOUT | 30 | pandoc 转换超时（秒） |
| LAB_TOOLS_DOCX_REFERENCE_TEMPLATE | 空 | pandoc 参考模板路径 |
| LAB_TOOLS_LAYOUT_RECONSTRUCTION | true | OCR 版面重建开关 |
| LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO / LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO / LAB_TOOLS_LAYOUT_INDENT_RATIO | 1.3 / 1.4 / 0.5 | 版面重建几何阈值 |
| LAB_TOOLS_COMPILE_MAX_MB | 50 | 文档汇编单文件大小上限 |
| LAB_TOOLS_SOFFICE_PATH | 空（自动探测） | LibreOffice 可执行文件路径（.doc 老格式转换 / 预览渲染 / 页码定位） |
| LAB_TOOLS_COMPILE_PREVIEW_DPI | 150 | 文档汇编预览渲染分辨率 |
| LAB_TOOLS_COMPILE_CONVERT_TIMEOUT | 120 | LibreOffice 转换进程超时（秒） |

> **变量名兼容性**：下列 OCR 相关变量同时接受「新短名」与「旧 `LAB_TOOLS_` 前缀名」，
> 优先取短名，因此历史部署脚本与 systemd 单元无需修改即可继续生效：
>
> | 新短名（优先） | 旧前缀名（兼容） |
> | --- | --- |
> | `OCR_NODE_URL` | `LAB_TOOLS_OCR_NODE_URL` |
> | `OCR_NODE_NAME` | `LAB_TOOLS_OCR_NODE_NAME` |
> | `OCR_NODE_ROLE` | `LAB_TOOLS_OCR_NODE_ROLE` |
> | `OCR_USE_LOCAL` | `LAB_TOOLS_OCR_USE_LOCAL` |

OCR 节点侧环境变量（`NODE_NAME`、`PORT`、`OCR_MAX_FILE_MB`、`OCR_MAX_PDF_PAGES`、`OCR_TIMEOUT_SEC`、`OCR_PDF_DPI`、`OCR_IDLE_UNLOAD_SEC`、`OCR_USE_GPU` 等）见 [docs/ocr-node.md](docs/ocr-node.md)。

---

## 安全

- 应用不做任何登录/鉴权，请务必置于 ZeroTrust（如 Cloudflare Access、Tailscale、自建 ZTNA）之后
- 生产环境建议在 ZeroTrust 网关终止 TLS（HTTP 即可），不要把 8000 直接暴露公网
- systemd 单元已启用 `NoNewPrivileges / ProtectSystem / ProtectHome`，数据写入仅限 data 目录

---

## 依赖速览

Python 依赖（`pip install -r <文件>`）：

| 场景 | 核心依赖 | requirements 文件 |
|------|----------|-------------------|
| 完整版（x86_64，含本地 OCR） | fastapi、uvicorn、pandas、openpyxl、mammoth、python-pptx、python-docx、rapidocr_onnxruntime、paddleocr 等 | `backend/requirements.txt` |
| 主服务器本地 OCR 回退 | rapidocr_onnxruntime、PyMuPDF、Pillow | `backend/requirements-ocr-cpu.txt` |
| 仅 Excel 工具（模式 C） | fastapi、uvicorn、pandas、openpyxl、xlrd | `backend/requirements-minimal.txt` |
| sugon（mips64el 龙芯，无 OCR 本地引擎） | fastapi、uvicorn、pandas、openpyxl、mammoth、python-pptx 等 | `backend/requirements-sugon.txt` |
| OCR 节点（Windows） | flask、flask-cors、paddleocr、paddlepaddle-gpu、PyMuPDF、opencv | `ocr_server/requirements_win11.txt`（冻结版：`requirements_win11_frozen.txt`） |

系统依赖（不通过 pip 安装，需包管理器提供）：

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| poppler-utils | PDF 提取与渲染（`pdftotext` / `pdftoppm` / `pdfinfo`），文档转换的 PDF 能力依赖它 | `sudo apt install poppler-utils` |
| pandoc（可选） | Markdown → docx 的优先引擎，缺失时自动降级为 python-docx | `sudo apt install pandoc` |

> 通讯录归档与管理工具仅依赖标准库 `sqlite3` 与 `openpyxl`，无需额外安装依赖。

---

## 数据存储

- Excel 拆分 / 比对 / 文档转换：上传与产物存放于 `LAB_TOOLS_DATA_DIR`（默认 `backend/data/`），按 `LAB_TOOLS_TTL_HOURS` 自动清理
- 通讯录归档与管理：使用 SQLite 数据库 `backend/data/contact_manager.db`，**不参与 TTL 清理**，需自行备份该文件（或通过界面导出 `.cmdb`）
  - 表结构为 `projects` → `contact_versions` → `contact_entities` → `contact_version_deltas`，按版本记录增量变更，因此可回溯任一时点的通讯录快照
  - 服务启动时会执行幂等迁移，自动修复旧版本遗留的表结构与悬空外键

---

## 规划中的工具

- 在线预览 / 表格编辑等交互式处理能力（当前各工具均为"上传 → 处理 → 下载"模式）
- Word / PPT / PDF 深度版面分析（多栏、表格结构化）

---

## 许可证

MIT License