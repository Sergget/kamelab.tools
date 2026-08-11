import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("LAB_TOOLS_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
STATIC_DIR = Path(os.getenv("LAB_TOOLS_STATIC_DIR", str(BASE_DIR / "app" / "static")))

TEMP_TTL_HOURS = float(os.getenv("LAB_TOOLS_TTL_HOURS", "2"))
MAX_UPLOAD_MB = int(os.getenv("LAB_TOOLS_MAX_UPLOAD_MB", "100"))
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

# ---- 文档转换工具（doc-convert）----
CONVERT_MAX_MB = int(os.getenv("LAB_TOOLS_CONVERT_MAX_MB", "50"))
OCR_NODE_URL = os.getenv("LAB_TOOLS_OCR_NODE_URL", "http://127.0.0.1:8001")
OCR_TIMEOUT = int(os.getenv("LAB_TOOLS_OCR_TIMEOUT", "120"))
PDF_TEXT_THRESHOLD = int(os.getenv("LAB_TOOLS_PDF_TEXT_THRESHOLD", "50"))
CROP_PDF_ZOOM = float(os.getenv("LAB_TOOLS_CROP_PDF_ZOOM", "2.0"))
PANDOC_TIMEOUT = int(os.getenv("LAB_TOOLS_PANDOC_TIMEOUT", "30"))
DOCX_REFERENCE_TEMPLATE = os.getenv("LAB_TOOLS_DOCX_REFERENCE_TEMPLATE", "").strip()
LAYOUT_RECONSTRUCTION_ENABLED = os.getenv(
    "LAB_TOOLS_LAYOUT_RECONSTRUCTION", "true"
).strip().lower() not in ("false", "0", "no")
LAYOUT_HEADING_HEIGHT_RATIO = float(os.getenv("LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO", "1.3"))
LAYOUT_PARAGRAPH_GAP_RATIO = float(os.getenv("LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO", "1.4"))
LAYOUT_INDENT_RATIO = float(os.getenv("LAB_TOOLS_LAYOUT_INDENT_RATIO", "0.5"))

# ---- 节点身份（健康检查展示用）----
NODE_NAME = os.getenv("LAB_TOOLS_NODE_NAME", socket.gethostname())
NODE_ROLE = os.getenv("LAB_TOOLS_NODE_ROLE", "main")

# ---- OCR 节点信息（用于 health 端点展示）----
OCR_NODE_NAME = os.getenv("LAB_TOOLS_OCR_NODE_NAME", "win11")
OCR_NODE_ROLE = os.getenv("LAB_TOOLS_OCR_NODE_ROLE", "heavy")

# ---- 启用的工具集合（逗号分隔，空 = 全部）----
_enabled = os.getenv("LAB_TOOLS_ENABLED", "").strip()
ENABLED_TOOLS = {t.strip() for t in _enabled.split(",") if t.strip()} if _enabled else None

HOST = os.getenv("LAB_TOOLS_HOST", "0.0.0.0")
PORT = int(os.getenv("LAB_TOOLS_PORT", "8000"))