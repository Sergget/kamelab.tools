"""工具注册表：首页根据此列表渲染可用工具。

后续新增工具时在此登记即可（id、名称、描述、前端路由、图标）。
"""

from .. import config

TOOLS = [
    {
        "id": "excel-split",
        "name": "Excel 表格拆分",
        "description": "上传 Excel，按表头值拆分内容，自定义输出文件标题，只保留需要的列。",
        "icon": "Grid",
        "route": "/tools/excel-split",
        "keywords": ["excel", "xlsx", "xls", "拆分", "表格"],
    },
    {
        "id": "doc-convert",
        "name": "文档转换",
        "description": "上传文档/图片/PDF，转换为 Markdown、纯文本或 Word，支持 OCR 识别与区域裁剪。",
        "icon": "Document",
        "route": "/tools/doc-convert",
        "keywords": ["docx", "pdf", "ocr", "markdown", "转换", "图片", "扫描", "扫描件"],
    },
    {
        "id": "excel-diff",
        "name": "Excel 表格比对",
        "description": "上传基准表与比对表，按指定键列匹配、可选值列，输出差异明细表或在表格中高亮差异。",
        "icon": "Files",
        "route": "/tools/excel-diff",
        "keywords": ["excel", "xlsx", "xls", "比对", "对比", "差异", "diff", "高亮", "表格"],
    },
]


def enabled_tools():
    """返回启用的工具列表。若配置了 LAB_TOOLS_ENABLED 则按其过滤，否则返回全部。"""
    if config.ENABLED_TOOLS is None:
        return TOOLS
    enabled = config.ENABLED_TOOLS
    return [t for t in TOOLS if t["id"] in enabled]