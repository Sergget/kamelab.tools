# PDF 高保真转 Word（pdf-reconstruct）说明

本文档对应后端工具包 `backend/app/tools/pdf_reconstruct/` 与前端页面 `frontend/src/views/PdfReconstructView.vue`（路由 `/tools/pdf-reconstruct`）。转换逻辑不在本仓库，全部委托给独立内核包 **`kame-officetools-core`**（源码 `../kame-officetools-core`）。

## 和"文档转换"有什么不一样

两个工具都能出 `.docx`，但走的不是同一条路：

| | 文档转换（doc-convert） | PDF 高保真转 Word（pdf-reconstruct） |
| --- | --- | --- |
| 输入 | office / 图片 / PDF / 文本等 20 余种 | **仅 PDF** |
| 出 docx 的路径 | 先转 Markdown，再 pandoc / python-docx 重建 | 直接按原版面结构生成 OOXML |
| 段落边界 | 由 Markdown 语义决定 | 由**行距 + 标点**启发式还原 |
| 排版保真度 | 低（标题层级、表格会变形） | 较高（保留段落切分与缩进意图） |
| 表格 / 图片 | 转成 Markdown 表格，基本可读 | **不保证保留**，会退化为文本行 |

一句话：要"能编辑、段落对得上"用这个；要"多种格式统一转成可检索文本"用文档转换。

## 处理流程

1. **类型判定**（内核 `detector.py`）：取首屏文字，字数 > 50 判为数字版；字数少但页面没有被一张大图占满时，**仍按数字版处理**（票据、证明、单页短函属于这一类，早期版本会误判成扫描件白跑一遍 OCR）。
2. **文字提取**：
   - 数字版 → `pdfplumber` 直接取文字层；
   - 扫描件 → 逐页渲染成位图后走 PaddleOCR（与 doc-convert 共用同一套 OCR 依赖）。
3. **段落还原**（内核 `processor.py:join_blocks`）：按 `页码 → y → x` 排序后，用三条规则断段——中文句末标点、下一行以列表序号开头、行间距超过 1.2 倍行高。半角标点后接西文单词会补空格。
4. **写 docx**：手写 OOXML，不依赖 python-docx。

**默认会裁边**：内核按页宽的 8% 裁左右、页高的 10% 裁上下，目的是去掉页眉页脚和页码。这是内核默认行为，当前没有暴露成前端开关。

## 已知边界

- 只认**中文句末标点**（`。！？`）断段。英文 PDF 以 `.` 结尾的句子不会断段，整页可能合并成一整段——这是有意的：把 `.` 纳入断段规则会把 `1.` 列表项和 `3.11` 这类版本号全打坏。
- 表格不结构化，会变成按行排列的纯文本。
- 多栏排版按 y 坐标顺序读取，可能出现左右栏交错。
- 图片、页眉页脚、脚注不保留。

## 依赖

### 内核（必需）

```bash
cd backend
.venv/bin/python -m pip install -e ../../kame-officetools-core
```

内核自身只依赖 `pdfplumber` / `pillow` / `numpy`；`pymupdf` 与 `paddleocr` 都是**按需懒加载**——纯数字版 PDF 不需要它们。

`pip install -e` 因内网索引不可达挂起时，用 `.pth` 等价替代（内容为内核 `src` 绝对路径，单行、UTF-8 无 BOM、不带结尾换行）：

```text
# backend/.venv/Lib/site-packages/kame_officetools_core_dev.pth
E:\Code\Kamelab\apps\kame-officetools-core\src
```

**内核缺失时的行为**：主服务照常启动，工具仍在 `/api/tools` 列表里，但 `/health` 返回 `DOWN`、转换请求返回 503（detail 会说明内核未安装）。前端在页面顶部显示红色告警并禁用"开始转换"。测试层面 `tests/test_pdf_reconstruct.py` 里依赖内核的 3 条用例会自动 skip（实测无内核 70 passed / 3 skipped，装内核 73 passed）。

### 扫描件（可选）

走 OCR 的 PDF 需要 `paddleocr` + `paddlepaddle`，与文档转换共用，不额外安装。版本约束见 [OCR 节点文档](ocr-node.md)。

### Python 版本

**3.11+**（内核 `requires-python >= 3.11`）。后端其它工具支持 3.10，装了本工具就等于把下限抬到 3.11。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LAB_TOOLS_RECONSTRUCT_MAX_MB` | 50 | 转换文件大小上限，超限返回 413 |
| `LAB_TOOLS_RECONSTRUCT_MAX_PAGES` | 0 | 单次转换页数上限，0 = 不限。扫描件建议设小值（如 20），避免单请求长时间占用 |

## 接口

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/tools/pdf-reconstruct/convert` | 上传 `file`（仅 `.pdf`），返回转换结果与 `job_id` |
| `GET /api/tools/pdf-reconstruct/download/{job_id}` | 下载产物（`application/vnd.openxmlformats-officedocument.wordprocessingml.document`） |
| `GET /api/tools/pdf-reconstruct/health` | 内核可用性探活：`status` / `engine` / `kernel_version` / `max_file_size_mb` / `max_pages` / `detail` |

### 响应字段

| 字段 | 说明 |
| --- | --- |
| `success` | 恒为 `true`（失败走 HTTP 错误码，不会返回假成功） |
| `job_id` | 下载凭据，受 `LAB_TOOLS_TTL_HOURS` 约束 |
| `download_name` | 输出文件名，由原文件名去掉非法字符后加 `.docx` |
| `pdf_type` | `digital`（有文字层）或 `scanned`（走了 OCR） |
| `chars` | 提取到的字符数 |
| `elapsed_ms` | 转换耗时（毫秒） |
| `engine` | 固定 `kame-officetools-core` |
| `kernel_version` | 内核版本，如 `0.1.0` |

**没有 `pages` 字段**——内核的 `ProcessResult` 不返回页数，这里不编一个出来。

### 错误码

| 状态码 | 场景 |
| --- | --- |
| 400 | 非 PDF 扩展名、文件为空 |
| 413 | 超过 `LAB_TOOLS_RECONSTRUCT_MAX_MB` |
| 422 | 内核转换失败（文件损坏、空白页无内容、扫描件 OCR 也没识别出东西） |
| 500 | 内核报告成功但产物为空 |
| 503 | 内核未安装 |

422 的 detail 是**面向用户的中文文案**。内核抛的是裸 Python 异常（例如 `Failed to open file 'C:\Users\...\pdfrecon_x\in\a.pdf' as type pdf.`），`service.py:_friendly_error()` 会把已知内部错误映射成人话、其余做 Windows 路径脱敏，原始信息只进日志。

## 实现要点

- **只调内核的公开 API**：用 `process_pdf_folder()` 处理一个只含单个 PDF 的临时目录，不碰私有的 `_process_single_pdf`。代价是多一次目录遍历，收益是内核内部重构时这个工具不用跟着改。
- **空内容判据来自事件**：`ProcessResult` 只有 `pdf_path` / `ok` / `output_path` / `error`，没有字符数。要判断"是不是空的"只能读 `on_event` 收到的 `stitch_done` 事件里的 `chars`——比再调一次提取器便宜。
- **临时目录即用即删**：转换在 `tempfile.mkdtemp()` 里完成，`finally` 里 `rmtree`；产物另存到 `data/` 受 TTL 清理。

## 相关文档

- [文档转换工具（doc-convert）](doc-convert.md)
- [OCR 节点（PaddleOCR）部署与依赖](ocr-node.md)
- [README（工具总览 / 部署 / 全部环境变量）](../README.md)
- 内核设计与迁移记录：`../../docs/branch-merge-and-desktop-diet.md` §10.4–§10.8
