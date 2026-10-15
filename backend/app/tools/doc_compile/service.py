"""文档汇编业务编排（doc-compile）。"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document as DocxDocument

from ... import config, temp_files
from . import converters, detect, merge, toc as toc_mod
from .models import CompileOptions, CompileRequest

# 简单计数指标
_metrics_lock = threading.Lock()
_metrics = {"uploads": 0, "drops": 0, "compiles": 0}


def _bump(name: str, delta: int = 1) -> None:
    with _metrics_lock:
        _metrics[name] = _metrics.get(name, 0) + delta


def get_metrics() -> Dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)


# ---------------------------------------------------------------------------
# 上传处理
# ---------------------------------------------------------------------------

def process_upload(content: bytes, original_name: str) -> Tuple[Optional[Dict], Optional[str]]:
    """处理一个上传文件：分类→转 docx→识别标题作者→落盘。

    返回 (item_dict, None) 成功 或 (None, 丢弃原因中文) 失败。
    """
    ext = (Path(original_name).suffix or "").lower()
    if ext not in config.COMPILE_ALLOWED_EXTENSIONS:
        return None, f"不支持的扩展名 {ext or '（无）'}（支持 doc/docx/docm/wps/rtf/txt）"
    if not content or not content.strip():
        return None, "文件为空"

    classified = converters.classify(content)
    warnings: List[str] = []

    # ---- 转换为统一 docx ----
    if classified == "docx":
        if not converters.valid_docx(content):
            # zip 但不是可读 OOXML：尝试 LibreOffice 兜底
            converted = converters.convert_with_soffice(content, ext, "docx")
            if converted is None:
                _bump("drops")
                return None, "文件不是有效的 Word 文档（OOXML 结构损坏或加密）"
            warnings.append("原文件结构异常，已通过 LibreOffice 转换读取")
        else:
            converted = content
        if ext == ".docm":
            warnings.append("docm 宏不会保留（仅汇编内容）")
    elif classified in ("doc", "rtf", "unknown"):
        if not converters.soffice_available():
            hint = "（私有 .wps 需在 WPS 中「另存为 .docx」后上传）" if ext == ".wps" else ""
            _bump("drops")
            return None, f"需要服务器安装 LibreOffice 才能转换 {ext} 老格式{hint}"
        converted = converters.convert_with_soffice(content, ext, "docx")
        if converted is None:
            _bump("drops")
            return None, f"{ext} 转换失败：文件可能已加密或格式不受支持"
        if ext == ".wps":
            warnings.append("该 .wps 为私有格式，已尽力转换，结果可能不完整")
    elif classified == "plain":
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            text = content.decode("gbk", errors="replace")
        converted = converters.text_to_docx_bytes(text)
    else:
        return None, "无法识别的文件格式"

    # ---- 标题 / 作者识别 ----
    doc = DocxDocument(io.BytesIO(converted))
    lines = detect.first_nonempty_paragraphs(doc)
    title, author, auto_detected, det_warnings = detect.detect_title_author(
        lines, original_name,
    )
    warnings.extend(det_warnings)
    # 识别标题是否为「文件名兜底」：仅在识别到真实标题时才启用正文前缀强消费
    title_from_filename = any("未识别标题" in w for w in det_warnings)

    file_id = temp_files.new_id()
    temp_files.save_work_file(file_id, f"original{ext}", content)
    temp_files.save_work_file(file_id, "converted.docx", converted)
    meta = {
        "original_name": original_name,
        "ext": ext,
        "classified_as": classified,
        "title": title,
        "author": author,
        "auto_detected": auto_detected,
        "title_from_filename": title_from_filename,
        "warnings": warnings,
        "source_updated": False,
    }
    temp_files.write_work_json(file_id, "meta.json", meta)

    _bump("uploads")
    return _item_dict(file_id, meta), None


# ---------------------------------------------------------------------------
# 条目元数据
# ---------------------------------------------------------------------------

def _item_dict(file_id: str, meta: Dict) -> Dict:
    return {
        "file_id": file_id,
        "original_name": meta.get("original_name", ""),
        "ext": meta.get("ext", ""),
        "classified_as": meta.get("classified_as", ""),
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "auto_detected": meta.get("auto_detected", False),
        "warnings": meta.get("warnings", []),
        "source_updated": meta.get("source_updated", False),
        "page_count": None,  # 由 /info 惰性计算
    }


def load_item(file_id: str) -> Optional[Dict]:
    meta = temp_files.read_work_json(file_id, "meta.json")
    if not meta or not temp_files.read_work_file(file_id, "converted.docx"):
        return None
    return _item_dict(file_id, meta)


def update_meta(file_id: str, title: str, author: str,
                apply_to_source: bool = False) -> Optional[Dict]:
    """更新标题/作者；可选写回源文档。返回更新后的条目或 None。"""
    meta = temp_files.read_work_json(file_id, "meta.json")
    if not meta:
        return None
    title = title.strip()
    author = author.strip()
    meta["title"] = title if title else meta.get("title", "")
    meta["author"] = author if author else meta.get("author", "")
    if title or author:
        meta["auto_detected"] = False
    meta.setdefault("warnings", [])

    if apply_to_source:
        converted = temp_files.read_work_file(file_id, "converted.docx")
        if converted is None:
            return None
        rewritten = converters.rewrite_first_paragraphs(
            converted, meta["title"] or "（未命名）", meta["author"],
        )
        ext = meta.get("ext", ".docx")
        soclass = meta.get("classified_as", "docx")
        native = soclass == "docx"  # OOXML 源（docx/docm，及 OOXML 型 .wps）
        if native:
            temp_files.save_work_file(file_id, f"updated{ext}", rewritten)
            meta["source_updated"] = True
        else:
            back = converters.convert_with_soffice(rewritten, ".docx", ext.lstrip("."))
            if back is None:
                msg = ("写回源文档失败：缺少 LibreOffice 或转换失败，"
                       "已修改的标题/作者仍将用于汇编输出")
                if msg not in meta["warnings"]:
                    meta["warnings"].append(msg)
            else:
                temp_files.save_work_file(file_id, f"updated{ext}", back)
                meta["source_updated"] = True

    temp_files.write_work_json(file_id, "meta.json", meta)
    return _item_dict(file_id, meta)


def get_page_count(file_id: str) -> Optional[int]:
    pdf = _ensure_preview_pdf(file_id)
    if pdf is None:
        return None
    return converters.pdfinfo_pages(pdf)


def get_preview_text(file_id: str) -> str:
    converted = temp_files.read_work_file(file_id, "converted.docx")
    if converted is None:
        return ""
    doc = DocxDocument(io.BytesIO(converted))
    lines = detect.first_nonempty_paragraphs(doc)
    text = "\n".join(lines)
    return text[:2000]


def _ensure_preview_pdf(file_id: str) -> Optional[bytes]:
    """转换 docx→pdf 并缓存（preview.pdf）。不可用时返回 None。"""
    cached = temp_files.read_work_file(file_id, "preview.pdf")
    if cached:
        return cached
    converted = temp_files.read_work_file(file_id, "converted.docx")
    if converted is None:
        return None
    pdf = converters.convert_with_soffice(converted, ".docx", "pdf")
    if pdf is None:
        return None
    temp_files.save_work_file(file_id, "preview.pdf", pdf)
    return pdf


def render_preview_png(file_id: str, page: int) -> Optional[bytes]:
    pdf = _ensure_preview_pdf(file_id)
    if pdf is None:
        return None
    return converters.pdftoppm_page_png(pdf, page, config.COMPILE_PREVIEW_DPI)


# ---------------------------------------------------------------------------
# 汇编
# ---------------------------------------------------------------------------

def _resolve_items(req: CompileRequest) -> Tuple[List[Dict], List[Dict], List[str]]:
    """解析队列项为合并输入；返回 (items, errors, warnings)。

    队列顺序 = 请求 items 顺序。某个文件缺失/无法识别时不中断整体汇编，
    记入 errors。
    """
    items: List[Dict] = []
    errors: List[Dict] = []
    warnings: List[str] = []
    for i, req_item in enumerate(req.items, start=1):
        meta = temp_files.read_work_json(req_item.file_id, "meta.json")
        if not meta:
            errors.append({"original_name": req_item.file_id, "reason": "上传文件不存在或已过期"})
            continue
        converted = temp_files.read_work_file(req_item.file_id, "converted.docx")
        if converted is None:
            errors.append({"original_name": meta.get("original_name", ""), "reason": "转换产物缺失"})
            continue
        title = req_item.title.strip() or meta.get("title", "") or "未命名文档"
        author = req_item.author.strip() or meta.get("author", "") or ""
        if req_item.apply_to_source:
            updated = update_meta(req_item.file_id, req_item.title, req_item.author, True)
            if updated is None:
                errors.append({"original_name": meta.get("original_name", ""), "reason": "写回源文档失败"})
        items.append({
            "seq": i,
            "file_id": req_item.file_id,
            "title": title,
            "author": author,
            "original_name": meta.get("original_name", ""),
            "docx_bytes": converted,
            # 跳过源文档前缀中与「识别值/当前值」匹配的标题作者段，避免重复
            "skip_texts": [meta.get("title", ""), meta.get("author", ""), title, author],
            # 原文头部确有真实标题时才启用启发式前缀消费（避免误吞无标题文档）
            "strong_skip": bool(meta.get("title")) and not meta.get("title_from_filename", False),
        })
    return items, errors, warnings


def compile_documents(req: CompileRequest) -> Dict:
    """执行汇编：合并→（可选页码反查）→按输出格式产出→落盘 job。"""
    items, errors, warnings = _resolve_items(req)
    if not items:
        raise ValueError("没有可汇编的文档，请检查队列")

    opts = req.options
    for it in items:
        it["warnings"] = []

    # ---- 自定义目录页码（两遍法：第一遍带定位标记，PDF 反查页码，第二遍落真值）----
    toc_pages: Optional[Dict[int, Optional[int]]] = None
    use_pages = (
        opts.toc.enabled and opts.toc.mode == "custom"
        and opts.toc.include_page_numbers
        and converters.soffice_available() and converters.poppler_available()
    )
    if use_pages:
        markers = [f"@@CMARK_{i:04d}@@" for i in range(1, len(items) + 1)]
        pass1 = merge.build_compiled_docx(items, opts, toc_pages=None, markers=markers)
        pass1_bytes = merge.save_docx(pass1)
        pdf = converters.convert_with_soffice(pass1_bytes, ".docx", "pdf")
        if pdf is not None:
            total = converters.pdfinfo_pages(pdf) or 0
            found = converters.locate_page_nums(total, pdf, markers)
            toc_pages = {i + 1: found[i] for i in range(len(items))}
            missing = sum(1 for v in found if v is None)
            if missing:
                warnings.append(f"{missing} 篇未能定位起始页（目录页码可能缺失，建议以 Word/WPS 打开后核对）")
        else:
            warnings.append("页码反查失败（docx→pdf 转换不可用），目录将不显示页码")

    # ---- 最终构建 ----
    doc = merge.build_compiled_docx(items, opts, toc_pages=toc_pages)
    docx_bytes = merge.save_docx(doc)

    # ---- 输出格式 ----
    out_format = opts.output_format.lower()
    if out_format not in ("docx", "doc", "wps"):
        raise ValueError(f"不支持的输出格式 {out_format}（docx/doc/wps）")
    download_name = f"汇编文档.{out_format}"
    if out_format == "docx":
        out_bytes, mime = docx_bytes, (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    elif out_format == "doc":
        out_bytes = converters.convert_with_soffice(docx_bytes, ".docx", "doc")
        if out_bytes is None:
            raise ValueError("输出 .doc 需要服务器安装 LibreOffice（soffice），当前不可用")
        mime = "application/msword"
    else:  # wps
        out_bytes = docx_bytes
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        warnings.append(
            "wps 输出为 OOXML 兼容内容 + .wps 扩展名：WPS 文字通常可直接打开；"
            "如需原生 .wps 请在 WPS 中另存为 .wps"
        )

    # ---- 总页数（尽力）----
    total_pages: Optional[int] = None
    compiled_pdf = converters.convert_with_soffice(docx_bytes, ".docx", "pdf") if converters.soffice_available() else None
    if compiled_pdf is not None:
        pp = converters.pdfinfo_pages(compiled_pdf)
        total_pages = pp if pp is not None else None

    job_id = temp_files.new_id()
    manifest = {
        "download_name": download_name,
        "mime_type": mime,
        "doc_count": len(items),
        "total_pages": total_pages,
        "output_format": out_format,
        "warnings": warnings,
        "errors": errors,
    }
    temp_files.save_job(job_id, {download_name: out_bytes}, None, manifest)
    _bump("compiles")

    return {
        "job_id": job_id,
        "download_name": download_name,
        "mime_type": mime,
        "stats": {
            "doc_count": len(items),
            "total_pages": total_pages,
            "toc_entries": len(items) if opts.toc.enabled else 0,
            "warnings": warnings,
        },
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# 能力声明
# ---------------------------------------------------------------------------

def supported_formats() -> Dict:
    soffice_ok = converters.soffice_available()
    poppler_ok = converters.poppler_available()
    return {
        "input_formats": sorted(config.COMPILE_ALLOWED_EXTENSIONS),
        "classifications": ["docx", "doc", "rtf", "plain", "unknown"],
        "output_formats": sorted(("docx", "doc", "wps")),
        "soffice": {"available": soffice_ok, "version": converters.soffice_version()},
        "poppler": {"available": poppler_ok, "version": converters.poppler_version()},
        "max_file_size_mb": config.COMPILE_MAX_MB,
        "capabilities": {
            "preview_image": soffice_ok and poppler_ok,
            "preview_text": True,
            "toc_page_numbers": soffice_ok and poppler_ok,
            "doc_output": soffice_ok,
            "wps_output": True,  # OOXML 兼容方案
            "apply_to_source": True,
        },
        "toc_templates": toc_mod.DEFAULT_TEMPLATES,
    }


def health() -> Dict:
    return {
        "status": "UP",
        "soffice": {"available": converters.soffice_available(),
                    "version": converters.soffice_version()},
        "poppler": {"available": converters.poppler_available(),
                    "version": converters.poppler_version()},
        "metrics": get_metrics(),
    }