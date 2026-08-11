"""文档转换工具测试。"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.doc_convert import service

client = TestClient(app)


# ---- crop 解析与校验 ----

def test_parse_crop_valid():
    crop = service.parse_crop('{"unit":"ratio","x":0.1,"y":0.2,"width":0.5,"height":0.3}')
    assert crop == {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3}


def test_parse_crop_none():
    assert service.parse_crop("") is None
    assert service.parse_crop(None) is None


@pytest.mark.parametrize("raw", [
    "not-json",
    '{"unit":"pixel","x":10}',
    '{"unit":"ratio","x":1.5,"y":0,"width":0.1,"height":0.1}',
    '{"unit":"ratio","x":0.6,"y":0,"width":0.5,"height":0.1}',
    '{"unit":"ratio","x":0,"y":0,"width":0,"height":0.1}',
    '{"unit":"ratio","x":0,"y":0,"width":-1,"height":0.1}',
])
def test_parse_crop_invalid(raw):
    with pytest.raises(service.DocConvertError):
        service.parse_crop(raw)


# ---- 输出格式 ----

MARKDOWN_SAMPLE = (
    "# 大标题\n\n"
    "**加粗**与*斜体*，`行内代码`，[链接](http://example.com)，![图](img.png)。\n\n"
    "> 引用内容\n\n"
    "| 姓名 | 分数 |\n"
    "| --- | --- |\n"
    "| 张三 | 90 |\n\n"
    "---\n\n"
    "- 项目A\n"
    "- 项目B\n\n"
    "```python\n"
    "print('hi')\n"
    "```\n"
)


def test_strip_markdown_light():
    text = service.strip_markdown_light(MARKDOWN_SAMPLE)
    assert "# 大标题" not in text
    assert "大标题" in text
    assert "**" not in text and "*斜体*" not in text
    assert "行内代码" in text
    assert "[链接]" not in text and "链接" in text
    assert "> 引用内容" not in text and "引用内容" in text
    assert "| 张三 | 90 |" not in text
    assert "张三   90" in text
    assert "```" not in text


def test_markdown_to_docx_fallback():
    docx_bytes, engine = service.markdown_to_docx_bytes(MARKDOWN_SAMPLE)
    assert engine == "python-docx-fallback"
    assert len(docx_bytes) > 0
    assert zipfile.is_zipfile(io.BytesIO(docx_bytes))
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "大标题" in xml
    assert "张三" in xml
    assert "项目A" in xml


def test_validate_output_format():
    assert service.validate_output_format("txt") == "txt"
    with pytest.raises(service.DocConvertError):
        service.validate_output_format("html")


# ---- 版面重建（bbox 几何启发式）----

def make_line(text, top, height, left=10.0):
    return {
        "text": text,
        "bbox": [
            [left, top], [left + 200, top],
            [left + 200, top + height], [left, top + height],
        ],
    }


def test_reconstruct_layout_headings_and_paragraphs():
    median = 12.0
    lines = [
        make_line("一级大标题", 0, median * 2.5),           # 高度 ≥ 2x 中位 → #
        make_line("正文第一行", 40, median),
        make_line("正文第二行", 54, median),                 # 同行连续 → 合并
        make_line("二级标题", 80, median * 1.8),            # 1.6~2x → ##
        make_line("缩进内容", 110, median, left=40.0),      # 左缩进 → 引用块
        make_line("第三段", 140, median),
    ]
    md = service._reconstruct_layout(lines)
    assert md.startswith("# 一级大标题")
    assert "## 二级标题" in md
    assert "正文第一行正文第二行" in md  # 中文字符直接拼接不补空格
    assert "> 缩进内容" in md
    assert "\n\n" in md


def test_reconstruct_layout_paragraph_gap():
    lines = [
        make_line("第一段开头", 0, 12.0),
        make_line("第一段结尾", 15.0, 12.0),
        make_line("第二段开头", 60.0, 12.0),   # 间距 60-27=33 >> 12*1.4 → 分段
    ]
    md = service._reconstruct_layout(lines)
    assert "第一段开头第一段结尾" in md
    assert md.count("\n\n") == 1
    assert md.split("\n\n")[1] == "第二段开头"


# ---- PDF 分类与路由入口 ----

def test_classify_pdf_garbage_is_scanned():
    assert service.classify_pdf(b"not-a-real-pdf") == "scanned"


def test_convert_rejects_unknown_ext():
    with pytest.raises(service.DocConvertError):
        service.convert_document(b"hello", "文件.xyz", None, "md")


def test_convert_rejects_docx_to_docx():
    with pytest.raises(service.DocConvertError, match="docx"):
        service.convert_document(b"x", "源文档.docx", None, "docx")


def test_convert_rejects_bad_crop():
    with pytest.raises(service.DocConvertError):
        service.parse_crop("not-json")


# ---- HTTP 接口 ----

def md_bytes() -> bytes:
    return "# 标题\n\n正文内容\n".encode("utf-8")


def test_convert_md_endpoint_and_download():
    r = client.post(
        "/api/tools/doc-convert/convert",
        files={"file": ("示例.md", md_bytes(), "text/markdown")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["engine"] == "markitdown"
    assert data["content"].startswith("# 标题")
    assert data["download_name"] == "示例.md"

    dl = client.get(f"/api/tools/doc-convert/download/{data['job_id']}")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("text/markdown")
    assert "标题" in dl.content.decode("utf-8")


def test_convert_docx_endpoint_download():
    r = client.post(
        "/api/tools/doc-convert/convert",
        files={"file": ("示例.md", md_bytes(), "text/markdown")},
        data={"output_format": "docx"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["docx_engine"] == "python-docx-fallback"
    assert zipfile.is_zipfile(io.BytesIO(__import__("base64").b64decode(data["file_base64"])))

    dl = client.get(f"/api/tools/doc-convert/download/{data['job_id']}")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/vnd.openxmlformats-")


def test_convert_formats_endpoint():
    r = client.get("/api/tools/doc-convert/supported-formats")
    assert r.status_code == 200
    assert r.json()["output_formats"] == ["md", "txt", "docx"]
    assert ".docx" in r.json()["local_formats"]
    assert ".png" in r.json()["ocr_formats"]


def test_convert_health_endpoint():
    r = client.get("/api/tools/doc-convert/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "UP"
    assert "ocr_status" in body and "metrics" in body


def test_tools_registry_contains_doc_convert():
    tools = client.get("/api/tools").json()
    assert any(t["id"] == "doc-convert" and t["route"] == "/tools/doc-convert" for t in tools)