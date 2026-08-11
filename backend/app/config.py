import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("LAB_TOOLS_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
STATIC_DIR = Path(os.getenv("LAB_TOOLS_STATIC_DIR", str(BASE_DIR / "app" / "static")))

TEMP_TTL_HOURS = float(os.getenv("LAB_TOOLS_TTL_HOURS", "2"))
MAX_UPLOAD_MB = int(os.getenv("LAB_TOOLS_MAX_UPLOAD_MB", "100"))
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

HOST = os.getenv("LAB_TOOLS_HOST", "0.0.0.0")
PORT = int(os.getenv("LAB_TOOLS_PORT", "8000"))