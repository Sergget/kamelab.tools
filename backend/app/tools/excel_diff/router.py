from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ... import config, temp_files
from ..excel_split.models import SheetInfo, UploadResponse
from ..excel_split.service import ExcelSplitError
from . import service
from .models import CompareRequest, CompareResponse, CompareStats, DiffRow

# 复用 excel_split 解析时可能抛 ExcelSplitError，一并转为 400
_BUSINESS_ERRORS = (service.ExcelDiffError, ExcelSplitError)

router = APIRouter(prefix="/api/tools/excel-diff", tags=["excel-diff"])
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
    except _BUSINESS_ERRORS as exc:
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


@router.post("/compare", response_model=CompareResponse)
async def compare(req: CompareRequest):
    base_meta = _get_workbook(req.base_file_id)
    compare_meta = _get_workbook(req.compare_file_id)

    base_path = temp_files.get_upload(req.base_file_id)
    compare_path = temp_files.get_upload(req.compare_file_id)
    if base_path is None or compare_path is None:
        raise HTTPException(status_code=404, detail="上传文件已过期，请重新上传")

    try:
        result = service.run_compare(
            base_path,
            compare_path,
            base_meta["file_name"],
            compare_meta["file_name"],
            req,
        )
    except _BUSINESS_ERRORS as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = temp_files.new_id()
    manifest = {
        "download_name": result["download_name"],
        "output_mode": result["output_mode"],
        "stats": result["stats"],
        "skipped_columns": result["skipped_columns"],
    }
    temp_files.save_job(job_id, {result["download_name"]: result["bytes"]}, None, manifest)

    return CompareResponse(
        job_id=job_id,
        download_name=result["download_name"],
        output_mode=result["output_mode"],
        stats=CompareStats(**result["stats"]),
        skipped_columns=result["skipped_columns"],
        preview=[DiffRow(**d) for d in result["preview"]],
        preview_total=result["preview_total"],
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
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
