# 文档转换工具（doc-convert）说明

本文档对应后端工具包 `backend/app/tools/doc_convert/` 与前端页面 `frontend/src/views/DocConvertView.vue`（路由 `/tools/doc-convert`）。核心逻辑移植自 puremark-converter。

## 功能概述

- **统一上传入口**：一个 `/convert` 端点按文件扩展名自动路由，无需用户选择引擎；
- **三种输出格式**：Markdown（默认）、纯文本（txt）、Word（docx）；
- **区域裁剪**：图片与 PDF 支持可视化框选（前端 Cropper），按同一比例裁剪后再转换；
- **版面重建**：对 OCR 结果按行级 bbox 做几何启发式排版（标题层级 / 段落 / 缩进 / 引用块），输出更接近原文档的 Markdown；
- **OCR 节点转发与降级**：图片 / 扫描 PDF 优先转发独立 OCR 节点（`ocr_server/`，PaddleOCR），节点不可达时自动降级为主服务本地 PaddleOCR，再不可用时文本型 PDF 仍可退回 MarkItDown。

## 支持格式与路由策略

| 输入类型 | 扩展名 | 处理方式 |
| --- | --- | --- |
| 办公文档 / 文本 | `.docx` `.xlsx` `.pptx` `.txt` `.csv` `.html` `.htm` `.xml` `.json` `.md` `.zip` `.epub` `.rtf` `.odt` `.ods` `.odp` | 本地 MarkItDown 提取（不经过 OCR） |
| 图片 | `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.tiff` `.webp` | OCR：优先转发 OCR 节点 → 降级本地 PaddleOCR |
| PDF | `.pdf` | 先分类：**文本型**（前 3 页字符数 ≥ `PDF_TEXT_THRESHOLD`，默认 50）走 MarkItDown；**扫描型**走 OCR（同上含降级） |

区域裁剪的分支行为：

- 图片：按比例裁剪后识别；
- 文本型 PDF：按比例裁剪每页并直接提取文字层，不走 OCR（`engine=pdfplumber_crop`）；
- 扫描型 PDF：按比例裁剪每页并渲染成 PNG，逐页 OCR 后拼接（`engine=paddleocr_cpu[_local]`）；
- 办公格式：不支持裁剪，忽略 crop 并整份转换（响应 `crop_ignored`）。

## 输出格式

- **md**：MarkItDown / OCR 原始结果；
- **txt**：用 `strip_markdown_light` 剥离常见 Markdown 语法（标题、链接、表格转为空格分隔等）；
- **docx**：Markdown → Word，**pandoc 优先**（可指定 `--reference-doc` 参考模板），pandoc 未安装或转换失败时自动降级为 **python-docx 手写引擎**（支持标题 / 表格 / 列表 / 引用块 / 分割线 / 代码块 / 行内样式），响应中的 `docx_engine` 标识实际使用的引擎。

注意：源文件是 `.docx` 时再选 docx 输出会被拒绝（会先转 Markdown 再重建，原始排版必然丢失），请直接使用原文件。

## 依赖（backend/requirements.txt）

### 必装（基础 + doc-convert）

| 包 | 用途 | 说明 |
| --- | --- | --- |
| fastapi / uvicorn / python-multipart | Web 框架与上传 | |
| pandas / openpyxl / xlrd | Excel 工具（拆分 / 比对） | `pandas>=2.0,<3.0`：**Python 3.14 无对应 wheel**（需 pandas 3.x 才支持），详见下文 Python 版本 |
| pytest / httpx | 测试 | |
| **markitdown[all]** | office 文档 / 文本型 PDF 的 Markdown 提取 | `[all]` 聚合全部转换后端，其中**音频转写（audio-transcription）会引入 torch / transformers / openai-whisper 等重型依赖**，安装体积很大。若不需要音频转写，可自行减配为 `markitdown[docx,pptx,xlsx,pdf]` 等轻量组合 |
| **pdfplumber** | 文本型 PDF 提取 / 分类 / 裁剪 | |
| **pymupdf** (fitz) | 扫描型 PDF 渲染 / 裁剪 | 同样受 Python 版本 wheel 影响 |
| **python-docx** | Markdown → docx 兜底引擎 | |
| **pillow** | 图片解码 / 裁剪 | |
| **requests** | OCR 节点转发与探活 | |
| **psutil** | 健康检查 CPU / 内存指标 | |

### 可选（本地 OCR 降级）

| 包 | 用途 | 说明 |
| --- | --- | --- |
| paddleocr + paddlepaddle | 主服务本地 OCR 降级引擎 | 不安装时：OCR 节点离线 → 图片 / 扫描 PDF 转换失败（文本型 PDF 仍可退回 MarkItDown）；安装版本约束与 OCR 节点一致，见 [OCR 节点文档](ocr-node.md) |

> 说明：`ocr_server/requirements.txt` 中的 `markitdown` 为历史遗留（OCR 节点本身不执行办公格式转换，其完整依赖以 `ocr_server/requirements_win11.txt` 为准）；`backend/requirements.txt` 中的 `markitdown[all]` 是 doc-convert 的必需依赖。

### Python 版本要求（重要）

| 组件 | 建议版本 | 原因 |
| --- | --- | --- |
| 后端（backend/） | **Python 3.10 – 3.13**（推荐 3.12） | 截至当前，`pandas 2.x`、`pymupdf` 尚无 Python 3.14 的预编译 wheel（3.14 需要 pandas 3.x，与 `pandas<3.0` 约束冲突；pymupdf 需更高版本）；请在 3.13 及以下环境安装 |
| OCR 节点（ocr_server/） | **Python 3.11**（实测 3.11.9） | `paddlepaddle==2.6.2` 与 `paddleocr==2.7.0.3` 的组合以 3.11 为准 |

## 可选能力配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LAB_TOOLS_CONVERT_MAX_MB` | 50 | 转换文件大小上限 |
| `LAB_TOOLS_OCR_NODE_URL` | http://127.0.0.1:8001 | OCR 节点地址 |
| `LAB_TOOLS_OCR_TIMEOUT` | 120 | 转发 OCR 节点的请求超时（秒） |
| `LAB_TOOLS_OCR_NODE_NAME` / `LAB_TOOLS_OCR_NODE_ROLE` | win11 / heavy | OCR 节点身份（仅展示用） |
| `LAB_TOOLS_PDF_TEXT_THRESHOLD` | 50 | PDF 文本/扫描分类的字符数阈值 |
| `LAB_TOOLS_CROP_PDF_ZOOM` | 2.0 | 扫描 PDF 裁剪渲染缩放倍率 |
| `LAB_TOOLS_PANDOC_TIMEOUT` | 30 | pandoc 转换超时（秒） |
| `LAB_TOOLS_DOCX_REFERENCE_TEMPLATE` | 空 | pandoc 参考模板路径（存在时自动附加 `--reference-doc`） |
| `LAB_TOOLS_LAYOUT_RECONSTRUCTION` | true | 是否启用 OCR 版面重建 |
| `LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO` | 1.3 | 标题判定的行高倍数阈值 |
| `LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO` | 1.4 | 段落分界的行距倍数阈值 |
| `LAB_TOOLS_LAYOUT_INDENT_RATIO` | 0.5 | 引用块判定的缩进倍数阈值 |

## 接口

- `POST /api/tools/doc-convert/convert` — 上传 `file`，表单参数 `output_format`（md/txt/docx）、`crop`（JSON：`{"unit":"ratio","x":..,"y":..,"width":..,"height":..}`）；返回转换结果与 `job_id`；
- `GET /api/tools/doc-convert/download/{job_id}` — 下载产物；
- `GET /api/tools/doc-convert/supported-formats` — 能力声明（本地格式 / OCR 格式 / 输出格式 / 上限 / OCR 节点地址）；
- `GET /api/tools/doc-convert/health` — 任务指标（成功 / 失败 / 平均耗时）+ OCR 节点探活（`ocr_status`）。

## 相关文档

- [OCR 节点（PaddleOCR）部署与依赖](ocr-node.md)
- [README（工具总览 / 部署 / 全部环境变量）](../README.md)
