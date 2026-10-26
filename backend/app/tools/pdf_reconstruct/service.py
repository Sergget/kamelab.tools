"""PDF 高保真转 Word 服务：包装 ``kame-officetools`` 内核。

内核（``apps/kame-officetools``）是从桌面客户端抽出的独立包，负责
数字版/扫描版双路径提取、版面归并与手写 OOXML 写出。本模块只做三件事：
落临时文件、调内核、把结果整理成 HTTP 层能用的形状。

内核一律**惰性导入**：没装内核时其它工具照常启动，只有本工具的路由报 503。
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PDF_EXTENSION = ".pdf"
ENGINE_NAME = "kame-officetools"

# 内核抛的是裸 Python 异常，直接透给前端既看不懂又会漏临时目录路径。
# 已知内部错误映射成人话，其余做路径脱敏。
_INTERNAL_ERROR_HINTS = (
    ("Failed to open file", "文件不是有效的 PDF，或文件已损坏，无法解析"),
    ("as type pdf", "文件不是有效的 PDF，或文件已损坏，无法解析"),
    ("'NoneType' object is not iterable",
     "内核没能从该 PDF 中读到内容，可能是空白页或图像层异常"),
)


def _friendly_error(raw: str) -> str:
    """把内核的内部异常转成能展示给用户的文案；原始信息只进日志。"""
    text = (raw or "").strip()
    for token, message in _INTERNAL_ERROR_HINTS:
        if token in text:
            return message
    cleaned = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "临时文件", text)
    return cleaned or "PDF 转换失败"


class ReconstructError(ValueError):
    """业务错误，携带建议的 HTTP 状态码。"""

    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def kernel_version() -> str:
    """内核版本号；未安装时返回空串（供 health 展示，不抛错）。"""
    try:
        from kame_officetools import __version__
    except Exception:
        return ""
    return __version__


def kernel_available() -> bool:
    try:
        import kame_officetools  # noqa: F401
    except Exception:
        return False
    return True


def _sanitize_stem(filename: str) -> str:
    """把上传文件名压成安全的输出主名（去掉路径分隔符与 Windows 非法字符）。"""
    stem = Path(filename or "").stem.strip() or "document"
    for ch in '<>:"/\\|?*':
        stem = stem.replace(ch, "_")
    stem = stem.strip(" .")
    return stem[:80] or "document"


def convert_pdf_to_docx(file_bytes: bytes,
                        filename: str,
                        max_pages: Optional[int] = None,
                        on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                        ) -> Dict[str, Any]:
    """把单个 PDF 转成 DOCX。

    Returns:
        ``{"content": bytes, "download_name": str, "pdf_type": str,
        "chars": int, "elapsed_ms": int}``

    Raises:
        ReconstructError: 内核缺失、转换失败或提取不到任何文字。
    """
    if not file_bytes:
        raise ReconstructError("文件为空", 400)

    try:
        from kame_officetools import PipelineOptions, process_pdf_folder
    except Exception as exc:  # 未安装内核
        logger.error("PDF 转换内核不可用: %s", exc)
        raise ReconstructError(
            f"PDF 转换内核不可用（kame-officetools 未安装）：{exc}", 503
        ) from exc

    t_start = time.perf_counter()
    work_dir = Path(tempfile.mkdtemp(prefix="pdfrecon_"))
    try:
        in_dir = work_dir / "in"
        out_dir = work_dir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        # 内核用 input_dir.glob("*.pdf") 找文件，大写扩展名会被漏掉，
        # 所以这里统一落成小写 .pdf，文件名与内容都不影响识别。
        pdf_path = in_dir / f"{_sanitize_stem(filename)}.pdf"
        pdf_path.write_bytes(file_bytes)

        options = PipelineOptions(enable_ai=False, max_pages=max_pages)

        events: List[Dict[str, Any]] = []

        def _collect(evt: Dict[str, Any]) -> None:
            events.append(evt)
            if on_event is not None:
                on_event(evt)

        results = process_pdf_folder(
            in_dir,
            out_dir,
            options,
            on_event=_collect,
            max_workers=1,
        )
        if len(results) != 1:
            raise ReconstructError("内核没有产出转换结果，请确认上传的是有效 PDF", 422)

        result = results[0]
        if not result.ok or result.output_path is None:
            logger.warning("内核转换失败 %s: %s", filename, result.error)
            raise ReconstructError(_friendly_error(result.error), 422)

        chars = 0
        pdf_type = ""
        for evt in events:
            if evt.get("type") == "stitch_done":
                chars = int(evt.get("chars") or 0)
            elif evt.get("type") == "pdf_start":
                pdf_type = evt.get("pdf_type") or ""

        if chars == 0:
            # 与 doc-convert 的空结果守卫同源：内核在没提到任何文字时仍会写出
            # 一个空 DOCX 并返回 ok=True，直接放行就是"转换成功但什么都没"。
            if pdf_type == "scanned":
                detail = ("该 PDF 是扫描件，且 OCR 没有识别出内容。"
                          "请确认 OCR 引擎可用后重试")
            else:
                detail = "该 PDF 没有可提取的文字层，请确认文件是否为扫描件或空文档"
            raise ReconstructError(detail, 422)

        docx_bytes = result.output_path.read_bytes()
        if not docx_bytes:
            raise ReconstructError("转换产出的 Word 文件为空，请重试", 500)

        return {
            "content": docx_bytes,
            "download_name": f"{_sanitize_stem(filename)}.docx",
            "pdf_type": pdf_type,
            "chars": chars,
            "elapsed_ms": int((time.perf_counter() - t_start) * 1000),
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
