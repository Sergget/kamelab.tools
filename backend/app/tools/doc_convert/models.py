"""文档转换接口模型。"""

from typing import Optional

from pydantic import BaseModel, Field

SUPPORTED_OUTPUT_FORMATS = ("md", "txt", "docx")


class ConvertResponse(BaseModel):
    success: bool
    job_id: str = ""
    filename: str = ""
    download_name: str = ""
    output_format: str = "md"
    mime_type: str = "text/markdown"
    content: Optional[str] = Field(None, description="md/txt 输出时的文本内容")
    file_base64: Optional[str] = Field(None, description="docx 输出时的文件内容（base64）")
    engine: str = ""
    routed_to: str = ""
    pages: Optional[int] = None
    elapsed_ms: int = 0
    file_size_mb: float = 0.0
    layout_reconstructed: bool = False
    crop_applied: bool = False
    crop_ignored: Optional[str] = None
    docx_engine: Optional[str] = None
    error: Optional[str] = None