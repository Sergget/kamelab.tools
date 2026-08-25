"""OCR 提取器工厂：根据部署模式和配置返回对应的提取器。"""

from __future__ import annotations

import logging
import shutil
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)


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


class LocalPurePythonExtractor(BaseExtractor):
    """纯 Python 本地提取器（模式 C/D 无 GPU/节点时使用）。
    依赖：poppler-utils (pdftotext/pdftoppm)、pdfplumber(旧版本)、local_extract。
    """

    def __init__(self):
        from . import local_extract
        self._local_extract = local_extract

    def extract(self, file_bytes: bytes, filename: str, ext: str) -> str:
        return self._local_extract.extract_markdown(file_bytes, ext)

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(file_bytes)
            tmp_path = f.name
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", tmp_path, "-"],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"pdftotext failed: {proc.stderr.decode()}")
            return proc.stdout.decode("utf-8", errors="ignore").strip()
        finally:
            import os
            os.unlink(tmp_path)

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        """使用 pdftotext -x/-y/-W/-H 裁剪提取（需页面尺寸）。"""
        import subprocess
        import tempfile
        import fitz  # PyMuPDF 仅用于获取页面尺寸

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        w_pt, h_pt = doc[0].rect.width, doc[0].rect.height
        doc.close()

        x = int(crop["x"] * w_pt)
        y = int(crop["y"] * h_pt)
        w = max(1, int(crop["width"] * w_pt))
        h = max(1, int(crop["height"] * h_pt))

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(file_bytes)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h), tmp_path, "-"],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"pdftotext crop failed: {proc.stderr.decode()}")
            return proc.stdout.decode("utf-8", errors="ignore").strip()
        finally:
            import os
            os.unlink(tmp_path)

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        import fitz
        import io
        from PIL import Image

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        try:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=mat)
                images.append((i, pix.tobytes("png")))
        finally:
            doc.close()
        return images


class PaddleOcrExtractor(BaseExtractor):
    """PaddleOCR 本地提取器（需 AVX 支持，模式 D GPU/CPU）。"""

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

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        # 文本型 PDF 用 pdftotext
        extractor = LocalPurePythonExtractor()
        return extractor.extract_pdf_text(file_bytes)

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        extractor = LocalPurePythonExtractor()
        return extractor.crop_pdf_text(file_bytes, crop)

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        try:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
                images.append((i, pix.tobytes("png")))
        finally:
            doc.close()
        return images

    def _ocr_image(self, img_bytes: bytes) -> dict:
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_array = np.array(img)
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


class RapidOcrExtractor(BaseExtractor):
    """RapidOCR (ONNXRuntime) 提取器（无 AVX 要求，模式 A/B/C/D 均可）。"""

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

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        extractor = LocalPurePythonExtractor()
        return extractor.extract_pdf_text(file_bytes)

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        extractor = LocalPurePythonExtractor()
        return extractor.crop_pdf_text(file_bytes, crop)

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        try:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
                images.append((i, pix.tobytes("png")))
        finally:
            doc.close()
        return images

    def _ocr_image(self, img_bytes: bytes) -> dict:
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_array = np.array(img)
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


class RemoteOcrExtractor(BaseExtractor):
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

    def extract_pdf_text(self, file_bytes: bytes) -> str:
        extractor = LocalPurePythonExtractor()
        return extractor.extract_pdf_text(file_bytes)

    def crop_pdf_text(self, file_bytes: bytes, crop: dict) -> str:
        extractor = LocalPurePythonExtractor()
        return extractor.crop_pdf_text(file_bytes, crop)

    def render_pdf_pages(self, file_bytes: bytes, dpi: int = 200) -> list:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        try:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
                images.append((i, pix.tobytes("png")))
        finally:
            doc.close()
        return images

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


def get_ocr_extractor() -> Optional[BaseExtractor]:
    """根据部署模式返回对应的 OCR 提取器。"""
    from .. import config

    if not config.ENABLE_DOC_CONVERT or config.DEPLOY_MODE == "C":
        return None

    # 有 OCR 节点 -> 远程调用（模式 A/B）
    if config.OCR_NODE_URL:
        return RemoteOcrExtractor(config.OCR_NODE_URL)

    # 无节点 -> 本地引擎（模式 D）
    engine = config.OCR_ENGINE
    if engine == "auto":
        engine = "paddleocr" if shutil.which("nvidia-smi") else "rapidocr"

    if engine == "paddleocr":
        return PaddleOcrExtractor(use_gpu=config.OCR_USE_GPU)
    elif engine == "rapidocr":
        return RapidOcrExtractor()
    else:
        raise ValueError(f"Unknown OCR_ENGINE: {engine}")