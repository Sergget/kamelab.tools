"""文档自动汇编工具（doc-compile）。

批量上传 Word/WPS 文档（doc/docx/docm/wps/rtf/txt），按「魔数」自动识别
真实格式并统一转换为 docx，提供队列预览、标题作者识别与编辑、写回源文档、
按序汇编为单个 Word 文档（可选目录/封面/分页），输出 doc/docx/wps。
"""

SUPPORTED_OUTPUT_FORMATS = ("docx", "doc", "wps")