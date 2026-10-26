"""PDF 高保真转 Word 接口模型。"""

from typing import Optional

from pydantic import BaseModel, Field

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class ReconstructResponse(BaseModel):
    success: bool
    job_id: str = ""
    filename: str = ""
    download_name: str = ""
    output_format: str = "docx"
    mime_type: str = DOCX_MIME
    pdf_type: str = Field("", description="digital（有文字层）或 scanned（走 OCR）")
    chars: int = Field(0, description="提取到的字符数，为 0 时不会返回成功")
    elapsed_ms: int = 0
    engine: str = ""
    kernel_version: str = ""
    error: Optional[str] = None
