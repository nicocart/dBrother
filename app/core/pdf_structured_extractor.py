import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pdfplumber  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pdfplumber = None

from app.core.pdf_processor_v2 import (
    NldftData,
    ProcessResult,
    interpolate_diameter,
    interpolate_volume,
)


@dataclass
class ExtractedTable:
    page_index: int
    table_index: int
    bbox: Tuple[float, float, float, float]
    rows: List[List[str]]


NUM_RE = re.compile(r"[+-]?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")

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


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    return text.replace("\u0000", "").strip()


def normalize_cell(cell: Optional[str]) -> str:
    return normalize_text(cell).replace("\r\n", "\n").replace("\r", "\n")


def label_variants(cell: Optional[str]) -> Iterable[str]:
    text = normalize_cell(cell)
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = [text.strip()]
    for line in lines:
        if not line:
            continue
        yield line
        yield line.lower()


def label_match_score(cell: Optional[str], targets: Sequence[str]) -> int:
    if not cell:
        return 0
    lowered_targets = [t.lower() for t in targets]
    best = 0
    for variant in label_variants(cell):
        v_lower = variant.lower()
        for target in lowered_targets:
            if not target:
                continue
            if v_lower == target:
                return 3
            if v_lower.endswith(target):
                best = max(best, 2)
            elif target in v_lower:
                best = max(best, 1)
    return best


def label_matches(cell: Optional[str], targets: Sequence[str]) -> bool:
    lowered_targets = [t.lower() for t in targets]
    for variant in label_variants(cell):
        v_lower = variant.lower()
        for target in lowered_targets:
            if target in v_lower:
                return True
    return False


def extract_number(value: Optional[str]) -> Optional[str]:
    text = normalize_cell(value)
    if not text:
        return None
    match = NUM_RE.search(text.replace(",", ""))
    if not match:
        return None
    return match.group(0)


def collect_tables(pdf_path: str) -> List[ExtractedTable]:
    if pdfplumber is None:
        raise RuntimeError("缺少 pdfplumber 依赖，请先安装后再使用结构化解析通道")
    tables: List[ExtractedTable] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            try:
                table_objs = page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            except Exception:
                table_objs = page.find_tables()
            if not table_objs:
                continue
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


def extract_summary_metrics(tables: Sequence[ExtractedTable]) -> Dict[str, str]:
    metrics: Dict[str, str] = {}
    sections = {
        "surface area": SURFACE_LABELS,
        "pore volume": PORE_VOLUME_LABELS,
        "pore size": PORE_SIZE_LABELS,
    }

    for table in tables:
        joined_header = " ".join(" ".join(row) for row in table.rows[:2]).lower()
        if not any(keyword in joined_header for keyword in sections):
            continue

        current_section: Optional[str] = None
        for row in table.rows:
            row_joined = " ".join(row).lower()
            for section_name in sections:
                if section_name in row_joined:
                    current_section = section_name
                    break
            if current_section is None:
                continue
            # 只在存在数值列时尝试解析
            target_labels = sections[current_section]
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
    candidates = MISC_LABELS.get(key)
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
    nldft_rows: List[NldftData] = []
    for table in tables:
        if not table.rows:
            continue
        header = [cell.lower() for cell in table.rows[0]]
        header_joined = " ".join(header)
        if "p/p0" not in header_joined:
            continue
        if "平均" not in header_joined and "average" not in header_joined:
            continue
        for row in table.rows[1:]:
            if len(row) < 5:
                continue
            avg = extract_number(row[2])
            integral = extract_number(row[4])
            if avg is None or integral is None:
                continue
            try:
                avg_val = float(avg)
                integral_val = float(integral)
            except ValueError:
                continue
            nldft_rows.append(NldftData(average_pore_diameter=avg_val, pore_integral_volume=integral_val))
    nldft_rows.sort(key=lambda r: r.pore_integral_volume)
    return nldft_rows


def extract_raw_text(pdf_path: str) -> str:
    segments: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            segments.append(text)
    return "\n".join(segments)


def process_pdf_structured(pdf_path: str) -> ProcessResult:
    try:
        tables = collect_tables(pdf_path)
    except Exception as exc:  # pragma: no cover - pdf解析异常直接报错
        return ProcessResult(success=False, error_message=f"结构化解析失败：{exc}")

    if not tables:
        return ProcessResult(success=False, error_message="未检测到任何表格结构")

    summary = extract_summary_metrics(tables)
    most_probable = extract_value_by_label(tables, "most_probable") or ""
    nldft_data = extract_nldft_data(tables)

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

    raw_text = extract_raw_text(pdf_path)
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
