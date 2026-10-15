"""文档汇编 API 路由（doc-compile）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from ... import config, temp_files
from . import service
from .models import CompileRequest, MetaUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools/doc-compile", tags=["doc-compile"])

_MISSING = "上传文件不存在或已过期"


def _get_file_id_or_404(file_id: str) -> str:
    if not temp_files.get_work_dir(file_id):
        raise HTTPException(status_code=404, detail=_MISSING)
    return file_id


def _read_upload_chunks(file: UploadFile) -> bytes:
    content = bytearray()
    max_bytes = config.COMPILE_MAX_MB * 1024 * 1024
    while chunk := file.file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过大小限制 {config.COMPILE_MAX_MB}MB",
            )
    return bytes(content)


@router.post("/upload")
def upload_files(files: List[UploadFile] = File(...)):
    """批量上传：逐文件分类→转 docx→识别标题作者；失败项收集到 dropped。"""
    items: List[dict] = []
    dropped: List[dict] = []
    for f in files:
        original_name = f.filename or "未命名"
        try:
            content = _read_upload_chunks(f)
        except HTTPException as exc:
            dropped.append({"original_name": original_name, "reason": exc.detail})
            continue
        item, reason = service.process_upload(content, original_name)
        if item is not None:
            items.append(item)
        else:
            dropped.append({"original_name": original_name, "reason": reason or "处理失败"})
    return {"items": items, "dropped": dropped}


@router.get("/files/{file_id}/info")
def file_info(file_id: str):
    """条目详情（含惰性计算的页数）。"""
    _get_file_id_or_404(file_id)
    item = service.load_item(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail=_MISSING)
    item["page_count"] = service.get_page_count(file_id)
    return item


@router.get("/files/{file_id}/preview-text")
def preview_text(file_id: str):
    """纯文本预览（任何环境可用）。"""
    _get_file_id_or_404(file_id)
    return {"text": service.get_preview_text(file_id)}


@router.get("/files/{file_id}/preview")
def preview_image(file_id: str, page: int = 1):
    """首页/指定页 PNG 预览（需 LibreOffice + poppler）。"""
    _get_file_id_or_404(file_id)
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须 ≥ 1")
    png = service.render_preview_png(file_id, page)
    if png is None:
        if service.get_page_count(file_id) is None:
            raise HTTPException(
                status_code=503,
                detail="预览渲染不可用：服务器缺少 LibreOffice（soffice）或 poppler，"
                       "可用下方纯文本预览",
            )
        raise HTTPException(status_code=400, detail=f"第 {page} 页渲染失败（可能超出页数）")
    return Response(content=png, media_type="image/png")


@router.put("/files/{file_id}/meta")
def update_file_meta(file_id: str, req: MetaUpdate):
    """修改标题/作者；apply_to_source=true 时写回源文档。"""
    _get_file_id_or_404(file_id)
    item = service.update_meta(file_id, req.title, req.author, req.apply_to_source)
    if item is None:
        raise HTTPException(status_code=404, detail=_MISSING)
    return item


@router.get("/files/{file_id}/source-download")
def source_download(file_id: str):
    """下载（已写回的）源文档。"""
    _get_file_id_or_404(file_id)
    meta = temp_files.read_work_json(file_id, "meta.json")
    ext = meta.get("ext", ".docx") if meta else ".docx"
    if meta and meta.get("source_updated"):
        path = temp_files.get_work_dir(file_id) / f"updated{ext}"
    else:
        path = temp_files.get_work_dir(file_id) / f"original{ext}"
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="源文档不存在或已过期")
    return FileResponse(
        str(path),
        filename=meta.get("original_name", Path(path).name),
        media_type="application/octet-stream",
    )


@router.post("/compile")
def compile_documents(req: CompileRequest):
    """按队列顺序汇编为单个 Word 文档。"""
    if not req.items:
        raise HTTPException(status_code=400, detail="请先在队列中添加文档")
    try:
        result = service.compile_documents(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/download/{job_id}")
def download(job_id: str):
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
def supported_formats():
    """能力声明：输入/输出格式、转换器可用性与功能开关。"""
    return service.supported_formats()


@router.get("/health")
def health():
    return service.health()