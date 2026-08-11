"""临时文件存储与过期清理。

所有用户上传与拆分产物都存放在 DATA_DIR 下，超时后由后台线程自动删除，
避免占用磁盘也不留用户数据。
"""

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from . import config


def _ensure_dirs() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def new_id() -> str:
    return uuid.uuid4().hex


def save_upload(file_id: str, ext: str, content: bytes, original_name: str) -> Path:
    _ensure_dirs()
    path = config.UPLOAD_DIR / (file_id + ext)
    path.write_bytes(content)
    meta_path = config.UPLOAD_DIR / (file_id + ".json")
    meta_path.write_text(
        json.dumps({"original_name": original_name}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def get_upload(file_id: str) -> Optional[Path]:
    for path in config.UPLOAD_DIR.glob(file_id + ".*"):
        if path.suffix.lower() in config.ALLOWED_EXTENSIONS:
            return path
    return None


def get_upload_meta(file_id: str) -> Dict[str, Any]:
    meta_path = config.UPLOAD_DIR / (file_id + ".json")
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_job(file_id: str, files: Dict[str, bytes], zip_bytes: Optional[bytes],
             manifest: Dict[str, Any]) -> Path:
    """把拆分产物写入 output 目录，并返回 job 目录。"""
    _ensure_dirs()
    job_dir = config.OUTPUT_DIR / file_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (job_dir / name).write_bytes(content)
    if zip_bytes is not None:
        (job_dir / manifest["download_name"]).write_bytes(zip_bytes)
    (job_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return job_dir


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    job_dir = config.OUTPUT_DIR / job_id
    manifest_path = job_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    manifest["dir"] = str(job_dir)
    return manifest


def _cleanup_dir(directory: Path, ttl_hours: float) -> None:
    now = time.time()
    ttl = ttl_hours * 3600
    if not directory.exists():
        return
    for entry in directory.iterdir():
        try:
            if now - entry.stat().st_mtime > ttl:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
        except OSError:
            pass


_cleanup_stop = threading.Event()
_cleanup_thread: Optional[threading.Thread] = None


def _cleanup_loop() -> None:
    while not _cleanup_stop.is_set():
        try:
            _cleanup_dir(config.UPLOAD_DIR, config.TEMP_TTL_HOURS)
            _cleanup_dir(config.OUTPUT_DIR, config.TEMP_TTL_HOURS)
        except Exception:
            pass
        _cleanup_stop.wait(300)


def start_cleanup() -> None:
    global _cleanup_thread
    if _cleanup_thread and _cleanup_thread.is_alive():
        return
    _cleanup_stop.clear()
    _cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
    _cleanup_thread.start()


def stop_cleanup() -> None:
    _cleanup_stop.set()