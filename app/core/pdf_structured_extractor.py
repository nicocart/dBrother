import math
import re
import unicodedata
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pdfplumber  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pdfplumber = None


@dataclass
class NldftData:
    average_pore_diameter: float
    pore_integral_volume: float


@dataclass
class ProcessResult:
    success: bool
    error_message: str = ""
    sp_bet: str = ""
    mp_bet: str = ""
    total_pore_vol: str = ""
    avg_pore_d: str = ""
    most_probable: str = ""
    raw_text: str = ""
    nldft_data: List[NldftData] = field(default_factory=list)
    d10_int: float = 0.0
    d10: float = 0.0
    d90_int: float = 0.0
    d90: float = 0.0
    d90_d10_ratio: float = 0.0
    pore_volume_A: float = 0.0
    d0_5: float = 0.0
    volume_0_5D: float = 0.0
    less_than_0_5D: float = 0.0
    d1_5: float = 0.0
    volume_1_5D: float = 0.0
    greater_than_1_5D: float = 0.0


@dataclass
class ExtractedTable:
    page_index: int
    table_index: int
    bbox: Tuple[float, float, float, float]
    rows: List[List[str]]


NUM_RE = re.compile(r"[+-]?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")
SPACE_RE = re.compile(r"\s+")

# 目标标签（中文优先，英文作为回退）
SURFACE_LABELS: Dict[str, Sequence[str]] = {
    "sp_bet": ("单点BET比表面积", "single point surface area"),
    "mp_bet": ("多点BET比表面积", "bet surface area"),
}

PORE_VOLUME_LABELS: Dict[str, Sequence[str]] = {
    "total_pore_vol": ("最高单点吸附总孔体积", "single point adsorption total pore volume"),
}

PORE_SIZE_LABELS: Dict[str, Sequence[str]] = {
    "avg_pore_d": ("单点总孔吸附平均孔直径", "total adsorption average pore width"),
}

MISC_LABELS: Dict[str, Sequence[str]] = {
    "most_probable": ("最可几孔径", "modal pore width", "mode pore width"),
}

def _lower_label_map(label_map: Dict[str, Sequence[str]]) -> Dict[str, Tuple[str, ...]]:
    return {key: tuple(label.lower() for label in labels if label) for key, labels in label_map.items()}


SURFACE_LABELS_LOWER = _lower_label_map(SURFACE_LABELS)
PORE_VOLUME_LABELS_LOWER = _lower_label_map(PORE_VOLUME_LABELS)
PORE_SIZE_LABELS_LOWER = _lower_label_map(PORE_SIZE_LABELS)
MISC_LABELS_LOWER = _lower_label_map(MISC_LABELS)

SECTION_LABELS = {
    "surface area": SURFACE_LABELS_LOWER,
    "pore volume": PORE_VOLUME_LABELS_LOWER,
    "pore size": PORE_SIZE_LABELS_LOWER,
}
SECTION_KEYWORDS = tuple(SECTION_LABELS.keys())

_PREFILTER_SOURCES = (SURFACE_LABELS, PORE_VOLUME_LABELS, PORE_SIZE_LABELS, MISC_LABELS)
_prefilter_keywords = {"surface area", "pore volume", "pore size", "bet", "nldft", "p/p0"}
for _label_map in _PREFILTER_SOURCES:
    for _labels in _label_map.values():
        for _label in _labels:
            if _label:
                _prefilter_keywords.add(_label)
PREFILTER_KEYWORDS = tuple(_prefilter_keywords)
PREFILTER_KEYWORDS_LOWER = tuple(keyword.lower() for keyword in PREFILTER_KEYWORDS if keyword)
PREFILTER_KEYWORDS_COMPACT = tuple(
    SPACE_RE.sub("", keyword) for keyword in PREFILTER_KEYWORDS_LOWER if keyword
)

TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

NLDFT_AVG_KEYWORDS = (
    "平均孔直径",
    "平均孔径",
    "average pore diameter",
    "average pore width",
    "avg pore diameter",
)
NLDFT_INTEGRAL_KEYWORDS = (
    "孔积分体积",
    "pore integral volume",
    "integral pore volume",
)
NLDFT_AVG_KEYWORDS_CLEAN = tuple(SPACE_RE.sub("", keyword.lower()) for keyword in NLDFT_AVG_KEYWORDS)
NLDFT_INTEGRAL_KEYWORDS_CLEAN = tuple(SPACE_RE.sub("", keyword.lower()) for keyword in NLDFT_INTEGRAL_KEYWORDS)

AVG_DECIMAL_PATTERN = re.compile(r"^[+-]?\d+\.\d{4}$")


@lru_cache(maxsize=4096)
def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    if value.isascii():
        return value.replace("\u0000", "").strip()
    text = unicodedata.normalize("NFKC", value)
    return text.replace("\u0000", "").strip()


def normalize_cell(cell: Optional[str]) -> str:
    return normalize_text(cell).replace("\r\n", "\n").replace("\r", "\n")


def label_variants_lower(cell: Optional[str]) -> Iterable[str]:
    text = normalize_cell(cell)
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = [text.strip()]
    for line in lines:
        if not line:
            continue
        yield line.lower()


def label_match_score(cell: Optional[str], targets_lower: Sequence[str]) -> int:
    if not cell:
        return 0
    best = 0
    for variant_lower in label_variants_lower(cell):
        for target in targets_lower:
            if not target:
                continue
            if variant_lower == target:
                return 3
            if variant_lower.endswith(target):
                best = max(best, 2)
            elif target in variant_lower:
                best = max(best, 1)
    return best


def label_matches(cell: Optional[str], targets_lower: Sequence[str]) -> bool:
    for variant_lower in label_variants_lower(cell):
        for target in targets_lower:
            if not target:
                continue
            if target in variant_lower:
                return True
    return False


@lru_cache(maxsize=8192)
def extract_number(value: Optional[str]) -> Optional[str]:
    text = normalize_cell(value)
    if not text:
        return None
    if not any(ch.isdigit() for ch in text):
        return None
    match = NUM_RE.search(text.replace(",", ""))
    if not match:
        return None
    return match.group(0)


def _page_has_keywords(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for keyword in PREFILTER_KEYWORDS_LOWER:
        if keyword and keyword in lowered:
            return True
    compact = SPACE_RE.sub("", lowered)
    for keyword in PREFILTER_KEYWORDS_COMPACT:
        if keyword and keyword in compact:
            return True
    return False


def _extract_tables_from_page(page, page_index: int) -> List[ExtractedTable]:
    try:
        table_objs = page.find_tables(TABLE_SETTINGS)
    except Exception:
        table_objs = page.find_tables()
    if not table_objs:
        return []
    tables: List[ExtractedTable] = []
    for table_index, table in enumerate(table_objs):
        data = table.extract()
        normalized_rows: List[List[str]] = [
            [normalize_cell(cell) for cell in row] for row in data if any(cell for cell in row)
        ]
        if not normalized_rows:
            continue
        tables.append(
            ExtractedTable(
                page_index=page_index,
                table_index=table_index,
                bbox=table.bbox,
                rows=normalized_rows,
            )
        )
    return tables


def collect_tables(
    pdf_path: str,
    prefilter: bool = True,
    collect_text: bool = True,
) -> Tuple[List[ExtractedTable], str]:
    if pdfplumber is None:
        raise RuntimeError("缺少 pdfplumber 依赖，请先安装后再使用结构化解析通道")
    tables: List[ExtractedTable] = []
    segments: List[str] = []
    if prefilter and not collect_text:
        prefilter = False
    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        for page_index, page in enumerate(pages):
            text = (page.extract_text() or "") if collect_text else ""
            if collect_text:
                segments.append(text)
            if not prefilter or _page_has_keywords(text):
                tables.extend(_extract_tables_from_page(page, page_index))
    return tables, "\n".join(segments)


def extract_summary_metrics(tables: Sequence[ExtractedTable]) -> Dict[str, str]:
    metrics: Dict[str, str] = {}
    for table in tables:
        joined_header = " ".join(" ".join(row) for row in table.rows[:2]).lower()
        if not any(keyword in joined_header for keyword in SECTION_KEYWORDS):
            continue

        current_section: Optional[str] = None
        for row in table.rows:
            row_joined = " ".join(row).lower()
            for section_name in SECTION_KEYWORDS:
                if section_name in row_joined:
                    current_section = section_name
                    break
            if current_section is None:
                continue
            # 只在存在数值列时尝试解析
            target_labels = SECTION_LABELS[current_section]
            for key, candidates in target_labels.items():
                if key in metrics:
                    continue
                for cell in row:
                    if label_matches(cell, candidates):
                        # 尝试读取同一行的其他单元格中的数值
                        for value_cell in row[::-1]:
                            value = extract_number(value_cell)
                            if value is not None:
                                metrics[key] = value
                                break
                        break
        # 当三个子表都解析到后即可提前结束
        if all(k in metrics for k in ("sp_bet", "mp_bet", "total_pore_vol", "avg_pore_d")):
            break
    return metrics


def extract_value_by_label(tables: Sequence[ExtractedTable], key: str) -> Optional[str]:
    candidates = MISC_LABELS_LOWER.get(key)
    if not candidates:
        return None
    best_key: Tuple[int, int, int] = (0, -1, -1)
    best_value: Optional[str] = None
    for table in tables:
        for row in table.rows:
            for col_index, cell in enumerate(row):
                score = label_match_score(cell, candidates)
                if score <= 0:
                    continue
                # 查找同一行的其他单元格
                for next_index in range(col_index + 1, len(row)):
                    value = extract_number(row[next_index])
                    if value is not None:
                        key = (score, table.page_index, -table.table_index)
                        if key > best_key:
                            best_key = key
                            best_value = value
                        break
    return best_value


def extract_nldft_data(tables: Sequence[ExtractedTable]) -> List[NldftData]:
    def contains_keywords(text: str, keywords: Sequence[str]) -> bool:
        cleaned = SPACE_RE.sub("", text.lower())
        for keyword in keywords:
            if keyword in cleaned:
                return True
        return False

    def is_data_row(row: Sequence[str]) -> bool:
        numeric_hits = 0
        first_is_number = False
        for idx, cell in enumerate(row):
            token = extract_number(cell)
            if token:
                numeric_hits += 1
                if idx == 0:
                    first_is_number = True
        return numeric_hits >= 2 and first_is_number

    aggregated_rows: List[NldftData] = []

    for table in tables:
        rows = table.rows
        if not rows:
            continue

        preview_text = " ".join(" ".join(row) for row in rows[:3]).lower()
        if "nldft" not in preview_text and "p/p0" not in preview_text:
            continue

        data_start_idx: Optional[int] = None
        for idx, row in enumerate(rows):
            if is_data_row(row):
                data_start_idx = idx
                break
        if data_start_idx is None:
            continue

        header_rows = rows[:data_start_idx] or rows[:1]
        max_cols = max(len(row) for row in rows)
        column_headers: Dict[int, str] = {}
        for col in range(max_cols):
            parts: List[str] = []
            for header_row in header_rows:
                if col < len(header_row):
                    cell = normalize_cell(header_row[col])
                    if cell:
                        parts.append(cell)
            column_headers[col] = " ".join(parts)

        avg_col: Optional[int] = None
        integral_col: Optional[int] = None
        for col, text in column_headers.items():
            if not text:
                continue
            if avg_col is None and contains_keywords(text, NLDFT_AVG_KEYWORDS_CLEAN):
                avg_col = col
            if integral_col is None and contains_keywords(text, NLDFT_INTEGRAL_KEYWORDS_CLEAN):
                integral_col = col

        if avg_col is None or integral_col is None:
            continue

        for row in rows[data_start_idx:]:
            if avg_col >= len(row) or integral_col >= len(row):
                continue
            avg_str = extract_number(row[avg_col])
            integral_str = extract_number(row[integral_col])
            if not avg_str or not integral_str:
                continue
            avg_clean = avg_str.replace(",", "")
            if not AVG_DECIMAL_PATTERN.fullmatch(avg_clean):
                continue
            try:
                avg_val = float(avg_clean)
                if abs(avg_val) < 1e-12:
                    continue
                integral_val = round(float(integral_str), 6)
            except ValueError:
                continue
            aggregated_rows.append(
                NldftData(
                    average_pore_diameter=avg_val,
                    pore_integral_volume=integral_val,
                )
            )

    if not aggregated_rows:
        return []

    # 检查平均孔径是否严格升序，若出现降序则认定解析异常
    prev = aggregated_rows[0].average_pore_diameter
    for idx, item in enumerate(aggregated_rows[1:], start=2):
        if item.average_pore_diameter < prev - 1e-8:
            raise ValueError(
                f"NLDFT平均孔径序列出现降序（第{idx}条 {item.average_pore_diameter:.4f} < 前一条 {prev:.4f}），请检查表格解析结果"
            )
        prev = item.average_pore_diameter

    aggregated_rows.sort(key=lambda r: (r.pore_integral_volume, r.average_pore_diameter))
    return aggregated_rows


def interpolate_diameter(target_volume: float, data: List[NldftData]) -> float:
    if not data:
        return 0.0
    lower: Optional[NldftData] = None
    for row in data:
        if math.isclose(row.pore_integral_volume, target_volume, rel_tol=1e-12, abs_tol=1e-15):
            return row.average_pore_diameter
        if row.pore_integral_volume < target_volume:
            lower = row
        elif row.pore_integral_volume > target_volume:
            if lower is None:
                return row.average_pore_diameter
            dx = row.pore_integral_volume - lower.pore_integral_volume
            if dx == 0:
                return lower.average_pore_diameter
            k = (row.average_pore_diameter - lower.average_pore_diameter) / dx
            b = lower.average_pore_diameter - k * lower.pore_integral_volume
            return k * target_volume + b
    return data[-1].average_pore_diameter


def interpolate_volume(target_diameter: float, data: List[NldftData]) -> float:
    if not data:
        return 0.0
    lower: Optional[NldftData] = None
    for row in data:
        if math.isclose(row.average_pore_diameter, target_diameter, rel_tol=1e-12, abs_tol=1e-15):
            return row.pore_integral_volume
        if row.average_pore_diameter < target_diameter:
            lower = row
        elif row.average_pore_diameter > target_diameter:
            if lower is None:
                return row.pore_integral_volume
            dx = row.average_pore_diameter - lower.average_pore_diameter
            if dx == 0:
                return lower.pore_integral_volume
            k = (row.pore_integral_volume - lower.pore_integral_volume) / dx
            b = lower.pore_integral_volume - k * lower.average_pore_diameter
            return k * target_diameter + b
    return data[-1].pore_integral_volume


def extract_raw_text(pdf_path: str) -> str:
    segments: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            segments.append(text)
    return "\n".join(segments)


def process_pdf_structured(pdf_path: str) -> ProcessResult:
    try:
        tables, raw_text = collect_tables(pdf_path, prefilter=True, collect_text=True)
    except Exception as exc:  # pragma: no cover - pdf解析异常直接报错
        return ProcessResult(success=False, error_message=f"结构化解析失败：{exc}")

    summary = extract_summary_metrics(tables)
    most_probable = extract_value_by_label(tables, "most_probable") or ""
    nldft_error = False
    try:
        nldft_data = extract_nldft_data(tables)
    except ValueError:
        nldft_error = True
        nldft_data = []

    if not tables or not nldft_data or not summary.get("total_pore_vol") or nldft_error:
        try:
            fallback_tables, _ = collect_tables(pdf_path, prefilter=False, collect_text=False)
        except Exception as exc:  # pragma: no cover - pdf解析异常直接报错
            return ProcessResult(success=False, error_message=f"结构化解析失败：{exc}")
        if fallback_tables:
            tables = fallback_tables
            summary = extract_summary_metrics(tables)
            most_probable = extract_value_by_label(tables, "most_probable") or ""
            nldft_data = extract_nldft_data(tables)

    if not tables:
        return ProcessResult(success=False, error_message="未检测到任何表格结构")

    if not nldft_data:
        return ProcessResult(success=False, error_message="未提取到NLDFT详细数据")

    total_pore_vol_str = summary.get("total_pore_vol")
    if not total_pore_vol_str:
        return ProcessResult(success=False, error_message="缺少最高单点吸附总孔体积，无法计算分位体积")

    try:
        total_pore_vol = float(total_pore_vol_str)
    except ValueError:
        return ProcessResult(success=False, error_message="最高单点吸附总孔体积解析失败")

    d10_int = total_pore_vol * 0.1
    d90_int = total_pore_vol * 0.9
    d10 = interpolate_diameter(d10_int, nldft_data)
    d90 = interpolate_diameter(d90_int, nldft_data)
    d90_d10_ratio = (d90 / d10) if d10 else 0.0

    pore_volume_A = max((row.pore_integral_volume for row in nldft_data), default=0.0)

    d0_5 = d1_5 = volume_0_5D = volume_1_5D = less_than_0_5D = greater_than_1_5D = 0.0
    if most_probable:
        try:
            modal = float(most_probable)
            d0_5 = modal * 0.5
            d1_5 = modal * 1.5
            volume_0_5D = interpolate_volume(d0_5, nldft_data)
            volume_1_5D = interpolate_volume(d1_5, nldft_data)
            if pore_volume_A > 1e-12:
                less_than_0_5D = (volume_0_5D / pore_volume_A) * 100.0
                greater_than_1_5D = ((pore_volume_A - volume_1_5D) / pore_volume_A) * 100.0
        except ValueError:
            pass

    return ProcessResult(
        success=True,
        sp_bet=summary.get("sp_bet", ""),
        mp_bet=summary.get("mp_bet", ""),
        total_pore_vol=total_pore_vol_str,
        avg_pore_d=summary.get("avg_pore_d", ""),
        most_probable=most_probable,
        raw_text=raw_text,
        nldft_data=nldft_data,
        d10_int=d10_int,
        d10=d10,
        d90_int=d90_int,
        d90=d90,
        d90_d10_ratio=d90_d10_ratio,
        pore_volume_A=pore_volume_A,
        d0_5=d0_5,
        volume_0_5D=volume_0_5D,
        less_than_0_5D=less_than_0_5D,
        d1_5=d1_5,
        volume_1_5D=volume_1_5D,
        greater_than_1_5D=greater_than_1_5D,
    )
