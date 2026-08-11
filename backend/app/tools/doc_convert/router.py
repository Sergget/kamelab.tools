"""文档转换 API 路由。"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ... import config, temp_files
from . import service
from .models import ConvertResponse, SUPPORTED_OUTPUT_FORMATS

router = APIRouter(prefix="/api/tools/doc-convert", tags=["doc-convert"])


def _read_upload_chunks(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while chunk := file.file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件超过大小限制 {max_bytes // (1024 * 1024)}MB")
    return bytes(content)


@router.post("/convert", response_model=ConvertResponse)
def convert_document(file: UploadFile = File(...),
                     output_format: str = Form("md"),
                     crop: str = Form("")):
    """统一转换入口：上传文档/图片，按扩展名自动路由，返回转换结果并可下载产物。"""
    original_name = file.filename or "未命名"
    ext = Path(original_name).suffix.lower()
    if not ext:
        raise HTTPException(status_code=400, detail="文件缺少扩展名，无法判断格式")
    if ext not in service.LOCAL_ONLY_EXTENSIONS | service.OCR_ONLY_EXTENSIONS | {service.PDF_EXTENSION}:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式 {ext}")

    content = _read_upload_chunks(file, config.CONVERT_MAX_MB * 1024 * 1024)
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    crop_region = None
    try:
        crop_region = service.parse_crop(crop)
    except service.DocConvertError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    try:
        result = service.convert_document(content, original_name, crop_region, output_format)
    except service.DocConvertError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    download_name = result["output_filename"]
    if result.get("file_base64"):
        output_bytes = base64.b64decode(result["file_base64"])
    else:
        output_bytes = (result.get("content") or "").encode("utf-8")

    job_id = temp_files.new_id()
    manifest = {
        "download_name": download_name,
        "mime_type": result["mime_type"],
        "original_name": original_name,
        "output_format": result.get("output_format"),
        "engine": result.get("engine"),
        "routed_to": result.get("routed_to"),
    }
    temp_files.save_job(job_id, {download_name: output_bytes}, None, manifest)

    return ConvertResponse(
        success=result["success"],
        job_id=job_id,
        filename=original_name,
        download_name=download_name,
        output_format=result.get("output_format", "md"),
        mime_type=result["mime_type"],
        content=result.get("content"),
        file_base64=result.get("file_base64"),
        engine=result.get("engine", ""),
        routed_to=result.get("routed_to", ""),
        pages=result.get("pages"),
        elapsed_ms=result.get("elapsed_ms", 0),
        file_size_mb=result.get("file_size_mb", 0.0),
        layout_reconstructed=result.get("layout_reconstructed", False),
        crop_applied=result.get("crop_applied", False),
        crop_ignored=result.get("crop_ignored"),
        docx_engine=result.get("docx_engine"),
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
        media_type=manifest.get("mime_type", "application/octet-stream"),
    )


@router.get("/supported-formats")
async def supported_formats():
    """能力声明：支持的格式、输出类型、OCR 节点配置。"""
    return {
        "local_formats": sorted(service.LOCAL_ONLY_EXTENSIONS),
        "ocr_formats": sorted(service.OCR_ONLY_EXTENSIONS),
        "pdf": True,
        "output_formats": list(SUPPORTED_OUTPUT_FORMATS),
        "max_file_size_mb": config.CONVERT_MAX_MB,
        "ocr_node": config.OCR_NODE_URL,
        "capabilities": {
            "crop": True,
            "layout_reconstruction": config.LAYOUT_RECONSTRUCTION_ENABLED,
            "docx_reference_template": bool(
                config.DOCX_REFERENCE_TEMPLATE
                and Path(config.DOCX_REFERENCE_TEMPLATE).is_file()
            ),
        },
    }


@router.get("/health")
async def health():
    """工具健康状态：任务指标 + OCR 节点探活。"""
    ocr_info = service.check_ocr_node()
    metrics = service.get_metrics()
    return {
        "status": "UP",
        "node": config.NODE_NAME,
        "role": config.NODE_ROLE,
        "ocr_node": config.OCR_NODE_URL,
        "ocr_node_name": config.OCR_NODE_NAME,
        "ocr_node_role": config.OCR_NODE_ROLE,
        "ocr_status": "UP" if ocr_info is not None else "DOWN",
        "active_tasks": metrics.pop("active_tasks"),
        "metrics": metrics,
    }