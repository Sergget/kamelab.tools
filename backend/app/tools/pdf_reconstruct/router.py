"""PDF 高保真转 Word API 路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ... import config, temp_files
from . import service
from .models import DOCX_MIME, ReconstructResponse

router = APIRouter(prefix="/api/tools/pdf-reconstruct", tags=["pdf-reconstruct"])


def _read_upload_chunks(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while chunk := file.file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过大小限制 {max_bytes // (1024 * 1024)}MB",
            )
    return bytes(content)


@router.post("/convert", response_model=ReconstructResponse)
def convert_pdf(file: UploadFile = File(...)):
    """上传 PDF，返回高保真转换后的 Word 产物与下载凭据。"""
    original_name = file.filename or "未命名.pdf"
    ext = Path(original_name).suffix.lower()
    if ext != service.PDF_EXTENSION:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 PDF 文件，收到 {ext or '无扩展名'}",
        )

    content = _read_upload_chunks(file, config.RECONSTRUCT_MAX_MB * 1024 * 1024)
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        result = service.convert_pdf_to_docx(
            content,
            original_name,
            max_pages=config.RECONSTRUCT_MAX_PAGES or None,
        )
    except service.ReconstructError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    job_id = temp_files.new_id()
    manifest = {
        "download_name": result["download_name"],
        "mime_type": DOCX_MIME,
        "original_name": original_name,
        "output_format": "docx",
        "engine": service.ENGINE_NAME,
        "pdf_type": result["pdf_type"],
    }
    temp_files.save_job(
        job_id, {result["download_name"]: result["content"]}, None, manifest
    )

    return ReconstructResponse(
        success=True,
        job_id=job_id,
        filename=original_name,
        download_name=result["download_name"],
        pdf_type=result["pdf_type"],
        chars=result["chars"],
        elapsed_ms=result["elapsed_ms"],
        engine=service.ENGINE_NAME,
        kernel_version=service.kernel_version(),
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
        media_type=manifest.get("mime_type", DOCX_MIME),
    )


@router.get("/health")
async def health():
    """内核可用性探活：没装内核时前端可提前给出提示。"""
    available = service.kernel_available()
    return {
        "status": "UP" if available else "DOWN",
        "node": config.NODE_NAME,
        "role": config.NODE_ROLE,
        "engine": service.ENGINE_NAME,
        "kernel_version": service.kernel_version(),
        "max_file_size_mb": config.RECONSTRUCT_MAX_MB,
        "max_pages": config.RECONSTRUCT_MAX_PAGES or None,
        "detail": "" if available else "kame-officetools 未安装，本工具不可用",
    }
