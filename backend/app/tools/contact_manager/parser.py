import re
from datetime import date, datetime
from typing import Optional
import openpyxl

# =============================================================================
# 值清理
# =============================================================================
# 需要移除的无意义字符：各类空白（含全角空格、不换行空格）、零宽字符、BOM。
# 通讯录多为中文录入，空白几乎都是无意义的排版噪声，因此统一移除（而非压缩为单空格），
# 这样「甲 单位」与「甲单位」、「1968 年 10 月」与「1968年10月」都能得到一致结果。
_NOISE_RE = re.compile(
    r"[\s\u00a0\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)


def clean_value(value) -> str:
    """清理单元格文本：移除空白/换行/零宽字符，并去掉首尾空白。

    None 返回空串；数值先转成字符串（避免 float 尾随 .0 等干扰）。
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # 1234.0 -> "1234"，避免把纯整数写成带小数点的形式
        text = str(int(value))
    else:
        text = str(value)
    return _NOISE_RE.sub("", text).strip()


# =============================================================================
# 出生年月格式化
# =============================================================================
# 需按「年-月」规范化的字段（按字段 label 判断）
_BIRTH_LABEL_KEYWORDS = ("出生", "生日", "出生年月", "出生日期")

# 形如 1968-10 / 1968/10 / 1968.10 / 1968年10月 / 196810 / 1968.10.01
_DATE_PATTERNS = (
    # 年 + 分隔符 + 月 (+ 日)
    re.compile(r"^(?P<y>(?:19|20)\d{2})\s*[-/.年]\s*(?P<m>\d{1,2})\s*(?:[-/.月]\s*(?P<d>\d{1,2})\s*日?)?$"),
    # 纯 6 位数字 YYYYMM
    re.compile(r"^(?P<y>(?:19|20)\d{2})(?P<m>\d{2})$"),
    # 中文年月，如 1968年10月
    re.compile(r"^(?P<y>(?:19|20)\d{2})\s*年\s*(?P<m>\d{1,2})\s*月?$"),
)


def is_birth_field(name: str = "", label: str = "") -> bool:
    """判断该字段是否应作为出生年月处理。"""
    text = f"{name or ''}{label or ''}"
    return any(kw in text for kw in _BIRTH_LABEL_KEYWORDS)


def _month_from_fraction(frac: str) -> Optional[int]:
    """把「点后面的数字」还原为月份。

    表格常把出生年月录成小数，Excel 会丢掉末尾的 0：
      - 两位（01-12）：直接就是月份（.01=1月、.11=11月）
      - 一位 d       ：只可能是「被截断的 10/11/12 月」——
                       .1 → 10 月（生产数据实测该列唯一出现的一位小数写法）
                       若将来出现 .2/.3，按同理理解为 20/30 月（不合法）故不采纳
    因此一位小数时仅 1 能映射为 10 月，其余无法确定月份，返回 None 由调用方保留原值。
    """
    if not frac:
        return None
    if len(frac) >= 2:
        mm = int(frac[:2])
        return mm if 1 <= mm <= 12 else None
    return 10 if frac == "1" else None


def format_birth_month(value) -> str:
    """把出生年月规范化为 'YYYY-MM'；无法识别时返回清理后的原值。

    支持的输入：
      - datetime / date 对象（openpyxl 对日期格式单元格会直接返回）
      - '1968-10' / '1968/10' / '1968年10月' / '1968.10.01' / '196810'
      - 小数/文本 1968.1（=1968年10月）、1968.01（=1968年1月）

    关于「点号 + 一位数字」：表格里常用小数录入出生年月，Excel 会把 1968.10 存成
    1968.1（末尾的 0 丢失），而 1 月会特意写成 1968.01。因此点号后只有一位数字时，
    按「被截断的两位月份」还原（1→10、2→11、3→12）；写全两位时按字面月份理解。
    """
    if value is None:
        return ""

    # 1) 原生日期类型
    if isinstance(value, (datetime, date)):
        return f"{value.year:04d}-{value.month:02d}"

    raw = clean_value(value)
    if not raw:
        return ""

    # 2) 「点号 + 仅一个月」：需优先于通用模式处理，否则 1968.1 会被当成 1 月。
    #    仅限单个点号且点后只有 1~2 位数字，避免误伤 1968.1.5 这类含日的写法。
    m = re.match(r"^(?P<y>(?:19|20)\d{2})[.．](?P<frac>[0-9]{1,2})$", raw)
    if m:
        y = int(m.group("y"))
        frac = m.group("frac")
        if len(frac) == 2:
            mo = int(frac)
            if 1 <= mo <= 12:
                return f"{y:04d}-{mo:02d}"
        else:
            mo = _month_from_fraction(frac)
            if mo:
                return f"{y:04d}-{mo:02d}"

    # 3) 字符串模式（含 年/月/日、连字符、斜杠等）
    for pattern in _DATE_PATTERNS:
        m = pattern.match(raw)
        if m:
            y = int(m.group("y"))
            mo = int(m.group("m"))
            if 1 <= mo <= 12:
                return f"{y:04d}-{mo:02d}"

    # 4) 纯 8 位 YYYYMMDD
    m = re.match(r"^(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})$", raw)
    if m:
        mo = int(m.group("m"))
        if 1 <= mo <= 12:
            return f"{int(m.group('y')):04d}-{mo:02d}"

    # 5) 只有年份等无法确定月份的情况：保留原值
    return raw


def format_field_value(name: str, label: str, value) -> str:
    """按字段类型规范化单个取值（目前仅出生年月需要特殊处理）。"""
    if is_birth_field(name, label):
        return format_birth_month(value)
    return clean_value(value)

def extract_date_from_filename(filename: str) -> str:
    """
    从文件名中提取日期，支持格式如: 20231001, 2023-10-01, 2023_10_01, 2023.10.01 等。
    若无匹配则返回今天日期。
    """
    # 匹配 8 位数字如 20231001 或带有分隔符的日期
    patterns = [
        r'(20\d{2})[._-]?(0[1-9]|1[0-2])[._-]?(0[1-9]|[12]\d|3[01])',
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            year, month, day = match.groups()
            try:
                dt = datetime(int(year), int(month), int(day))
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
    return datetime.now().strftime('%Y-%m-%d')

def get_excel_sheets(file_path: str):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    return wb.sheetnames

def read_excel_preview(file_path: str, sheet_name: str, max_rows: int = 15):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    if sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    rows = []
    for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if r_idx > max_rows:
            break
        # 转为列表并处理 None 为空字符串
        row_vals = [str(cell) if cell is not None else "" for cell in row]
        # 去除全空行
        if any(row_vals):
            rows.append({"row_index": r_idx, "values": row_vals})
    return rows

FIELD_KEYWORDS = {
    "name": ["姓名", "名字", "人员姓名", "姓名："],
    "title": ["职务", "职称", "岗位", "职务/职称", "职级"],
    "unit": ["单位", "部门", "工作单位", "单位名称", "所属单位", "公司", "机构"],
    "gender": ["性别", "男/女", "性　别"],
    "phone": ["电话", "固定电话", "办公电话", "宅电", "座机", "联系电话"],
    "mobile": ["手机", "手机号", "移动电话", "手机号码", "联系手机"],
    "email": ["邮箱", "电子邮箱", "Email", "E-mail"],
    "office": ["办公地址", "地址", "地点", "办公地点", "房间号"],
}

# 模糊匹配时，命中词至少要覆盖单元格文本的这个比例，否则视为不相关。
# 例：「单位」在「某单位通讯录」中只占 1/3，不应把标题行误判为单位列；
# 而「单位」在「工作单位」中占 1/2，可以匹配。
_CONTAINMENT_MIN_RATIO = 0.5


def _term_matches_cell(term: str, cell: str) -> bool:
    """判断某个字段关键词/label 是否与该单元格文本匹配。

    完全相等 → 匹配；否则要求「包含」关系且命中词足够长，
    避免长句（如标题「某单位通讯录」）因含「单位」二字被误判。
    """
    term = (term or "").strip()
    cell = (cell or "").strip()
    if not term or not cell:
        return False
    if term == cell:
        return True
    if term in cell:
        return len(term) >= max(2, len(cell) * _CONTAINMENT_MIN_RATIO)
    if cell in term:
        return len(cell) >= max(2, len(term) * _CONTAINMENT_MIN_RATIO)
    return False


def match_row_fields(values, existing_fields):
    """对一行的各列做字段匹配，返回 (mapping, score)。

    匹配优先级：
      1. 当前项目已有字段的显示名完全相同（命中得 2 分）
      2. 内置特征关键词（命中得 2 分，但仅在该字段确实存在于当前项目时生效）
      3. 与已有字段显示名模糊匹配（命中得 1 分）
    mapping 形如 {col_index: field_name}

    注意：只有「当前项目确实存在的字段名」才会被写入 mapping。
    未匹配到的列不返回字段名，由前端决定是新建字段还是忽略，
    避免产生指向不存在字段的映射（那会导致数据写入后不可见）。
    """
    known_names = {ef["name"] for ef in existing_fields}
    score = 0
    mapping = {}
    for col_idx, val in enumerate(values):
        val_clean = (val or "").strip()
        if not val_clean:
            continue

        matched_field = None

        # 1) 与已有字段显示名完全相同 —— 最可靠
        for ef in existing_fields:
            if ef["label"].strip() == val_clean:
                matched_field = ef["name"]
                score += 2
                break

        # 2) 内置特征关键词（要求该字段在当前项目中存在）
        if not matched_field:
            for field_name, kw_list in FIELD_KEYWORDS.items():
                if field_name in known_names and any(
                    _term_matches_cell(kw, val_clean) for kw in kw_list
                ):
                    matched_field = field_name
                    score += 2
                    break

        # 3) 与已有字段显示名模糊匹配
        if not matched_field:
            for ef in existing_fields:
                if _term_matches_cell(ef["label"], val_clean):
                    matched_field = ef["name"]
                    score += 1
                    break

        if matched_field:
            mapping[col_idx] = matched_field

    return mapping, score


def detect_header_and_map(rows, existing_fields):
    """
    遍历前几行，根据特征词（姓名、职务、单位、性别、电话、手机等）计算得分，
    识别最可能的标题行，并自动与已有数据库字段进行匹配。
    """
    best_row_idx = 1
    max_score = -1
    best_mapping = {}

    for row_obj in rows[:10]:
        mapping, score = match_row_fields(row_obj["values"], existing_fields)
        if score > max_score:
            max_score = score
            best_row_idx = row_obj["row_index"]
            best_mapping = mapping

    return {
        "detected_header_row": best_row_idx,
        "mapping": best_mapping
    }


def map_fields_for_header_row(rows, header_row, existing_fields):
    """对用户指定的表头行做字段匹配（用于手动切换表头行后重新自动匹配）。"""
    for row_obj in rows:
        if row_obj["row_index"] == header_row:
            mapping, _score = match_row_fields(row_obj["values"], existing_fields)
            return mapping
    return {}

def parse_sheet_data(file_path: str, sheet_name: str, header_row: int, mapping: dict,
                     field_labels: dict = None):
    """根据确定的表头行和字段映射，解析整张 sheet 的数据。

    mapping 格式: {col_index: field_name}
    field_labels: {field_name: label}，用于判断字段是否需要特殊格式化（如出生年月）

    解析时统一清理无意义符号（空白/换行/零宽字符），并按字段类型规范化取值。
    返回 (contacts, row_numbers)：row_numbers 与 contacts 一一对应，记录来源 Excel 行号。
    """
    field_labels = field_labels or {}
    wb = openpyxl.load_workbook(file_path, data_only=True)
    if sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    contacts = []
    row_numbers = []
    header_found = False

    for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if r_idx < header_row:
            continue
        if r_idx == header_row:
            header_found = True
            continue

        if not header_found:
            continue

        if not any(c is not None and str(c).strip() for c in row):
            continue  # 跳过空行

        contact_data = {}
        has_content = False
        for col_idx, field_name in mapping.items():
            if col_idx < len(row):
                val = format_field_value(
                    field_name, field_labels.get(field_name, ""), row[col_idx])
                contact_data[field_name] = val
                if val:
                    has_content = True

        if has_content:
            contacts.append(contact_data)
            row_numbers.append(r_idx)

    return contacts, row_numbers


# =============================================================================
# 同名记录处理
# =============================================================================

def find_duplicate_names(contacts, name_field: str = "name"):
    """找出同一份表中重复出现的姓名。

    返回 [{"name": 姓名, "count": 条数, "rows": [行号...], "records": [记录...]}, ...]
    仅统计姓名非空的记录。
    """
    groups = {}
    for rec in contacts:
        key = clean_value(rec.get(name_field, ""))
        if not key:
            continue
        groups.setdefault(key, []).append(rec)

    dupes = []
    for key, records in groups.items():
        if len(records) > 1:
            dupes.append({
                "name": key,
                "count": len(records),
                "records": records,
            })
    # 重复条数多的排前面，便于用户优先处理
    dupes.sort(key=lambda d: -d["count"])
    return dupes


def merge_records(records, multi_value_sep: str = "、"):
    """把同名多条记录合并为一条：逐字段合并。

    - 只有一个非空值 → 取该值
    - 多个**不同**的非空值 → 用分隔符拼接（如「甲单位、乙单位」）
    - None/空值忽略
    返回 (merged, conflicts)：conflicts 记录发生拼接的字段及取值，供前端提示。
    """
    merged = {}
    conflicts = {}
    for rec in records:
        for key, val in rec.items():
            text = clean_value(val)
            if not text:
                continue
            if key not in merged or not merged[key]:
                merged[key] = text
                continue
            if merged[key] == text:
                continue
            # 已有值且不同 → 拼接（避免重复追加同一个值）
            parts = merged[key].split(multi_value_sep)
            if text not in parts:
                merged[key] = f"{merged[key]}{multi_value_sep}{text}"
                conflicts.setdefault(key, list(parts))
                if text not in conflicts[key]:
                    conflicts[key].append(text)
    return merged, conflicts
