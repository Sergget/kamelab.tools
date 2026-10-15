"""OCR 提取器工厂：根据部署模式和配置返回对应的提取器。"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .. import config

logger = logging.getLogger(__name__)

# PDF 渲染/提取的子进程超时（秒）
PDF_TOOL_TIMEOUT = 120
# pdfinfo 解析失败时的兜底页面尺寸（A4 纵向，单位 pt）
DEFAULT_PAGE_SIZE_PT = (595.0, 842.0)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"服务器未安装 {name}（poppler-utils）")
    return path


def _render_pdf_pages_poppler(file_bytes: bytes, dpi: int = 200) -> List[Tuple[int, bytes]]:
    """用 poppler 的 pdftoppm 将 PDF 渲染为 PNG 列表 [(page_no, png_bytes), ...]。

    不依赖 PyMuPDF：在无预编译 wheel 的架构（如 mips64el）上 PyMuPDF 不可得，
    而 poppler-utils 通常由系统包提供，渲染结果等价。
    """
    binary = _require_tool("pdftoppm")
    with tempfile.TemporaryDirectory(prefix="labtools-ocr-") as tmpdir:
        src = Path(tmpdir) / "in.pdf"
        src.write_bytes(file_bytes)
        prefix = Path(tmpdir) / "page"
        proc = subprocess.run(
            [binary, "-png", "-r", str(dpi), str(src), str(prefix)],
            capture_output=True,
            timeout=PDF_TOOL_TIMEOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "pdftoppm 渲染失败: "
                f"{proc.stderr.decode('utf-8', errors='ignore')[:300]}"
            )
        rendered = sorted(Path(tmpdir).glob(f"{prefix.name}-*.png"))
        if not rendered:
            raise RuntimeError("pdftoppm 未生成任何页面图片")
        return [(idx, png.read_bytes()) for idx, png in enumerate(rendered, start=1)]


def _pdf_page_size(file_bytes: bytes) -> Tuple[float, float]:
    """用 pdfinfo 取第一页尺寸（pt），不依赖 PyMuPDF。失败时返回 A4 兜底值。"""
    binary = shutil.which("pdfinfo")
    if not binary:
        return DEFAULT_PAGE_SIZE_PT
    with tempfile.TemporaryDirectory(prefix="labtools-pdf-") as tmpdir:
        src = Path(tmpdir) / "in.pdf"
        src.write_bytes(file_bytes)
        try:
            proc = subprocess.run(
                [binary, "-f", "1", "-l", "1", str(src)],
                capture_output=True,
                timeout=PDF_TOOL_TIMEOUT,
            )
            m = re.search(
                r"Page\s+\d+ size:\s+([\d.]+)\s+x\s+([\d.]+)",
                proc.stdout.decode("utf-8", errors="ignore"),
            )
            if m:
                return float(m.group(1)), float(m.group(2))
        except Exception as exc:
            logger.warning("pdfinfo 读取页面尺寸失败，使用 A4 兜底: %s", exc)
    return DEFAULT_PAGE_SIZE_PT


def _open_rgb_image(img_bytes: bytes):
    """把图片字节解码为 RGB 模式的 PIL Image。"""
    from PIL import Image

    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


class _LocalPdfMixin:
    """基于 poppler 的本地 PDF 处理实现（文本提取 / 裁剪 / 渲染）。

    由各提取器共用，避免重复实现，同时保持对 PyMuPDF 的零依赖：
    mips64el 等架构没有 PyMuPDF 预编译 wheel，而 poppler-utils 由系统包提供。
    """

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        binary = _require_tool("pdftotext")
        with tempfile.TemporaryDirectory(prefix="labtools-pdf-") as tmpdir:
            src = Path(tmpdir) / "in.pdf"
            src.write_bytes(file_bytes)
            proc = subprocess.run(
                [binary, "-layout", str(src), "-"],
                capture_output=True,
                timeout=PDF_TOOL_TIMEOUT,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "pdftotext 提取失败: "
                    f"{proc.stderr.decode('utf-8', errors='ignore')[:300]}"
                )
            return proc.stdout.decode("utf-8", errors="ignore").strip()

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        """用 pdftotext -x/-y/-W/-H 裁剪提取（页面尺寸经 pdfinfo 获取）。"""
        binary = _require_tool("pdftotext")
        w_pt, h_pt = _pdf_page_size(file_bytes)

        x = int(crop["x"] * w_pt)
        y = int(crop["y"] * h_pt)
        w = max(1, int(crop["width"] * w_pt))
        h = max(1, int(crop["height"] * h_pt))

        with tempfile.TemporaryDirectory(prefix="labtools-pdf-") as tmpdir:
            src = Path(tmpdir) / "in.pdf"
            src.write_bytes(file_bytes)
            proc = subprocess.run(
                [binary, "-layout", "-x", str(x), "-y", str(y),
                 "-W", str(w), "-H", str(h), str(src), "-"],
                capture_output=True,
                timeout=PDF_TOOL_TIMEOUT,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "pdftotext 裁剪提取失败: "
                    f"{proc.stderr.decode('utf-8', errors='ignore')[:300]}"
                )
            return proc.stdout.decode("utf-8", errors="ignore").strip()

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        return _render_pdf_pages_poppler(file_bytes, dpi)


class BaseExtractor:
    """提取器基类：定义统一接口。"""

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        raise NotImplementedError

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        """文本型 PDF 全文提取。"""
        raise NotImplementedError

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        """文本型 PDF 裁剪提取。"""
        raise NotImplementedError

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        """PDF 渲染为图片列表 [(page_no, png_bytes), ...]。"""
        raise NotImplementedError


class LocalPurePythonExtractor(_LocalPdfMixin, BaseExtractor):
    """纯 Python 本地提取器（无 GPU / 无节点的降级路径）。
    依赖：poppler-utils (pdftotext/pdftoppm/pdfinfo)、local_extract。
    """

    def __init__(self):
        from . import local_extract
        self._local_extract = local_extract

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        return self._local_extract.extract_markdown(file_bytes, ext)


class PaddleOcrExtractor(_LocalPdfMixin, BaseExtractor):
    """PaddleOCR 本地提取器（需 AVX 支持，可选 GPU）。"""

    def __init__(self, use_gpu: bool = False):
        self._use_gpu = use_gpu
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is not None:
            return self._ocr
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang="ch",
                use_angle_cls=False,
                use_gpu=self._use_gpu,
            )
            return self._ocr
        except Exception as e:
            logging.error(f"PaddleOCR 初始化失败: {e}")
            raise

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        # Office/文本文件走 local_extract
        from . import local_extract
        return local_extract.extract_markdown(file_bytes, ext)

    def _ocr_image(self, img_bytes: bytes) -> dict:
        import numpy as np

        ocr = self._get_ocr()
        img_array = np.array(_open_rgb_image(img_bytes))
        raw_result = ocr.ocr(img_array, cls=False)
        # PaddleOCR 格式: [[bbox, (text, conf)], ...]
        lines = []
        for item in (raw_result[0] or []):
            if item is None:
                continue
            bbox_raw, (text, confidence) = item
            if not text or not text.strip():
                continue
            bbox = [[round(float(x), 1), round(float(y), 1)] for x, y in bbox_raw]
            lines.append({"text": text, "bbox": bbox, "confidence": round(float(confidence), 4)})
        text = "\n".join(line["text"] for line in lines)
        return {"text": text, "pages": 1, "lines": lines}


class RapidOcrExtractor(_LocalPdfMixin, BaseExtractor):
    """RapidOCR (ONNXRuntime) 提取器（无 AVX 要求）。"""

    def __init__(self):
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is not None:
            return self._ocr
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()
        return self._ocr

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        from . import local_extract
        return local_extract.extract_markdown(file_bytes, ext)

    def _ocr_image(self, img_bytes: bytes) -> dict:
        import numpy as np

        ocr = self._get_ocr()
        img_array = np.array(_open_rgb_image(img_bytes))
        raw_result, _elapse = ocr(img_array)
        lines = []
        for item in (raw_result or []):
            if not item or len(item) < 3:
                continue
            bbox_raw, text, confidence = item[0], item[1], item[2]
            if not text or not str(text).strip():
                continue
            bbox = [[round(float(x), 1), round(float(y), 1)] for x, y in bbox_raw]
            lines.append({"text": str(text), "bbox": bbox, "confidence": round(float(confidence), 4)})
        text = "\n".join(line["text"] for line in lines)
        return {"text": text, "pages": 1, "lines": lines}


class RemoteOcrExtractor(_LocalPdfMixin, BaseExtractor):
    """远程 OCR 节点提取器（模式 A/B）。"""

    def __init__(self, node_url: str):
        self._node_url = node_url.rstrip("/")
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        from . import local_extract
        return local_extract.extract_markdown(file_bytes, ext)

    def _ocr_image(self, img_bytes: bytes) -> dict:
        import requests
        files = {"file": ("image.png", img_bytes, "image/png")}
        resp = requests.post(
            f"{self._node_url}/convert",
            files=files,
            params={"include_lines": "true"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()


# ---- 本地引擎注册表 ----
# 使用注册表模式：新增引擎只需在这里注册，无需修改 get_ocr_extractor()。
# 每个工厂函数接收 config 对象，返回对应的 Extractor 实例。
_LOCAL_ENGINE_FACTORIES = {
    "paddleocr": lambda: PaddleOcrExtractor(use_gpu=config.OCR_USE_GPU),
    "rapidocr": lambda: RapidOcrExtractor(),
}


def _resolve_local_engine(engine: str) -> str:
    """解析 'auto' 为具体引擎名。

    auto 模式：有 nvidia-smi 且 OCR_USE_GPU=true → paddleocr（GPU）；
    否则 → rapidocr（ONNXRuntime，无 AVX 要求）。
    """
    if engine == "auto":
        if shutil.which("nvidia-smi") and config.OCR_USE_GPU:
            return "paddleocr"
        return "rapidocr"
    return engine


def get_ocr_extractor() -> Optional[BaseExtractor]:
    """根据部署模式返回对应的 OCR 提取器。"""
    if not config.ENABLE_DOC_CONVERT or config.DEPLOY_MODE == "C":
        return None

    # 有 OCR 节点 -> 远程调用（模式 A/B）
    if config.OCR_NODE_URL:
        return RemoteOcrExtractor(config.OCR_NODE_URL)

    # 无节点 -> 本地引擎（模式 D）
    engine = _resolve_local_engine(config.OCR_ENGINE)
    factory_fn = _LOCAL_ENGINE_FACTORIES.get(engine)
    if factory_fn is None:
        raise ValueError(f"Unknown OCR_ENGINE: {config.OCR_ENGINE}")
    return factory_fn()
