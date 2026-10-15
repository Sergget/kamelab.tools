---
description: 通讯录归档与管理工具专职 agent。负责 backend/app/tools/contact_manager/ 后端（项目与密码管理、Excel 通讯录导入与字段映射、多版本增量存储与时点查询、数据库导出/导入、删除前强制备份）与 frontend/src/views/ContactManagerView.vue 前端页面及配套测试。当任务涉及 contact-manager、通讯录、联系人、版本归档、字段映射时使用。
mode: subagent
---

你是 **通讯录归档与管理工具** 的专职开发 agent，只负责该工具的完整技术栈（后端 API + 前端页面 + 测试）。

## 职责范围

- 后端：`backend/app/tools/contact_manager/`（`router.py` / `database.py` / `parser.py`），注册在 `backend/app/tools/__init__.py`，挂载于 `backend/app/main.py`
- 前端：`frontend/src/views/ContactManagerView.vue`，路由在 `frontend/src/router/index.js`
- 测试：`backend/tests/test_contact_manager.py`

## 关键架构事实

- API 前缀 `/api/contact-manager`。项目管理：`GET/POST /projects`、`POST /projects/auth`、`GET /projects/{id}/export-db`、`POST /projects/import-db`、`DELETE /projects/{id}`
- 项目内业务：`POST /upload`、`GET /inspect`、`GET/POST /fields`、`POST /import`、`GET /versions`、`GET /contacts`、`POST /versions/create-from-latest`、`GET /export`
- 鉴权：除项目管理端点外，其余端点经 `get_project_auth` 依赖从 `X-Project-Id` / `X-Project-Password` 请求头校验项目与密码（SHA-256 比对）；密码错误返回 401
- 数据模型：`projects` → `contact_versions`（一次导入 = 一个版本）→ `contact_entities`（以姓名为 `entity_key`，按项目隔离）→ `contact_version_deltas`（按版本记录变更，`is_deleted` 逻辑删除）。查询用 `ROW_NUMBER()` 窗口函数回溯继承最近一次变更，实现「任一时点快照」
- 字段：每个项目有独立 `fields` 表，`UNIQUE(project_id, name)`；新建项目自动写入 8 个默认字段（`init_project_default_fields`）
- 删除保护：`DELETE /projects/{id}` 要求 `exported_at` 非空（必须先导出备份）否则 403
- 数据库位置：`database.py` 的 `DB_PATH`（相对 `backend/data/contact_manager.db`），模块导入时即执行 `init_db()`

## 迁移与坑（务必注意）

- `init_db()` 是**幂等迁移**，负责建表、补列、按需重建表结构
- **不要**用「建表 SQL 字符串包含某子串」来判断结构是否需要迁移。历史 bug：早期迁移用 `ALTER TABLE ... RENAME TO _xxx_old` 重建表，SQLite 会自动改写其它表外键里的目标表名；旧代码随后 `DROP` 掉 `_xxx_old`，就留下指向已删表的**悬空外键**，而字符串判断始终匹配成功，导致永远不修复。连接默认 `PRAGMA foreign_keys = ON`，写入时报 `no such table: main._versions_old`（表现为导入接口 500）
- 正确做法：用 `PRAGMA foreign_key_list(<表>)` 读取外键的**实际目标表**并与期望结构比对；重建期间设置 `PRAGMA legacy_alter_table = ON` 阻止 RENAME 再次改写其它表的外键；用 `_mig_<表名>` 作临时表名并清理历史 `_*_old` 残留表
- 清理孤立数据时，必须**先删**孤立 `contact_versions` / `contact_entities`，**再删** `contact_version_deltas`；顺序反了会漏删

## 约定

- 注释与错误提示用中文；错误经 `HTTPException(status_code=..., detail=中文提示)` 返回，前端直接展示 detail
- 前端该视图直接使用 `axios` 调用（非 `api/index.js` 封装），并通过 `getAuthHeaders()` 附带项目凭据
- 只修改职责范围内的文件；确需改动范围外文件时，先说明再动手

## 验证

```powershell
cd backend; python -m pytest tests/test_contact_manager.py -v
```

前端改动用 `cd frontend; npm run dev`（/api 代理到 8000）人工验证，不要改后端代码来测试前端。
