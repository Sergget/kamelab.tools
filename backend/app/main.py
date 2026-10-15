"""Lab Tools 入口：FastAPI 提供 API，并托管前端构建产物。"""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config, temp_files
from .tools import enabled_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    temp_files.start_cleanup()
    yield
    temp_files.stop_cleanup()


app = FastAPI(title="Lab Tools", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 工具 id -> 路由模块（相对 app 包的模块路径）。新增工具时在此登记；工具包本身在
# backend/app/tools/<name>/，并需在 tools/__init__.py 的 TOOLS 中登记元信息。
_TOOL_ROUTER_MODULES = {
    "excel-split": "tools.excel_split.router",
    "doc-convert": "tools.doc_convert.router",
    "excel-diff": "tools.excel_diff.router",
    "contact-manager": "tools.contact_manager.router",
    "doc-compile": "tools.doc_compile.router",
}

# 实际挂载成功的工具 id 集合，用于 /api/tools 只对外通告真正可用的工具
_mounted_tools: set[str] = set()


def _mount_tool_routers() -> None:
    """按 ENABLED_TOOLS 挂载工具路由（惰性导入 + 容错）。

    某个工具包缺失、或依赖不全导致导入失败时，只记录警告并跳过该工具，
    不影响其它工具与整个服务的启动。这样在仓库中登记了工具元信息、
    但工具包尚未实现（或依赖未安装）时，服务仍可正常启动。
    """
    for tool_id, module_suffix in _TOOL_ROUTER_MODULES.items():
        if config.ENABLED_TOOLS is not None and tool_id not in config.ENABLED_TOOLS:
            continue
        module_path = f"{__package__}.{module_suffix}"
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001 - 任何导入失败都不应阻断启动
            logger.warning(
                "跳过工具 %s：导入 %s 失败（%s: %s）",
                tool_id, module_path, type(exc).__name__, exc,
            )
            continue
        app.include_router(module.router)
        _mounted_tools.add(tool_id)


_mount_tool_routers()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    """返回可用工具列表（只包含实际挂载成功的工具）。"""
    return enabled_tools(mounted=_mounted_tools)


if config.STATIC_DIR.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        target = config.STATIC_DIR / full_path if full_path else config.STATIC_DIR / "index.html"
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(config.STATIC_DIR / "index.html")
