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
    {
        "id": "contact-manager",
        "name": "通讯录归档与管理",
        "description": "处理、格式化、归档不同日期的通讯录Excel，自动提取特征与字段映射，支持多版本时点查询与可视化增删改查。删除项目前必须先验证密码，再导出完整数据库备份。",
        "icon": "User",
        "route": "/tools/contact-manager",
        "keywords": ["通讯录", "excel", "归档", "管理", "联系人", "版本"],
    },
    {
        "id": "doc-compile",
        "name": "文档汇编",
        "description": "批量上传 Word/WPS 文档（doc/docx/docm/wps 等），拖拽排序后自动汇编为单个 Word 文档，支持标题作者识别编辑、目录与封面，可写回源文档。",
        "icon": "Collection",
        "route": "/tools/doc-compile",
        "keywords": ["doc", "docx", "docm", "wps", "汇编", "合并", "目录", "Word", "批量"],
    },
]


def enabled_tools(mounted=None):
    """返回启用的工具列表。

    - 若配置了 LAB_TOOLS_ENABLED，则按其过滤；否则返回全部登记项。
    - mounted 为实际挂载成功的工具 id 集合（由 main.py 传入）：只对外通告
      真正可用的工具，避免首页出现「登记了但工具包缺失/依赖不全」的入口。
    """
    tools = TOOLS
    if config.ENABLED_TOOLS is not None:
        enabled = config.ENABLED_TOOLS
        tools = [t for t in tools if t["id"] in enabled]
    if mounted is not None:
        tools = [t for t in tools if t["id"] in mounted]
    return tools