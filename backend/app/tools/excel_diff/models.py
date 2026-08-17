from typing import List, Optional

from pydantic import BaseModel, Field

from ..excel_split.models import SheetInfo, UploadResponse  # noqa: F401  (复用上传响应模型)


class CompareRequest(BaseModel):
    base_file_id: str = Field(..., description="基准表文件 id")
    compare_file_id: str = Field(..., description="比对对象文件 id")
    base_sheet: str = Field(..., description="基准表要比对的 sheet 名称")
    compare_sheet: str = Field(..., description="比对表要比对的 sheet 名称")
    base_key_column: str = Field(..., description="基准表键列表头")
    compare_key_column: str = Field(..., description="比对表键列表头")
    value_columns: Optional[List[str]] = Field(
        None, description="要比对的值列表头；为空表示自动取两表共有的非键列"
    )
    output_mode: str = Field(
        "diff", description="输出模式：diff=独立差异明细表；highlight=在表格中高亮"
    )
    highlight_target: str = Field(
        "base", description="高亮底版：base=基准表；compare=比对表（仅 highlight 模式生效）"
    )


class DiffRow(BaseModel):
    diff_type: str = Field(..., description="changed=值差异；only_base=仅基准有；only_compare=仅比对有")
    key_column: str = ""
    key_value: str = ""
    column: str = ""
    base_value: str = ""
    compare_value: str = ""


class CompareStats(BaseModel):
    base_rows: int = 0
    compare_rows: int = 0
    matched: int = 0
    changed_rows: int = 0
    only_base: int = 0
    only_compare: int = 0
    identical: int = 0


class CompareResponse(BaseModel):
    job_id: str
    download_name: str
    output_mode: str
    stats: CompareStats
    skipped_columns: List[str] = []
    preview: List[DiffRow] = []
    preview_total: int = 0
