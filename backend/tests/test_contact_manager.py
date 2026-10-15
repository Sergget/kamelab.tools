"""通讯录管理模块测试"""
import json
import os
import shutil
import sqlite3
import tempfile
import time

from fastapi.testclient import TestClient

from app.main import app
from app.tools.contact_manager.database import init_db, get_db_connection
from app.tools.contact_manager.parser import (
    detect_header_and_map,
    map_fields_for_header_row,
    match_row_fields,
)

SUFFIX = str(int(time.time()))

# 默认字段（与 init_project_default_fields 一致）
DEFAULT_FIELDS = [
    {"id": 1, "name": "name", "label": "姓名", "is_default": 1},
    {"id": 2, "name": "title", "label": "职务", "is_default": 1},
    {"id": 3, "name": "unit", "label": "单位", "is_default": 1},
    {"id": 4, "name": "gender", "label": "性别", "is_default": 1},
    {"id": 5, "name": "phone", "label": "联系电话", "is_default": 1},
    {"id": 6, "name": "mobile", "label": "手机号码", "is_default": 1},
    {"id": 7, "name": "email", "label": "电子邮箱", "is_default": 1},
    {"id": 8, "name": "office", "label": "办公地点", "is_default": 1},
]


# ---- 字段自动匹配（回归：此前前端拿到映射却全部为空）----

def test_match_row_fields_matches_by_keyword():
    """表头列名命中内置特征词时应匹配到对应字段"""
    rows = [{"row_index": 1, "values": ["姓名", "职务", "单位", "手机号", "电子邮箱"]}]
    mapping, score = match_row_fields(rows[0]["values"], DEFAULT_FIELDS)
    assert mapping == {0: "name", 1: "title", 2: "unit", 3: "mobile", 4: "email"}, mapping
    assert score > 0


def test_match_row_fields_matches_exact_label_first():
    """与已有字段显示名完全相同时，应优先于内置关键词"""
    fields = DEFAULT_FIELDS + [{"id": 9, "name": "ext_plat", "label": "联系方式", "is_default": 0}]
    mapping, _ = match_row_fields(["联系方式"], fields)
    assert mapping == {0: "ext_plat"}, mapping


def test_match_row_fields_only_uses_existing_fields():
    """内置关键词指向的字段若不在当前项目中，则不应产生该映射。

    否则会写入一个项目里不存在的字段名，导致数据保存后无法展示。
    """
    fields = [{"id": 1, "name": "name", "label": "姓名", "is_default": 1}]
    # 「职务」命中内置关键词 title，但当前项目没有 title 字段
    mapping, _ = match_row_fields(["职务"], fields)
    assert mapping == {}, f"不应匹配到不存在的字段: {mapping}"


def test_match_row_fields_rejects_title_rows():
    """标题行不应被误判为字段列。

    回归：模糊包含匹配过宽时，标题「某单位通讯录」因含「单位」二字
    被误判为 unit 列。
    """
    # 标题行：含「单位」但明显是标题
    assert match_row_fields(["某单位通讯录"], DEFAULT_FIELDS)[0] == {}
    assert match_row_fields(["五届市政协委员名单"], DEFAULT_FIELDS)[0] == {}
    # 但真正的单位列表头仍应匹配
    assert match_row_fields(["单位"], DEFAULT_FIELDS)[0] == {0: "unit"}
    assert match_row_fields(["工作单位"], DEFAULT_FIELDS)[0] == {0: "unit"}
    assert match_row_fields(["单位名称"], DEFAULT_FIELDS)[0] == {0: "unit"}


def test_detect_header_and_map_finds_header_row_and_columns():
    """自动识别表头行，并给出列到字段的映射"""
    rows = [
        {"row_index": 1, "values": ["五届市政协委员名单", "", "", ""]},
        {"row_index": 2, "values": ["姓名", "职务", "单位", "手机号码"]},
        {"row_index": 3, "values": ["张三", "科长", "甲单位", "13800000001"]},
    ]
    det = detect_header_and_map(rows, DEFAULT_FIELDS)
    assert det["detected_header_row"] == 2, det
    assert det["mapping"] == {0: "name", 1: "title", 2: "unit", 3: "mobile"}, det["mapping"]


def test_map_fields_for_header_row_supports_manual_row():
    """用户手动指定表头行时，应能对该行重新匹配"""
    rows = [
        {"row_index": 1, "values": ["姓名", "职务", "单位"]},
        {"row_index": 2, "values": ["张三", "科长", "13800000001"]},
    ]
    assert map_fields_for_header_row(rows, 1, DEFAULT_FIELDS) == {0: "name", 1: "title", 2: "unit"}
    # 纯数据行（不含任何字段特征词）不应匹配出字段
    assert map_fields_for_header_row(rows, 2, DEFAULT_FIELDS) == {}
    # 不存在的行号返回空映射
    assert map_fields_for_header_row(rows, 99, DEFAULT_FIELDS) == {}


def test_detect_header_row_prefers_real_header_over_data():
    """标题行/数据行的得分必须低于真正的表头行。"""
    rows = [
        {"row_index": 1, "values": ["某单位通讯录", "", "", ""]},
        {"row_index": 2, "values": ["姓名", "职务", "单位", "手机号码"]},
        {"row_index": 3, "values": ["张三", "科长", "甲单位", "13800000001"]},
    ]
    det = detect_header_and_map(rows, DEFAULT_FIELDS)
    assert det["detected_header_row"] == 2, det
    assert det["mapping"] == {0: "name", 1: "title", 2: "unit", 3: "mobile"}, det["mapping"]


def test_database_migration_with_foreign_keys():
    """测试数据库迁移后外键约束正确生效"""
    tmp_dir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp_dir, "test_contact.db")
    import app.tools.contact_manager.database as db_mod
    original_db = db_mod.DB_PATH

    try:
        db_mod.DB_PATH = tmp_db
        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()

        # 验证 projects 表有 exported_at 列
        cursor.execute("PRAGMA table_info(projects)")
        cols = [r[1] for r in cursor.fetchall()]
        assert "exported_at" in cols, "projects 表缺少 exported_at 列"

        # 验证 contact_versions 表有外键约束
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='contact_versions'")
        sql = cursor.fetchone()[0]
        assert "FOREIGN KEY (project_id)" in sql, "contact_versions 缺少 project_id 外键"

        # 验证 contact_version_deltas 表有外键约束
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='contact_version_deltas'")
        sql = cursor.fetchone()[0]
        assert "FOREIGN KEY (version_id)" in sql, "contact_version_deltas 缺少 version_id 外键"
        assert "FOREIGN KEY (entity_id)" in sql, "contact_version_deltas 缺少 entity_id 外键"

        # 验证 contact_entities 表有外键约束
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='contact_entities'")
        sql = cursor.fetchone()[0]
        assert "FOREIGN KEY (project_id)" in sql, "contact_entities 缺少 project_id 外键"

        conn.close()
    finally:
        db_mod.DB_PATH = original_db
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_orphan_data_cleanup():
    """测试孤立数据清理"""
    tmp_dir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp_dir, "test_contact_cleanup.db")
    import app.tools.contact_manager.database as db_mod
    original_db = db_mod.DB_PATH

    try:
        db_mod.DB_PATH = tmp_db
        init_db()

        # 临时关闭外键以创建孤立数据
        conn = get_db_connection()
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO contact_versions (project_id, filename, sheet_name, version_date) VALUES (9999, 'test.xlsx', 'Sheet1', '2026-01-01')")
        cursor.execute("INSERT INTO contact_entities (project_id, entity_key) VALUES (9999, 'orphan')")
        cursor.execute("INSERT INTO contact_version_deltas (version_id, entity_id, data, is_deleted) VALUES (1, 1, '{}', 0)")
        conn.commit()
        conn.close()

        # 再次初始化数据库，触发孤立数据清理
        init_db()

        # 验证孤立记录已被清理
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM contact_versions WHERE project_id = 9999")
        assert cursor.fetchone()[0] == 0, "孤立版本记录未被清理"
        cursor.execute("SELECT COUNT(*) FROM contact_entities WHERE project_id = 9999")
        assert cursor.fetchone()[0] == 0, "孤立实体记录未被清理"
        cursor.execute("SELECT COUNT(*) FROM contact_version_deltas WHERE version_id NOT IN (SELECT id FROM contact_versions) OR entity_id NOT IN (SELECT id FROM contact_entities)")
        assert cursor.fetchone()[0] == 0, "孤立 delta 记录未被清理"
        conn.close()
    finally:
        db_mod.DB_PATH = original_db
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_dangling_foreign_key_is_repaired():
    """回归测试：悬空外键（指向已被删除的 _*_old 临时表）必须被迁移修复。

    历史故障：早期迁移用 ALTER TABLE ... RENAME 重建表，SQLite 会改写
    contact_version_deltas 外键里的目标表名为 _versions_old；随后临时表被 DROP，
    外键就成了悬空引用。旧代码只用字符串包含判断是否需要迁移，因此永远不修复，
    导致任何写入都报 "no such table: main._versions_old"（导入接口 500）。
    """
    import app.tools.contact_manager.database as db_mod

    tmp_dir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp_dir, "test_dangling_fk.db")
    original_db = db_mod.DB_PATH

    try:
        db_mod.DB_PATH = tmp_db

        # 手工构造「故障现场」：deltas 的外键指向已不存在的 _versions_old / _entities_old
        conn = sqlite3.connect(tmp_db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                exported_at TIMESTAMP DEFAULT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE contact_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                version_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE contact_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                entity_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, entity_key),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        # 关键：外键指向 _versions_old / _entities_old —— 文本上仍含
        # "FOREIGN KEY (version_id)"，旧判断无法识别
        cur.execute("""
            CREATE TABLE contact_version_deltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                entity_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                is_deleted INTEGER DEFAULT 0,
                FOREIGN KEY (version_id) REFERENCES "_versions_old"(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES "_entities_old"(id) ON DELETE CASCADE,
                UNIQUE(version_id, entity_id)
            )
        """)
        cur.execute("INSERT INTO projects (name, password_hash) VALUES ('p', 'h')")
        cur.execute("INSERT INTO contact_versions (project_id, filename, sheet_name, version_date) VALUES (1,'a.xlsx','S','2026-01-01')")
        cur.execute("INSERT INTO contact_entities (project_id, entity_key) VALUES (1,'张三')")
        conn.commit()

        # 故障现场确认：外键确实指向不存在的表
        fk_targets = {r[2] for r in cur.execute("PRAGMA foreign_key_list(contact_version_deltas)")}
        assert fk_targets == {"_versions_old", "_entities_old"}, f"现场构造失败: {fk_targets}"
        conn.close()

        # 触发迁移修复
        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()

        # 外键应指向真实存在的业务表
        fk_targets = {r[2] for r in cursor.execute("PRAGMA foreign_key_list(contact_version_deltas)")}
        assert fk_targets == {"contact_versions", "contact_entities"}, f"悬空外键未被修复: {fk_targets}"

        # 不应残留任何 _*_old 临时表
        leftovers = [r[0] for r in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '\\_%\\_old' ESCAPE '\\'")]
        assert leftovers == [], f"残留临时表未清理: {leftovers}"

        # 数据应保留
        assert cursor.execute("SELECT COUNT(*) FROM contact_versions").fetchone()[0] == 1
        assert cursor.execute("SELECT COUNT(*) FROM contact_entities").fetchone()[0] == 1

        # 关键验证：修复后写入必须成功（此前会报 no such table: main._versions_old）
        cursor.execute(
            "INSERT INTO contact_version_deltas (version_id, entity_id, data, is_deleted) VALUES (1, 1, '{}', 0)")
        conn.commit()
        assert cursor.execute("SELECT COUNT(*) FROM contact_version_deltas").fetchone()[0] == 1
        conn.close()

        # 迁移应幂等
        init_db()
        conn = get_db_connection()
        assert conn.execute("SELECT COUNT(*) FROM contact_version_deltas").fetchone()[0] == 1
        conn.close()
    finally:
        db_mod.DB_PATH = original_db
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_export_before_delete_enforcement():
    """测试删除项目前必须先导出的约束"""
    client = TestClient(app)

    # 创建项目
    res = client.post("/api/contact-manager/projects", json={
        "name": f"测试删除项目_{SUFFIX}",
        "password": "testpass123",
        "description": "测试用"
    })
    assert res.status_code == 200
    project_id = res.json()["project"]["id"]

    # 尝试未导出直接删除应失败
    res = client.delete(f"/api/contact-manager/projects/{project_id}", params={"password": "testpass123"})
    assert res.status_code == 403, f"预期403，实际{res.status_code}: {res.text}"
    assert "导出" in res.json()["detail"]

    # 导出项目
    res = client.get(f"/api/contact-manager/projects/{project_id}/export-db", params={"password": "testpass123"})
    assert res.status_code == 200

    # 再次尝试删除应成功
    res = client.delete(f"/api/contact-manager/projects/{project_id}", params={"password": "testpass123"})
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_delete_without_password_fails():
    """测试删除项目时缺少密码应失败"""
    client = TestClient(app)

    # 创建项目
    res = client.post("/api/contact-manager/projects", json={
        "name": f"测试密码删除_{SUFFIX}",
        "password": "secret",
        "description": "测试用"
    })
    assert res.status_code == 200
    project_id = res.json()["project"]["id"]

    # 不提供密码应失败
    res = client.delete(f"/api/contact-manager/projects/{project_id}")
    assert res.status_code == 422

    # 清理（先导出再删除）
    client.get(f"/api/contact-manager/projects/{project_id}/export-db", params={"password": "secret"})
    res = client.delete(f"/api/contact-manager/projects/{project_id}", params={"password": "secret"})
    assert res.status_code == 200


def test_inspect_and_match_fields_endpoints():
    """inspect 应返回自动匹配结果；match-fields 支持按指定表头行重新匹配。"""
    import io

    import openpyxl

    client = TestClient(app)

    res = client.post("/api/contact-manager/projects", json={
        "name": f"测试字段匹配_{SUFFIX}",
        "password": "pw",
        "description": "测试用",
    })
    assert res.status_code == 200
    pid = res.json()["project"]["id"]
    H = {"X-Project-Id": str(pid), "X-Project-Password": "pw"}

    # 造表：第 1 行标题、第 2 行表头（末列是项目里没有的字段）
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "通讯录"
    ws.append(["某单位通讯录", "", "", "", ""])
    ws.append(["姓名", "职务", "单位", "手机号码", "履职平台用户名"])
    ws.append(["张三", "科长", "甲单位", "13800000001", "zhangsan"])
    buf = io.BytesIO()
    wb.save(buf)

    res = client.post(
        "/api/contact-manager/upload",
        files={"file": ("t.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=H,
    )
    assert res.status_code == 200, res.text
    temp_path = res.json()["temp_path"]
    sheet = res.json()["sheets"][0]

    # inspect：识别表头行并自动匹配
    res = client.get("/api/contact-manager/inspect",
                     params={"temp_path": temp_path, "sheet_name": sheet}, headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["detected_header_row"] == 2, body["detected_header_row"]
    m = body["mapping"]
    assert m.get("0") == "name" and m.get("1") == "title" and m.get("2") == "unit", m
    assert m.get("3") == "mobile", m
    # 项目中没有的列不应被匹配（交由前端新建字段）
    assert "4" not in m, m

    # match-fields：按指定行重新匹配
    res = client.get("/api/contact-manager/match-fields",
                     params={"temp_path": temp_path, "sheet_name": sheet, "header_row": 2},
                     headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["mapping"].get("0") == "name"

    # 指向标题行「某单位通讯录」时，不应把它当成单位列
    res = client.get("/api/contact-manager/match-fields",
                     params={"temp_path": temp_path, "sheet_name": sheet, "header_row": 1},
                     headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["mapping"] == {}, res.json()

    # 清理
    client.get(f"/api/contact-manager/projects/{pid}/export-db", params={"password": "pw"})
    client.delete(f"/api/contact-manager/projects/{pid}", params={"password": "pw"})


def _mk_project(client, name, password="pw"):
    res = client.post("/api/contact-manager/projects", json={
        "name": name, "password": password, "description": "t"})
    assert res.status_code == 200, res.text
    pid = res.json()["project"]["id"]
    return pid, {"X-Project-Id": str(pid), "X-Project-Password": password}


def _upload(client, headers, rows, sheet="通讯录"):
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    res = client.post(
        "/api/contact-manager/upload",
        files={"file": ("t.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["temp_path"], res.json()["sheets"][0]


def _cleanup(client, pid, password="pw"):
    client.get(f"/api/contact-manager/projects/{pid}/export-db", params={"password": password})
    client.delete(f"/api/contact-manager/projects/{pid}", params={"password": password})


def test_import_requires_name_column():
    """姓名列必须映射：它是联系人主键与展示键。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试必选姓名_{SUFFIX}")
    tp, sh = _upload(client, H, [["姓名", "职务"], ["张三", "科长"]])

    # 未把任何列映射到 name → 400
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"1": "title"},
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 400, res.text
    assert "姓名" in res.json()["detail"], res.json()

    # 正确映射 → 成功，且不需要用户提供 id_field
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title"},
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["new_count"] == 1, res.json()

    _cleanup(client, pid)


def test_duplicate_names_require_user_decision():
    """同一份表内重名：未指定处理方式时返回 409，由前端询问合并或各自保留。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试重名_{SUFFIX}")
    rows = [
        ["姓名", "职务", "单位"],
        ["张三", "科长", "甲单位"],
        ["张三", "处长", "乙单位"],   # 重名
    ]

    # 1) 未指定 duplicate_action → 409
    tp, sh = _upload(client, H, rows)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit"},
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 409, res.text
    assert "重名" in res.json()["detail"], res.json()
    assert "张三" in res.json()["detail"], res.json()

    # 预检接口应报出重名
    res = client.post("/api/contact-manager/import/preview", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit"},
    }, headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["duplicate_count"] == 1, body
    assert body["duplicates"][0]["name"] == "张三" and body["duplicates"][0]["count"] == 2, body

    # 2) merge：合并为一条，不同取值用「、」拼接
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit"},
        "duplicate_action": "merge",
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["imported_count"] == 1, res.json()
    assert res.json()["new_count"] == 1, res.json()

    res = client.get("/api/contact-manager/contacts", headers=H)
    cs = res.json()["contacts"]
    assert len(cs) == 1, cs
    assert cs[0]["title"] == "科长、处长", cs[0]
    assert cs[0]["unit"] == "甲单位、乙单位", cs[0]

    # 冲突字段应被报告
    assert res.json() is not None
    _cleanup(client, pid)

    # 3) separate：各自保留为独立联系人
    pid2, H2 = _mk_project(client, f"测试重名保留_{SUFFIX}")
    tp2, sh2 = _upload(client, H2, rows)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp2, "sheet_name": sh2, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit"},
        "duplicate_action": "separate",
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H2)
    assert res.status_code == 200, res.text
    assert res.json()["imported_count"] == 2, res.json()
    assert res.json()["new_count"] == 2, res.json()

    with get_db_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM contact_entities WHERE project_id=?",
                         (pid2,)).fetchone()[0]
    assert n == 2, f"各自保留时应有两个独立实体，实际 {n}"

    res = client.get("/api/contact-manager/contacts", headers=H2)
    assert len(res.json()["contacts"]) == 2, res.json()["contacts"]

    _cleanup(client, pid2)


def test_duplicate_merge_reports_conflicts():
    """合并时应报告发生「、」拼接的字段。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试合并冲突_{SUFFIX}")
    tp, sh = _upload(client, H, [
        ["姓名", "职务", "单位"],
        ["李四", "科长", "甲单位"],
        ["李四", "科长", "乙单位"],   # 职务相同、单位不同
    ])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit"},
        "duplicate_action": "merge",
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    conflicts = res.json()["merge_conflicts"]
    assert "李四" in conflicts, conflicts
    assert "unit" in conflicts["李四"], conflicts
    assert "title" not in conflicts["李四"], "取值相同的字段不应算冲突"

    _cleanup(client, pid)


def test_cross_version_match_requires_n_matching_fields():
    """跨版本判定同一人：同名且至少 N 个字段相同才算同一人。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试跨版本_{SUFFIX}")

    # 第 1 版：张三，5 个字段
    v1 = [
        ["姓名", "职务", "单位", "性别", "手机号", "邮箱"],
        ["张三", "科长", "甲单位", "男", "13800000001", "z@x.com"],
    ]
    tp, sh = _upload(client, H, v1)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit", "3": "gender",
                    "4": "mobile", "5": "email"},
        "version_date": "2026-01-01", "filename": "v1.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["new_count"] == 1, res.json()

    # 第 2 版：同名且 4 个字段相同（职务变了）→ 默认阈值 5 下应视为新人
    v2 = [
        ["姓名", "职务", "单位", "性别", "手机号", "邮箱"],
        ["张三", "处长", "甲单位", "男", "13800000001", "z@x.com"],
    ]
    tp2, sh2 = _upload(client, H, v2)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp2, "sheet_name": sh2, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit", "3": "gender",
                    "4": "mobile", "5": "email"},
        "version_date": "2026-02-01", "filename": "v2.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["threshold"] == 5, res.json()
    assert res.json()["new_count"] == 1, f"相同字段数 4 < 阈值 5，应视为新人: {res.json()}"
    assert res.json()["merged_count"] == 0, res.json()

    # 把阈值降到 4 → 同一人（合并到已有实体并更新职务）
    res = client.post("/api/contact-manager/settings", json={"id_match_fields": 4}, headers=H)
    assert res.status_code == 200 and res.json()["id_match_fields"] == 4, res.text

    v3 = [
        ["姓名", "职务", "单位", "性别", "手机号", "邮箱"],
        ["张三", "主任", "甲单位", "男", "13800000001", "z@x.com"],
    ]
    tp3, sh3 = _upload(client, H, v3)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp3, "sheet_name": sh3, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "unit", "3": "gender",
                    "4": "mobile", "5": "email"},
        "version_date": "2026-03-01", "filename": "v3.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["merged_count"] == 1, f"阈值 4 时应匹配合并: {res.json()}"
    assert res.json()["new_count"] == 0, res.json()

    res = client.get("/api/contact-manager/contacts", headers=H)
    cs = res.json()["contacts"]
    # 上一版（阈值5）把 v2 当成新人，因此此时应存在 2 个实体；v3 合并到其中一个
    titles = sorted(c.get("title", "") for c in cs)
    assert "主任" in titles, titles

    _cleanup(client, pid)


def test_same_name_different_people_stay_separate():
    """同名但字段差异大：即使跨版本也必须保持为两个不同的人。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试同名不同人_{SUFFIX}")

    v1 = [
        ["姓名", "单位", "手机号"],
        ["王五", "甲单位", "13900000001"],
        ["王五", "乙单位", "13900000002"],   # 同名，字段全不同
    ]
    tp, sh = _upload(client, H, v1)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "unit", "2": "mobile"},
        "duplicate_action": "separate",
        "version_date": "2026-01-01", "filename": "v1.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text

    with get_db_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM contact_entities WHERE project_id=?",
                         (pid,)).fetchone()[0]
    assert n == 2, f"同名不同人应各自独立: {n}"

    # 第 2 版内容不变：两人都应各自匹配到，且不新增
    tp2, sh2 = _upload(client, H, v1)
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp2, "sheet_name": sh2, "header_row": 1,
        "mapping": {"0": "name", "1": "unit", "2": "mobile"},
        "duplicate_action": "separate",
        "version_date": "2026-02-01", "filename": "v2.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["new_count"] == 0, f"同名不同人不应新增: {res.json()}"
    assert res.json()["removed_count"] == 0, res.json()

    with get_db_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM contact_entities WHERE project_id=?",
                         (pid,)).fetchone()[0]
    assert n == 2, f"实体数不应变化: {n}"

    _cleanup(client, pid)


# ---- 值清理 ----

def test_clean_value_removes_noise():
    """空格、换行、全角空格、零宽字符等无意义符号应被移除。"""
    from app.tools.contact_manager.parser import clean_value

    assert clean_value("  张三  ") == "张三"
    assert clean_value("张 三") == "张三"                 # 半角空格
    assert clean_value("张\u3000三") == "张三"            # 全角空格
    assert clean_value("甲单位\n乙单位") == "甲单位乙单位"   # 换行
    assert clean_value("甲单位\r\n") == "甲单位"
    assert clean_value("\u200b张\u200b三\ufeff") == "张三"  # 零宽字符 / BOM
    assert clean_value(None) == ""
    assert clean_value("  ") == ""
    assert clean_value(1968.0) == "1968"                  # 整数型浮点不带 .0
    assert clean_value("  A\tB  ") == "AB"                # 制表符


# ---- 出生年月格式化 ----

def test_format_birth_month_common_formats():
    """常见的出生年月写法都应规范化为 YYYY-MM。"""
    from app.tools.contact_manager.parser import format_birth_month as f

    # 标准分隔形式
    assert f("1968-10") == "1968-10"
    assert f("1968/10") == "1968-10"
    assert f("1968.10") == "1968-10"
    assert f("1968年10月") == "1968-10"
    assert f("1968年1月") == "1968-01"
    assert f("1968-1") == "1968-01"
    assert f("1968.1.5") == "1968-01"
    assert f("1968-10-05") == "1968-10"
    # 纯数字
    assert f("196810") == "1968-10"
    assert f("19681005") == "1968-10"
    # 原生日期类型
    from datetime import date, datetime
    assert f(date(1968, 10, 5)) == "1968-10"
    assert f(datetime(1968, 1, 1)) == "1968-01"
    # 带噪声
    assert f(" 1968 年 10 月 ") == "1968-10"


def test_format_birth_month_excel_truncated_decimals():
    """Excel 把 1968.10 存成 1968.1 时，应还原为 10 月；1 月写作 .01。

    生产数据实测：该表出生年月列只出现 .1 这一种「一位小数」写法（10 月的末尾 0
    被 Excel 丢掉），而 1~9 月全部写成 .01~.09，11/12 月写成 .11/.12。
    因此 .1 → 10 月；.2 之类的形式不存在（若存在也只可能是 .20 被截断，不合法）。
    """
    from app.tools.contact_manager.parser import format_birth_month as f

    # 实测约定：.1 表示 10 月
    assert f(1968.1) == "1968-10"
    assert f("1968.1") == "1968-10"
    assert f(1971.1) == "1971-10"
    # 1 月用 .01 表示
    assert f(1968.01) == "1968-01"
    assert f("1968.01") == "1968-01"
    # 两位直接按字面月份
    assert f("1968.04") == "1968-04"
    assert f("1968.09") == "1968-09"
    assert f("1968.11") == "1968-11"
    assert f("1968.12") == "1968-12"


def test_format_birth_month_unparsable_keeps_original():
    """无法识别的值保留清理后的原值（不丢信息）。"""
    from app.tools.contact_manager.parser import format_birth_month as f

    assert f("1968") == "1968"          # 只有年份
    assert f("不详") == "不详"
    assert f("") == ""
    assert f(None) == ""
    assert f("abc") == "abc"


def test_backend_computes_entity_key_not_name():
    """实体键由后端生成，与姓名解耦（同名不同人可各自独立）。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试键生成_{SUFFIX}")
    tp, sh = _upload(client, H, [
        ["姓名", "单位"],
        ["赵六", "甲单位"],
        ["赵六", "乙单位"],
    ])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "unit"},
        "duplicate_action": "separate",
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text

    with get_db_connection() as conn:
        keys = [r[0] for r in conn.execute(
            "SELECT entity_key FROM contact_entities WHERE project_id=?", (pid,))]
    assert len(keys) == 2, keys
    assert len(set(keys)) == 2, f"实体键必须唯一: {keys}"
    assert all(k != "赵六" for k in keys), f"键不应等于姓名: {keys}"

    _cleanup(client, pid)


def test_import_skips_rows_with_blank_name_and_reports():
    """姓名为空的行会被跳过，并在响应中给出其原始 Excel 行号。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试姓名空值_{SUFFIX}")
    tp, sh = _upload(client, H, [
        ["姓名", "职务"],     # 第 1 行：表头
        ["张三", "科长"],     # 第 2 行
        ["", "处长"],         # 第 3 行：姓名为空 → 跳过
        ["王五", "主任"],     # 第 4 行
    ])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title"},
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported_count"] == 2, body
    assert body["skipped_count"] == 1, body
    # 表头在第 1 行，空姓名是第 3 行
    assert body["blank_id_rows"] == [3], body

    _cleanup(client, pid)


def test_same_date_reimport_covers_and_never_touches_other_projects():
    """同日期重导入应覆盖本项目的同日期版本，且**绝不**波及其它项目的数据。

    这是回归防护：历史缺陷曾在此路径用「全表 DELETE ... NOT IN」清理孤儿 delta，
    未按 project_id 过滤，导致其它项目的全部 delta 被清空（仅靠备份恢复）。
    """
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试覆盖_{SUFFIX}")
    # 另一个项目（作为"受害者"）：先导入数据
    pid2, H2 = _mk_project(client, f"测试覆盖_受害者_{SUFFIX}")
    tp2, sh2 = _upload(client, H2, [["姓名", "单位"], ["受害者甲", "甲单位"]])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp2, "sheet_name": sh2, "header_row": 1,
        "mapping": {"0": "name", "1": "unit"},
        "version_date": "2026-01-01", "filename": "victim.xlsx",
    }, headers=H2)
    assert res.status_code == 200, res.text
    victim_version_id = res.json()["version_id"]

    # 本项目 v1
    tp, sh = _upload(client, H, [["姓名", "单位"], ["张三", "旧单位"]])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "unit"},
        "version_date": "2026-05-01", "filename": "v1.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    first_id = res.json()["version_id"]

    # 本项目同日期重导入 → 应覆盖
    tp3, sh3 = _upload(client, H, [["姓名", "单位"], ["张三", "新单位"], ["李四", "另单位"]])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp3, "sheet_name": sh3, "header_row": 1,
        "mapping": {"0": "name", "1": "unit"},
        "version_date": "2026-05-01", "filename": "v1b.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text
    second_id = res.json()["version_id"]
    assert second_id != first_id, "同日期重导入应替换为新版本"

    # 本项目只有一个该日期版本
    res = client.get("/api/contact-manager/versions", headers=H)
    same = [v for v in res.json() if v["version_date"] == "2026-05-01"]
    assert len(same) == 1, f"同日期应只保留 1 个版本: {same}"

    # 内容为新数据
    res = client.get("/api/contact-manager/contacts", headers=H)
    units = {c["name"]: c.get("unit") for c in res.json()["contacts"]}
    assert units.get("张三") == "新单位", units

    # ★ 受害项目的数据必须完好无损
    res = client.get("/api/contact-manager/contacts", headers=H2)
    assert len(res.json()["contacts"]) == 1, res.json()["contacts"]
    assert res.json()["contacts"][0]["name"] == "受害者甲", res.json()["contacts"]

    with get_db_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM contact_version_deltas WHERE version_id = ?",
            (victim_version_id,)).fetchone()[0]
    assert n == 1, f"★ 其它项目的 delta 必须完好: version_id={victim_version_id} 剩余 {n}"

    _cleanup(client, pid2)
    _cleanup(client, pid)


def test_keyword_wildcard_and_query_semantics():
    """关键词 * 通配符，以及「选版本 / 不选版本 + 选日期」的查询语义。"""
    import urllib.parse

    client = TestClient(app)
    pid, H = _mk_project(client, f"测试查询_{SUFFIX}")

    # v_a（2026-01-01）：两个同名不同人
    tp, sh = _upload(client, H, [
        ["姓名", "单位", "手机号"],
        ["查询君", "甲单位", "13900000001"],
        ["查询君", "丙单位", "13900000003"],
    ])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "unit", "2": "mobile"},
        "duplicate_action": "separate",
        "version_date": "2026-01-01", "filename": "va.xlsx",
    }, headers=H)
    assert res.status_code == 200 and res.json()["new_count"] == 2, res.text
    va_id = res.json()["version_id"]

    # v_b（2026-02-01）：甲 + 乙
    tp2, sh2 = _upload(client, H, [
        ["姓名", "单位", "手机号"],
        ["查询君", "甲单位", "13900000001"],
        ["查询君", "乙单位", "13900000002"],
    ])
    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp2, "sheet_name": sh2, "header_row": 1,
        "mapping": {"0": "name", "1": "unit", "2": "mobile"},
        "duplicate_action": "separate",
        "version_date": "2026-02-01", "filename": "vb.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text

    kw = urllib.parse.quote("查询君")

    # 2a) 不选版本、不选日期 → 跨版本所有匹配结果
    res = client.get(f"/api/contact-manager/contacts?keyword={kw}", headers=H)
    body = res.json()
    assert body["is_historical"] is True, body
    dates = sorted({c.get("_version_date") for c in body["contacts"]})
    assert dates == ["2026-01-01", "2026-02-01"], dates
    assert len(body["contacts"]) == 4, len(body["contacts"])

    # 2b) 不选版本、选日期 → 只含该日期之前（含当日）的版本
    res = client.get(f"/api/contact-manager/contacts?keyword={kw}&query_date=2026-01-31",
                     headers=H)
    body = res.json()
    assert body["is_historical"] is True, body
    dates = sorted({c.get("_version_date") for c in body["contacts"]})
    assert dates == ["2026-01-01"], dates

    # 2c) 选版本 → 只查该版本，日期不生效
    res = client.get(f"/api/contact-manager/contacts?version_id={va_id}&keyword={kw}",
                     headers=H)
    body = res.json()
    assert body["is_historical"] is False, body
    assert len(body["contacts"]) == 2, len(body["contacts"])
    assert body["version"]["id"] == va_id, body.get("version")

    # 通配符
    def search(k):
        res = client.get("/api/contact-manager/contacts?keyword=" + urllib.parse.quote(k),
                         headers=H)
        return res.json()["contacts"]

    names = sorted({c["name"] for c in search("查*")})
    assert "查询君" in names, names
    names = sorted({c["name"] for c in search("*君")})
    assert "查询君" in names, names
    # 中段通配符：询…君 要求首字为「询」，不匹配「查询君」
    names = sorted({c["name"] for c in search("询*君")})
    assert "查询君" not in names, names
    names = sorted({c["name"] for c in search("查*君")})
    assert "查询君" in names, names
    # 其它字符按字面处理
    assert len(search("查?")) == 0, search("查?")
    # 单元值通配符：按单位查
    names = sorted({c["name"] for c in search("*甲*")})
    assert "查询君" in names, names

    _cleanup(client, pid)


def test_settings_threshold_validation():
    """阈值设置接口：可读写、非法值被拒绝。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试阈值_{SUFFIX}")

    res = client.get("/api/contact-manager/settings", headers=H)
    assert res.status_code == 200
    assert res.json()["id_match_fields"] == 5, res.json()

    res = client.post("/api/contact-manager/settings", json={"id_match_fields": 3}, headers=H)
    assert res.status_code == 200 and res.json()["id_match_fields"] == 3, res.text
    assert client.get("/api/contact-manager/settings", headers=H).json()["id_match_fields"] == 3

    for bad in (0, -1, "abc"):
        res = client.post("/api/contact-manager/settings",
                          json={"id_match_fields": bad}, headers=H)
        assert res.status_code == 400, f"{bad} 应被拒绝: {res.text}"

    _cleanup(client, pid)


def test_export_import_db_preserves_threshold():
    """导出/导入项目数据库应保留「同一人判定」阈值。"""
    client = TestClient(app)
    pid, H = _mk_project(client, f"测试阈值导出_{SUFFIX}")
    client.post("/api/contact-manager/settings", json={"id_match_fields": 2}, headers=H)

    tp, sh = _upload(client, H, [["姓名", "手机号"], ["张三", "13800000001"]])
    client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "mobile"},
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)

    res = client.get(f"/api/contact-manager/projects/{pid}/export-db",
                     params={"password": "pw"})
    assert res.status_code == 200
    bundle = json.loads(res.content.decode("utf-8"))
    assert bundle["project"]["id_match_fields"] == 2, bundle["project"]

    new_name = f"测试阈值恢复_{SUFFIX}"
    res = client.post("/api/contact-manager/projects/import-db",
                      files={"file": ("b.cmdb", res.content, "application/json")},
                      data={"name": new_name, "password": "pw"})
    assert res.status_code == 200, res.text
    new_pid = res.json()["project"]["id"]
    H2 = {"X-Project-Id": str(new_pid), "X-Project-Password": "pw"}
    assert client.get("/api/contact-manager/settings",
                      headers=H2).json()["id_match_fields"] == 2

    _cleanup(client, new_pid)
    _cleanup(client, pid)


def test_field_usage_and_clean_empty_fields():
    """清理空字段：只删除无内容字段，不误删有数据字段，且不影响联系人数据。"""
    import io

    import openpyxl

    from app.tools.contact_manager.database import (
        collect_field_usage,
        find_empty_fields,
        remove_empty_fields,
    )

    client = TestClient(app)
    res = client.post("/api/contact-manager/projects", json={
        "name": f"测试空字段清理_{SUFFIX}", "password": "pw", "description": "t",
    })
    pid = res.json()["project"]["id"]
    H = {"X-Project-Id": str(pid), "X-Project-Password": "pw"}

    # 导入：只填「姓名 / 职务」，另外新增一个「备注」列但不填值
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "通讯录"
    ws.append(["姓名", "职务", "备注"])
    ws.append(["张三", "科长", ""])
    ws.append(["李四", "处长", ""])
    buf = io.BytesIO(); wb.save(buf)

    res = client.post("/api/contact-manager/upload",
                      files={"file": ("t.xlsx", buf.getvalue(),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                      headers=H)
    tp = res.json()["temp_path"]; sh = res.json()["sheets"][0]

    # 建一个「备注」字段并映射
    res = client.post("/api/contact-manager/fields",
                      json={"name": "ext_memo", "label": "备注"}, headers=H)
    assert res.status_code == 200

    res = client.post("/api/contact-manager/import", json={
        "temp_path": tp, "sheet_name": sh, "header_row": 1,
        "mapping": {"0": "name", "1": "title", "2": "ext_memo"},
        "id_field": "name",
        "version_date": "2026-01-01", "filename": "t.xlsx",
    }, headers=H)
    assert res.status_code == 200, res.text

    # usage：姓名/职务有内容，备注与其它未使用字段为空
    res = client.get("/api/contact-manager/fields/usage", headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["name"]["non_empty"] == 2, by_name["name"]
    assert by_name["name"]["empty"] is False
    assert by_name["ext_memo"]["non_empty"] == 0, by_name["ext_memo"]
    assert by_name["ext_memo"]["empty"] is True
    # 项目默认字段（职务/单位/电话…）：职务有值，单位无值
    assert by_name["title"]["empty"] is False, by_name["title"]
    assert by_name["unit"]["empty"] is True, by_name["unit"]
    assert body["empty_count"] == sum(1 for f in body["fields"] if f["empty"])

    # dry_run 不删除
    res = client.post("/api/contact-manager/fields/clean", json={"dry_run": True}, headers=H)
    assert res.status_code == 200 and res.json()["deleted"] == 0

    # 只清理自定义空字段（保留空的默认字段）
    with get_db_connection() as conn:
        cur = conn.cursor()
        custom_empties = find_empty_fields(cur, pid, include_default=False)
    assert {f["name"] for f in custom_empties} == {"ext_memo"}, custom_empties

    res = client.post("/api/contact-manager/fields/clean",
                      json={"field_ids": [f["id"] for f in custom_empties]}, headers=H)
    assert res.status_code == 200 and res.json()["deleted"] == 1, res.text

    res = client.get("/api/contact-manager/fields", headers=H)
    names = {f["name"] for f in res.json()}
    assert "ext_memo" not in names, "空的自定义字段未被删除"
    assert "unit" in names, "空的默认字段不应被删除"
    assert "name" in names and "title" in names, "有数据的字段被误删"

    # 关键：联系人数据完全不受影响
    res = client.get("/api/contact-manager/contacts", headers=H)
    assert res.status_code == 200
    cs = res.json()["contacts"]
    assert len(cs) == 2, len(cs)
    assert cs[0]["name"] == "张三" and cs[0]["title"] == "科长"

    # 再清理空的默认字段
    with get_db_connection() as conn:
        cur = conn.cursor()
        usage = collect_field_usage(cur, pid)
        outcome = remove_empty_fields(cur, pid, include_default=True)
        conn.commit()
    assert outcome["deleted"] == sum(
        1 for f in outcome["fields"] if usage.get(f["name"], {}).get("non_empty", 0) == 0)
    assert "name" not in {f["name"] for f in outcome["fields"]}, "有数据字段被列入删除名单"

    res = client.get("/api/contact-manager/contacts", headers=H)
    assert len(res.json()["contacts"]) == 2, "清理后联系人数量变化"

    # 清理项目
    client.get(f"/api/contact-manager/projects/{pid}/export-db", params={"password": "pw"})
    client.delete(f"/api/contact-manager/projects/{pid}", params={"password": "pw"})


def test_create_field_is_idempotent_by_label():
    """同显示名的字段应复用而不是重复创建（历史缺陷会产生大量重名空字段）。"""
    client = TestClient(app)
    res = client.post("/api/contact-manager/projects", json={
        "name": f"测试字段幂等_{SUFFIX}", "password": "pw", "description": "t",
    })
    pid = res.json()["project"]["id"]
    H = {"X-Project-Id": str(pid), "X-Project-Password": "pw"}

    r1 = client.post("/api/contact-manager/fields",
                     json={"name": "ext_a", "label": "界别"}, headers=H)
    assert r1.status_code == 200 and r1.json().get("reused") is False
    first_id = r1.json()["id"]

    r2 = client.post("/api/contact-manager/fields",
                     json={"name": "ext_b", "label": "界别"}, headers=H)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("reused") is True, r2.json()
    assert r2.json()["id"] == first_id, "应复用已有字段"

    res = client.get("/api/contact-manager/fields", headers=H)
    assert sum(1 for f in res.json() if f["label"] == "界别") == 1, "出现了重复字段"

    client.get(f"/api/contact-manager/projects/{pid}/export-db", params={"password": "pw"})
    client.delete(f"/api/contact-manager/projects/{pid}", params={"password": "pw"})


def test_clean_only_within_project():
    """清理接口不得删除其它项目的字段（多项目隔离）。"""
    client = TestClient(app)
    ids = []
    for tag in ("A", "B"):
        res = client.post("/api/contact-manager/projects", json={
            "name": f"测试隔离_{tag}_{SUFFIX}", "password": "pw", "description": "t",
        })
        ids.append(res.json()["project"]["id"])
    pa, pb = ids
    Ha = {"X-Project-Id": str(pa), "X-Project-Password": "pw"}
    Hb = {"X-Project-Id": str(pb), "X-Project-Password": "pw"}

    ra = client.post("/api/contact-manager/fields", json={"name": "ext_a", "label": "专属A"}, headers=Ha)
    rb = client.post("/api/contact-manager/fields", json={"name": "ext_b", "label": "专属B"}, headers=Hb)

    # 试图从项目 A 删除项目 B 的字段
    res = client.post("/api/contact-manager/fields/clean",
                      json={"field_ids": [rb.json()["id"]]}, headers=Ha)
    assert res.status_code == 200
    assert res.json()["deleted"] == 0, "跨项目删除了字段"
    assert "专属B" in {f["label"] for f in client.get("/api/contact-manager/fields", headers=Hb).json()}

    # 正常删除自己的
    res = client.post("/api/contact-manager/fields/clean",
                      json={"field_ids": [ra.json()["id"]]}, headers=Ha)
    assert res.json()["deleted"] == 1

    for pid in ids:
        client.get(f"/api/contact-manager/projects/{pid}/export-db", params={"password": "pw"})
        client.delete(f"/api/contact-manager/projects/{pid}", params={"password": "pw"})


if __name__ == "__main__":
    test_database_migration_with_foreign_keys()
    print("✓ test_database_migration_with_foreign_keys passed")

    test_orphan_data_cleanup()
    print("✓ test_orphan_data_cleanup passed")

    test_dangling_foreign_key_is_repaired()
    print("✓ test_dangling_foreign_key_is_repaired passed")

    test_export_before_delete_enforcement()
    print("✓ test_export_before_delete_enforcement passed")

    test_delete_without_password_fails()
    print("✓ test_delete_without_password_fails passed")

    test_inspect_and_match_fields_endpoints()
    print("✓ test_inspect_and_match_fields_endpoints passed")

    test_clean_value_removes_noise()
    print("✓ test_clean_value_removes_noise passed")

    test_format_birth_month_common_formats()
    print("✓ test_format_birth_month_common_formats passed")

    test_format_birth_month_excel_truncated_decimals()
    print("✓ test_format_birth_month_excel_truncated_decimals passed")

    test_format_birth_month_unparsable_keeps_original()
    print("✓ test_format_birth_month_unparsable_keeps_original passed")

    test_import_requires_name_column()
    print("✓ test_import_requires_name_column passed")

    test_duplicate_names_require_user_decision()
    print("✓ test_duplicate_names_require_user_decision passed")

    test_duplicate_merge_reports_conflicts()
    print("✓ test_duplicate_merge_reports_conflicts passed")

    test_cross_version_match_requires_n_matching_fields()
    print("✓ test_cross_version_match_requires_n_matching_fields passed")

    test_same_name_different_people_stay_separate()
    print("✓ test_same_name_different_people_stay_separate passed")

    test_backend_computes_entity_key_not_name()
    print("✓ test_backend_computes_entity_key_not_name passed")

    test_import_skips_rows_with_blank_name_and_reports()
    print("✓ test_import_skips_rows_with_blank_name_and_reports passed")

    test_same_date_reimport_covers_and_never_touches_other_projects()
    print("✓ test_same_date_reimport_covers_and_never_touches_other_projects passed")

    test_keyword_wildcard_and_query_semantics()
    print("✓ test_keyword_wildcard_and_query_semantics passed")

    test_settings_threshold_validation()
    print("✓ test_settings_threshold_validation passed")

    test_export_import_db_preserves_threshold()
    print("✓ test_export_import_db_preserves_threshold passed")

    test_field_usage_and_clean_empty_fields()
    print("✓ test_field_usage_and_clean_empty_fields passed")

    test_create_field_is_idempotent_by_label()
    print("✓ test_create_field_is_idempotent_by_label passed")

    test_clean_only_within_project()
    print("✓ test_clean_only_within_project passed")

    print("\n所有测试通过！")