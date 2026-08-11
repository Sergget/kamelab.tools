"""Lab Tools 入口：FastAPI 提供 API，并托管前端构建产物。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config, temp_files
from .tools import TOOLS
from .tools.excel_split.router import router as excel_split_router


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

app.include_router(excel_split_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    return TOOLS


if config.STATIC_DIR.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        target = config.STATIC_DIR / full_path if full_path else config.STATIC_DIR / "index.html"
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(config.STATIC_DIR / "index.html")