"""标题 / 作者识别（doc-compile）。

规则（全部可在前端编辑覆盖）：
- 默认：第 1 个非空段落 = 标题，第 2 个非空段落 = 作者。
- 若首段疑似日期/机构/摘要等元信息，窗口下移。
- 作者启发式：剥离「作者：/撰稿：/著：/撰文：」等前缀；超长或含大量句读
  视为正文，作者置空并给出警告。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# 疑似元信息首行：日期、页码、机构抬头等
_META_LINE_RE = re.compile(
    r"^(第\s*\d+\s*[页篇]|"
    r"\d{4}\s*年|"
    r"出版日期|发布日期|"
    r"摘要[:：]|关键词[:：]|"
    r"(所在)?(单位|机构|学院|学校|部门|公司)[:：]|"
    r"文件编号|编号[:：]|"
    r"^\s*[-—–•·*#]+)"
)
_AUTHOR_PREFIX_RE = re.compile(
    r"^(作者|撰稿|撰写|著|撰文|执笔|文)\s*[:：]\s*|^文[/／]\s*|^(拟稿|拟文)\s*[:：]\s*"
)
_STRONG_SENTENCE_RE = re.compile(r"[。！？；，]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def clean_line(text: str) -> str:
    text = _HTML_TAG_RE.sub("", text or "")
    return text.strip().strip("\u3000\"'“”‘’·-—– ")


def first_nonempty_paragraphs(doc) -> List[str]:
    """取文档前若干非空段落文本（顺序）。"""
    out: List[str] = []
    for para in doc.paragraphs:
        line = clean_line(para.text)
        if not line:
            continue
        out.append(line)
        if len(out) >= 12:
            break
    return out


def detect_title_author(lines: List[str], filename: str = "") -> Tuple[str, str, bool, List[str]]:
    """自动识别标题与作者。

    返回 (title, author, auto_detected, warnings)。
    """
    warnings: List[str] = []
    texts = [clean_line(ln) for ln in lines]
    texts = [ln for ln in texts if ln]

    # 标题：跳过元信息行
    title_idx = 0
    while title_idx < len(texts):
        line = texts[title_idx]
        if _META_LINE_RE.match(line) or len(line) > 60:
            title_idx += 1
            continue
        break
    title = texts[title_idx] if title_idx < len(texts) else ""

    # 作者：紧随标题的下一个非空段
    author = ""
    idx = title_idx + 1
    if idx < len(texts):
        candidate = texts[idx]
        m = _AUTHOR_PREFIX_RE.match(candidate)
        if m:
            candidate = candidate[m.end():].strip()
        candidate = _HTML_TAG_RE.sub("", candidate).strip()
        # 作者启发式约束
        if not candidate:
            author = ""
        elif len(candidate) > 40 or len(_STRONG_SENTENCE_RE.findall(candidate)) >= 2:
            author = ""
            warnings.append("未识别作者：第二行疑似正文，请在列表中手动填写")
        else:
            author = candidate

    auto_detected = bool(title or author)
    if not title:
        warnings.append("未识别标题，汇编时将使用文件名")
    if filename and not title:
        title = path_safe(filename)
    return title, author, auto_detected, warnings


def path_safe(filename: str) -> str:
    """取文件名（去掉扩展名）作为标题回退。"""
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for ext in (".docx", ".docm", ".doc", ".wps", ".rtf", ".txt"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.strip() or "未命名"