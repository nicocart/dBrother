
import re
import math
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Dict

try:
    # pdfminer.six
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:  # pragma: no cover
    pdf_extract_text = None


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
    pore_volume_A: float = 0.0  # 孔容A（最大孔积分体积）
    d0_5: float = 0.0           # 0.5D（最可几孔径×0.5）
    volume_0_5D: float = 0.0    # 0.5D对应的体积
    less_than_0_5D: float = 0.0 # ＜0.5D的百分比
    d1_5: float = 0.0           # 1.5D（最可几孔径×1.5）
    volume_1_5D: float = 0.0    # 1.5D对应的体积
    greater_than_1_5D: float = 0.0  # ＞1.5D的百分比


# ---------- 基础工具 ----------

def clean_text(text: str) -> str:
    """NFKC 规范化、统一换行、替换不可见空白/全角空格。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00A0", " ").replace("\u3000", " ")
    return text


def extract_text_from_pdf(pdf_path: str) -> str:
    """读取PDF文本并做基本清洗。"""
    if pdf_extract_text is None:
        raise RuntimeError("缺少 pdfminer.six 依赖")
    try:
        raw = pdf_extract_text(pdf_path) or ""
        return clean_text(raw)
    except Exception as e:
        # 不抛出，让上层去处理
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


# ---------- 关键词数值提取（更宽松的单位匹配） ----------

# 匹配 m^2/g 的各种写法：m^2/g、m 2̂/g、m²/g、m 2 / g 等
UNIT_M2G = r"m\s*(?:\^?\s*2|²|2[\u0300-\u036F]*)\s*/\s*g"
# 匹配 cm^3/g 或 ml/g 的各种写法
UNIT_CM3G = r"(?:(?:cm\s*(?:\^?\s*3|³|3[\u0300-\u036F]*))|(?:m\s*l))\s*/\s*g"

NUM_REGEX = r"([+-]?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)"

def _find_near(text: str, anchor_pos: int, unit_regex: str, window: int) -> Optional[str]:
    start = max(0, anchor_pos - window // 2)
    end = min(len(text), anchor_pos + window // 2)
    segment = text[start:end]
    rel = anchor_pos - start
    # 在小窗口内寻找 “数字(单位)”
    pattern = re.compile(rf"{NUM_REGEX}\s*\({unit_regex}\)", flags=re.IGNORECASE)
    cands = []
    for m in pattern.finditer(segment):
        center = (m.start() + m.end()) / 2.0
        dist = abs(center - rel)
        cands.append((dist, m.group(1).replace(",", "")))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0][1]

def extract_value_near_any(text: str, keywords: List[str], unit_regex: str, window: int = 1000, reference_keyword: str = None) -> str:
    """
    在多个 keyword 附近找"数字(单位)"并取最近者。
    """
    # 如果提供参考关键词，则优先靠近参考关键词的出现位置
    ref_pos = None
    if reference_keyword:
        m = re.search(re.escape(reference_keyword), text)
        if m:
            ref_pos = m.start()

    best: Optional[tuple] = None  # (distance, value)
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text):
            pos = m.start()
            if ref_pos is not None:
                # 综合距离：距离锚点越近越优
                dist = abs(pos - ref_pos)
            else:
                dist = 0
            val = _find_near(text, pos, unit_regex, window)
            if val is None:
                continue
            score = (dist, -len(kw))  # 参考越近、关键字越长越优
            cand = (score, val)
            if (best is None) or (cand[0] < best[0]):
                best = cand
    return best[1] if best else ""


def extract_surface_area_map(text: str) -> Dict[str, str]:
    """
    在“比表面积分析报告”这节内，按出现顺序采集 m^2/g 的结果，
    依次映射到以下标签：
      1 单点BET比表面积
      2 多点BET比表面积
      3 Langmuir比表面积
      4 T图法微孔面积
      5 T图法外表面积
      6 BJH吸附累积孔内表面积
      7 BJH脱附累积孔内表面积
    ——新旧版本中单位写法不一，这里放宽单位识别。
    """
    sec = section_text(text, "比表面积分析报告",
                       ["孔体积分析报告", "孔径分析报告", "比表面及孔径分析报告"])
    if not sec:
        return {}
    pattern = re.compile(rf"{NUM_REGEX}\s*\({UNIT_M2G}\)", flags=re.IGNORECASE)
    vals = [m.group(1).replace(",", "") for m in pattern.finditer(sec)]
    labels = ["单点BET比表面积", "多点BET比表面积", "Langmuir比表面积",
              "T图法微孔面积", "T图法外表面积",
              "BJH吸附累积孔内表面积", "BJH脱附累积孔内表面积"]
    out: Dict[str, str] = {}
    for i, v in enumerate(vals):
        if i < len(labels):
            out[labels[i]] = v
    return out


def extract_total_pore_volume_fallback(text: str) -> str:
    """
    兼容新版：若找不到“最高单点吸附总孔体积”，尝试从“孔体积百分比”一节读取，
    取该节窗口内出现的 ml/g / cm^3/g 数值的最大者作为总孔体积。
    """
    idx = text.find("孔体积百分比")
    if idx == -1:
        return ""
    win = text[idx: idx + 600]
    # 1) 括号内单位
    pattern = re.compile(rf"{NUM_REGEX}\s*\({UNIT_CM3G}\)", flags=re.IGNORECASE)
    values = []
    for m in pattern.finditer(win):
        try:
            values.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    # 2) 或者直接 "X ml/g" 不带括号
    if not values:
        pattern2 = re.compile(rf"{NUM_REGEX}\s*ml\s*/\s*g", flags=re.IGNORECASE)
        for m in pattern2.finditer(win):
            try:
                values.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
    if not values:
        return ""
    return f"{max(values):.5f}"


# ---------- NLDFT 表解析（鲁棒） ----------

_float_re = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_range_re = re.compile(r"^\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?$")

def _next_nonempty(lines: List[str], idx: int) -> int:
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    return idx

def parse_nldft_pairs(text: str) -> List[NldftData]:
    """
    从“NLDFT详细数据/详细数据NLDFT/孔直径范围”位置起，顺次抽取:
      P/P0 -> 孔径范围(a-b) -> 平均孔径 -> 孔微分体积 -> 孔积分体积 -> (可选)吸附量
    组合为(NldftData 平均孔径, 积分体积)列表。
    """
    lines = text.splitlines()
    # 寻找起点
    start_idx = None
    for i, line in enumerate(lines):
        if ("NLDFT详细数据" in line) or ("详细数据NLDFT" in line) or (("NLDFT" in line and "详细数据" in line)) or ("孔直径范围" in line):
            start_idx = i
            break
    if start_idx is None:
        return []
    data: List[NldftData] = []
    i = start_idx + 1
    # 宽松地跳转字段
    while i < len(lines) - 5:
        i = _next_nonempty(lines, i)
        if i >= len(lines): break
        # 1) P/P0
        if not _float_re.match(lines[i].strip()):
            i += 1
            continue
        # 2) 范围
        j = _next_nonempty(lines, i + 1)
        if j >= len(lines) or not _range_re.match(lines[j].strip()):
            i = j
            continue
        # 3) 平均孔径
        k = _next_nonempty(lines, j + 1)
        if k >= len(lines) or not _float_re.match(lines[k].strip()):
            i = k
            continue
        avg = lines[k].strip()
        # 4) 孔微分体积
        m = _next_nonempty(lines, k + 1)
        if m >= len(lines) or not _float_re.match(lines[m].strip()):
            i = m
            continue
        # 5) 孔积分体积
        n = _next_nonempty(lines, m + 1)
        if n >= len(lines) or not _float_re.match(lines[n].strip()):
            i = n
            continue
        integ = lines[n].strip()
        # 6) 可选“吸附量”跳过
        i = _next_nonempty(lines, n + 1)
        # 记录
        try:
            data.append(NldftData(float(avg), float(integ)))
        except ValueError:
            pass
    # 以积分体积升序，便于“体积->直径”插值
    data.sort(key=lambda r: r.pore_integral_volume)
    return data


# ---------- 插值 ----------

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


# ---------- 核心处理 ----------

def process_pdf(pdf_path: str) -> ProcessResult:
    try:
        text = extract_text_from_pdf(pdf_path)
        if not text.strip():
            return ProcessResult(success=False, error_message="无法从PDF中提取文本内容")

        # 表面积（按节内顺序映射）
        sa_map = extract_surface_area_map(text)

        # 1) 单点BET
        sp_bet = sa_map.get("单点BET比表面积", "")
        if not sp_bet:
            sp_bet = extract_value_near_any(
                text,
                ["单点BET比表面积", "单点 比表面积BET", "单点BET 比表面积"],
                UNIT_M2G, 1000
            )

        # 2) 多点BET
        mp_bet = sa_map.get("多点BET比表面积", "")
        if not mp_bet:
            mp_bet = extract_value_near_any(
                text,
                ["多点BET比表面积", "多点 比表面积BET", "BET测试结果", "测试结果BET"],
                UNIT_M2G, 1000
            )

        # 其它标量
        total_pore_vol = extract_value_near_any(
            text,
            ["最高单点吸附总孔体积", "吸附累积孔体积", "总孔体积"],
            UNIT_CM3G, 1200
        )
        if not total_pore_vol:
            total_pore_vol = extract_total_pore_volume_fallback(text)

        avg_pore_d = extract_value_near_any(
            text,
            ["单点总孔吸附平均孔直径"],
            r"nm", 2000
        )
        most_probable = extract_value_near_any(
            text,
            ["最可几孔径", "最可几孔径BJH", "BJH最可几孔径", "SF最可几孔径"],
            r"nm", 400, "NLDFT"
        )

        # NLDFT 表
        nldft = parse_nldft_pairs(text)
        if not nldft:
            return ProcessResult(success=False, error_message="未提取到NLDFT详细数据")

        if not total_pore_vol:
            return ProcessResult(success=False, error_message="未找到最高单点吸附总孔体积，无法计算D10/D90等指标")

        try:
            total = float(total_pore_vol)
        except ValueError:
            return ProcessResult(success=False, error_message="最高单点吸附总孔体积解析失败，无法计算")

        # D10 / D90
        d10_int = total * 0.1
        d90_int = total * 0.9
        d10 = interpolate_diameter(d10_int, nldft)
        d90 = interpolate_diameter(d90_int, nldft)
        d90_d10_ratio = (d90 / d10) if d10 else 0.0

        # 孔容A与 0.5D / 1.5D
        pore_volume_A = max((row.pore_integral_volume for row in nldft), default=0.0)

        d0_5 = d1_5 = volume_0_5D = volume_1_5D = less_than_0_5D = greater_than_1_5D = 0.0
        if most_probable:
            try:
                D = float(most_probable)
                d0_5 = D * 0.5
                d1_5 = D * 1.5
                volume_0_5D = interpolate_volume(d0_5, nldft)
                volume_1_5D = interpolate_volume(d1_5, nldft)
                if pore_volume_A > 1e-12:
                    less_than_0_5D = (volume_0_5D / pore_volume_A) * 100.0
                    greater_than_1_5D = ((pore_volume_A - volume_1_5D) / pore_volume_A) * 100.0
            except ValueError:
                pass

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
    except Exception as e:  # pragma: no cover
        return ProcessResult(success=False, error_message=f"处理过程中发生错误: {e}")
