"""Excel 拆分核心逻辑。"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .models import SplitRequest

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t\0]+')
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

EMPTY_KEY_LABEL = "空值"
MAX_FILENAME_LEN = 100
MAX_SHEET_TITLE_LEN = 31


class ExcelSplitError(ValueError):
    pass


def load_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    ext = path.suffix.lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    try:
        sheets = pd.read_excel(path, sheet_name=None, engine=engine)
    except ValueError as exc:
        if "no sheet" in str(exc).lower() or "empty" in str(exc).lower():
            return {"Sheet1": pd.DataFrame()}
        raise ExcelSplitError(f"无法解析 Excel 文件: {exc}") from exc
    except Exception as exc:  # 文件损坏、格式不支持等
        raise ExcelSplitError(f"无法解析 Excel 文件: {exc}") from exc
    result: Dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        df = df.dropna(how="all")
        result[str(name)] = df
    return result


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (pd.Timedelta,)):
        return str(value)
    return value


def preview_sheet(df: pd.DataFrame, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
    total = len(df)
    skip = max(0, skip)
    limit = min(max(1, limit), 200)
    part = df.iloc[skip: skip + limit]
    headers = [str(c) for c in df.columns]
    rows = [[_normalize_cell(v) for v in row.tolist()] for _, row in part.iterrows()]
    return {"headers": headers, "rows": rows, "total": total, "skip": skip, "limit": limit}


def _value_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _split_column_values(df: pd.DataFrame, column: str) -> List[str]:
    if column not in df.columns:
        raise ExcelSplitError(f"拆分列不存在: {column}")
    return [_value_key(v) for v in df[column].tolist()]


def sanitize_filename_part(text: str, fallback: str = "未命名") -> str:
    text = str(text).strip()
    text = INVALID_FILENAME_CHARS.sub("_", text)
    text = text.strip(" .")
    if not text or text.lower() in WINDOWS_RESERVED:
        return fallback
    return text[:MAX_FILENAME_LEN]


def render_template(template: str, *, value: str, sheet: str, index: int,
                    now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    safe_value = sanitize_filename_part(value, fallback=EMPTY_KEY_LABEL)
    mapping = {
        "{value}": safe_value,
        "{sheet}": sanitize_filename_part(sheet, fallback="Sheet"),
        "{index}": f"{index:03d}",
        "{date}": now.strftime("%Y%m%d"),
        "{time}": now.strftime("%H%M%S"),
    }
    result = template
    for key, val in mapping.items():
        result = result.replace(key, val)
    result = sanitize_filename_part(result, fallback=safe_value)
    return result or safe_value


def _validate_options(df: pd.DataFrame, req: SplitRequest) -> List[str]:
    if req.split_column not in df.columns:
        raise ExcelSplitError(f"拆分列不存在: {req.split_column}")
    keep = req.keep_columns
    if keep:
        keep = [c for c in keep if c in df.columns]
        if not keep:
            raise ExcelSplitError("保留列列表为空或全部不存在")
    return keep or [str(c) for c in df.columns]


def _group_dataframe(df: pd.DataFrame, split_column: str) -> List[Tuple[str, pd.DataFrame]]:
    keys = _split_column_values(df, split_column)
    df = df.copy()
    df["__kame_split_key__"] = keys
    groups: List[Tuple[str, pd.DataFrame]] = []
    for key, group in df.groupby("__kame_split_key__", sort=False):
        groups.append((str(key), group.drop(columns=["__kame_split_key__"])))
    return groups


def _dataframe_to_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    return buffer.getvalue()


def _build_workbook(groups: List[Tuple[str, pd.DataFrame]], req: SplitRequest,
                    now: datetime) -> bytes:
    buffer = io.BytesIO()
    used_titles = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for index, (key, group) in enumerate(groups, start=1):
            value = key or EMPTY_KEY_LABEL
            template = req.sheet_title_template or "{value}"
            title = render_template(template, value=value, sheet="", index=index, now=now)
            title = title[:MAX_SHEET_TITLE_LEN]
            if not title:
                title = value[:MAX_SHEET_TITLE_LEN] or "Sheet"
            base = title
            counter = 2
            while title in used_titles:
                title = f"{base[:MAX_SHEET_TITLE_LEN - 3]}_{counter}"
                counter += 1
            used_titles.add(title)
            group.to_excel(writer, index=False, sheet_name=title)
    return buffer.getvalue()


def _collect_sheet_groups(df: pd.DataFrame, req: SplitRequest, sheet_name: str
                          ) -> Tuple[List[Tuple[str, pd.DataFrame]], List[str]]:
    """按 sheet 收集分组，返回 (分组列表, 保留列)。sheet 无拆分列时分组为空。"""
    header = list(df.columns)
    if not header or req.split_column not in header:
        return [], []
    keep = _validate_options(df, req)
    groups = _group_dataframe(df, req.split_column)
    return [(key, group[keep]) for key, group in groups], keep


def _unique_helper(base: str, used: set, max_len: int) -> str:
    if base not in used:
        used.add(base)
        return base
    prefix = base[: max_len - 3]
    counter = 2
    while True:
        candidate = f"{prefix}_{counter}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def split_workbook(sheets: Dict[str, pd.DataFrame], req: SplitRequest,
                   original_stem: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """拆分完整工作簿，生成产物并返回 manifest 与文件内容。

    separate: 每个 (sheet, 值) 生成一个 xlsx 文件，多个文件打包为 zip；
    workbook: 跨 sheet 按值合并，输出一个多 sheet 工作簿。
    """
    now = now or datetime.now()
    if not sheets:
        raise ExcelSplitError("文件中没有可用的数据")
    if req.output_mode not in ("separate", "workbook"):
        raise ExcelSplitError(f"不支持的输出模式: {req.output_mode}")

    per_sheet_groups: List[Tuple[str, str, pd.DataFrame]] = []
    for sheet_name, df in sheets.items():
        groups, _ = _collect_sheet_groups(df, req, sheet_name)
        per_sheet_groups.extend((sheet_name, key, group) for key, group in groups)

    if not per_sheet_groups:
        raise ExcelSplitError("没有任何可拆分的行（请确认拆分列在各 sheet 中存在）")

    groups_result = []
    files = {}
    total_rows = 0

    if req.output_mode == "workbook":
        merged: Dict[str, pd.DataFrame] = {}
        order: List[str] = []
        for _, key, group in per_sheet_groups:
            if key not in merged:
                merged[key] = group
                order.append(key)
            else:
                merged[key] = pd.concat([merged[key], group], ignore_index=True)
        workbook_groups = [(key, merged[key]) for key in order]
        content = _build_workbook(workbook_groups, req, now)
        download_name = f"{sanitize_filename_part(original_stem)}_拆分.xlsx"
        files[download_name] = content
        for key, group in workbook_groups:
            groups_result.append(
                {"key": key or EMPTY_KEY_LABEL, "file_name": "", "sheet_name": "", "rows": len(group)}
            )
            total_rows += len(group)
        is_zip = False
        zip_bytes = None
    else:
        used_names = set()
        for sheet_name, key, group in per_sheet_groups:
            value = key or EMPTY_KEY_LABEL
            index = sum(1 for r in groups_result) + 1
            file_stem = render_template(req.filename_template, value=value,
                                        sheet=sheet_name, index=index, now=now)
            file_name = _unique_helper(file_stem, used_names, MAX_FILENAME_LEN) + ".xlsx"
            files[file_name] = _dataframe_to_bytes(group)
            groups_result.append(
                {"key": value, "file_name": file_name, "sheet_name": sheet_name, "rows": len(group)}
            )
            total_rows += len(group)
        if len(files) == 1:
            download_name = next(iter(files))
            is_zip = False
            zip_bytes = None
        else:
            download_name = f"{sanitize_filename_part(original_stem)}_拆分.zip"
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, content in files.items():
                    zf.writestr(name, content)
            zip_bytes = zip_buffer.getvalue()
            is_zip = True

    manifest = {
        "download_name": download_name,
        "is_zip": is_zip,
        "mode": req.output_mode,
        "groups": groups_result,
        "total_rows": total_rows,
    }
    return {"manifest": manifest, "files": files, "zip_bytes": zip_bytes}