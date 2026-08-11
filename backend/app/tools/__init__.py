"""工具注册表：首页根据此列表渲染可用工具。

后续新增工具时在此登记即可（id、名称、描述、前端路由、图标）。
"""

TOOLS = [
    {
        "id": "excel-split",
        "name": "Excel 表格拆分",
        "description": "上传 Excel，按表头值拆分内容，自定义输出文件标题，只保留需要的列。",
        "icon": "Grid",
        "route": "/tools/excel-split",
        "keywords": ["excel", "xlsx", "xls", "拆分", "表格"],
    },
]