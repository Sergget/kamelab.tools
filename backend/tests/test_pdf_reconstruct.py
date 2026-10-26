"""pdf-reconstruct 工具接口测试。

转换链路依赖 kame-officetools 内核，未安装时相关用例跳过；
不依赖内核的分支（参数校验、下载 404、健康探活）始终执行。
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.pdf_reconstruct import service

client = TestClient(app)

CONVERT_URL = "/api/tools/pdf-reconstruct/convert"
DOWNLOAD_URL = "/api/tools/pdf-reconstruct/download"


def _docx_paragraphs(data: bytes) -> list:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    out = []
    for chunk in xml.split("<w:p>")[1:]:
        start = chunk.find("<w:t")
        if start < 0:
            continue
        text = chunk[chunk.find(">", start) + 1:chunk.find("</w:t>")]
        if text.strip():
            out.append(text.strip())
    return out


def _make_pdf(lines) -> bytes:
    fitz = pytest.importorskip("fitz", reason="需要 PyMuPDF 生成测试 PDF")
    doc = fitz.open()
    page = doc.new_page()
    y = 90
    for line in lines:
        page.insert_text((72, y), line, fontsize=13, fontname="china-s")
        y += 34
    data = doc.tobytes()
    doc.close()
    return data


# ---- 工具注册 ----


def test_tool_is_registered():
    tools = client.get("/api/tools").json()
    ids = [t["id"] for t in tools]
    assert "pdf-reconstruct" in ids


def test_tool_registry_entry_shape():
    tools = client.get("/api/tools").json()
    entry = next(t for t in tools if t["id"] == "pdf-reconstruct")
    assert entry["route"] == "/tools/pdf-reconstruct"
    assert entry["name"]
    assert entry["description"]
    assert entry["icon"] == "Tickets"
    assert "pdf" in entry["keywords"]


# ---- 健康探活 ----


def test_health_reports_kernel_state():
    resp = client.get("/api/tools/pdf-reconstruct/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"UP", "DOWN"}
    assert body["engine"] == service.ENGINE_NAME
    assert body["max_file_size_mb"] > 0
    if body["status"] == "UP":
        assert body["kernel_version"]
    else:
        assert body["detail"]


# ---- 参数校验（不依赖内核）----


def test_convert_rejects_non_pdf():
    resp = client.post(
        CONVERT_URL, files={"file": ("note.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_convert_rejects_empty_file():
    resp = client.post(
        CONVERT_URL, files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert resp.status_code == 400
    assert "空" in resp.json()["detail"]


def test_download_returns_404_for_unknown_job():
    resp = client.get(f"{DOWNLOAD_URL}/not-a-real-job")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "产物不存在或已过期"


# ---- 内核封装（不依赖真实 PDF）----


def test_service_rejects_empty_bytes():
    with pytest.raises(service.ReconstructError) as exc:
        service.convert_pdf_to_docx(b"", "empty.pdf")
    assert exc.value.status == 400


def test_friendly_error_maps_corrupt_pdf():
    raw = "Failed to open file 'C:\\Temp\\pdfrecon_x\\in\\a.pdf' as type pdf."
    assert service._friendly_error(raw) == "文件不是有效的 PDF，或文件已损坏，无法解析"


def test_friendly_error_strips_windows_paths():
    cleaned = service._friendly_error("boom at C:\\Temp\\pdfrecon_x\\in\\a.pdf now")
    assert "C:\\Temp" not in cleaned
    assert "临时文件" in cleaned


def test_friendly_error_falls_back_for_blank_message():
    assert service._friendly_error("") == "PDF 转换失败"


def test_sanitize_stem_removes_illegal_chars():
    # Path(...).stem 会先丢掉路径分量，再替换 Windows 非法字符
    assert service._sanitize_stem('a<b>c:d"e/f\\g|h?i*.pdf') == "g_h_i_"


def test_sanitize_stem_blocks_path_traversal():
    assert service._sanitize_stem("../../etc/passwd.pdf") == "passwd"


def test_sanitize_stem_falls_back_when_empty():
    assert service._sanitize_stem("...") == "document"
    assert service._sanitize_stem("") == "document"


def test_sanitize_stem_caps_length():
    assert len(service._sanitize_stem("x" * 200 + ".pdf")) == 80


# ---- 真实转换（依赖内核）----


def test_convert_digital_pdf_returns_docx():
    pytest.importorskip("kame_officetools", reason="未安装转换内核")
    pdf = _make_pdf(["甲方应在验收后十个工作日内付款。"])

    resp = client.post(
        CONVERT_URL, files={"file": ("合同 扫描.pdf", pdf, "application/pdf")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["pdf_type"] == "digital"
    assert body["chars"] > 0
    assert body["download_name"] == "合同 扫描.docx"
    assert body["kernel_version"]
    assert body["elapsed_ms"] >= 0

    dl = client.get(f"{DOWNLOAD_URL}/{body['job_id']}")
    assert dl.status_code == 200
    assert dl.content[:2] == b"PK"
    assert "wordprocessingml" in dl.headers["content-type"]
    assert "十个工作日" in "".join(_docx_paragraphs(dl.content))


def test_convert_splits_chinese_paragraphs():
    pytest.importorskip("kame_officetools", reason="未安装转换内核")
    pdf = _make_pdf(
        ["一、项目背景", "本合同项下的服务范围包括三项。", "二、付款方式", "甲方应在十个工作日内付款。"]
    )

    resp = client.post(CONVERT_URL, files={"file": ("分段.pdf", pdf, "application/pdf")})
    assert resp.status_code == 200, resp.text
    dl = client.get(f"{DOWNLOAD_URL}/{resp.json()['job_id']}")
    paras = _docx_paragraphs(dl.content)
    assert len(paras) >= 3
    assert any(p.startswith("一、项目背景") for p in paras)
    assert any(p.startswith("二、付款方式") for p in paras)


def test_convert_blank_pdf_returns_422_not_fake_success():
    pytest.importorskip("kame_officetools", reason="未安装转换内核")
    pdf = _make_pdf([])

    resp = client.post(CONVERT_URL, files={"file": ("空白.pdf", pdf, "application/pdf")})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "C:\\" not in detail  # 不把服务器临时路径透给前端
