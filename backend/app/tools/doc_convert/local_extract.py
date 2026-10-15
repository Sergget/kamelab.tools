"""纯 Python 本地文档内容提取（MarkItDown 替代实现）。

用于无法安装 MarkItDown 依赖链的平台（如 mips64el 上 magika→onnxruntime
无预编译 wheel 且不可源码编译）。全部依赖均为纯 Python 或已验证可编译：

    .txt / .md / .log 等文本        → 直接解码
    .csv                            → csv 模块 → Markdown 表格
    .json / .xml                    → 直接解码（原样保留）
    .html / .htm                    → 轻量标签剥离 → 文本
    .docx                           → mammoth（纯 Python）→ Markdown
    .xls                            → xlrd → Markdown 表格
    .xlsx / .xlsm                   → openpyxl → Markdown 表格
    .pptx                           → python-pptx → 逐页文本
"""

from __future__ import annotations

import csv
import io
import logging
import re
from html import unescape
from typing import List

logger = logging.getLogger(__name__)

# 单表最多渲染行数（防止超大表格撑爆内存/前端）
MAX_TABLE_ROWS = 2000


class LocalExtractError(ValueError):
    """本地提取失败（不支持的格式 / 文件损坏等）。"""


def extract_markdown(file_bytes: bytes, ext: str) -> str:
    """按扩展名分发到对应的纯 Python 提取器，返回 Markdown 文本。"""
    handlers = {
        ".docx": _extract_docx,
        ".xls": _extract_xls,
        ".xlsx": _extract_xlsx,
        ".xlsm": _extract_xlsx,
        ".csv": _extract_csv,
        ".pptx": _extract_pptx,
        ".html": _extract_html,
        ".htm": _extract_html,
        ".json": _extract_text,
        ".xml": _extract_text,
        ".md": _extract_text,
        ".txt": _extract_text,
    }
    handler = handlers.get(ext)
    if handler is None:
        raise LocalExtractError(f"本地提取不支持 {ext} 格式")
    try:
        return handler(file_bytes)
    except LocalExtractError:
        raise
    except Exception as exc:
        raise LocalExtractError(f"{ext} 内容提取失败: {exc}") from exc


# ---- 文本类 ----

def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_text(file_bytes: bytes) -> str:
    return _decode_bytes(file_bytes)


# ---- HTML：轻量标签剥离 ----

_BLOCK_TAGS_RE = re.compile(
    r"</?(p|div|br|h[1-6]|li|tr|table|ul|ol|blockquote|section|article)[^>]*>",
    re.IGNORECASE,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def _extract_html(file_bytes: bytes) -> str:
    text = _decode_bytes(file_bytes)
    text = _SCRIPT_STYLE_RE.sub("", text)
    # 块级标签转换行；表格行加分隔便于阅读
    text = re.sub(r"</(h[1-6]|p|div|li|tr|blockquote)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]>", " | ", text, flags=re.IGNORECASE)
    text = _BLOCK_TAGS_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub("", text)
    text = unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---- Markdown 表格工具 ----

def _escape_cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _rows_to_markdown(rows: List[List[str]]) -> str:
    rows = rows[:MAX_TABLE_ROWS]
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    norm = [(r + [""] * ncols)[:ncols] for r in rows]
    out: List[str] = []
    out.append("| " + " | ".join(_escape_cell(c) for c in norm[0]) + " |")
    out.append("|" + "|".join([" --- "] * ncols) + "|")
    for r in norm[1:]:
        out.append("| " + " | ".join(_escape_cell(c) for c in r) + " |")
    return "\n".join(out)


# ---- CSV ----

def _extract_csv(file_bytes: bytes) -> str:
    text = _decode_bytes(file_bytes)
    sample = text[:4096]
    delim = ";"
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        pass
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delim) if any(row)]
    return _rows_to_markdown(rows)


# ---- DOCX（mammoth）----

def _extract_docx(file_bytes: bytes) -> str:
    import mammoth

    with io.BytesIO(file_bytes) as stream:
        result = mammoth.convert_to_markdown(stream)
    md = result.value or ""
    messages = [m.message for m in result.messages[:10]]
    if messages:
        logger.info("mammoth 提示: %s", "; ".join(messages))
    return md.strip()


# ---- XLSX（openpyxl）/ XLS（xlrd）----

def _sheet_rows(rows_iter) -> str:
    rows = [[("" if c is None else c) for c in row] for row in rows_iter]
    # 去掉整行为空的尾部
    while rows and not any(str(c).strip() for c in rows[-1]):
        rows.pop()
    return _rows_to_markdown([[str(c) for c in r] for r in rows])


def _extract_xlsx(file_bytes: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    parts: List[str] = []
    try:
        for ws in wb.worksheets:
            parts.append(f"## {ws.title}\n\n{_sheet_rows(ws.iter_rows(values_only=True))}")
    finally:
        wb.close()
    return "\n\n".join(p for p in parts if p.strip())


def _extract_xls(file_bytes: bytes) -> str:
    import xlrd

    wb = xlrd.open_workbook(file_contents=file_bytes)
    parts: List[str] = []
    for ws in wb.sheets():
        rows = [ws.row_values(r) for r in range(ws.nrows)]
        parts.append(f"## {ws.name}\n\n{_sheet_rows(rows)}")
    return "\n\n".join(p for p in parts if p.strip())


# ---- PPTX（python-pptx）----

def _extract_pptx(file_bytes: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(file_bytes))
    parts: List[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        blocks: List[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                txt = "\n".join(
                    para.text for para in shape.text_frame.paragraphs if para.text.strip()
                )
                if txt.strip():
                    blocks.append(txt)
            if getattr(shape, "has_table", False):
                tbl = [
                    [cell.text for cell in row.cells]
                    for row in shape.table.rows
                ]
                rendered = _rows_to_markdown(tbl)
                if rendered:
                    blocks.append(rendered)
        if blocks:
            parts.append(f"## 第 {idx} 页\n\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)


