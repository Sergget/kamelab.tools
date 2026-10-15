# 文档转换工具（doc-convert）说明

本文档对应后端工具包 `backend/app/tools/doc_convert/` 与前端页面 `frontend/src/views/DocConvertView.vue`（路由 `/tools/doc-convert`）。

## 功能概述

- **统一上传入口**：一个 `/convert` 端点按文件扩展名自动路由，无需用户选择引擎；
- **三种输出格式**：Markdown（默认）、纯文本（txt）、Word（docx）；
- **区域裁剪**：图片与 PDF 支持可视化框选（前端 Cropper），按同一比例裁剪后再转换；
- **版面重建**：对 OCR 结果按行级 bbox 做几何启发式排版（标题层级 / 段落 / 缩进 / 引用块），输出更接近原文档的 Markdown；
- **OCR 节点转发与降级**：图片 / 扫描 PDF 优先转发独立 OCR 节点（`ocr_server/`），节点不可达时自动降级为主服务本地引擎（`factory.get_ocr_extractor()` 按 `DEPLOY_MODE` / `OCR_ENGINE` 选择 RapidOCR / PaddleOCR / 远程节点）。

## 支持格式与路由策略

| 输入类型 | 扩展名 | 处理方式 |
| --- | --- | --- |
| 办公文档 / 文本 | `.docx` `.xlsx` `.xlsm` `.xls` `.pptx` `.txt` `.csv` `.html` `.htm` `.xml` `.json` `.md` | 本地纯 Python 提取（`local_extract.py`，不经过 OCR） |
| 文本型 PDF | `.pdf` | poppler `pdftotext -layout` 提取文字层 |
| 图片 | `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.tiff` `.webp` | OCR：远程节点优先 → 本地引擎降级 |
| 扫描型 PDF | `.pdf` | 渲染每页为 PNG 后逐页 OCR |

PDF 先分类：前 3 页去空白后的字符数 ≥ `LAB_TOOLS_PDF_TEXT_THRESHOLD`（默认 50）判为文本型，否则为扫描型。

区域裁剪的分支行为：

- 图片：按比例裁剪后识别；
- 文本型 PDF：按比例裁剪每页并直接提取文字层，不走 OCR（`engine=poppler_crop`）；
- 扫描型 PDF：按比例裁剪每页并渲染成 PNG，逐页 OCR 后拼接（`routed_to=local`）；
- 办公格式：不支持裁剪，忽略 crop 并整份转换（响应 `crop_ignored`）。

## 输出格式

- **md**：本地提取 / OCR 原始结果；
- **txt**：用 `strip_markdown_light` 剥离常见 Markdown 语法（标题、链接、表格转为空格分隔等）；
- **docx**：Markdown → Word，**pandoc 优先**（可指定 `--reference-doc` 参考模板），pandoc 未安装或转换失败时自动降级为 **python-docx 手写引擎**（支持标题 / 表格 / 列表 / 引用块 / 分割线 / 代码块 / 行内样式），响应中的 `docx_engine` 标识实际使用的引擎。

注意：源文件是 `.docx` 时再选 docx 输出会被拒绝（会先转 Markdown 再重建，原始排版必然丢失），请直接使用原文件。

## 依赖

### 必装

| 包 | 用途 | 说明 |
| --- | --- | --- |
| fastapi / uvicorn / python-multipart | Web 框架与上传 | |
| pandas / openpyxl / xlrd | Excel 工具（拆分 / 比对） | |
| pytest / httpx | 测试 | |
| **mammoth** | `.docx` → Markdown（纯 Python） | `local_extract` 使用 |
| **python-pptx** | `.pptx` → 文本（纯 Python） | `local_extract` 使用 |
| **python-docx** | Markdown → docx 兜底引擎 | |
| **pillow** | 图片解码 / 裁剪 | |
| **requests** | OCR 节点转发与探活 | |
| **psutil** | 健康检查 CPU / 内存指标 | |
| **poppler-utils**（系统包） | `pdftotext` / `pdftoppm` / `pdfinfo` | 文本型 PDF 提取与扫描型 PDF 渲染，需 `apt install poppler-utils` |

> 早期版本依赖 `markitdown[all]` / `pdfplumber` / `pymupdf`。在无预编译 wheel 的架构（如 mips64el）上无法安装，因此改为
> 纯 Python 的 `local_extract` + 系统 poppler。当前代码**不再**依赖 markitdown / pdfplumber / pymupdf。

### 可选（本地 OCR 降级）

| 包 | 用途 | 说明 |
| --- | --- | --- |
| rapidocr_onnxruntime | 本地 OCR 引擎（无 AVX 要求） | `OCR_ENGINE=rapidocr` 或 `auto` 且无 NVIDIA GPU 时使用 |
| paddleocr + paddlepaddle | 本地 OCR 引擎（需 AVX，可选 GPU） | `OCR_ENGINE=paddleocr` 时使用，见 [OCR 节点文档](ocr-node.md) |

不安装任何本地 OCR 引擎时：OCR 节点离线 → 图片 / 扫描 PDF 转换失败（文本型 PDF 与办公文档仍可正常转换）。

### Python 版本要求（重要）

| 组件 | 建议版本 | 原因 |
| --- | --- | --- |
| 后端（backend/） | **Python 3.11**（实测 3.11.9） | mips64el 上 `numpy`/`pandas`/`pydantic-core` 需源码编译；`fastapi` 锁在 0.115.x 以使用纯 Python 的 pydantic v1（pydantic v2 的 pydantic-core 需要 Rust，而 Rust 未发布 mips64el 编译器） |
| OCR 节点（ocr_server/） | **Python 3.11**（实测 3.11.9） | `paddlepaddle==2.6.2` 与 `paddleocr==2.7.0.3` 的组合以 3.11 为准 |

## 可选能力配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LAB_TOOLS_CONVERT_MAX_MB` | 50 | 转换文件大小上限 |
| `OCR_NODE_URL`（兼容 `LAB_TOOLS_OCR_NODE_URL`） | 空 | OCR 节点地址；为空则直接使用本地引擎 |
| `OCR_NODE_TIMEOUT` | 5 | OCR 节点探活超时（秒） |
| `LAB_TOOLS_OCR_TIMEOUT` | 120 | 转发 OCR 节点的请求超时（秒） |
| `OCR_NODE_NAME` / `OCR_NODE_ROLE`（兼容 `LAB_TOOLS_OCR_NODE_NAME` / `LAB_TOOLS_OCR_NODE_ROLE`） | ocr-node / heavy | OCR 节点身份（仅展示用） |
| `OCR_ENGINE` | auto | 本地引擎：`rapidocr` \| `paddleocr` \| `auto` |
| `OCR_USE_GPU` | false | 本地引擎是否启用 GPU |
| `OCR_USE_LOCAL`（兼容 `LAB_TOOLS_OCR_USE_LOCAL`） | false | true = 本地优先，不探测外部节点 |
| `DEPLOY_MODE` | A | 部署模式 A/B/C/D；`C` 表示禁用文档转换 |
| `ENABLE_DOC_CONVERT` | true | 文档转换总开关 |
| `LAB_TOOLS_PDF_TEXT_THRESHOLD` | 50 | PDF 文本/扫描分类的字符数阈值 |
| `LAB_TOOLS_CROP_PDF_ZOOM` | 2.0 | 扫描 PDF 裁剪渲染缩放倍率 |
| `LAB_TOOLS_PANDOC_TIMEOUT` | 30 | pandoc 转换超时（秒） |
| `LAB_TOOLS_DOCX_REFERENCE_TEMPLATE` | 空 | pandoc 参考模板路径（存在时自动附加 `--reference-doc`） |
| `LAB_TOOLS_LAYOUT_RECONSTRUCTION` | true | 是否启用 OCR 版面重建 |
| `LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO` | 1.3 | 标题判定的行高倍数阈值 |
| `LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO` | 1.4 | 段落分界的行距倍数阈值 |
| `LAB_TOOLS_LAYOUT_INDENT_RATIO` | 0.5 | 引用块判定的缩进倍数阈值 |

> OCR 相关变量同时接受不带前缀的短名与历史的 `LAB_TOOLS_` 前缀名（短名优先），
> 因此既有部署脚本与 systemd 单元无需修改即可继续生效。

## 接口

- `POST /api/tools/doc-convert/convert` — 上传 `file`，表单参数 `output_format`（md/txt/docx）、`crop`（JSON：`{"unit":"ratio","x":..,"y":..,"width":..,"height":..}`）；返回转换结果与 `job_id`；
- `GET /api/tools/doc-convert/download/{job_id}` — 下载产物；
- `GET /api/tools/doc-convert/supported-formats` — 能力声明（本地格式 / OCR 格式 / 输出格式 / 上限 / OCR 节点地址）；
- `GET /api/tools/doc-convert/health` — 任务指标（成功 / 失败 / 平均耗时）+ OCR 节点探活（`ocr_status`）。

## 相关文档

- [OCR 节点（PaddleOCR）部署与依赖](ocr-node.md)
- [通讯录归档与管理工具](contact-manager.md)
- [README（工具总览 / 部署 / 全部环境变量）](../README.md)
