"""多 docx 深度合并（doc-compile）。

- 由空白基础文档开始，按队列顺序逐篇追加：
    篇前分页（可选）→ Heading1 标题 → 作者段 → 源 docx body 元素深拷贝。
- 源文档中的插图（a:blip r:embed）经 get_or_add_image 导入目标包并重映射
  rId，保证图片随合并保留（按内容去重）。
- 支持封面页、Word 目录域（field 模式）与静态自定义目录。
- 页眉页脚与源节属性（sectPr）不跨篇复制（文档已注明该限制）。
"""

from __future__ import annotations

import copy
import io
import re
from typing import Dict, List, Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from . import toc as toc_mod
from .models import CompileOptions, CompileItem, StyleSheet


# ---------------------------------------------------------------------------
# 基础文档与样式
# ---------------------------------------------------------------------------

def _set_run_font(run, name: str, size_pt: Optional[int] = None, bold: Optional[bool] = None):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    if size_pt:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold


def new_base_document(stylesheet: StyleSheet = None) -> Document:
    stylesheet = stylesheet or StyleSheet()
    doc = Document()
    # 正文默认字体（中文排版常用宋体）
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(12)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "宋体")
    return doc


def add_compiled_heading(doc: Document, text: str, stylesheet: StyleSheet,
                         level: int = 1) -> None:
    """添加带样式的汇编标题（Heading 级别，供目录域抓取）。"""
    para = doc.add_heading("", level=level)
    run = para.add_run(text)
    _set_run_font(run, stylesheet.title_font, stylesheet.title_size_pt, bold=True)
    return para


def add_author_line(doc: Document, author: str, stylesheet: StyleSheet) -> None:
    if not author:
        return
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(author)
    _set_run_font(run, stylesheet.author_font, stylesheet.author_size_pt)


# ---------------------------------------------------------------------------
# 可视化元素
# ---------------------------------------------------------------------------

def add_page_break(doc: Document) -> None:
    para = doc.add_paragraph()
    run = para.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def add_cover(doc: Document, title: str, subtitle: str = "", date: str = "") -> None:
    for _ in range(6):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(title or "汇编文档")
    _set_run_font(r, "黑体", 26, bold=True)
    if subtitle:
        s = doc.add_paragraph()
        s.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rs = s.add_run(subtitle)
        _set_run_font(rs, "宋体", 14)
    if date:
        d = doc.add_paragraph()
        d.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rd = d.add_run(date)
        _set_run_font(rd, "宋体", 12)
    for _ in range(4):
        doc.add_paragraph()
    add_page_break(doc)


def add_toc_field(doc: Document) -> None:
    r"""插入 Word 目录域（TOC \o "1-3" \h \z \u），并要求打开时更新域。"""
    para = doc.add_paragraph()
    run1 = para.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run1._r.append(fld_begin)

    run2 = para.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r' TOC \o "1-3" \h \z \u '
    run2._r.append(instr)

    run3 = para.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run3._r.append(fld_sep)

    run4 = para.add_run("目录（打开文档后提示更新域，或在 Word/WPS 中右键「更新域」生成）")
    _set_run_font(run4, "宋体", 10)

    run5 = para.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run5._r.append(fld_end)

    _enable_update_fields(doc)


def _enable_update_fields(doc: Document) -> None:
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        settings.append(uf)


def add_toc_heading(doc: Document) -> None:
    """目录标题（非 Heading 样式，避免目录域自引用）。"""
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run("目  录")
    _set_run_font(run, "黑体", 18, bold=True)


# ---------------------------------------------------------------------------
# 正文合并（含图片关系重映射）
# ---------------------------------------------------------------------------

def _import_images(element, src_doc: Document, dst_doc: Document, warnings: List[str]) -> None:
    """把源文档内的图片（a:blip r:embed）导入目标文档并重映射 rId。"""
    src_part = src_doc.part
    for blip in element.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        rel = src_part.rels.get(rid)
        if rel is None:
            continue
        try:
            blob = rel.target_part.blob
        except Exception:
            continue
        try:
            new_rid, _ = dst_doc.part.get_or_add_image(io.BytesIO(blob))
        except Exception:
            warnings.append("部分图片未能导入（格式不支持或文件损坏）")
            continue
        blip.set(qn("r:embed"), new_rid)


def merge_body(doc: Document, src_doc: Document, warnings: List[str],
               skip_texts: Optional[List[str]] = None,
               strong_skip: bool = False) -> int:
    """把源 docx 的 body 内容（段落/表格/区块）深拷贝进目标文档。

    skip_texts：源文档「前缀」中与这些文本精确匹配的段落会被跳过（去掉源文档
    自带的标题/作者段，避免与汇编插入的标题作者重复）。
    strong_skip：当原文头部确有标题结构（服务端已识别出真实标题）时开启，
    前缀消费还会按「标题段→作者段」启发式判据跳过与配置值不一致的原文标题/
    作者段（例如用户修改了标题，原文首段仍是旧标题）。
    两者都只在「前缀位置」生效：遇到第一个不像标题/作者的段落即停止消费，
    后续内容原样进入正文。返回拷贝的元素数量；源节属性与页眉页脚不拷贝。
    """
    skip_set = {_norm(t) for t in (skip_texts or []) if t and _norm(t)}
    count = 0
    consumed = 0  # 已消费的前缀标题/作者段数（最多 2 段：标题+作者）
    active = bool(skip_set) or strong_skip
    src_body = src_doc.element.body
    for child in list(src_body):
        if child.tag == qn("w:sectPr"):
            continue
        if child.tag == qn("w:p") and active and consumed < 2:
            text = _para_text(child)
            norm = _norm(text)
            is_meta = bool(norm) and norm in skip_set
            if not is_meta and strong_skip:
                if consumed == 0:
                    is_meta = _looks_like_title(child, text)
                else:
                    is_meta = _looks_like_author(text)
            if is_meta:
                consumed += 1
                continue
            active = False  # 第一个不像标题/作者的段 → 停止前缀消费
        new_el = copy.deepcopy(child)
        _import_images(new_el, src_doc, doc, warnings)
        doc.element.body.append(new_el)
        count += 1
    return count


# 标题/作者启发式判据（strong_skip 用）
_TITLE_STYLE_HINTS = ("heading", "title", "标题", "题注")
_SENTENCE_PUNCT_RE = re.compile(r"[。！？；，、：]")


def _p_style_name(el) -> str:
    ppr = el.find(qn("w:pPr"))
    if ppr is None:
        return ""
    pstyle = ppr.find(qn("w:pStyle"))
    if pstyle is None:
        return ""
    return (pstyle.get(qn("w:val")) or "").lower()


def _looks_like_title(el, text: str) -> bool:
    """疑似原文标题段：标题样式，或短小且不含句读。"""
    style = _p_style_name(el)
    if any(h in style for h in _TITLE_STYLE_HINTS):
        return True
    text = text or ""
    return 0 < len(text) <= 40 and not _SENTENCE_PUNCT_RE.search(text)


def _looks_like_author(text: str) -> bool:
    """疑似作者段：极短、不含句读（人名/单位名常见形态）。"""
    text = text or ""
    return 0 < len(text) <= 12 and not _SENTENCE_PUNCT_RE.search(text)


def _para_text(el) -> str:
    """提取段落内 w:t 文本（标准做法，避免 lxml tail/text 传播干扰）。"""
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _norm(text: str) -> str:
    import re as _re
    return _re.sub(r"\s+", "", text or "")


# ---------------------------------------------------------------------------
# 汇编主构建
# ---------------------------------------------------------------------------

def build_compiled_docx(items: List[Dict], options: CompileOptions,
                        toc_pages: Optional[Dict[int, Optional[int]]] = None,
                        markers: Optional[List[str]] = None) -> Document:
    """按顺序构建汇编文档。

    items: [{"title", "author", "docx_bytes"}]
    toc_pages: {序号(1-based): 页码}，custom 目录含页码时传入
    markers: 每篇标题内插入的定位标记（用于页码反查，最终文档不含）
    """
    stylesheet = options.stylesheet
    doc = new_base_document(stylesheet)

    # ---- 封面 ----
    if options.cover.enabled:
        add_cover(doc, options.cover.title, options.cover.subtitle, options.cover.date)

    # ---- 目录 ----
    toc_entries = 0
    if options.toc.enabled:
        add_toc_heading(doc)
        if options.toc.mode == "field":
            add_toc_field(doc)
        else:
            entries = []
            for i, item in enumerate(items, start=1):
                entries.append({
                    "seq": i,
                    "title": item["title"],
                    "author": item["author"],
                    "page": (toc_pages or {}).get(i),
                })
            toc_mod.build_custom_toc(doc, entries, options.toc.template)
            toc_entries = len(entries)
        add_page_break(doc)

    # ---- 各篇正文 ----
    for i, item in enumerate(items, start=1):
        title = item["title"] or f"未命名文档 {i}"
        if i > 1 or options.cover.enabled or options.toc.enabled:
            p = add_compiled_heading(doc, title, stylesheet)
            p.paragraph_format.page_break_before = True
        else:
            add_compiled_heading(doc, title, stylesheet)
        # 定位标记（仅页码反查用，最终输出不含）
        if markers and i - 1 < len(markers) and markers[i - 1]:
            mp = doc.add_paragraph()
            mr = mp.add_run(markers[i - 1])
            _set_run_font(mr, "宋体", 6)
        add_author_line(doc, item["author"], stylesheet)
        warnings: List[str] = []
        src = Document(io.BytesIO(item["docx_bytes"]))
        merge_body(doc, src, warnings, skip_texts=item.get("skip_texts"),
                   strong_skip=bool(item.get("strong_skip")))
    return doc


def save_docx(doc: Document) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()