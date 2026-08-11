from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ... import config, temp_files
from . import service
from .models import (GroupResult, SheetInfo, SplitRequest, SplitResponse,
                     UploadResponse)

router = APIRouter(prefix="/api/tools/excel-split", tags=["excel-split"])
_open_workbooks: dict = {}  # file_id -> {sheets, file_name}


def _get_workbook(file_id: str):
    meta = _open_workbooks.get(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文件不存在或已过期，请重新上传")
    return meta


def _read_upload_chunks(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while chunk := file.file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件超过大小限制 {max_bytes // (1024 * 1024)}MB")
    return bytes(content)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    original_name = file.filename or "未命名"
    ext = Path(original_name).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型 {ext or '(无扩展名)'}，仅支持 .xlsx / .xls")

    content = _read_upload_chunks(file, config.MAX_UPLOAD_MB * 1024 * 1024)
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    file_id = temp_files.new_id()
    path = temp_files.save_upload(file_id, ext, content, original_name)

    try:
        sheets = service.load_sheets(path)
    except service.ExcelSplitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _open_workbooks[file_id] = {"sheets": sheets, "file_name": original_name}
    sheet_info = [
        SheetInfo(
            name=name,
            rows=len(df),
            cols=0 if df.empty else len(df.columns),
            headers=[str(c) for c in df.columns],
        )
        for name, df in sheets.items()
    ]
    return UploadResponse(file_id=file_id, file_name=original_name, sheets=sheet_info)


@router.get("/{file_id}/sheets")
async def list_sheets(file_id: str):
    meta = _get_workbook(file_id)
    return [
        {
            "name": name,
            "rows": len(df),
            "cols": 0 if df.empty else len(df.columns),
            "headers": [str(c) for c in df.columns],
        }
        for name, df in meta["sheets"].items()
    ]


@router.get("/{file_id}/preview")
async def preview(file_id: str, sheet: str = "", skip: int = 0, limit: int = 100):
    meta = _get_workbook(file_id)
    if not sheet:
        sheet = next(iter(meta["sheets"]), None)
    if not sheet or sheet not in meta["sheets"]:
        raise HTTPException(status_code=404, detail="sheet 不存在")
    return service.preview_sheet(meta["sheets"][sheet], skip=skip, limit=limit)


@router.post("/{file_id}/split", response_model=SplitResponse)
async def split_file(file_id: str, req: SplitRequest):
    meta = _get_workbook(file_id)
    try:
        result = service.split_workbook(
            meta["sheets"], req, Path(meta["file_name"]).stem
        )
    except service.ExcelSplitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = temp_files.new_id()
    manifest = result["manifest"]
    temp_files.save_job(job_id, result["files"], result["zip_bytes"], manifest)

    return SplitResponse(
        job_id=job_id,
        mode=manifest["mode"],
        download_name=manifest["download_name"],
        is_zip=manifest["is_zip"],
        groups=[GroupResult(**g) for g in manifest["groups"]],
        total_rows=manifest["total_rows"],
    )


@router.get("/download/{job_id}")
async def download(job_id: str):
    manifest = temp_files.get_job(job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="产物不存在或已过期")
    file_path = Path(manifest["dir"]) / manifest["download_name"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="产物不存在或已过期")
    return FileResponse(
        file_path,
        filename=manifest["download_name"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if manifest["download_name"].endswith(".xlsx")
        else "application/zip",
    )