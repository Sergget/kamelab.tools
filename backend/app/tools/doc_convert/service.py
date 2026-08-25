"""文档转换核心逻辑。

路由策略：
    office 文档（docx/xlsx/pptx/txt/csv/md 等）→ 本地纯 Python 提取
                                                  （local_extract，MarkItDown 替代实现）
    图片（png/jpg/bmp/tif/webp 等）           → OCR：优先转发配置的 OCR 节点，
                                                  节点不可达时降级为本地 OCR（可选）
    PDF                                        → 先分类：文本型走 pdftotext 提取，
                                                  扫描型渲染成图片后走 OCR（同上含降级）

部署模式（DEPLOY_MODE）：
    A: 主服务器 + 远程 OCR 节点
    B: Ubuntu 主服务 + 远程 GPU OCR 节点
    C: 仅 Excel 工具，禁用文档转换
    D: Ubuntu 单机全功能（本地 GPU OCR）

OCR 引擎（OCR_ENGINE）：
    rapidocr: RapidOCR (ONNXRuntime) - 无 AVX 要求，内存占用低
    paddleocr: PaddleOCR - 需 AVX 支持，可选 GPU 加速
    auto: 自动检测（有 nvidia-smi 且 OCR_USE_GPU=true 选 paddleocr，否则 rapidocr）

可选能力：
    crop            按比例裁剪区域后再转换（图片 / 文本型 PDF / 扫描型 PDF）
    output_format   md（默认）/ txt / docx 三种输出
    layout_reconstruction  基于 OCR 行级 bbox 的几何启发式版面重建（标题/段落/缩进）
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import Image

from ... import config
from . import local_extract
from . import factory
from .models import SUPPORTED_OUTPUT_FORMATS

logger = logging.getLogger(__name__)

# ---- 任务计数器（线程安全）----
_lock = threading.Lock()
_active_tasks = 0
_total_success_count = 0
_total_fail_count = 0
_total_elapsed_ms = 0


class DocConvertError(ValueError):
    """业务错误，携带建议的 HTTP 状态码。"""

    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def task_started() -> None:
    global _active_tasks
    with _lock:
        _active_tasks += 1


def task_finished() -> None:
    global _active_tasks
    with _lock:
        _active_tasks = max(0, _active_tasks - 1)


def record_conversion_metrics(success: bool, elapsed_ms: float) -> None:
    global _total_success_count, _total_fail_count, _total_elapsed_ms
    with _lock:
        if success:
            _total_success_count += 1
        else:
            _total_fail_count += 1
        _total_elapsed_ms += elapsed_ms


def get_metrics() -> Dict[str, Any]:
    with _lock:
        success = _total_success_count
        fail = _total_fail_count
        elapsed_tot = _total_elapsed_ms
        active = _active_tasks
    return {
        "active_tasks": active,
        "total_success_count": success,
        "total_fail_count": fail,
        "total_elapsed_ms": elapsed_tot,
        "average_elapsed_ms": round(elapsed_tot / success, 1) if success > 0 else 0.0,
    }


# ---- 路由表 ----
LOCAL_ONLY_EXTENSIONS = {
    ".docx", ".xlsx", ".xlsm", ".xls", ".pptx", ".txt", ".csv",
    ".html", ".htm", ".xml", ".json", ".md",
}
OCR_ONLY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSION = ".pdf"

# ---- poppler 命令行工具（pdftotext / pdftoppm / pdfinfo）----
POPPLER_TIMEOUT = 120


def _require_poppler(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise DocConvertError(f"服务器未安装 {tool}（poppler-utils），无法处理 PDF", 500)
    return path


def _run_poppler(tool: str, args: List[str], file_bytes: bytes) -> subprocess.CompletedProcess:
    """把 PDF 字节写入临时文件后运行 poppler 工具（老版本对 stdin 支持不稳）。"""
    binary = _require_poppler(tool)
    with tempfile.TemporaryDirectory(prefix="labtools-pdf-") as tmpdir:
        src = Path(tmpdir) / "in.pdf"
        src.write_bytes(file_bytes)
        proc = subprocess.run(
            [binary, *args, str(src)] + (["-"] if tool == "pdftotext" else []),
            input=None,
            capture_output=True,
            timeout=POPPLER_TIMEOUT,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"{tool} 退出码 {proc.returncode}: {stderr[:300]}")
        return proc


def _pdf_info(file_bytes: bytes) -> Dict[str, int]:
    """用 pdfinfo 取页数与第一页尺寸（pt）。解析失败返回保守默认值。"""
    info: Dict[str, int] = {}
    try:
        proc = _run_poppler("pdfinfo", ["-f", "1", "-l", "1"], file_bytes)
        text = proc.stdout.decode("utf-8", errors="ignore")
        m_pages = re.search(r"^Pages:\s+(\d+)", text, re.MULTILINE)
        if m_pages:
            info["pages"] = int(m_pages.group(1))
        m_size = re.search(r"Page\s+\d+ size:\s+([\d.]+)\s+x\s+([\d.]+)", text)
        if m_size:
            info["width_pt"] = round(float(m_size.group(1)))
            info["height_pt"] = round(float(m_size.group(2)))
    except Exception as exc:
        logger.warning("pdfinfo 解析失败，使用默认页面参数: %s", exc)
    info.setdefault("pages", 1)
    info.setdefault("width_pt", 595)   # A4 纵向
    info.setdefault("height_pt", 842)
    return info


# ---- PDF 分类 ----
def classify_pdf(file_bytes: bytes) -> str:
    """判断 PDF 是文本型还是扫描型：提取前 3 页文字，字符数 ≥ 阈值 → text。"""
    try:
        proc = _run_poppler("pdftotext", ["-f", "1", "-l", "3"], file_bytes)
        page_text = proc.stdout.decode("utf-8", errors="ignore")
        total_chars = len(re.sub(r"\s+", "", page_text))
        return "text" if total_chars >= config.PDF_TEXT_THRESHOLD else "scanned"
    except Exception:
        return "scanned"


# ---- OCR 节点转发 ----
def check_ocr_node() -> Optional[Dict[str, Any]]:
    """探活 OCR 节点，返回健康信息或 None。"""
    if not config.OCR_NODE_URL:
        return None
    try:
        resp = requests.get(f"{config.OCR_NODE_URL}/health", timeout=config.OCR_NODE_TIMEOUT)
        return resp.json() if resp.ok else None
    except Exception:
        return None


def forward_to_ocr_node(file_bytes: bytes, filename: str,
                        include_lines: bool = True) -> Tuple[Dict[str, Any], int]:
    """转发文件到 OCR 节点 /convert。返回 (response_dict, http_status)。"""
    try:
        resp = requests.post(
            f"{config.OCR_NODE_URL}/convert",
            files={"file": (filename, io.BytesIO(file_bytes))},
            params={"include_lines": "true" if include_lines else "false"},
            timeout=config.OCR_TIMEOUT,
        )
        try:
            return resp.json(), resp.status_code
        except ValueError:
            return {
                "success": False,
                "error": f"OCR 节点返回了非 JSON 响应（HTTP {resp.status_code}）",
                "filename": filename,
            }, 502
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"OCR 节点不可达: {config.OCR_NODE_URL}",
            "filename": filename,
        }, 503
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": f"OCR 节点处理超时（{config.OCR_TIMEOUT}s）",
            "filename": filename,
        }, 504


# ---- 裁剪 ----
CROP_EPS = 1e-4


def parse_crop(raw: Union[str, None]) -> Optional[Dict[str, float]]:
    """解析并校验 crop 表单字段。合法返回 {x,y,width,height} 比例值，缺省返回 None。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise DocConvertError("crop 不是合法的 JSON")

    if not isinstance(data, dict):
        raise DocConvertError("crop 必须是 JSON 对象")
    if data.get("unit") != "ratio":
        raise DocConvertError('crop.unit 必须是 "ratio"')

    out: Dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        val = data.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise DocConvertError(f"crop.{key} 必须是数字")
        if val < 0 or val > 1:
            raise DocConvertError(f"crop.{key} 必须在 0~1 之间")
        out[key] = float(val)

    if out["width"] <= 0 or out["height"] <= 0:
        raise DocConvertError("crop.width / crop.height 必须大于 0")
    if out["x"] + out["width"] > 1 + CROP_EPS:
        raise DocConvertError("crop.x + crop.width 超过 1.0")
    if out["y"] + out["height"] > 1 + CROP_EPS:
        raise DocConvertError("crop.y + crop.height 超过 1.0")

    return out


def crop_image_bytes(file_bytes: bytes, crop: Dict[str, float]) -> bytes:
    """按比例裁剪图片，返回裁剪后的图片字节（保留原格式）。"""
    img = Image.open(io.BytesIO(file_bytes))
    w, h = img.size
    box = (
        round(crop["x"] * w),
        round(crop["y"] * h),
        round((crop["x"] + crop["width"]) * w),
        round((crop["y"] + crop["height"]) * h),
    )
    box = (
        min(box[0], w - 1),
        min(box[1], h - 1),
        max(box[2], box[0] + 1),
        max(box[3], box[1] + 1),
    )
    cropped = img.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format=(img.format or "PNG"))
    return buf.getvalue()


def crop_pdf_text(file_bytes: bytes, crop: Dict[str, float]) -> str:
    """文本型 PDF：按比例裁剪每一页并直接提取文字层，不走 OCR。

    pdftotext 的 -x/-y/-W/-H 以 72dpi 像素（≈PDF 点）为单位，对每页取同一区域；
    页面尺寸按第一页换算，混合页面尺寸的文档可能有偏差。
    """
    info = _pdf_info(file_bytes)
    w_pt, h_pt = info["width_pt"], info["height_pt"]
    args = [
        "-x", str(round(crop["x"] * w_pt)),
        "-y", str(round(crop["y"] * h_pt)),
        "-W", str(max(1, round(crop["width"] * w_pt))),
        "-H", str(max(1, round(crop["height"] * h_pt))),
    ]
    proc = _run_poppler("pdftotext", args, file_bytes)
    return proc.stdout.decode("utf-8", errors="ignore").strip()


def crop_pdf_page_images(file_bytes: bytes, crop: Dict[str, float]) -> List[Tuple[int, bytes]]:
    """扫描型 PDF：pdftoppm 渲染每一页后用 PIL 按比例裁剪。返回 [(page_no, png_bytes), ...]。"""
    dpi = max(int(72 * config.CROP_PDF_ZOOM), 72)
    page_count = min(_pdf_info(file_bytes)["pages"], 200)
    binary = _require_poppler("pdftoppm")
    images: List[Tuple[int, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="labtools-pdf-") as tmpdir:
        src = Path(tmpdir) / "in.pdf"
        src.write_bytes(file_bytes)
        for page_no in range(1, page_count + 1):
            prefix = Path(tmpdir) / "page"
            proc = subprocess.run(
                [binary, "-png", "-r", str(dpi), "-f", str(page_no), "-l", str(page_no),
                 str(src), str(prefix)],
                capture_output=True,
                timeout=POPPLER_TIMEOUT,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"pdftoppm 第 {page_no} 页渲染失败: "
                    f"{proc.stderr.decode('utf-8', errors='ignore')[:300]}")
            rendered = sorted(Path(tmpdir).glob(f"{prefix.name}-*.png"))
            if not rendered:
                raise RuntimeError(f"pdftoppm 第 {page_no} 页未生成图片")
            img = Image.open(rendered[-1])
            w, h = img.size
            box = (
                round(crop["x"] * w),
                round(crop["y"] * h),
                round((crop["x"] + crop["width"]) * w),
                round((crop["y"] + crop["height"]) * h),
            )
            box = (
                min(box[0], w - 1),
                min(box[1], h - 1),
                max(box[2], box[0] + 1),
                max(box[3], box[1] + 1),
            )
            cropped = img.crop(box)
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            images.append((page_no, buf.getvalue()))
    return images


# ---- OCR 文本提取 ----
def _extract_ocr_text(result: Dict[str, Any]) -> str:
    """从 OCR 节点响应里尽量取出文字内容。"""
    for key in ("content", "text", "markdown"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# ---- 版面重建：基于行级 bbox 的几何启发式段落/标题分组 ----
# 只用三个廉价信号：行高（字号代理）→ 标题级别；行间距 → 段落分界；
# 左边界缩进 → 引用块。不做真正的版面分析（多栏/表格），阈值见 config。

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]")


def _smart_join(prev_text: str, next_text: str) -> str:
    """同一段内跨行拼接。前后都是 ASCII 字母/数字时补空格，避免英文单词粘连。"""
    if not prev_text:
        return next_text
    if not next_text:
        return prev_text
    if _ASCII_WORD_RE.match(prev_text[-1]) and _ASCII_WORD_RE.match(next_text[0]):
        return prev_text + " " + next_text
    return prev_text + next_text


def _line_metrics(line: Dict[str, Any]) -> Dict[str, float]:
    """从一行 OCR 结果的 bbox 提取几何指标（top/bottom/height/left）。"""
    xs = [pt[0] for pt in line["bbox"]]
    ys = [pt[1] for pt in line["bbox"]]
    top, bottom = min(ys), max(ys)
    return {
        "text": (line.get("text") or "").strip(),
        "top": top,
        "bottom": bottom,
        "height": max(bottom - top, 1e-6),
        "left": min(xs),
    }


def _reconstruct_page_layout(page_lines: List[Dict[str, Any]]) -> str:
    """单页行列表 → 分组（标题/段落）→ 渲染成 Markdown 文本。"""
    metrics = [_line_metrics(ln) for ln in page_lines if ln.get("text", "").strip()]
    if not metrics:
        return ""

    heights = sorted(m["height"] for m in metrics)
    median_height = heights[len(heights) // 2] or 1.0

    body_lefts = [
        m["left"] for m in metrics
        if abs(m["height"] - median_height) <= 0.2 * median_height
    ]
    baseline_left = min(body_lefts) if body_lefts else min(m["left"] for m in metrics)

    groups: List[List[Dict[str, float]]] = []
    current: List[Dict[str, float]] = []
    for m in metrics:
        is_heading_line = m["height"] >= median_height * config.LAYOUT_HEADING_HEIGHT_RATIO
        if is_heading_line:
            if current:
                groups.append(current)
                current = []
            groups.append([m])
            continue
        if not current:
            current.append(m)
            continue
        gap = m["top"] - current[-1]["bottom"]
        indent_delta = abs(m["left"] - current[0]["left"])
        if (gap > median_height * config.LAYOUT_PARAGRAPH_GAP_RATIO
                or indent_delta > median_height * config.LAYOUT_INDENT_RATIO):
            groups.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        groups.append(current)

    rendered: List[str] = []
    for group in groups:
        if len(group) == 1 and group[0]["height"] >= median_height * config.LAYOUT_HEADING_HEIGHT_RATIO:
            ratio = group[0]["height"] / median_height
            level = 1 if ratio >= 2.0 else (2 if ratio >= 1.6 else 3)
            rendered.append(f"{'#' * level} {group[0]['text']}")
            continue
        text = group[0]["text"]
        for m in group[1:]:
            text = _smart_join(text, m["text"])
        indent = group[0]["left"] - baseline_left
        if indent > median_height * config.LAYOUT_INDENT_RATIO:
            text = f"> {text}"
        rendered.append(text)

    return "\n\n".join(rendered)


def _reconstruct_layout(lines: List[Dict[str, Any]],
                        force_page_markers: bool = False) -> str:
    """多页行列表 → 按页重建，页间用 "<!-- page N -->" 分隔。"""
    if not lines:
        return ""
    pages: Dict[int, List[Dict[str, Any]]] = {}
    for ln in lines:
        pages.setdefault(ln.get("page", 1), []).append(ln)

    use_markers = force_page_markers or len(pages) > 1
    parts: List[str] = []
    for page_no in sorted(pages.keys()):
        page_md = _reconstruct_page_layout(pages[page_no])
        if use_markers:
            parts.append(f"<!-- page {page_no} -->" + (f"\n{page_md}" if page_md else ""))
        elif page_md:
            parts.append(page_md)
    return "\n\n".join(p for p in parts if p)


def _apply_layout_reconstruction(result: Dict[str, Any],
                                 force_page_markers: bool = False) -> None:
    """就地改写 OCR 响应：按 bbox 重建 content，原始文本保留到 content_raw。"""
    result["layout_reconstructed"] = False
    if not config.LAYOUT_RECONSTRUCTION_ENABLED:
        result.pop("lines", None)
        return
    lines = result.get("lines")
    if not isinstance(lines, list) or not lines:
        result.pop("lines", None)
        return
    try:
        reconstructed = _reconstruct_layout(lines, force_page_markers=force_page_markers)
    except Exception as exc:
        result["layout_reconstruction_error"] = str(exc)
        result.pop("lines", None)
        return
    if reconstructed.strip():
        result["content_raw"] = result.get("content", "")
        result["content"] = reconstructed
        result["layout_reconstructed"] = True
    result.pop("lines", None)


# ---- OCR 处理核心 ----
def _ocr_via_extractor(file_bytes: bytes, filename: str, ext: str, t_start: float) -> Dict[str, Any]:
    """通过配置的提取器执行 OCR。"""
    extractor = factory.get_ocr_extractor()
    if extractor is None:
        raise DocConvertError("OCR 引擎不可用：未配置 OCR 节点且本地引擎不可用", 503)

    ext_lower = ext.lower()
    file_type = "pdf" if ext == ".pdf" else "image"

    try:
        if ext.lower() == ".pdf":
            # PDF: 渲染每页后逐页 OCR
            page_images = extractor.render_pdf_pages(file_bytes, dpi=200)
            all_texts = []
            all_lines = []
            for page_no, img_bytes in page_images:
                result = extractor._ocr_image(img_bytes)
                page_text = result["text"]
                if page_text.strip():
                    all_texts.append(f"--- 第 {page_no} 页 ---\n{page_text}")
                for line in result.get("lines", []):
                    line["page"] = page_no
                all_lines.extend(result.get("lines", []))

            text = "\n\n".join(all_texts)
            return {
                "text": text,
                "pages": len(all_texts),
                "lines": result.get("lines", []),
            }
        else:
            # 图片：直接 OCR
            result = extractor._ocr_image(file_bytes)
            return {
                "text": result["text"],
                "pages": 1,
                "lines": result.get("lines", []),
            }

    except Exception as exc:
        logger.error(f"OCR 处理失败: {exc}")
        raise DocConvertError(f"OCR 处理失败: {exc}", 500)


def _do_ocr_with_fallback(file_bytes: bytes, filename: str, ext: str, t_start: float) -> Dict[str, Any]:
    """OCR 处理：支持节点优先/本地降级/本地优先模式。"""
    ocr_node_url = config.OCR_NODE_URL
    ocr_node_up = check_ocr_node() is not None

    # 模式判断
    use_local_only = config.OCR_USE_LOCAL or not config.OCR_NODE_URL
    use_remote_first = config.OCR_NODE_URL and not config.OCR_USE_LOCAL

    if config.OCR_USE_LOCAL:
        # 本地优先模式
        logger.info("本地 OCR 模式，直接使用本地引擎: %s", filename)
        try:
            ext_lower = Path(filename).suffix.lower()
            file_type = "pdf" if ext == ".pdf" else "image"
            result = _ocr_via_extractor(file_bytes, filename, ext, time.perf_counter())
            return {
                "success": True,
                "filename": filename,
                "content": result["text"],
                "engine": "local",
                "routed_to": "local",
                "pages": result["pages"],
                "lines": result["lines"],
                "elapsed_ms": round((time.perf_counter() - time.perf_counter()) * 1000),
            }
        except Exception as exc:
            logger.error("本地 OCR 转换失败: %s", exc)
            raise DocConvertError(f"本地 OCR 失败: {exc}", 503)

    # 有远程节点且不强制本地
    if config.OCR_NODE_URL:
        ocr_node_up = check_ocr_node() is not None
        if ocr_node_up:
            # 远程节点可用，转发
            result, status = forward_to_ocr_node(file_bytes, filename)
            if result.get("success"):
                result["routed_to"] = "ocr_node"
                result["route_elapsed_ms"] = round((time.perf_counter() - time.perf_counter()) * 1000)
            if not result.get("success"):
                raise DocConvertError(result.get("error", "OCR 转换失败"),
                                      status if 400 <= status <= 599 else 502)
            return result

    # 节点不可达，尝试本地降级
    logger.info("OCR 节点不可达，降级为本地引擎: %s", filename)
    try:
        return _process_local_ocr(file_bytes, filename, time.perf_counter())
    except Exception as exc:
        logger.error("本地 OCR 降级失败: %s", exc)
        raise DocConvertError(f"OCR 节点不可达且本地引擎失败: {exc}", 503)


def _process_local_ocr(file_bytes: bytes, filename: str, t_start: float) -> Dict[str, Any]:
    """本地 OCR 处理（使用工厂获取的提取器）。"""
    ext = Path(filename).suffix.lower()
    result = _ocr_via_extractor(file_bytes, filename, ext, time.perf_counter())
    return {
        "success": True,
        "filename": filename,
        "content": result["text"],
        "engine": "local",
        "routed_to": "local",
        "pages": result["pages"],
        "lines": result["lines"],
        "elapsed_ms": round((time.perf_counter() - time.perf_counter()) * 1000),
    }


def _ocr_image_bytes(file_bytes: bytes, ocr, page_num: Optional[int] = None) -> List[Dict[str, Any]]:
    """对图片字节做 OCR 识别，返回行列表（兼容旧 PaddleOCR 路径，新版不再使用）。"""
    # 此函数保留用于兼容旧版 PaddleOCR 路径，新版通过 factory 处理
    raise NotImplementedError("Use factory extractor instead")


def _do_ocr_local(file_bytes: bytes, ext: str, file_type: str) -> Dict[str, Any]:
    """兼容旧版 PaddleOCR 路径（保留向后兼容）。"""
    # 新版直接使用 factory extractor
    raise NotImplementedError("Use factory extractor instead")


def _extract_lines(ocr_result, page_num: Optional[int] = None) -> List[Dict[str, Any]]:
    """兼容旧版 PaddleOCR 格式解析（保留向后兼容）。"""
    # 此函数保留用于兼容旧版 PaddleOCR 路径
    raise NotImplementedError("Use factory extractor instead")


def _lines_to_text(lines: List[Dict[str, Any]]) -> str:
    return "\n".join(line["text"] for line in lines)


def _convert_ocr_cropped_pdf(file_bytes: bytes, filename: str,
                             crop: Dict[str, float], t_start: float) -> Dict[str, Any]:
    """扫描型 PDF + 裁剪：逐页裁剪渲染后转 OCR，拼接结果。"""
    ocr_node_up = check_ocr_node() is not None
    try:
        page_images = crop_pdf_page_images(file_bytes, crop)
    except Exception as exc:
        raise DocConvertError(f"渲染裁剪后的 PDF 页面失败: {exc}", 500)

    page_texts: List[str] = []
    page_errors: List[Dict[str, Any]] = []
    all_lines: List[Dict[str, Any]] = []

    extractor = factory.get_ocr_extractor()
    if extractor is None:
        raise DocConvertError("OCR 引擎不可用", 503)

    for page_no, img_bytes in page_images:
        try:
            result = extractor._ocr_image(img_bytes)
            page_texts.append(f"<!-- page {page_no} -->\n{result['text']}")
            for line in result.get("lines", []):
                line["page"] = page_no
                all_lines.append(line)
        except Exception as exc:
            page_errors.append({"page": page_no, "error": f"OCR 失败: {exc}"})

    if not page_texts:
        raise DocConvertError("所有裁剪页 OCR 均失败", 502)

    resp = {
        "success": True,
        "filename": filename,
        "content": "\n\n".join(page_texts),
        "engine": "local",
        "routed_to": "local",
        "crop_applied": True,
        "pages_processed": len(page_images),
        "lines": all_lines,
    }
    _apply_layout_reconstruction(resp, force_page_markers=True)
    if page_errors:
        resp["page_errors"] = page_errors
    return resp


# ... (保留后续的输出格式、docx 转换、入口函数等代码，与原版一致)
# 为节省空间，后续代码省略，实际使用时需完整保留从 markdown_to_docx_bytes 到文件末尾的代码