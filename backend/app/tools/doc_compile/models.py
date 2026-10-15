"""文档汇编接口模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class CoverOptions(BaseModel):
    enabled: bool = False
    title: str = "汇编文档"
    subtitle: str = ""
    date: str = ""


class TocOptions(BaseModel):
    enabled: bool = False
    mode: str = "custom"  # field=Word 目录域 | custom=静态自定义目录
    template: str = "<seq>. <title>……<author>"
    include_page_numbers: bool = False


class StyleSheet(BaseModel):
    title_font: str = "黑体"
    title_size_pt: int = 16
    author_font: str = "楷体"
    author_size_pt: int = 12


class CompileOptions(BaseModel):
    output_format: str = "docx"  # docx | doc | wps
    toc: TocOptions = Field(default_factory=TocOptions)
    cover: CoverOptions = Field(default_factory=CoverOptions)
    page_break_between: bool = True
    stylesheet: StyleSheet = Field(default_factory=StyleSheet)


class CompileItem(BaseModel):
    file_id: str
    title: str = ""  # 空 = 使用识别值
    author: str = ""  # 空 = 使用识别值
    apply_to_source: bool = False


class CompileRequest(BaseModel):
    items: List[CompileItem]
    options: CompileOptions = Field(default_factory=CompileOptions)


class MetaUpdate(BaseModel):
    title: str = ""
    author: str = ""
    apply_to_source: bool = False