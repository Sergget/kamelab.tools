import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(*names: str, default: str = "") -> str:
    """按顺序读取环境变量，返回第一个已设置的（兼容新旧变量名）。

    历史部署脚本与 systemd 单元使用的是 LAB_TOOLS_ 前缀（如
    LAB_TOOLS_OCR_NODE_URL），而文档与新模式沿用不带前缀的写法
    （如 OCR_NODE_URL）。两者都支持，且优先取不带前缀的新名称，
    避免已部署环境因改名而静默失效。
    """
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value
    return default


def _env_bool(*names: str, default: bool = False) -> bool:
    value = _env(*names, default="").strip().lower()
    if not value:
        return default
    return value not in ("false", "0", "no")


DATA_DIR = Path(_env("LAB_TOOLS_DATA_DIR", default=str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
STATIC_DIR = Path(_env("LAB_TOOLS_STATIC_DIR", default=str(BASE_DIR / "app" / "static")))

TEMP_TTL_HOURS = float(_env("LAB_TOOLS_TTL_HOURS", default="2"))
MAX_UPLOAD_MB = int(_env("LAB_TOOLS_MAX_UPLOAD_MB", default="100"))
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

# ---- 部署模式：A | B | C | D ----
# A: 主服务器 + 远程 OCR 节点
# B: Ubuntu 主服务 + 远程 GPU OCR 节点
# C: 仅 Excel 工具，禁用文档转换
# D: Ubuntu 单机全功能（本地 GPU OCR）
DEPLOY_MODE = _env("DEPLOY_MODE", default="A").upper()

# ---- OCR 节点（模式 A/B 生效）----
OCR_NODE_URL = _env("OCR_NODE_URL", "LAB_TOOLS_OCR_NODE_URL", default="http://127.0.0.1:8001").strip()
OCR_NODE_TIMEOUT = int(_env("OCR_NODE_TIMEOUT", default="5"))
OCR_NODE_NAME = _env("OCR_NODE_NAME", "LAB_TOOLS_OCR_NODE_NAME", default="ocr-node")
OCR_NODE_ROLE = _env("OCR_NODE_ROLE", "LAB_TOOLS_OCR_NODE_ROLE", default="heavy")

# 本地 OCR 引擎：rapidocr | paddleocr | auto
OCR_ENGINE = _env("OCR_ENGINE", default="auto").lower()

# GPU 加速：true | false（OCR 节点或本地 GPU 模式）
OCR_USE_GPU = _env_bool("OCR_USE_GPU")

# 文档转换总开关（模式 C 设 false）
ENABLE_DOC_CONVERT = _env_bool("ENABLE_DOC_CONVERT", default=True)

# 本地 OCR 回退（模式 A/B 节点不可达时）
OCR_USE_LOCAL = _env_bool("OCR_USE_LOCAL", "LAB_TOOLS_OCR_USE_LOCAL")

# ---- 文档转换工具（doc-convert）----
CONVERT_MAX_MB = int(_env("LAB_TOOLS_CONVERT_MAX_MB", default="50"))
OCR_TIMEOUT = int(_env("LAB_TOOLS_OCR_TIMEOUT", default="120"))
PDF_TEXT_THRESHOLD = int(_env("LAB_TOOLS_PDF_TEXT_THRESHOLD", default="50"))
CROP_PDF_ZOOM = float(_env("LAB_TOOLS_CROP_PDF_ZOOM", default="2.0"))
PANDOC_TIMEOUT = int(_env("LAB_TOOLS_PANDOC_TIMEOUT", default="30"))
DOCX_REFERENCE_TEMPLATE = _env("LAB_TOOLS_DOCX_REFERENCE_TEMPLATE").strip()
LAYOUT_RECONSTRUCTION_ENABLED = _env_bool("LAB_TOOLS_LAYOUT_RECONSTRUCTION", default=True)
LAYOUT_HEADING_HEIGHT_RATIO = float(_env("LAB_TOOLS_LAYOUT_HEADING_HEIGHT_RATIO", default="1.3"))
LAYOUT_PARAGRAPH_GAP_RATIO = float(_env("LAB_TOOLS_LAYOUT_PARAGRAPH_GAP_RATIO", default="1.4"))
LAYOUT_INDENT_RATIO = float(_env("LAB_TOOLS_LAYOUT_INDENT_RATIO", default="0.5"))

# ---- 文档汇编工具（doc-compile）----
COMPILE_MAX_MB = int(_env("LAB_TOOLS_COMPILE_MAX_MB", default="50"))
# LibreOffice 可执行文件路径（留空 = 自动探测 which soffice 及常见安装目录）
SOFFICE_PATH = _env("LAB_TOOLS_SOFFICE_PATH").strip()
COMPILE_PREVIEW_DPI = int(_env("LAB_TOOLS_COMPILE_PREVIEW_DPI", default="150"))
COMPILE_CONVERT_TIMEOUT = int(_env("LAB_TOOLS_COMPILE_CONVERT_TIMEOUT", default="120"))
# 支持的输入扩展名（.wps 按魔数分类后再分派；分类为 zip 的 .wps 直接按 docx 处理）
COMPILE_ALLOWED_EXTENSIONS = {".doc", ".docm", ".docx", ".wps", ".rtf", ".txt"}

# ---- PDF 高保真转 Word 工具（pdf-reconstruct）----
RECONSTRUCT_MAX_MB = int(os.getenv("LAB_TOOLS_RECONSTRUCT_MAX_MB", "50"))
# 0 = 不限页数；扫描件走 OCR 时建议设小值，避免单个请求跑太久
RECONSTRUCT_MAX_PAGES = int(os.getenv("LAB_TOOLS_RECONSTRUCT_MAX_PAGES", "0"))

# ---- 节点身份（健康检查展示用）----
NODE_NAME = _env("LAB_TOOLS_NODE_NAME", default=socket.gethostname())
NODE_ROLE = _env("LAB_TOOLS_NODE_ROLE", default="main")

# OCR 节点信息（健康检查展示用）
OCR_NODE_NAME_DISPLAY = OCR_NODE_NAME
OCR_NODE_ROLE_DISPLAY = OCR_NODE_ROLE

# ---- 启用的工具集合（逗号分隔，空 = 全部）----
_enabled = _env("LAB_TOOLS_ENABLED").strip()
ENABLED_TOOLS = {t.strip() for t in _enabled.split(",") if t.strip()} if _enabled else None

HOST = _env("LAB_TOOLS_HOST", default="0.0.0.0")
PORT = int(_env("LAB_TOOLS_PORT", default="8000"))