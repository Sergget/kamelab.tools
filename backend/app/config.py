import os
import shutil
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

# ---- 部署模式：A | B | C | D ----
# A: 主服务器 + 远程 OCR 节点
# B: Ubuntu 主服务 + 远程 GPU OCR 节点
# C: 仅 Excel 工具，禁用文档转换
# D: Ubuntu 单机全功能（本地 GPU OCR）
DEPLOY_MODE = os.getenv("DEPLOY_MODE", "A").upper()

# ---- OCR 节点（模式 A/B 生效）----
OCR_NODE_URL = os.getenv("OCR_NODE_URL", "").strip()
OCR_NODE_TIMEOUT = int(os.getenv("OCR_NODE_TIMEOUT", "5"))
OCR_NODE_NAME = os.getenv("OCR_NODE_NAME", "ocr-node")
OCR_NODE_ROLE = os.getenv("OCR_NODE_ROLE", "heavy")

# 本地 OCR 引擎：rapidocr | paddleocr | auto
OCR_ENGINE = os.getenv("OCR_ENGINE", "auto").lower()

# GPU 加速：true | false（OCR 节点或本地 GPU 模式）
OCR_USE_GPU = os.getenv("OCR_USE_GPU", "false").lower() == "true"

# 文档转换总开关（模式 C 设 false）
ENABLE_DOC_CONVERT = os.getenv("ENABLE_DOC_CONVERT", "true").lower() == "true"

# 本地 OCR 回退（模式 A/B 节点不可达时）
OCR_USE_LOCAL = os.getenv("OCR_USE_LOCAL", "false").strip().lower() not in ("false", "0", "no", "")

# ---- 文档转换工具（doc-convert）----
CONVERT_MAX_MB = int(os.getenv("LAB_TOOLS_CONVERT_MAX_MB", "50"))
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

# OCR 节点信息（健康检查展示用）
OCR_NODE_NAME_DISPLAY = os.getenv("OCR_NODE_NAME", "ocr-node")
OCR_NODE_ROLE_DISPLAY = os.getenv("OCR_NODE_ROLE", "heavy")

# ---- 启用的工具集合（逗号分隔，空 = 全部）----
_enabled = os.getenv("LAB_TOOLS_ENABLED", "").strip()
ENABLED_TOOLS = {t.strip() for t in _enabled.split(",") if t.strip()} if _enabled else None

HOST = os.getenv("LAB_TOOLS_HOST", "0.0.0.0")
PORT = int(os.getenv("LAB_TOOLS_PORT", "8000"))