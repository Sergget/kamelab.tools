# Lab Tools — 开发协作指南

自托管的办公文件处理工具箱。FastAPI 后端（`backend/`）+ Vue 3 前端（`frontend/`），另有独立 OCR 节点（`ocr_server/`）与部署脚本（`deploy/`）。PDF 高保真转 Word 的转换逻辑在**外部内核包** `kame-officetools-core`（`../kame-officetools-core`），不在本仓库。

## 调度规则（主 agent 用）

本仓库按工具/领域拆分了专职 subagent（`.opencode/agent/`）。收到任务时：

1. 判断任务归属，用 Task 工具派发给对应 subagent（可并行派发互不依赖的任务）：
   - `excel-split` — Excel 表格拆分工具（后端 + 前端 + 测试）
   - `excel-diff` — Excel 表格比对工具（后端 + 前端 + 测试）
   - `contact-manager` — 通讯录归档与管理工具（后端 + 前端 + 测试）
   - `doc-convert` — 文档转换工具（后端 + 前端 + OCR 对接 + 测试）
   - `frontend` — 前端通用工作（视图 / 路由 / API 封装 / 构建）
   - `backend` — 后端基础设施（入口 / 配置 / 临时文件 / 工具注册 / 测试框架）
   - `ocr` — OCR 独立节点（ocr_server/）
   - `deploy` — 部署脚本与本地启动器
2. 跨领域任务按职责拆分派发，例如"新增某工具"= backend agent（注册+挂载）+ 对应工具 agent（实现）+ frontend agent（路由+页面），主 agent 负责对齐接口契约后汇总集成。
3. 集成验证（pytest、前端 build）由主 agent 最后统一执行。
4. 新增工具时，建议按同样模式新增一个专职工具 subagent（含后端包、前端视图、测试三项职责）。

## 结构速览

| 目录 | 说明 |
| --- | --- |
| `backend/app/main.py` | 入口：CORS、按 `ENABLED_TOOLS` 惰性挂载工具路由（单个工具导入失败只跳过该工具并告警，不影响整体启动）、SPA 静态托管 |
| `backend/app/config.py` | 全部 `LAB_TOOLS_*` 环境变量（OCR 相关同时兼容不带前缀的短名） |
| `backend/app/temp_files.py` | 上传/产物存储 + TTL 清理 |
| `backend/app/tools/` | 工具包：`excel_split/`、`excel_diff/`、`doc_convert/`、`doc_compile/`、`contact_manager/`、`pdf_reconstruct/`，注册表在 `__init__.py`（工具元信息登记后，工具包本身可稍后实现：未挂载的工具不会出现在 `/api/tools`） |
| `backend/tests/` | pytest，按工具 `test_<tool>.py` |
| `frontend/src/` | Vue 3 `<script setup>` + Element Plus；`api/index.js` 统一封装后端调用 |
| `ocr_server/` | 独立 OCR 节点（8001），被 doc-convert 经 HTTP 调用 |
| `deploy/` | Ubuntu/Windows 部署脚本 + systemd 单元 |
| `docs/` | 工具与依赖文档：`doc-convert.md`（文档转换）、`doc-compile.md`（文档汇编）、`contact-manager.md`（通讯录归档）、`pdf-reconstruct.md`（PDF 转 Word 与内核依赖）、`ocr-node.md`（OCR 节点依赖/部署），README 有导航链接 |

## 通用约定

- 注释、文档、错误提示用中文
- 后端错误：工具内业务异常 → router 转 `HTTPException`，detail 中文，前端直接展示
- 无登录鉴权，整体置于 ZeroTrust 之后；不要在代码中引入认证或暴露公网
- 新增环境变量须同步 README 表格
- 前端构建产物最终由后端托管于 `backend/app/static/`
- **前端没有类型检查器**：`package.json` 只有 `dev`/`build`/`preview`，没装 `vue-tsc`，`vite build` **不会**因模板里绑定了未定义的变量而失败。改视图时必须人工核对"模板用到的每个标识符都在 `<script setup>` 里定义过"，`build` 通过不等于页面能跑
- 工具的外部依赖缺失时应"降级可见"而不是"静默坏掉"：工具仍在注册表里，`/health` 报 `DOWN`，调用返回 503 并说明原因（参考 `pdf_reconstruct/service.py:kernel_available()`）
- 改动工具功能或依赖时，同步更新 `docs/` 下对应文档与 README

## 验证命令

```powershell
cd backend; python -m pytest -v      # 后端测试
cd frontend; npm run build           # 前端构建检查
```
