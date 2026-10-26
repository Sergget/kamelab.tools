import os
import json
import re
import shutil
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Header, Depends
from fastapi.responses import FileResponse, Response
import openpyxl

from .database import (
    get_db,
    init_db,
    hash_password,
    verify_password,
    init_project_default_fields,
    collect_field_usage,
    find_empty_fields,
    delete_fields,
    remove_empty_fields,
    resolve_id_field,
    get_default_id_field,
    get_id_match_fields,
)
from .parser import (
    extract_date_from_filename,
    get_excel_sheets,
    read_excel_preview,
    detect_header_and_map,
    map_fields_for_header_row,
    parse_sheet_data,
    clean_value,
    find_duplicate_names,
    merge_records,
)
import urllib.parse
from ... import config

router = APIRouter(prefix="/api/contact-manager", tags=["contact-manager"])

# 初始化数据库（幂等迁移，见 database.init_db）
init_db()


# ================= 鉴权与项目辅助函数 =================

def _verify_project(cursor, project_id: int, password: Optional[str]) -> dict:
    """验证项目存在且密码正确。

    密码是项目的唯一访问控制，缺失与错误同样拒绝——以前这里是
    ``if password is not None``，不传 X-Project-Password 就能直接放行。
    """
    cursor.execute("SELECT id, name, password_hash, description, created_at, exported_at FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在或已被删除")
    proj = dict(row)
    if not password or not verify_password(password, proj["password_hash"]):
        raise HTTPException(status_code=401, detail="项目密码错误，访问受限")
    return proj


def _safe_name_part(value: str, fallback: str = "project") -> str:
    """把用户可控文本压成文件名片段：去掉分隔符与 Windows 非法字符。"""
    cleaned = re.sub(r"[^\w\-]+", "_", value or "").strip("_")
    return cleaned[:60] or fallback

def get_project_auth(
    x_project_id: Optional[int] = Header(None, alias="X-Project-Id"),
    x_project_password: Optional[str] = Header(None, alias="X-Project-Password")
) -> dict:
    """FastAPI 依赖项：从 Header 中提取并验证项目凭据"""
    if not x_project_id:
        raise HTTPException(status_code=400, detail="缺少 X-Project-Id 请求头，请先选择并进入项目")
    with get_db() as conn:
        cursor = conn.cursor()
        return _verify_project(cursor, x_project_id, x_project_password)

def _field_label(cursor, project_id: int, name: str) -> str:
    """取字段的显示名，取不到则回退为字段名本身。"""
    cursor.execute(
        "SELECT label FROM fields WHERE project_id = ? AND name = ?", (project_id, name))
    row = cursor.fetchone()
    return row["label"] if row else name


def _get_entity_key(data: dict, id_field: str = "name") -> str:
    """联系人数据的显示用键：始终为姓名（清理后）。"""
    return clean_value(data.get("name", ""))


# 由 _get_all_entities_at_version 注入的元数据键（非业务字段），比较时必须排除
_INTERNAL_KEYS = ("id", "_entity_id", "_entity_key", "_version_date",
                  "_filename", "_version_id", "_entity_key")


def _similarity_fields(data: dict, name_field: str = "name"):
    """取出用于「同一人」相似度比较的字段（排除姓名与内部注入的元数据键）。"""
    return {
        k: clean_value(v)
        for k, v in (data or {}).items()
        if not k.startswith("_") and k not in _INTERNAL_KEYS and k != name_field
        and clean_value(v)
    }


def _count_matching_fields(a: dict, b: dict) -> int:
    """统计两份记录中「取值相同的非空字段」个数。"""
    fa, fb = _similarity_fields(a), _similarity_fields(b)
    return sum(1 for k, v in fa.items() if fb.get(k) == v)


def _effective_threshold(record: dict, threshold: int, name_field: str = "name") -> int:
    """把阈值限制在「本记录可比字段数」以内。

    threshold 是用户期望的严格度；但若某条记录除姓名外只有 F 个非空字段，
    要求多于 F 个字段相同是不可能的 —— 那会导致每次导入都被判为「新人」，
    旧记录整批被标记删除。此时退化为「这 F 个字段必须全部相同」。

    F == 0（只有姓名）时返回 0，即以姓名为唯一依据。
    """
    available = len(_similarity_fields(record, name_field))
    return min(threshold, available)


def _match_entity(cursor, project_id: int, record: dict, index: dict, threshold: int):
    """在上一版本中为当前记录寻找「同一个人」。

    规则：同名的人中，只要有某个候选与本记录「除姓名外至少 threshold 个字段取值相同」
    （threshold 会按本记录可比字段数收敛，见 _effective_threshold），即认为是同一人，
    取相同字段数最多者。找不到则视为新人。

    返回 (entity_id, matched_record, matched_fields)；未命中时 entity_id 为 None。
    """
    name = clean_value(record.get("name", ""))
    if not name:
        return None, None, 0

    eff = _effective_threshold(record, threshold)
    candidates = index.get(name, [])
    best = None
    best_fields = -1
    for cand in candidates:
        n = _count_matching_fields(record, cand)
        if n >= eff and n > best_fields:
            best, best_fields = cand, n

    if best is None:
        return None, None, 0
    return best.get("_entity_id"), best, best_fields


def _next_entity_key(cursor, project_id: int) -> str:
    """生成下一个可用的实体键（项目内唯一）。"""
    cursor.execute(
        "SELECT COUNT(*) FROM contact_entities WHERE project_id = ?", (project_id,))
    return f"e{cursor.fetchone()[0] + 1}"


def _create_entity(cursor, project_id: int, entity_key: str = None) -> int:
    """新建实体并返回 id（键由后端生成，保证唯一）。"""
    key = entity_key or _next_entity_key(cursor, project_id)
    # 极端情况下（并发/删除后重算）可能撞键，追加后缀确保唯一
    while True:
        cursor.execute(
            "SELECT 1 FROM contact_entities WHERE project_id = ? AND entity_key = ?",
            (project_id, key))
        if not cursor.fetchone():
            break
        key = f"{key}_{os.urandom(2).hex()}"
    cursor.execute(
        "INSERT INTO contact_entities (project_id, entity_key) VALUES (?, ?)",
        (project_id, key))
    return cursor.lastrowid


# ---- 跨版本同一人判定 ----

def _build_previous_index(cursor, project_id: int, prev_version_id: int):
    """构建上一版本实体索引：姓名 -> [实体状态, ...]"""
    index = {}
    if not prev_version_id:
        return index
    for entity in _get_all_entities_at_version(cursor, project_id, prev_version_id):
        name = clean_value(entity.get("name", ""))
        if not name:
            continue
        index.setdefault(name, []).append(entity)
    return index


def _upsert_delta(cursor, version_id: int, entity_id: int, data: dict, is_deleted: int = 0):
    cursor.execute("""
        INSERT OR REPLACE INTO contact_version_deltas (version_id, entity_id, data, is_deleted)
        VALUES (?, ?, ?, ?)
    """, (version_id, entity_id,
          json.dumps(data, ensure_ascii=False) if not is_deleted else "{}",
          is_deleted))

def _get_latest_version_id(cursor, project_id: int) -> Optional[int]:
    """获取项目下最新版本 ID"""
    cursor.execute("""
        SELECT id FROM contact_versions
        WHERE project_id = ?
        ORDER BY version_date DESC, id DESC LIMIT 1
    """, (project_id,))
    row = cursor.fetchone()
    return row["id"] if row else None

def _get_entity_state_at_version(cursor, entity_id: int, version_id: int) -> Optional[dict]:
    """
    获取某个实体在指定版本下的完整状态（向前回溯继承）。
    """
    cursor.execute("""
        SELECT cvd.data, cvd.is_deleted, cvd.version_id
        FROM contact_version_deltas cvd
        JOIN contact_versions cv ON cvd.version_id = cv.id
        WHERE cvd.entity_id = ? AND cv.version_date <= (SELECT version_date FROM contact_versions WHERE id = ?)
        ORDER BY cv.version_date DESC, cv.id DESC LIMIT 1
    """, (entity_id, version_id))
    row = cursor.fetchone()
    if row and not row["is_deleted"]:
        return json.loads(row["data"])
    return None

def _get_all_entities_at_version(cursor, project_id: int, version_id: int) -> List[dict]:
    """
    获取项目某版本下所有实体的完整状态（合并增量数据）。
    """
    cursor.execute("""
        WITH latest_deltas AS (
            SELECT cvd.entity_id, cvd.data, cvd.is_deleted,
                   ROW_NUMBER() OVER (PARTITION BY cvd.entity_id ORDER BY cv.version_date DESC, cv.id DESC) as rn
            FROM contact_version_deltas cvd
            JOIN contact_versions cv ON cvd.version_id = cv.id
            WHERE cv.project_id = ? AND cv.version_date <= (SELECT version_date FROM contact_versions WHERE id = ?)
        )
        SELECT ce.id as entity_id, ce.entity_key, ld.data, ld.is_deleted
        FROM contact_entities ce
        JOIN latest_deltas ld ON ce.id = ld.entity_id
        WHERE ce.project_id = ? AND ld.rn = 1 AND ld.is_deleted = 0
    """, (project_id, version_id, project_id))

    results = []
    for row in cursor.fetchall():
        data = json.loads(row["data"])
        data["_entity_id"] = row["entity_id"]
        data["_entity_key"] = row["entity_key"]
        data["id"] = row["entity_id"]
        results.append(data)
    return results

def _create_version_from_entities(cursor, project_id: int, filename: str, sheet_name: str,
                                  version_date: str, entities: List[dict]) -> int:
    """基于完整实体列表在项目中创建新版本，只记录有变动的实体。

    entities 中的每项可带 _entity_id（在线编辑时由前端回传），据此精确定位实体；
    没有 _entity_id 的按姓名 + 相似度匹配（等价于一次正常导入）。
    """
    cursor.execute(
        "INSERT INTO contact_versions (project_id, filename, sheet_name, version_date) VALUES (?, ?, ?, ?)",
        (project_id, filename, sheet_name, version_date)
    )
    new_version_id = cursor.lastrowid

    # 获取该项目前一个版本 ID（用于对比变动）
    cursor.execute("""
        SELECT id FROM contact_versions
        WHERE project_id = ? AND version_date < ?
        ORDER BY version_date DESC, id DESC LIMIT 1
    """, (project_id, version_date))
    prev_version = cursor.fetchone()
    prev_version_id = prev_version["id"] if prev_version else None

    threshold = get_id_match_fields(cursor, project_id)
    index = _build_previous_index(cursor, project_id, prev_version_id)
    seen_entity_ids = set()

    for entity_data in entities:
        if not clean_value(entity_data.get("name", "")):
            continue

        store_data = {k: v for k, v in entity_data.items() if not k.startswith("_")}
        # 实体 id：优先 _entity_id，其次 data 里的 id（前端在线编辑时回传）
        entity_id = entity_data.get("_entity_id") or store_data.get("id")
        try:
            entity_id = int(entity_id) if entity_id is not None and str(entity_id).isdigit() else None
        except (TypeError, ValueError):
            entity_id = None

        # 前端已指定实体（在线编辑）→ 直接用；否则按姓名 + 相似度匹配
        if entity_id:
            cursor.execute(
                "SELECT id FROM contact_entities WHERE project_id = ? AND id = ?",
                (project_id, entity_id))
            if not cursor.fetchone():
                entity_id = None
        if not entity_id:
            entity_id, _cand, _n = _match_entity(
                cursor, project_id, store_data, index, threshold)
        if not entity_id:
            entity_id = _create_entity(cursor, project_id)

        seen_entity_ids.add(entity_id)

        is_changed = True
        if prev_version_id:
            prev_state = _get_entity_state_at_version(cursor, entity_id, prev_version_id)
            if prev_state and prev_state == store_data:
                is_changed = False

        if is_changed:
            _upsert_delta(cursor, new_version_id, entity_id, store_data)

    # 上一版本有、本版本没有 → 逻辑删除
    if prev_version_id:
        for pe in _get_all_entities_at_version(cursor, project_id, prev_version_id):
            if pe["_entity_id"] not in seen_entity_ids:
                _upsert_delta(cursor, new_version_id, pe["_entity_id"], {}, is_deleted=1)

    return new_version_id


# ================= 1. 项目管理 API =================

@router.get("/projects")
async def list_projects():
    """获取所有项目列表（不返回密码哈希，包含版本数和最新版本联系人数量）

    联系人数量统计的是项目**最新版本**中未被标记删除的联系人数（即
    contact_version_deltas.is_deleted = 0 的记录数），而非跨所有版本累加的
    实体总数。因为实体（contact_entities）是跨版本复用的同一人标识，累加会
    导致版本越多数字越大，与实际展示意图不符。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.name, p.description, p.created_at,
                   (SELECT COUNT(*) FROM contact_versions WHERE project_id = p.id) as version_count,
                   (SELECT COUNT(*) FROM contact_version_deltas cvd
                    WHERE cvd.version_id = (
                        SELECT cv2.id FROM contact_versions cv2
                        WHERE cv2.project_id = p.id
                        ORDER BY cv2.version_date DESC, cv2.id DESC LIMIT 1
                    ) AND cvd.is_deleted = 0) as entity_count
            FROM projects p
            ORDER BY p.id DESC
        """)
        projects = [dict(row) for row in cursor.fetchall()]
    return projects

@router.post("/projects")
async def create_project(data: dict):
    """创建新项目并设置密码"""
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    description = data.get("description", "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="必须为项目设定访问密码")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM projects WHERE name = ?", (name,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="项目名称已存在")

        pwd_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO projects (name, password_hash, description) VALUES (?, ?, ?)",
            (name, pwd_hash, description)
        )
        project_id = cursor.lastrowid
        # 初始化该项目的默认基础字段
        init_project_default_fields(cursor, project_id)

    return {
        "success": True,
        "project": {
            "id": project_id,
            "name": name,
            "description": description
        }
    }

@router.post("/projects/auth")
async def verify_project_password(data: dict):
    """验证项目密码"""
    project_id = data.get("project_id")
    password = data.get("password", "").strip()

    if not project_id or not password:
        raise HTTPException(status_code=400, detail="缺少项目ID或密码")

    with get_db() as conn:
        cursor = conn.cursor()
        proj = _verify_project(cursor, int(project_id), password)

    return {
        "success": True,
        "project": {
            "id": proj["id"],
            "name": proj["name"],
            "description": proj["description"],
            "created_at": proj["created_at"]
        }
    }

@router.get("/projects/{project_id}/export-db")
async def export_project_database(project_id: int, password: str = Query(...)):
    """
    导出项目的完整数据库（包含元数据、字段定义、各版本归档及联系人数据）。
    导出的文件用于本地备份或后续重新导入。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        proj = _verify_project(cursor, project_id, password)
        cursor.execute("UPDATE projects SET exported_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))

        # 1. 字段
        cursor.execute("SELECT name, label, is_default FROM fields WHERE project_id = ?", (project_id,))
        fields = [dict(r) for r in cursor.fetchall()]

        # 2. 版本
        cursor.execute("SELECT id, filename, sheet_name, version_date, created_at FROM contact_versions WHERE project_id = ? ORDER BY id ASC", (project_id,))
        versions = [dict(r) for r in cursor.fetchall()]

        # 3. 实体
        cursor.execute("SELECT id, entity_key, created_at FROM contact_entities WHERE project_id = ? ORDER BY id ASC", (project_id,))
        entities = [dict(r) for r in cursor.fetchall()]

        # 4. Deltas
        cursor.execute("""
            SELECT cvd.version_id, cvd.entity_id, cvd.data, cvd.is_deleted
            FROM contact_version_deltas cvd
            JOIN contact_versions cv ON cvd.version_id = cv.id
            WHERE cv.project_id = ?
        """, (project_id,))
        deltas = [dict(r) for r in cursor.fetchall()]

        # 5. 跨版本同一人判定阈值（供恢复后保持一致）
        export_threshold = get_id_match_fields(cursor, project_id)

    export_bundle = {
        "format": "kame_lab_contact_manager_db",
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "project": {
            "name": proj["name"],
            "description": proj["description"],
            "id_match_fields": export_threshold,
        },
        "fields": fields,
        "versions": versions,
        "entities": entities,
        "deltas": deltas
    }

    content = json.dumps(export_bundle, ensure_ascii=False, indent=2).encode('utf-8')
    raw_filename = f"Project_{proj['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.cmdb"
    encoded_filename = urllib.parse.quote(raw_filename)

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )

@router.post("/projects/import-db")
async def import_project_database(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    password: str = Form(...),
    description: Optional[str] = Form(None)
):
    """
    导入项目数据库文件（.cmdb / .json），恢复为独立的新项目或指定名称的项目。
    """
    try:
        content = await file.read()
        db_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析项目数据库文件: {str(e)}")

    if db_data.get("format") != "kame_lab_contact_manager_db":
        raise HTTPException(status_code=400, detail="非法的项目数据库格式文件")

    proj_meta = db_data.get("project", {})
    target_name = (name or proj_meta.get("name") or f"导入项目_{datetime.now().strftime('%m%d%H%M')}").strip()
    target_desc = (description if description is not None else proj_meta.get("description", "")).strip()

    if not password.strip():
        raise HTTPException(status_code=400, detail="必须为导入的项目设置访问密码")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM projects WHERE name = ?", (target_name,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"项目名称 '{target_name}' 已存在，请指定不同的项目名称")

        pwd_hash = hash_password(password.strip())
        cursor.execute(
            "INSERT INTO projects (name, password_hash, description) VALUES (?, ?, ?)",
            (target_name, pwd_hash, target_desc)
        )
        new_proj_id = cursor.lastrowid

        # 恢复字段
        fields = db_data.get("fields", [])
        for f in fields:
            cursor.execute(
                "INSERT INTO fields (project_id, name, label, is_default) VALUES (?, ?, ?, ?)",
                (new_proj_id, f["name"], f["label"], f.get("is_default", 0))
            )

        # 恢复跨版本同一人判定阈值（旧备份可能没有，回退默认 5）
        try:
            restored_threshold = int(proj_meta.get("id_match_fields", 5))
        except (TypeError, ValueError):
            restored_threshold = 5
        if restored_threshold < 1:
            restored_threshold = 5
        cursor.execute(
            "UPDATE projects SET id_match_fields = ? WHERE id = ?",
            (restored_threshold, new_proj_id))

        # 映射旧 entity_id -> 新 entity_id
        old_to_new_entity = {}
        for ent in db_data.get("entities", []):
            cursor.execute(
                "INSERT INTO contact_entities (project_id, entity_key) VALUES (?, ?)",
                (new_proj_id, ent["entity_key"])
            )
            old_to_new_entity[ent["id"]] = cursor.lastrowid

        # 映射旧 version_id -> 新 version_id
        old_to_new_version = {}
        for ver in db_data.get("versions", []):
            cursor.execute(
                "INSERT INTO contact_versions (project_id, filename, sheet_name, version_date) VALUES (?, ?, ?, ?)",
                (new_proj_id, ver["filename"], ver["sheet_name"], ver["version_date"])
            )
            old_to_new_version[ver["id"]] = cursor.lastrowid

        # 恢复 deltas
        for delta in db_data.get("deltas", []):
            old_ver_id = delta["version_id"]
            old_ent_id = delta["entity_id"]
            new_ver_id = old_to_new_version.get(old_ver_id)
            new_ent_id = old_to_new_entity.get(old_ent_id)
            if new_ver_id and new_ent_id:
                cursor.execute("""
                    INSERT OR REPLACE INTO contact_version_deltas (version_id, entity_id, data, is_deleted)
                    VALUES (?, ?, ?, ?)
                """, (new_ver_id, new_ent_id, delta["data"], delta.get("is_deleted", 0)))

    return {
        "success": True,
        "project": {
            "id": new_proj_id,
            "name": target_name,
            "description": target_desc
        },
        "message": f"项目 '{target_name}' 导入成功，共恢复 {len(old_to_new_version)} 个版本及 {len(old_to_new_entity)} 位联系人"
    }

@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, password: str = Query(...)):
    """
    删除项目及其所有通讯录数据（级联删除，服务器不保留任何痕迹）。
    必须先导出数据库备份（exported_at 不为空），再提供正确的项目密码进行二次确认。
    """
    if not password:
        raise HTTPException(status_code=400, detail="必须提供项目密码以确认删除")

    with get_db() as conn:
        cursor = conn.cursor()
        proj = _verify_project(cursor, project_id, password)

        if proj["exported_at"] is None:
            raise HTTPException(status_code=403, detail="必须先导出项目数据库备份后才能删除")

        # 级联删除项目（contact_versions, contact_entities, contact_version_deltas, fields 均被级联清除）
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    return {"success": True, "message": "项目及其所有数据已从服务器彻底删除"}


# ================= 2. 项目内通讯录业务 API =================

@router.post("/upload")
async def upload_contact_excel(
    file: UploadFile = File(...),
    proj: dict = Depends(get_project_auth)
):
    """上传通讯录 Excel 文件，暂存并返回日期建议与工作表列表"""
    temp_filename = f"contact_p{proj['id']}_{os.urandom(6).hex()}_{file.filename}"
    temp_path = config.UPLOAD_DIR / temp_filename
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    suggested_date = extract_date_from_filename(file.filename)
    try:
        sheets = get_excel_sheets(temp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析 Excel 文件: {str(e)}")

    return {
        "temp_path": str(temp_path),
        "filename": file.filename,
        "suggested_date": suggested_date,
        "sheets": sheets
    }

@router.get("/inspect")
async def inspect_sheet(
    temp_path: str,
    sheet_name: str,
    proj: dict = Depends(get_project_auth)
):
    """读取指定 sheet 的前 15 行预览，并自动结合当前项目的字段进行表头特征匹配"""
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="临时文件不存在或已过期，请重新上传")

    try:
        preview_rows = read_excel_preview(temp_path, sheet_name, max_rows=15)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, label, is_default FROM fields WHERE project_id = ?", (proj["id"],))
            fields = [dict(row) for row in cursor.fetchall()]
            threshold = get_id_match_fields(cursor, proj["id"])

        detection = detect_header_and_map(preview_rows, fields)

        return {
            "preview_rows": preview_rows,
            "fields": fields,
            "detected_header_row": detection["detected_header_row"],
            "mapping": detection["mapping"],
            # 跨版本「同一人」判定所需相同字段数（前端展示用）
            "id_match_fields": threshold,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析预览失败: {str(e)}")


@router.get("/match-fields")
async def match_fields_for_row(
    temp_path: str,
    sheet_name: str,
    header_row: int,
    proj: dict = Depends(get_project_auth)
):
    """对用户指定的表头行重新做字段自动匹配（切换表头行后调用）。"""
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="临时文件不存在或已过期，请重新上传")

    try:
        preview_rows = read_excel_preview(temp_path, sheet_name, max_rows=max(header_row, 15))

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, label, is_default FROM fields WHERE project_id = ?", (proj["id"],))
            fields = [dict(row) for row in cursor.fetchall()]

        mapping = map_fields_for_header_row(preview_rows, header_row, fields)
        return {"header_row": header_row, "mapping": {str(k): v for k, v in mapping.items()}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字段匹配失败: {str(e)}")

@router.get("/fields")
async def get_fields(proj: dict = Depends(get_project_auth)):
    """获取当前项目的字段定义"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, label, is_default FROM fields WHERE project_id = ?", (proj["id"],))
        fields = [dict(row) for row in cursor.fetchall()]
    return fields

@router.get("/fields/usage")
async def get_fields_usage(proj: dict = Depends(get_project_auth)):
    """字段内容统计：每个字段在已归档数据中的非空取值次数。

    前端据此标记「无内容」字段并提供清理入口。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, label, is_default FROM fields WHERE project_id = ? ORDER BY id",
            (proj["id"],))
        fields = [dict(row) for row in cursor.fetchall()]
        usage = collect_field_usage(cursor, proj["id"])

    result = []
    for f in fields:
        stat = usage.get(f["name"], {})
        non_empty = stat.get("non_empty", 0)
        result.append({
            **f,
            "non_empty": non_empty,
            "referenced": stat.get("referenced", 0),
            "empty": non_empty == 0,
        })
    empty_count = sum(1 for r in result if r["empty"])
    return {"fields": result, "empty_count": empty_count, "total": len(result)}

@router.post("/fields/clean")
async def clean_empty_fields(
    data: dict = None,
    proj: dict = Depends(get_project_auth)
):
    """删除当前项目中没有内容的字段。

    请求体可选：
      - include_default（默认 true）：是否连同空的默认字段一起删除
      - field_ids：只删除指定 id（限定在本项目内）；不传则删除全部空字段
      - dry_run（默认 false）：只统计不删除
    """
    payload = data or {}
    include_default = bool(payload.get("include_default", True))
    dry_run = bool(payload.get("dry_run", False))
    field_ids = payload.get("field_ids")

    with get_db() as conn:
        cursor = conn.cursor()
        if field_ids:
            empties = find_empty_fields(cursor, proj["id"], include_default=include_default)
            allowed = {f["id"] for f in empties}
            targets = [int(i) for i in field_ids if int(i) in allowed]
            if not targets:
                return {"success": True, "deleted": 0, "fields": [],
                        "message": "指定的字段不存在、不属于本项目，或仍有内容，未删除任何字段"}
            if dry_run:
                chosen = [f for f in empties if f["id"] in set(targets)]
                return {"success": True, "deleted": 0, "dry_run": True,
                        "fields": chosen,
                        "message": f"将要删除 {len(chosen)} 个空字段"}
            deleted = delete_fields(cursor, proj["id"], targets)
            chosen = [f for f in empties if f["id"] in set(targets)]
        else:
            if dry_run:
                empties = find_empty_fields(cursor, proj["id"], include_default=include_default)
                return {"success": True, "deleted": 0, "dry_run": True,
                        "fields": empties,
                        "message": f"将要删除 {len(empties)} 个空字段"}
            outcome = remove_empty_fields(cursor, proj["id"], include_default=include_default)
            deleted = outcome["deleted"]
            chosen = outcome["fields"]

    labels = [f["label"] for f in chosen]
    return {
        "success": True,
        "deleted": deleted,
        "fields": chosen,
        "message": (f"已删除 {deleted} 个无内容字段" + (f"：{'、'.join(labels)}" if labels else "")),
    }

@router.post("/fields")
async def create_field(
    data: dict,
    proj: dict = Depends(get_project_auth)
):
    """在当前项目中新增自定义字段。

    若同显示名的字段已存在则直接复用，避免历史缺陷（前端重复提交）造成的
    同名字段堆积 —— 那会让导入时匹配到错误的空字段、数据看起来「丢失」。
    """
    name = (data.get("name") or "").strip()
    label = (data.get("label") or "").strip()
    if not name or not label:
        raise HTTPException(status_code=400, detail="字段标识和显示名称不能为空")

    with get_db() as conn:
        cursor = conn.cursor()
        # 已存在同显示名字段 → 复用（幂等）
        cursor.execute(
            "SELECT id, name, label, is_default FROM fields WHERE project_id = ? AND label = ? LIMIT 1",
            (proj["id"], label))
        existing = cursor.fetchone()
        if existing:
            return {**dict(existing), "reused": True}

        try:
            cursor.execute(
                "INSERT INTO fields (project_id, name, label, is_default) VALUES (?, ?, ?, 0)",
                (proj["id"], name, label)
            )
            field_id = cursor.lastrowid
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"字段已存在或创建失败: {str(e)}")

    return {"id": field_id, "name": name, "label": label, "is_default": 0, "reused": False}

@router.get("/settings")
async def get_settings(proj: dict = Depends(get_project_auth)):
    """读取项目设置。

    id_match_fields：跨版本判定「同一个人」所需的相同字段数（不含姓名，默认 5）。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        threshold = get_id_match_fields(cursor, proj["id"])
    return {
        "id_match_fields": threshold,
        # 身份键固定为姓名，保留该字段供前端展示说明
        "id_field": get_default_id_field(),
        "id_field_label": _field_label_text(proj["id"]),
    }


def _field_label_text(project_id: int) -> str:
    with get_db() as conn:
        return _field_label(conn.cursor(), project_id, get_default_id_field())


@router.post("/settings")
async def update_settings(data: dict, proj: dict = Depends(get_project_auth)):
    """更新项目设置：跨版本「同一人」判定的相同字段数（id_match_fields）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        updated = {}
        if "id_match_fields" in data:
            try:
                n = int(data.get("id_match_fields"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="id_match_fields 必须是整数")
            if n < 1:
                raise HTTPException(status_code=400, detail="相同字段数至少为 1")
            cursor.execute(
                "UPDATE projects SET id_match_fields = ? WHERE id = ?", (n, proj["id"]))
            updated["id_match_fields"] = n

        threshold = get_id_match_fields(cursor, proj["id"])

    return {
        "success": True,
        "id_match_fields": threshold,
        "message": f"跨版本同一人判定已设为「{threshold} 个字段相同」",
    }


@router.post("/import/preview")
async def preview_import(
    data: dict,
    proj: dict = Depends(get_project_auth)
):
    """导入前预检：返回重名情况与跨版本匹配结果，供前端决定「合并 / 保留」并提示。

    不写入任何数据。
    """
    temp_path = data.get("temp_path")
    sheet_name = data.get("sheet_name")
    header_row = int(data.get("header_row", 1))
    mapping = {int(k): v for k, v in data.get("mapping", {}).items()}
    project_id = proj["id"]

    if not temp_path or not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="临时文件不存在")

    try:
        parsed_contacts, row_numbers = _parse_with_labels(
            temp_path, sheet_name, header_row, mapping, proj["id"])

        with get_db() as conn:
            cursor = conn.cursor()
            threshold = get_id_match_fields(cursor, project_id)
            prev_version_id = _get_latest_version_id(cursor, project_id)
            index = _build_previous_index(cursor, project_id, prev_version_id)

            dupes = find_duplicate_names(parsed_contacts)

            # 逐条给出跨版本匹配预估
            matched, new_people = 0, 0
            for rec in parsed_contacts:
                eid, _cand, _n = _match_entity(cursor, project_id, rec, index, threshold)
                if eid:
                    matched += 1
                else:
                    new_people += 1

        return {
            "duplicates": [
                {"name": d["name"], "count": d["count"]} for d in dupes
            ],
            "duplicate_count": len(dupes),
            "total_rows": len(parsed_contacts),
            "threshold": threshold,
            "prev_version_id": prev_version_id,
            "matched_count": matched,
            "new_count": new_people,
            "has_previous": prev_version_id is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


def _parse_with_labels(temp_path: str, sheet_name: str, header_row: int, mapping: dict,
                       project_id: int):
    """解析表格，并带上字段显示名（用于出生年月等按字段类型格式化）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, label FROM fields WHERE project_id = ?", (project_id,))
        labels = {row["name"]: row["label"] for row in cursor.fetchall()}
    return parse_sheet_data(temp_path, sheet_name, header_row, mapping, field_labels=labels)


@router.post("/import")
async def import_contacts(
    data: dict,
    proj: dict = Depends(get_project_auth)
):
    """
    在当前项目中导入通讯录 Excel，生成新版本并计算增量变动。

    身份标识由后端自行计算（不再要求用户选择字段）：
      - 实体的唯一键由后端生成，与姓名解耦，因此同名不同人可以各自独立存在
      - 同一次导入内出现重名时：按 duplicate_action 处理
          merge    → 合并为一条（不同取值用「、」拼接）
          separate → 各自保留为独立联系人
        未指定时直接返回 409，由前端询问用户
      - 跨版本判定「同一个人」：同名的人中，只要有某个候选与本记录除姓名外
        至少 id_match_fields（默认 5，可按项目配置）个字段取值相同，即认为是同一人
    """
    temp_path = data.get("temp_path")
    sheet_name = data.get("sheet_name")
    header_row = int(data.get("header_row", 1))
    mapping = {int(k): v for k, v in data.get("mapping", {}).items()}
    version_date = data.get("version_date")
    filename = data.get("filename", "unknown.xlsx")
    duplicate_action = (data.get("duplicate_action") or "").strip().lower()
    project_id = proj["id"]

    if not temp_path or not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="临时文件不存在")
    if not version_date:
        raise HTTPException(status_code=400, detail="版本日期不能为空")

    try:
        parsed_contacts, row_numbers = _parse_with_labels(
            temp_path, sheet_name, header_row, mapping, project_id)

        # 姓名是唯一的展示键，必须映射到某一列
        if "name" not in mapping.values():
            raise HTTPException(
                status_code=400,
                detail="姓名列必须映射到「姓名」字段（用于识别联系人）")

        # 1) 重名处理：需要用户决定时才询问
        dupes = find_duplicate_names(parsed_contacts)
        if dupes and duplicate_action not in ("merge", "separate"):
            names = "、".join(d["name"] for d in dupes[:5])
            more = f" 等 {len(dupes)} 个姓名" if len(dupes) > 5 else ""
            # 注意：重名列表只能放在 detail（JSON 体）里 —— HTTP 头是 latin-1，
            # 无法承载中文姓名，放进 header 会直接抛 UnicodeEncodeError。
            raise HTTPException(
                status_code=409,
                detail=f"发现重名：{names}{more}，请选择「合并为一条」或「各自保留」。")

        merge_conflicts = {}
        # 用 (记录, Excel 行号) 配对，保证合并后行号仍能对应回原表
        paired = list(zip(parsed_contacts, row_numbers))
        if dupes and duplicate_action == "merge":
            by_name = {}
            for rec, row_no in paired:
                key = clean_value(rec.get("name", ""))
                by_name.setdefault(key, []).append((rec, row_no))
            paired = []
            for key, group in by_name.items():
                if len(group) == 1:
                    paired.append(group[0])
                else:
                    merged, conflicts = merge_records([g[0] for g in group])
                    # 保留第一行的行号，便于用户回到原表定位
                    paired.append((merged, group[0][1]))
                    if conflicts:
                        merge_conflicts[key] = conflicts
        elif dupes and duplicate_action == "separate":
            # 各自保留：同名记录按出现顺序保留原始行号
            pass

        with get_db() as conn:
            cursor = conn.cursor()
            threshold = get_id_match_fields(cursor, project_id)

            # 0) 同一日期视为同一个版本：覆盖之前上传的同日期版本
            #    严格限定在本项目内；deltas 依赖外键 ON DELETE CASCADE 随版本一并删除，
            #    contact_entities 与字段定义不受影响。
            #    ★ 切勿在此追加「清理孤儿 delta」的全表语句 —— 不按 project_id 过滤会
            #      把其它项目的数据一并删掉（历史上已因此清空过全部 delta，靠备份恢复）。
            same_date = cursor.execute(
                "SELECT id FROM contact_versions WHERE project_id = ? AND version_date = ?",
                (project_id, version_date)).fetchall()
            if same_date:
                ids = [r["id"] for r in same_date]
                marks = ",".join("?" * len(ids))
                cursor.execute(
                    f"DELETE FROM contact_versions WHERE id IN ({marks}) AND project_id = ?",
                    (*ids, project_id))

            # 1) 版本记录：先插入以取得 version_id（用作上一版本比较的边界）
            cursor.execute(
                "INSERT INTO contact_versions (project_id, filename, sheet_name, version_date) VALUES (?, ?, ?, ?)",
                (project_id, filename, sheet_name, version_date))
            version_id = cursor.lastrowid

            # 2) 上一版本（同一时点之前的最近版本）
            cursor.execute("""
                SELECT id FROM contact_versions
                WHERE project_id = ? AND (version_date < ? OR (version_date = ? AND id < ?))
                ORDER BY version_date DESC, id DESC LIMIT 1
            """, (project_id, version_date, version_date, version_id))
            prev_row = cursor.fetchone()
            prev_version_id = prev_row["id"] if prev_row else None
            index = _build_previous_index(cursor, project_id, prev_version_id)

            seen_entity_ids = set()
            skipped = 0
            blank_rows = []
            merged_count = 0
            new_count = 0

            for rec, row_no in paired:
                name = clean_value(rec.get("name", ""))
                if not name:
                    skipped += 1
                    blank_rows.append(row_no)
                    continue

                entity_id, _cand, n_match = _match_entity(
                    cursor, project_id, rec, index, threshold)

                if entity_id is None:
                    # 新人：后端生成唯一键
                    entity_id = _create_entity(cursor, project_id)
                    new_count += 1
                else:
                    merged_count += 1
                    # 从索引中移除，避免同名多行重复匹配到同一个旧实体
                    matched_name = name
                    if matched_name in index:
                        index[matched_name] = [
                            c for c in index[matched_name]
                            if c.get("_entity_id") != entity_id
                        ]

                seen_entity_ids.add(entity_id)
                _upsert_delta(cursor, version_id, entity_id, rec)

            # 上一版本有、本次没有 → 逻辑删除
            removed = 0
            if prev_version_id:
                for pe in _get_all_entities_at_version(cursor, project_id, prev_version_id):
                    eid = pe["_entity_id"]
                    if eid not in seen_entity_ids:
                        _upsert_delta(cursor, version_id, eid, {}, is_deleted=1)
                        removed += 1

        return {
            "success": True,
            "version_id": version_id,
            "imported_count": len(paired) - skipped,
            "skipped_count": skipped,
            "blank_id_rows": blank_rows[:20],
            "removed_count": removed,
            "new_count": new_count,
            "merged_count": merged_count,
            "duplicate_action": duplicate_action or "none",
            "duplicate_merged": sum(1 for d in dupes) if duplicate_action == "merge" else 0,
            "merge_conflicts": merge_conflicts,
            "threshold": threshold,
            "version_date": version_date,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/versions")
async def list_versions(proj: dict = Depends(get_project_auth)):
    """获取当前项目的历史通讯录版本列表"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, v.filename, v.sheet_name, v.version_date, v.created_at,
                   (SELECT COUNT(*) FROM contact_version_deltas cvd
                    WHERE cvd.version_id = v.id AND cvd.is_deleted = 0) as contact_count
            FROM contact_versions v
            WHERE v.project_id = ?
            ORDER BY v.version_date DESC, v.id DESC
        """, (proj["id"],))
        versions = [dict(row) for row in cursor.fetchall()]
    return versions

def build_keyword_matcher(keyword):
    """构造关键词匹配函数。

    - 关键词含 `*` 时按简单通配符处理：`*` 匹配任意字符序列（含空），其余字符按字面匹配；
      整串要求完全匹配（前后隐式锚定）。例：`张*` 匹配以「张」开头；`*委员*` 匹配包含「委员」。
    - 不含 `*` 时为普通的「包含」匹配。
    两侧都会先做值清理（去空白等），与存储的数据保持一致。
    """
    kw = clean_value(keyword or "")
    if not kw:
        return None

    if "*" in kw:
        # 逐字符构造：`*` → 任意字符序列，其余按字面转义。
        # 保留连续/首尾的 `*`（每个都对应一个 `.*`），因此 `张*`、`*委员*`、`*员` 语义正确。
        pattern = "^" + "".join(".*" if ch == "*" else re.escape(ch) for ch in kw) + "$"
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = None

        if rx is not None:
            def match(v):
                if v is None:
                    return False
                return rx.match(clean_value(v)) is not None
            return match

    needle = kw
    def match(v):
        if v is None:
            return False
        return needle in clean_value(v)
    return match


def _record_matches_keyword(record, matcher):
    """记录的任一字段命中即算匹配。"""
    for k, v in (record or {}).items():
        if k.startswith("_") or k == "id":
            continue
        if matcher(v):
            return True
    return False


@router.get("/contacts")
async def query_contacts(
    version_id: Optional[int] = None,
    query_date: Optional[str] = None,
    keyword: Optional[str] = None,
    proj: dict = Depends(get_project_auth)
):
    """
    在当前项目内查询联系人。

    查询语义（由「版本归档」选择决定）：
      - 选择了版本：只在该版本内查询，日期条件不生效（前端会禁用日期选择）；
      - 未选择版本：跨版本查询 ——
          · 不选日期：返回**所有版本**中匹配到的记录；
          · 选择日期：返回**版本日期 ≤ 该日期**的所有版本中匹配到的记录。
    关键词支持 `*` 通配符（如 `张*`、`*委员*`）。
    """
    project_id = proj["id"]
    matcher = build_keyword_matcher(keyword)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, label, is_default FROM fields WHERE project_id = ?", (project_id,))
        fields = {row["name"]: row["label"] for row in cursor.fetchall()}
        fields_list = [{"name": k, "label": v} for k, v in fields.items()]

        # ---- 情景 A: 未选择版本 → 跨版本查询（可带日期上限）----
        if not version_id:
            date_clause = "AND cv.version_date <= ?" if query_date else ""
            params = [project_id] + ([query_date] if query_date else [])
            cursor.execute(f"""
                SELECT ce.entity_key, cvd.data, cvd.is_deleted,
                       cv.version_date, cv.filename, cv.id as version_id
                FROM contact_version_deltas cvd
                JOIN contact_versions cv ON cvd.version_id = cv.id
                JOIN contact_entities ce ON cvd.entity_id = ce.id
                WHERE cv.project_id = ? AND cvd.is_deleted = 0 {date_clause}
                ORDER BY cv.version_date DESC, cv.id DESC
            """, params)
            rows = cursor.fetchall()

            contacts = []
            for r in rows:
                try:
                    c_data = json.loads(r["data"])
                except (TypeError, ValueError):
                    continue
                if matcher is not None and not _record_matches_keyword(c_data, matcher):
                    continue
                contacts.append({
                    "_entity_key": r["entity_key"],
                    "_version_date": r["version_date"],
                    "_filename": r["filename"],
                    "_version_id": r["version_id"],
                    **c_data
                })
            return {
                "version": None,
                "fields": fields_list,
                "contacts": contacts,
                "is_historical": True,
                "query_scope": {"date_limit": query_date or None},
            }

        # ---- 情景 B: 选择了版本 → 只查该版本（日期条件不生效）----
        cursor.execute("SELECT * FROM contact_versions WHERE id = ? AND project_id = ?",
                       (version_id, project_id))
        version_info_row = cursor.fetchone()
        if not version_info_row:
            return {"version": None, "contacts": [], "fields": fields_list,
                    "is_historical": False}
        version_info = dict(version_info_row)

        entities = _get_all_entities_at_version(cursor, project_id, version_id)

        contacts = []
        for e in entities:
            if matcher is not None and not _record_matches_keyword(e, matcher):
                continue
            contacts.append(e)

    return {
        "version": version_info,
        "fields": fields_list,
        "contacts": contacts,
        "is_historical": False,
        "query_scope": {"version_id": version_id},
    }

@router.post("/versions/create-from-latest")
async def create_version_from_latest(
    data: dict,
    proj: dict = Depends(get_project_auth)
):
    """
    在当前项目中基于最新版本创建新版本（增量/继承模式）。
    """
    project_id = proj["id"]
    version_date = data.get("version_date")
    filename = data.get("filename", f"manual_update_{version_date}.xlsx")
    sheet_name = data.get("sheet_name", "Sheet1")
    operations = data.get("operations", [])

    if not version_date:
        raise HTTPException(status_code=400, detail="必须提供新版本日期")

    with get_db() as conn:
        cursor = conn.cursor()

        latest_version_id = _get_latest_version_id(cursor, project_id)
        if not latest_version_id:
            raise HTTPException(status_code=400, detail="没有可继承的历史版本")

        # 身份键由后端计算：前端在编辑时回传 _entity_id 以精确定位实体
        entities = _get_all_entities_at_version(cursor, project_id, latest_version_id)
        entity_map = {str(e["_entity_id"]): e for e in entities}

        deleted_ids = set()
        for op in operations:
            op_type = op.get("type")
            if op_type == "upsert":
                op_data = op.get("data", {})
                op_id = op.get("id") or op_data.get("_entity_id") or op_data.get("id")
                key = str(op_id) if op_id is not None else None
                if key and key in entity_map:
                    entity_map[key] = {**entity_map[key], **op_data}
                elif clean_value(op_data.get("name", "")):
                    # 无 id（新增）：按姓名 + 相似度寻找是否已有同一人
                    eid, _c, _n = _match_entity(
                        cursor, project_id, op_data, {
                            clean_value(e["name"]): [e]
                            for e in entity_map.values() if e.get("name")
                        }, get_id_match_fields(cursor, project_id))
                    if eid:
                        entity_map[str(eid)] = {**entity_map.get(str(eid), {}), **op_data}
                    else:
                        entity_map[f"new_{len(entity_map)}"] = dict(op_data)

            elif op_type == "delete":
                del_id = op.get("id")
                del_name = clean_value(op.get("name", ""))
                targets = set()
                if del_id is not None and str(del_id) in entity_map:
                    targets.add(str(del_id))
                if not targets and del_name:
                    # 按姓名删除：可能命中多条（同名不同人），全部删除
                    targets = {
                        k for k, v in entity_map.items()
                        if clean_value(v.get("name", "")) == del_name
                    }
                deleted_ids |= targets

        for key in deleted_ids:
            entity_map.pop(key, None)

        final_entities = []
        for entity in entity_map.values():
            clean_entity = {k: v for k, v in entity.items() if not k.startswith("_")}
            if clean_entity.get("name"):
                final_entities.append(clean_entity)

        new_version_id = _create_version_from_entities(cursor, project_id, filename, sheet_name, version_date, final_entities)

        return {
            "success": True,
            "new_version_id": new_version_id,
            "version_date": version_date,
            "total_contacts": len(final_entities),
            "message": f"已基于增量逻辑创建新版本 {version_date}，共 {len(final_entities)} 条记录"
        }

@router.get("/export")
async def export_contacts_excel(
    version_id: Optional[int] = None,
    query_date: Optional[str] = None,
    proj: dict = Depends(get_project_auth)
):
    """导出当前项目指定版本或日期点的通讯录为 Excel 文件"""
    project_id = proj["id"]
    with get_db() as conn:
        cursor = conn.cursor()
        target_version_id = version_id
        if not target_version_id:
            if query_date:
                cursor.execute("""
                    SELECT id FROM contact_versions WHERE project_id = ? AND version_date <= ?
                    ORDER BY version_date DESC, id DESC LIMIT 1
                """, (project_id, query_date))
            else:
                cursor.execute("""
                    SELECT id FROM contact_versions WHERE project_id = ?
                    ORDER BY version_date DESC, id DESC LIMIT 1
                """, (project_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="没有找到可导出的通讯录版本")
            target_version_id = row["id"]

        cursor.execute("SELECT * FROM contact_versions WHERE id = ? AND project_id = ?", (target_version_id, project_id))
        version_info = dict(cursor.fetchone())

        cursor.execute("SELECT name, label FROM fields WHERE project_id = ?", (project_id,))
        fields = {row["name"]: row["label"] for row in cursor.fetchall()}
        field_keys = list(fields.keys())
        field_labels = list(fields.values())

        entities = _get_all_entities_at_version(cursor, project_id, target_version_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = version_info.get("sheet_name", "通讯录")

    ws.append(field_labels)
    for e in entities:
        row_vals = [e.get(k, "") for k in field_keys]
        ws.append(row_vals)

    # 项目名来自用户输入，不能直接拼进路径（曾可被 ../../ 逃出 OUTPUT_DIR）。
    # 内容文件用随机名，避免同名项目并发导出互相覆盖；下载名只影响浏览器保存的文件。
    export_filename = (
        f"{_safe_name_part(proj['name'])}_ContactBook_"
        f"{_safe_name_part(version_info['version_date'], 'unknown')}.xlsx"
    )
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = config.OUTPUT_DIR / f"{uuid.uuid4().hex}.xlsx"
    wb.save(export_path)

    return FileResponse(
        export_path,
        filename=export_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
