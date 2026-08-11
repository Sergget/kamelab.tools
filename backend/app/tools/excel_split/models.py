from typing import List, Optional

from pydantic import BaseModel, Field


class SplitRequest(BaseModel):
    sheet: Optional[str] = Field(None, description="要拆分的 sheet 名称；为空表示拆分所有 sheet")
    split_column: str = Field(..., description="用于拆分的表头名称")
    keep_columns: Optional[List[str]] = Field(None, description="输出文件中保留的列；为空表示全部保留")
    filename_template: str = Field(
        "{value}",
        description="输出文件名模板，支持 {value}/{sheet}/{index}/{date}/{time}",
    )
    sheet_title_template: Optional[str] = Field(
        None, description="单工作簿模式下每个分组的 sheet 标题模板，默认 {value}"
    )
    output_mode: str = Field("separate", description="separate=多个文件(压缩包)；workbook=单个工作簿多 sheet")


class SheetInfo(BaseModel):
    name: str
    rows: int
    cols: int
    headers: List[str] = []


class UploadResponse(BaseModel):
    file_id: str
    file_name: str
    sheets: List[SheetInfo]


class GroupResult(BaseModel):
    key: str
    file_name: str = ""
    sheet_name: str = ""
    rows: int


class SplitResponse(BaseModel):
    job_id: str
    mode: str
    download_name: str
    is_zip: bool
    groups: List[GroupResult]
    total_rows: int