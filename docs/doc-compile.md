# 文档汇编（doc-compile）

批量上传 Word/WPS 文档（`.doc`、`.docx`、`.docm`、`.wps`、`.rtf`、`.txt`），自动识别标题与作者，拖拽排序后汇编为单个 Word 文档，可选目录、封面、篇间分页，输出 `docx / doc / wps`，并支持把修改后的标题作者写回源文档。

## 功能

- **批量上传与队列**：多文件一次上传，队列内**鼠标拖拽排序**；支持按文件名/标题排序、倒序、批量移除。
- **老格式兼容**：不信任扩展名，按「魔数」分类：
  | 魔数 | 真实类型 | 处理方式 |
  | --- | --- | --- |
  | `PK`（ZIP） | OOXML（docx/docm，及 WPS 以 OOXML 保存的 .wps） | python-docx 直接读，零依赖 |
  | OLE2 | 老版 `.doc` 等 | LibreOffice 转 docx |
  | `{\rtf` | RTF | LibreOffice 转 docx |
  | 文本 | txt | 直接组装 |
  | 其它二进制 | 真私有 .wps | 尝试 LibreOffice；失败则**丢弃并提示**（建议在 WPS 中另存 .docx） |
  无法处理的文件**自动丢弃**并在上传结果中列出中文原因，不进入队列。
- **标题/作者识别**：默认首行 = 标题、次行 = 作者；自动跳过日期/机构等元信息行、剥离「作者：」等前缀；可在网页中直接修改，**应用回源文档**（可选）。
- **汇编输出**：按队列顺序合并为单个 Word 文档；保留表格与插图（图片经关系重映射导入）；每篇 = 汇编标题 → 作者 → 原文正文，**原文自带的前部标题/作者段会被消费掉**（即便你把标题/作者改成了与原文不同的值也不会重复）；覆盖页与篇间分页可开关。
- **目录**：`field` 模式插入 Word 目录域（打开后提示更新域）；`custom` 模式静态目录，模板如
  - `<seq>. <title>……<author>`
  - `<seq>. <title>【<author>】……<page>`
  `……` 等引导符在 Word 中呈现为点线制表位；custom + 页码时通过 docx→pdf 分页定位（近似值，以 Word/WPS 打开后为准）。
- **输出格式**：`docx`（原生）；`doc`（需 LibreOffice）；`wps`（OOXML 兼容内容 + .wps 扩展名，WPS 通常可直接打开；如需原生 .wps 请在 WPS 中另存）。
- **安全**：`.docm` 宏不复制执行，仅汇编内容；加密/损坏文件明确报错丢弃。

## 依赖

| 依赖 | 用途 | 缺失时的影响 |
| --- | --- | --- |
| python-docx | 读/写/合并 docx（必须） | 工具不可用 |
| LibreOffice（soffice） | `.doc`/RTF/私有 .wps → docx；docx→`doc`；docx→PDF（预览/页码） | 老格式被丢弃并提示；预览降级为纯文本；`.doc` 输出禁用 |
| poppler-utils（pdftotext/pdftoppm/pdfinfo） | 预览渲染、页码定位 | 图片预览与目录页码不可用（纯文本预览可用） |

> 不依赖 PyMuPDF：sugon（mips64el / 龙芯）无该 wheel，PDF 能力走 poppler。
> LibreOffice 可 `sudo apt install libreoffice`（sugon 的 UOS 仓库有 mips64el 候选）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LAB_TOOLS_COMPILE_MAX_MB` | 50 | 单文件大小上限 |
| `LAB_TOOLS_SOFFICE_PATH` | 空=自动探测 | LibreOffice 可执行文件路径（Windows 下通常需显式指定） |
| `LAB_TOOLS_COMPILE_PREVIEW_DPI` | 150 | 预览渲染分辨率 |
| `LAB_TOOLS_COMPILE_CONVERT_TIMEOUT` | 120 | LibreOffice 转换进程超时（秒） |

## API

前缀 `/api/tools/doc-compile`：

| 方法/路径 | 说明 |
| --- | --- |
| `POST /upload` | 批量上传（multipart `files`，可多个）；返回 `items[]`（含 file_id/标题/作者/识别标记/警告）与 `dropped[]`（被丢弃文件+原因） |
| `GET /files/{file_id}/info` | 条目详情（含惰性计算的页数） |
| `GET /files/{file_id}/preview?page=N` | 指定页 PNG（需 LibreOffice+poppler；否则 503，可改用文本预览） |
| `GET /files/{file_id}/preview-text` | 首页纯文本预览（任何环境可用） |
| `PUT /files/{file_id}/meta` | 修改标题/作者；`apply_to_source`=true 时写回源文档 |
| `GET /files/{file_id}/source-download` | 下载（已写回的）源文档 |
| `POST /compile` | 汇编；body：`{items:[{file_id,title,author,apply_to_source}…], options:{output_format, toc:{enabled,mode,template,include_page_numbers}, cover:{…}, page_break_between, stylesheet}}`；items 顺序即队列顺序 |
| `GET /download/{job_id}` | 下载产物 |
| `GET /supported-formats` | 能力声明（转换器可用性、模板、各功能开关） |
| `GET /health` | 工具健康与转换器信息 |

## 设计决策

- **魔数分类优先于扩展名**：大量 `.wps` 实为 OOXML zip，直接按 docx 处理；真私有二进制才进入 LibreOffice/WPS 通道，失败即丢弃并提示（而不是静默或阻断整批）。
- **合并方向**：python-docx + lxml 深度合并（非 pandoc 文本拼接），保证表格/插图/行内样式保真；插图通过 `get_or_add_image` 按内容去重导入。页眉页脚与源节属性不跨篇复制（已知限制）。
- **自定义目录页码为近似值**：两遍法（第一遍带定位标记 → docx→pdf 反查每篇起始页 → 第二遍落真页码），与最终 Word/WPS 的翻页可能有 ±1 页偏差，提示用户打开后核对。
- **sugon 落地**：WPS 仅作存在性探测（无命令行自动化），`.wps` 输入依赖 WPS 桌面另存；`.doc` 能力依赖安装 LibreOffice。

## 测试

```bash
cd backend && python -m pytest tests/test_doc_compile.py -v
```

LibreOffice/poppler 相关的用例（图片预览、目录页码、`.doc` 输出）在缺工具时自动跳过。