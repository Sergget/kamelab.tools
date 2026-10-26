import os
import sqlite3
import hashlib
import secrets
import re
from contextlib import contextmanager
from typing import Optional

from ... import config

# 库文件跟随 LAB_TOOLS_DATA_DIR（默认仍是 backend/data），
# 否则测试与多实例部署都会写到同一个硬编码路径上。
DB_PATH = os.path.abspath(str(config.DATA_DIR / "contact_manager.db"))

_PBKDF2_ITERATIONS = 100_000
_SALT_BYTES = 16
# 格式：pbkdf2$<iterations>$<salt_hex>$<hash_hex>
_HASH_RE = re.compile(r"^pbkdf2\$(\d+)\$([0-9a-f]+)\$([0-9a-f]+)$")


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt.

    返回格式：pbkdf2$<iterations>$<salt_hex>$<hash_hex>
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配哈希值。

    支持新格式（pbkdf2$iter$salt$hash）；
    兼容旧的纯 SHA-256 哈希（32 字节 hex），便于旧数据平滑迁移。
    """
    if not stored_hash:
        return False
    m = _HASH_RE.match(stored_hash)
    if m:
        iterations = int(m.group(1))
        salt = bytes.fromhex(m.group(2))
        expected = bytes.fromhex(m.group(3))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(dk, expected)
    # 兼容旧的 unsalted SHA-256（4350cf1f... 这种 64 字符 hex）
    if len(stored_hash) == 64 and re.fullmatch(r"[0-9a-f]{64}", stored_hash):
        sha = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return secrets.compare_digest(sha, stored_hash)
    return False

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ================= 表结构定义与迁移 =================
#
# 历史问题（导致导入接口 500）：
#   早期迁移用 ALTER TABLE ... RENAME TO _xxx_old 重建表，而 SQLite 会自动
#   改写其它表外键里的目标表名。随后旧代码 DROP 掉 _xxx_old，留在
#   contact_version_deltas 外键中的引用就变成悬空外键（指向已不存在的表）。
#   旧代码只用字符串包含判断（"FOREIGN KEY (version_id)" in sql）决定是否迁移，
#   悬空外键的文本依然匹配，于是永远不会被修复；而连接默认
#   PRAGMA foreign_keys = ON，写入时报 "no such table: main._versions_old"。
#
# 现在的做法：用 PRAGMA foreign_key_list 读取外键的**实际目标表**，与期望结构
# 比对，不一致（含指向已不存在或 _*_old 的表）就重建该表；重建期间用
# legacy_alter_table=ON 阻止 RENAME 再次改写其它表的外键引用。

_EXPECTED_TABLES = {
    "fields": {
        "create": """
        CREATE TABLE fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            label TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            UNIQUE(project_id, name),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        "columns": ["id", "project_id", "name", "label", "is_default"],
        "fk_targets": {"projects"},
        "unique": "UNIQUE(project_id, name)",
        "copy_required": ["project_id"],
        "copy_filter": "project_id IN (SELECT id FROM projects)",
    },
    "contact_versions": {
        "create": """
        CREATE TABLE contact_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            version_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        "columns": ["id", "project_id", "filename", "sheet_name", "version_date", "created_at"],
        "fk_targets": {"projects"},
        "unique": None,
        "copy_required": ["project_id"],
        "copy_filter": "project_id IN (SELECT id FROM projects)",
    },
    "contact_entities": {
        "create": """
        CREATE TABLE contact_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            entity_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, entity_key),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        "columns": ["id", "project_id", "entity_key", "created_at"],
        "fk_targets": {"projects"},
        "unique": "UNIQUE(project_id, entity_key)",
        "copy_required": ["project_id"],
        "copy_filter": "project_id IN (SELECT id FROM projects)",
    },
    "contact_version_deltas": {
        "create": """
        CREATE TABLE contact_version_deltas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            is_deleted INTEGER DEFAULT 0,
            FOREIGN KEY (version_id) REFERENCES contact_versions(id) ON DELETE CASCADE,
            FOREIGN KEY (entity_id) REFERENCES contact_entities(id) ON DELETE CASCADE,
            UNIQUE(version_id, entity_id)
        )
        """,
        "columns": ["id", "version_id", "entity_id", "data", "is_deleted"],
        "fk_targets": {"contact_versions", "contact_entities"},
        "unique": "UNIQUE(version_id, entity_id)",
        "copy_required": ["version_id", "entity_id", "data"],
        "copy_filter": (
            "version_id IN (SELECT id FROM contact_versions) "
            "AND entity_id IN (SELECT id FROM contact_entities)"
        ),
    },
}

# 历史迁移可能残留的临时表（含悬空外键指向的表）
_LEGACY_TEMP_TABLES = (
    "_fields_old",
    "_versions_old",
    "_entities_old",
    "_deltas_old",
    "_mig_fields",
    "_mig_contact_versions",
    "_mig_contact_entities",
    "_mig_contact_version_deltas",
)


def _table_sql(cursor, name: str) -> Optional[str]:
    """返回表的建表 SQL；表不存在返回 None。"""
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,))
    row = cursor.fetchone()
    return row[0] if row else None


def _fk_targets(cursor, name: str) -> set:
    """返回表外键实际指向的目标表名集合。"""
    cursor.execute(f"PRAGMA foreign_key_list({name})")
    return {row[2] for row in cursor.fetchall()}


def _needs_rebuild(cursor, name: str, spec: dict) -> bool:
    """结构（外键目标 / 唯一约束）与期望不一致时需要重建。"""
    sql = _table_sql(cursor, name)
    if sql is None:
        return False
    if _fk_targets(cursor, name) != spec["fk_targets"]:
        return True
    if spec.get("unique") and spec["unique"] not in sql:
        return True
    return False


def _rebuild_table(cursor, name: str, spec: dict) -> None:
    """按期望结构重建表，保留原有数据（含主键 id，供外键引用）。"""
    tmp = f"_mig_{name}"
    cursor.execute(f"DROP TABLE IF EXISTS {tmp}")
    cursor.execute(f"ALTER TABLE {name} RENAME TO {tmp}")
    cursor.execute(spec["create"])

    cursor.execute(f"PRAGMA table_info({tmp})")
    old_cols = [row[1] for row in cursor.fetchall()]

    # 旧结构缺少必要列时无法安全搬运数据，只保留新空表
    if all(col in old_cols for col in spec["copy_required"]):
        cols = [c for c in spec["columns"] if c in old_cols]
        collist = ", ".join(cols)
        where = spec.get("copy_filter")
        cursor.execute(
            f"INSERT OR IGNORE INTO {name} ({collist}) SELECT {collist} FROM {tmp}"
            + (f" WHERE {where}" if where else "")
        )

    cursor.execute(f"DROP TABLE {tmp}")


def _ensure_table(cursor, name: str) -> None:
    """表不存在则创建；结构过时（含悬空外键）则重建。"""
    spec = _EXPECTED_TABLES[name]
    if _table_sql(cursor, name) is None:
        cursor.execute(spec["create"])
        return
    if _needs_rebuild(cursor, name, spec):
        _rebuild_table(cursor, name, spec)


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 迁移期间关闭外键约束；legacy_alter_table=ON 阻止 RENAME 改写其它表的外键引用
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute("PRAGMA legacy_alter_table = ON")

    # 1. 项目表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        exported_at TIMESTAMP DEFAULT NULL,
        id_field TEXT DEFAULT NULL
    )
    """)
    row_proj = _table_sql(cursor, "projects")
    if row_proj and "exported_at" not in row_proj:
        cursor.execute("ALTER TABLE projects ADD COLUMN exported_at TIMESTAMP DEFAULT NULL")
    # id_field：历史遗留（早期由用户选身份字段）。现已改为后端按姓名 + 字段相似度
    # 自行判定身份，该列保留仅为兼容旧数据，不再参与逻辑。
    if row_proj and "id_field" not in row_proj:
        cursor.execute("ALTER TABLE projects ADD COLUMN id_field TEXT DEFAULT NULL")
    # id_match_fields：跨版本判断「同一个人」所需的相同字段数（不含姓名），默认 5
    if row_proj and "id_match_fields" not in row_proj:
        cursor.execute("ALTER TABLE projects ADD COLUMN id_match_fields INTEGER DEFAULT 5")

    # 2~5. 业务表：结构不符（含悬空外键）即重建
    for name in ("fields", "contact_versions", "contact_entities", "contact_version_deltas"):
        _ensure_table(cursor, name)

    # 清理历史迁移残留的临时表（悬空外键的来源）
    for tmp in _LEGACY_TEMP_TABLES:
        cursor.execute(f"DROP TABLE IF EXISTS {tmp}")

    # 清理孤立数据：必须先删孤立项目/版本/实体，再删引用它们的 delta，
    # 否则 delta 在本步仍能匹配到"尚存的"孤立版本/实体而被漏掉。
    cursor.execute("DELETE FROM contact_versions WHERE project_id NOT IN (SELECT id FROM projects)")
    cursor.execute("DELETE FROM contact_entities WHERE project_id NOT IN (SELECT id FROM projects)")
    cursor.execute("DELETE FROM fields WHERE project_id NOT IN (SELECT id FROM projects)")
    cursor.execute("""
        DELETE FROM contact_version_deltas
        WHERE version_id NOT IN (SELECT id FROM contact_versions)
           OR entity_id NOT IN (SELECT id FROM contact_entities)
    """)

    # 创建索引加速查询
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fields_proj ON fields(project_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_versions_proj ON contact_versions(project_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_proj ON contact_entities(project_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deltas_ver ON contact_version_deltas(version_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deltas_ent ON contact_version_deltas(entity_id)")

    # 恢复 SQLite 默认行为并重新开启外键
    cursor.execute("PRAGMA legacy_alter_table = OFF")
    cursor.execute("PRAGMA foreign_keys = ON")

    conn.commit()
    conn.close()

def get_default_id_field() -> str:
    """身份键固定使用姓名字段（后端自行计算 id，不再由用户选择）。"""
    return "name"


def get_id_match_fields(cursor, project_id: int) -> int:
    """取跨版本判定「同一个人」所需的相同字段数（不含姓名），默认 5。"""
    cursor.execute("SELECT id_match_fields FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    value = None
    if row and "id_match_fields" in row.keys():
        value = row["id_match_fields"]
    try:
        n = int(value) if value is not None else 5
    except (TypeError, ValueError):
        n = 5
    return n if n >= 1 else 5


def resolve_id_field(cursor, project_id: int) -> str:
    """身份键始终为姓名（保留函数以便其它模块调用）。"""
    return get_default_id_field()


def init_project_default_fields(cursor, project_id: int):
    """为新建的项目初始化默认核心字段"""
    default_fields = [
        ("name", "姓名", 1),
        ("title", "职务", 1),
        ("unit", "单位", 1),
        ("gender", "性别", 1),
        ("phone", "联系电话", 1),
        ("mobile", "手机号码", 1),
        ("email", "电子邮箱", 1),
        ("office", "办公地点", 1)
    ]
    for name, label, is_default in default_fields:
        cursor.execute("""
            INSERT OR IGNORE INTO fields (project_id, name, label, is_default)
            VALUES (?, ?, ?, ?)
        """, (project_id, name, label, is_default))


def collect_field_usage(cursor, project_id: int) -> dict:
    """统计项目各字段的内容情况。

    返回 {field_name: {"non_empty": n, "referenced": m}}：
      - referenced：该字段在 contact_version_deltas.data(JSON) 中出现的次数
      - non_empty ：其中取值为非空（去空白后）的次数

    字段数据存放在 deltas 的 JSON 里，因此「是否有内容」必须解析 JSON 统计，
    不能只看 fields 表本身。
    """
    import json as _json

    usage: dict = {}
    cursor.execute("""
        SELECT cvd.data FROM contact_version_deltas cvd
        JOIN contact_versions cv ON cvd.version_id = cv.id
        WHERE cv.project_id = ?
    """, (project_id,))
    for row in cursor.fetchall():
        try:
            obj = _json.loads(row["data"])
        except (TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        for key, val in obj.items():
            entry = usage.setdefault(key, {"non_empty": 0, "referenced": 0})
            entry["referenced"] += 1
            if str(val if val is not None else "").strip():
                entry["non_empty"] += 1
    return usage


def find_empty_fields(cursor, project_id: int, include_default: bool = True) -> list:
    """找出项目中没有内容的字段。

    include_default=False 时保留 is_default=1 的标准字段（即使为空）。
    """
    usage = collect_field_usage(cursor, project_id)
    cursor.execute(
        "SELECT id, name, label, is_default FROM fields WHERE project_id = ? ORDER BY id",
        (project_id,))
    empties = []
    for row in cursor.fetchall():
        if usage.get(row["name"], {}).get("non_empty", 0) > 0:
            continue
        if not include_default and row["is_default"]:
            continue
        empties.append(dict(row))
    return empties


def delete_fields(cursor, project_id: int, field_ids: list) -> int:
    """删除项目内指定 id 的字段，返回实际删除数量。

    仅按 id 删除也要求 project_id 匹配，避免越权删除其它项目的字段。
    """
    if not field_ids:
        return 0
    placeholders = ",".join("?" for _ in field_ids)
    cursor.execute(
        f"DELETE FROM fields WHERE project_id = ? AND id IN ({placeholders})",
        (project_id, *field_ids))
    return cursor.rowcount


def remove_empty_fields(cursor, project_id: int, include_default: bool = True) -> dict:
    """删除项目中所有空字段，返回删除明细。

    注意：字段数据保存在 deltas 的 JSON 中，删除 fields 记录**不会**影响
    已有的联系人数据 —— 只是该字段不再展示/导出。因此调用前应确认这些字段
    确实没有内容（find_empty_fields 已保证）。
    """
    empties = find_empty_fields(cursor, project_id, include_default=include_default)
    deleted = delete_fields(cursor, project_id, [f["id"] for f in empties])
    return {"deleted": deleted, "fields": empties}

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
