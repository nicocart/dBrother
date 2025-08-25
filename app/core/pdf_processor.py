import re
import math
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Dict, Callable

# 引入pdfminer.six
from pdfminer.high_level import extract_text as pdf_extract_text


@dataclass
class NldftData:
    average_pore_diameter: float  # 平均孔直径 (nm)
    pore_integral_volume: float   # 孔积分体积 (cm^3/g, STP)


@dataclass
class ProcessResult:
    """处理结果数据类"""
    success: bool
    error_message: str = ""
    sp_bet: str = ""
    mp_bet: str = ""
    total_pore_vol: str = ""
    avg_pore_d: str = ""
    most_probable: str = ""
    nldft_data: List[NldftData] = None
    d10_int: float = 0.0
    d10: float = 0.0
    d90_int: float = 0.0
    d90: float = 0.0
    d90_d10_ratio: float = 0.0
    # 新增字段
    pore_volume_A: float = 0.0  # 孔容A（最大孔积分体积）
    d0_5: float = 0.0  # 0.5D（最可几孔径×0.5）
    volume_0_5D: float = 0.0  # 0.5D对应的体积
    less_than_0_5D: float = 0.0  # ＜0.5D的百分比
    d1_5: float = 0.0  # 1.5D（最可几孔径×1.5）
    volume_1_5D: float = 0.0  # 1.5D对应的体积
    greater_than_1_5D: float = 0.0  # ＞1.5D的百分比

    def __post_init__(self):
        if self.nldft_data is None:
            self.nldft_data = []


# ---------- 基础工具 ----------
def clean_text(text: str) -> str:
    """NFKC 规范化、统一换行、替换不可见空白/全角空格。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00A0", " ").replace("\u3000", " ")
    return text


def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        return clean_text(pdf_extract_text(pdf_path) or "")
    except Exception as e:
        print(f"处理PDF时发生错误: {e}")
        return ""


def section_text(text: str, start_label: str, end_labels: List[str]) -> str:
    """从 start_label 起，截到最先出现的任一 end_label（若无则至文末）。"""
    start = text.find(start_label)
    if start == -1:
        return ""
    ends = [text.find(lbl, start + len(start_label)) for lbl in end_labels]
    ends = [p for p in ends if p != -1]
    end = min(ends) if ends else len(text)
    return text[start:end]


# ---------- 关键词数值提取 ----------
def extract_value_near(text: str, keyword: str, unit_regex: str, window: int = 1000) -> str:
    """
    在 keyword 附近（左右对称窗口）找"数字(单位)"并取最近者。
    支持科学计数、千分位；返回不带逗号的数字字符串。
    """
    # 使用正则表达式进行精确匹配，避免匹配包含关键词的其他字符串
    keyword_pattern = re.compile(rf'\b{re.escape(keyword)}\b')
    match = keyword_pattern.search(text)
    if not match:
        return ""
    
    pos = match.start()
    start = max(0, pos - window // 2)
    end = min(len(text), pos + window)
    segment = text[start:end]
    rel = pos - start

    pattern = re.compile(rf"([+-]?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)\s*\({unit_regex}\)")
    cands = []
    for m in pattern.finditer(segment):
        center = (m.start() + m.end()) / 2.0
        dist = abs(center - rel)
        cands.append((dist, m.group(1).replace(",", "")))
    
    if not cands:
        return ""
    
    cands.sort(key=lambda x: x[0])
    result = cands[0][1]
    return result


def extract_surface_area_map(text: str) -> Dict[str, str]:
    """
    在"比表面积分析报告"这节内，按出现顺序采集 m^2/g 的结果，
    依次映射到以下标签：
      1 单点BET比表面积
      2 多点BET比表面积
      3 Langmuir比表面积
      4 T图法微孔面积
      5 T图法外表面积
      6 BJH吸附累积孔内表面积
      7 BJH脱附累积孔内表面积
    """
    sec = section_text(text, "比表面积分析报告",
                       ["孔体积分析报告", "孔径分析报告", "比表面及孔径分析报告"])
    vals = re.findall(r"([+-]?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)\s*\(m\^2/g\)", sec)
    vals = [v.replace(",", "") for v in vals]
    labels = ["单点BET比表面积", "多点BET比表面积", "Langmuir比表面积",
              "T图法微孔面积", "T图法外表面积",
              "BJH吸附累积孔内表面积", "BJH脱附累积孔内表面积"]
    out: Dict[str, str] = {}
    for i, v in enumerate(vals):
        if i < len(labels):
            out[labels[i]] = v
    return out


# ---------- NLDFT 表解析 ----------
def parse_nldft_pairs(text: str) -> List[NldftData]:
    """
    从"NLDFT详细数据"起向后扫描全文，按
      [孔径范围 -> 平均孔径 -> 孔微分体积 -> 孔积分体积 -> (可选)吸附量]
    的顺序分组抽取，得到 (平均孔径, 孔积分体积) 列表。
    注意：PDF 文本是"单元格逐行"，中间夹杂空行，需逐个跳过空白。
    """
    lines = text.splitlines()
    
    # 起点
    start_idx = None
    for i, line in enumerate(lines):
        if "NLDFT详细数据" in line:
            start_idx = i
            break
    if start_idx is None:
        return []

    float_re = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
    range_re = re.compile(r"^\d+(?:\.\d+)?-\d+(?:\.\d+)?$")

    def next_nonempty(idx: int) -> int:
        while idx < len(lines) and lines[idx].strip() == "":
            idx += 1
        return idx

    data: List[NldftData] = []
    i = start_idx
    while i < len(lines):
        s = lines[i].strip()
        if range_re.match(s):
            j = next_nonempty(i + 1)
            if j >= len(lines): break
            s_avg = lines[j].strip()
            if not float_re.match(s_avg): i += 1; continue

            k = next_nonempty(j + 1)
            if k >= len(lines): break
            s_diff = lines[k].strip()
            if not float_re.match(s_diff): i += 1; continue

            m = next_nonempty(k + 1)
            if m >= len(lines): break
            s_int = lines[m].strip()
            if not float_re.match(s_int): i += 1; continue

            # （可有可无）吸附量列，跳过即可
            n = next_nonempty(m + 1)
            # 不强制要求 n 是数字；若不是数字也不影响下一轮

            try:
                data.append(NldftData(float(s_avg), float(s_int)))
            except ValueError:
                pass

            i = (n if n > m else m) + 1
            continue
        i += 1

    data.sort(key=lambda r: r.pore_integral_volume)
    return data


# ---------- 数值计算 ----------
def interpolate_diameter(target_volume: float, data: List[NldftData]) -> float:
    """在 (积分体积 → 平均孔径) 上做线性插值求直径。"""
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
    """在 (平均孔径 → 积分体积) 上做线性插值求体积。"""
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


# ---------- 核心处理函数 ----------
def process_pdf(pdf_path: str) -> ProcessResult:
    """
    处理PDF文件并返回结果
    
    Args:
        pdf_path: PDF文件路径
        
    Returns:
        ProcessResult: 处理结果
    """
    try:
        text = extract_text_from_pdf(pdf_path)
        
        if not text.strip():
            return ProcessResult(success=False, error_message="无法从PDF中提取文本内容")
        
        # 表面积（按节内顺序映射）
        sa_map = extract_surface_area_map(text)
        
        sp_bet = sa_map.get("单点BET比表面积") or extract_value_near(text, "单点BET比表面积", r"m\^2/g", 1000)
        mp_bet = sa_map.get("多点BET比表面积") or extract_value_near(text, "多点BET比表面积", r"m\^2/g", 1000)

        # 其它标量（就近取）
        total_pore_vol = extract_value_near(text, "最高单点吸附总孔体积", r"cm\^3/g", 1000)
        avg_pore_d = extract_value_near(text, "单点总孔吸附平均孔直径", r"nm", 1000)
        most_probable = extract_value_near(text, "最可几孔径", r"nm", 1000)

        # NLDFT 表
        nldft = parse_nldft_pairs(text)
        
        if not nldft:
            return ProcessResult(success=False, error_message="未提取到NLDFT详细数据")

        # 计算 D10 / D90
        if not total_pore_vol:
            return ProcessResult(success=False, error_message="无法进行后续计算，因为未找到最高单点吸附总孔体积")

        try:
            total = float(total_pore_vol)
        except ValueError:
            return ProcessResult(success=False, error_message="最高单点吸附总孔体积解析失败，无法计算")

        d10_int = total * 0.1
        d90_int = total * 0.9
        
        d10 = interpolate_diameter(d10_int, nldft)
        d90 = interpolate_diameter(d90_int, nldft)
        
        d90_d10_ratio = d90 / d10 if d10 != 0 else 0.0

        # 计算孔容A（孔积分体积最大值）
        pore_volume_A = max(row.pore_integral_volume for row in nldft) if nldft else 0.0

        # 计算0.5D相关结果
        if most_probable:
            try:
                most_probable_val = float(most_probable)
                
                d0_5 = most_probable_val * 0.5
                volume_0_5D = interpolate_volume(d0_5, nldft)
                less_than_0_5D = (volume_0_5D / pore_volume_A) * 100.0 if pore_volume_A > 1e-9 else 0.0

                # 计算1.5D相关结果
                d1_5 = most_probable_val * 1.5
                volume_1_5D = interpolate_volume(d1_5, nldft)
                greater_than_1_5D = ((pore_volume_A - volume_1_5D) / pore_volume_A) * 100.0 if pore_volume_A > 1e-9 else 0.0
            except ValueError:
                # 如果最可几孔径解析失败，设置为0
                d0_5 = volume_0_5D = less_than_0_5D = 0.0
                d1_5 = volume_1_5D = greater_than_1_5D = 0.0
        else:
            d0_5 = volume_0_5D = less_than_0_5D = 0.0
            d1_5 = volume_1_5D = greater_than_1_5D = 0.0

        return ProcessResult(
            success=True,
            sp_bet=sp_bet,
            mp_bet=mp_bet,
            total_pore_vol=total_pore_vol,
            avg_pore_d=avg_pore_d,
            most_probable=most_probable,
            nldft_data=nldft,
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
            greater_than_1_5D=greater_than_1_5D
        )

    except Exception as e:
        return ProcessResult(success=False, error_message=f"处理过程中发生错误: {str(e)}")
