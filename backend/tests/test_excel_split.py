import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_workbook_bytes() -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df1 = pd.DataFrame(
            {
                "部门": ["销售", "销售", "研发", "研发", "测试"],
                "姓名": ["张三", "李四", "王五", "赵六", "钱七"],
                "工资": [100, 200, 300, 400, 500],
            }
        )
        df2 = pd.DataFrame(
            {
                "部门": ["销售", "研发"],
                "姓名": ["孙八", "周九"],
                "工资": [600, 700],
            }
        )
        df1.to_excel(writer, index=False, sheet_name="工资表")
        df2.to_excel(writer, index=False, sheet_name="补充表")
    return buffer.getvalue()


def make_empty_workbook_bytes() -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, index=False, sheet_name="空表")
    return buffer.getvalue()


def upload(content: bytes, fname: str = "测试工资.xlsx") -> dict:
    response = client.post(
        "/api/tools/excel-split/upload",
        files={"file": (fname, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def uploaded():
    return upload(make_workbook_bytes())


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_tools_registry():
    tools = client.get("/api/tools").json()
    ids = [t["id"] for t in tools]
    assert "excel-split" in ids


def test_upload_rejects_bad_ext():
    response = client.post(
        "/api/tools/excel-split/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_sheets(uploaded):
    assert uploaded["file_name"] == "测试工资.xlsx"
    names = [s["name"] for s in uploaded["sheets"]]
    assert names == ["工资表", "补充表"]
    assert uploaded["sheets"][0]["rows"] == 5


def test_preview(uploaded):
    file_id = uploaded["file_id"]
    response = client.get(f"/api/tools/excel-split/{file_id}/preview", params={"sheet": "工资表"})
    data = response.json()
    assert data["headers"] == ["部门", "姓名", "工资"]
    assert data["total"] == 5
    assert data["rows"][0] == ["销售", "张三", 100]
    assert data["rows"][3] == ["研发", "赵六", 400]


def test_preview_pagination(uploaded):
    file_id = uploaded["file_id"]
    response = client.get(
        f"/api/tools/excel-split/{file_id}/preview",
        params={"sheet": "工资表", "skip": 2, "limit": 2},
    )
    data = response.json()
    assert len(data["rows"]) == 2
    assert data["rows"][0][1] == "王五"


def test_split_separate_zip(uploaded):
    file_id = uploaded["file_id"]
    response = client.post(
        f"/api/tools/excel-split/{file_id}/split",
        json={
            "split_column": "部门",
            "keep_columns": ["部门", "姓名"],
            "filename_template": "{value}_{sheet}",
            "output_mode": "separate",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "separate"
    assert data["is_zip"] is True
    assert data["total_rows"] == 7
    keys = sorted(g["key"] for g in data["groups"])
    assert keys == ["测试", "研发", "研发", "销售", "销售"]
    names = {g["file_name"] for g in data["groups"]}
    assert names == {"销售_工资表.xlsx", "销售_补充表.xlsx", "研发_工资表.xlsx",
                     "研发_补充表.xlsx", "测试_工资表.xlsx"}

    dl = client.get(f"/api/tools/excel-split/download/{data['job_id']}")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"

    import zipfile

    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
        assert set(zf.namelist()) == names
        df = pd.read_excel(zf.open("销售_工资表.xlsx"))
        assert list(df.columns) == ["部门", "姓名"]
        assert len(df) == 2


def test_split_filename_collision_suffix(uploaded):
    file_id = uploaded["file_id"]
    response = client.post(
        f"/api/tools/excel-split/{file_id}/split",
        json={
            "split_column": "部门",
            "filename_template": "{value}",
            "output_mode": "separate",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    names = sorted(g["file_name"] for g in data["groups"])
    assert names == ["测试.xlsx", "研发.xlsx", "研发_2.xlsx", "销售.xlsx", "销售_2.xlsx"]


def test_split_single_file():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"部门": ["销售", "销售", "销售"], "姓名": ["甲", "乙", "丙"]}).to_excel(
            writer, index=False, sheet_name="表"
        )
    data = upload(buffer.getvalue(), "单值.xlsx")
    response = client.post(
        f"/api/tools/excel-split/{data['file_id']}/split",
        json={"split_column": "部门", "filename_template": "{value}", "output_mode": "separate"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["groups"]) == 1
    assert result["is_zip"] is False
    dl = client.get(f"/api/tools/excel-split/download/{result['job_id']}")
    assert dl.status_code == 200
    df = pd.read_excel(io.BytesIO(dl.content))
    assert len(df) == 3

    # 按姓名拆分（全部唯一）则打包 zip，且文件名按模板带序号
    response = client.post(
        f"/api/tools/excel-split/{data['file_id']}/split",
        json={"split_column": "姓名", "filename_template": "单据_{index}", "output_mode": "separate"},
    )
    result = response.json()
    assert len(result["groups"]) == 3
    assert result["is_zip"] is True


def test_split_workbook_mode(uploaded):
    file_id = uploaded["file_id"]
    response = client.post(
        f"/api/tools/excel-split/{file_id}/split",
        json={
            "split_column": "部门",
            "sheet_title_template": "分组_{value}",
            "output_mode": "workbook",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_zip"] is False
    assert data["download_name"].endswith(".xlsx")

    dl = client.get(f"/api/tools/excel-split/download/{data['job_id']}")
    sheets = pd.read_excel(io.BytesIO(dl.content), sheet_name=None)
    assert set(sheets.keys()) == {"分组_测试", "分组_研发", "分组_销售"}
    assert len(sheets["分组_销售"]) == 3


def test_split_invalid_column(uploaded):
    response = client.post(
        f"/api/tools/excel-split/{uploaded['file_id']}/split",
        json={"split_column": "不存在的列"},
    )
    assert response.status_code == 400


def test_split_no_kept_columns(uploaded):
    response = client.post(
        f"/api/tools/excel-split/{uploaded['file_id']}/split",
        json={"split_column": "部门", "keep_columns": ["不存在的列"]},
    )
    assert response.status_code == 400


def test_invalid_extension_upload():
    response = client.post(
        "/api/tools/excel-split/upload",
        files={"file": ("bad.csv", b"a,b", "text/csv")},
    )
    assert response.status_code == 400


def test_empty_workbook():
    data = upload(make_empty_workbook_bytes(), "空表.xlsx")
    response = client.post(
        f"/api/tools/excel-split/{data['file_id']}/split",
        json={"split_column": "部门"},
    )
    assert response.status_code == 400


def test_unknown_job_download():
    response = client.get("/api/tools/excel-split/download/deadbeef")
    assert response.status_code == 404


def test_sanitize_filename_part():
    from app.tools.excel_split import service

    assert service.sanitize_filename_part('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert service.sanitize_filename_part("con") == "未命名"
    assert service.sanitize_filename_part("") == "未命名"


def test_render_template():
    from datetime import datetime
    from app.tools.excel_split import service

    out = service.render_template("{value}-{sheet}-{index}", value=" 销售 ", sheet="工资表", index=3, now=datetime(2026, 8, 11, 9, 30))
    assert out == "销售-工资表-003"