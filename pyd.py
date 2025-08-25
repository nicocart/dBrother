#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
import csv
import math
import argparse
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Callable

# 依赖：pdfminer.six
try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except ImportError:
    print("错误: 需要安装 pdfminer.six。请执行: pip install pdfminer.six")
    sys.exit(1)


@dataclass
class NldftData:
    average_pore_diameter: float  # 平均孔直径 (nm)
    pore_integral_volume: float   # 孔积分体积 (cm^3/g, STP)


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
    在 keyword 附近（左右对称窗口）找“数字(单位)”并取最近者。
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
    在“比表面积分析报告”这节内，按出现顺序采集 m^2/g 的结果，
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
    从“NLDFT详细数据”起向后扫描全文，按
      [孔径范围 -> 平均孔径 -> 孔微分体积 -> 孔积分体积 -> (可选)吸附量]
    的顺序分组抽取，得到 (平均孔径, 孔积分体积) 列表。
    注意：PDF 文本是“单元格逐行”，中间夹杂空行，需逐个跳过空白。
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


def write_nldft_csv(rows: List[NldftData], out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["average_pore_diameter_nm", "pore_integral_volume_cm3_per_g_STP"])
        for r in rows:
            w.writerow([f"{r.average_pore_diameter:.6f}", f"{r.pore_integral_volume:.6f}"])


# ---------- 核心处理函数 ----------
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


def process_pdf(pdf_path: str, progress_callback: Optional[Callable[[str], None]] = None) -> ProcessResult:
    """
    处理PDF文件并返回结果

    Args:
        pdf_path: PDF文件路径
        progress_callback: 进度回调函数，接收进度信息字符串

    Returns:
        ProcessResult: 处理结果
    """
    def update_progress(msg: str):
        if progress_callback:
            progress_callback(msg)

    try:
        update_progress("正在提取PDF文本...")
        
        text = extract_text_from_pdf(pdf_path)
        
        if not text.strip():
            return ProcessResult(success=False, error_message="无法从PDF中提取文本内容")
        
        update_progress("正在分析表面积数据...")
        
        # 表面积（按节内顺序映射）
        sa_map = extract_surface_area_map(text)
        
        sp_bet = sa_map.get("单点BET比表面积") or extract_value_near(text, "单点BET比表面积", r"m\^2/g", 1000)
        mp_bet = sa_map.get("多点BET比表面积") or extract_value_near(text, "多点BET比表面积", r"m\^2/g", 1000)

        # 其它标量（就近取）
        total_pore_vol = extract_value_near(text, "最高单点吸附总孔体积", r"cm\^3/g", 1000)
        avg_pore_d = extract_value_near(text, "单点总孔吸附平均孔直径", r"nm", 1000)
        most_probable = extract_value_near(text, "最可几孔径", r"nm", 1000)

        update_progress("正在解析NLDFT数据...")
        
        # NLDFT 表
        nldft = parse_nldft_pairs(text)
        
        if not nldft:
            return ProcessResult(success=False, error_message="未提取到NLDFT详细数据")

        update_progress("正在计算D10/D90...")
        
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

        update_progress("正在计算新增指标...")
        
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
                greater_than_1_5D = ((volume_1_5D - pore_volume_A) / pore_volume_A) * 100.0 if pore_volume_A > 1e-9 else 0.0
            except ValueError:
                # 如果最可几孔径解析失败，设置为0
                d0_5 = volume_0_5D = less_than_0_5D = 0.0
                d1_5 = volume_1_5D = greater_than_1_5D = 0.0
        else:
            d0_5 = volume_0_5D = less_than_0_5D = 0.0
            d1_5 = volume_1_5D = greater_than_1_5D = 0.0

        update_progress("处理完成！")

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


# ---------- GUI界面 ----------
class PoreAnalysisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("孔径分析工具 - PDF数据提取")
        self.root.geometry("1200x700")

        # 设置样式
        style = ttk.Style()
        style.theme_use('clam')

        self.setup_ui()
        self.result_data = None

    def setup_ui(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(5, weight=1)
        main_frame.rowconfigure(6, weight=1)

        # 文件选择区域
        ttk.Label(main_frame, text="PDF文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.file_var = tk.StringVar()
        file_entry = ttk.Entry(main_frame, textvariable=self.file_var, width=50)
        file_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5), pady=5)
        ttk.Button(main_frame, text="浏览", command=self.browse_file).grid(row=0, column=2, padx=(5, 0), pady=5)

        # CSV导出选项
        ttk.Label(main_frame, text="CSV导出:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.csv_var = tk.StringVar()
        csv_entry = ttk.Entry(main_frame, textvariable=self.csv_var, width=50)
        csv_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 5), pady=5)
        ttk.Button(main_frame, text="选择", command=self.browse_csv).grid(row=1, column=2, padx=(5, 0), pady=5)

        # 处理按钮
        self.process_btn = ttk.Button(main_frame, text="开始处理", command=self.process_file)
        self.process_btn.grid(row=2, column=1, pady=10)

        # 进度条
        self.progress_var = tk.StringVar(value="准备就绪")
        ttk.Label(main_frame, textvariable=self.progress_var).grid(row=3, column=0, columnspan=3, pady=5)

        # 结果显示区域
        result_frame = ttk.LabelFrame(main_frame, text="处理结果", padding="5")
        result_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        ttk.Label(result_frame, text="数据结果:").grid(row=0, column=0, sticky=tk.W)
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, height=20)
        self.result_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 导出按钮框架
        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=5, column=0, columnspan=3, pady=5)

        self.export_csv_btn = ttk.Button(export_frame, text="导出NLDFT数据到CSV",
                                        command=self.export_csv, state='disabled')
        self.export_csv_btn.pack(side=tk.LEFT, padx=5)

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="选择PDF文件",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if filename:
            self.file_var.set(filename)

    def browse_csv(self):
        filename = filedialog.asksaveasfilename(
            title="选择CSV保存位置",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filename:
            self.csv_var.set(filename)

    def update_progress(self, message):
        self.progress_var.set(message)
        self.root.update_idletasks()

    def process_file(self):
        pdf_path = self.file_var.get().strip()
        if not pdf_path:
            messagebox.showerror("错误", "请选择PDF文件")
            return

        if not os.path.exists(pdf_path):
            messagebox.showerror("错误", "PDF文件不存在")
            return

        # 禁用处理按钮
        self.process_btn.config(state='disabled')
        self.export_csv_btn.config(state='disabled')

        # 清空结果
        self.result_text.delete(1.0, tk.END)

        def process_thread():
            try:
                result = process_pdf(pdf_path, self.update_progress)
                self.root.after(0, lambda: self.show_result(result))
            except Exception as e:
                self.root.after(0, lambda: self.show_error(f"处理失败: {str(e)}"))
            finally:
                self.root.after(0, lambda: self.process_btn.config(state='normal'))

        # 在新线程中处理，避免界面冻结
        threading.Thread(target=process_thread, daemon=True).start()

    def show_result(self, result: ProcessResult):
        if not result.success:
            self.show_error(result.error_message)
            return

        self.result_data = result

        # 显示结果
        output = []
        output.append("=== 提取的数据结果 ===")
        output.append(f"单点BET比表面积: {result.sp_bet if result.sp_bet else '未找到'}")
        output.append(f"多点BET比表面积: {result.mp_bet if result.mp_bet else '未找到'}")
        output.append(f"最高单点吸附总孔体积: {result.total_pore_vol if result.total_pore_vol else '未找到'}")
        output.append(f"单点总孔吸附平均孔直径: {result.avg_pore_d if result.avg_pore_d else '未找到'}")
        output.append(f"最可几孔径: {result.most_probable if result.most_probable else '未找到'}")
        output.append("")

        output.append(f"=== NLDFT详细数据 ===")
        output.append(f"共提取到 {len(result.nldft_data)} 行数据")
        output.append("前10行示例（平均孔直径, 孔积分体积）：")
        for i, row in enumerate(result.nldft_data[:10]):
            output.append(f"{i+1:2d}. {row.average_pore_diameter:.6f}, {row.pore_integral_volume:.6f}")
        if len(result.nldft_data) > 10:
            output.append("...")
        output.append("")

        output.append("=== 计算结果 ===")
        output.append(f"D10积分: {result.d10_int:.6f}")
        output.append(f"D10: {result.d10:.6f}")
        output.append(f"D90积分: {result.d90_int:.6f}")
        output.append(f"D90: {result.d90:.6f}")
        if result.d90_d10_ratio > 0:
            output.append(f"D90 / D10: {result.d90_d10_ratio:.6f}")
        else:
            output.append("D90 / D10: 无法计算（D10为0）")
        
        output.append("")
        output.append("=== 新增计算结果 ===")
        output.append(f"孔容A（最大孔积分体积）: {result.pore_volume_A:.6f}")
        output.append(f"0.5D（最可几孔径×0.5）: {result.d0_5:.6f}")
        output.append(f"0.5D对应体积: {result.volume_0_5D:.6f}")
        output.append(f"＜0.5D（百分比）: {result.less_than_0_5D:.2f}%")
        output.append(f"1.5D（最可几孔径×1.5）: {result.d1_5:.6f}")
        output.append(f"1.5D对应体积: {result.volume_1_5D:.6f}")
        output.append(f"＞1.5D（百分比）: {result.greater_than_1_5D:.2f}%")

        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, "\n".join(output))

        # 启用导出按钮
        self.export_csv_btn.config(state='normal')

        # 如果设置了CSV路径，自动导出
        csv_path = self.csv_var.get().strip()
        if csv_path:
            try:
                write_nldft_csv(result.nldft_data, csv_path)
                messagebox.showinfo("成功", f"NLDFT数据已导出到: {csv_path}")
            except Exception as e:
                messagebox.showerror("导出失败", f"无法导出CSV文件: {str(e)}")

    def show_error(self, error_message):
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"错误: {error_message}")
        messagebox.showerror("处理失败", error_message)

    def export_csv(self):
        if not self.result_data or not self.result_data.success:
            messagebox.showerror("错误", "没有可导出的数据")
            return

        filename = filedialog.asksaveasfilename(
            title="导出NLDFT数据",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if filename:
            try:
                write_nldft_csv(self.result_data.nldft_data, filename)
                messagebox.showinfo("成功", f"数据已导出到: {filename}")
            except Exception as e:
                messagebox.showerror("导出失败", f"无法导出CSV文件: {str(e)}")


# ---------- 主程序 ----------
def main():
    ap = argparse.ArgumentParser(description="从孔径报告 PDF 提取关键数值、解析 NLDFT 表，并计算 D10/D90。")
    ap.add_argument("pdf", nargs='?', help="报告 PDF 路径（可选，如果不提供则启动GUI）")
    ap.add_argument("--csv", help="可选：导出 NLDFT 两列到 CSV 文件路径")
    ap.add_argument("--gui", action='store_true', help="强制启动GUI界面")
    args = ap.parse_args()

    # 如果没有提供PDF参数或者指定了--gui，启动GUI
    if not args.pdf or args.gui:
        root = tk.Tk()
        app = PoreAnalysisGUI(root)
        root.mainloop()
        return 0

    # 命令行模式
    result = process_pdf(args.pdf, None)
    if not result.success:
        print(f"错误: {result.error_message}")
        return 1

    print("提取的数据结果：")
    print(f"单点BET比表面积: {result.sp_bet if result.sp_bet else '未找到'}")
    print(f"多点BET比表面积: {result.mp_bet if result.mp_bet else '未找到'}")
    print(f"最高单点吸附总孔体积: {result.total_pore_vol if result.total_pore_vol else '未找到'}")
    print(f"单点总孔吸附平均孔直径: {result.avg_pore_d if result.avg_pore_d else '未找到'}")
    print(f"最可几孔径: {result.most_probable if result.most_probable else '未找到'}")
    print()

    print(f"NLDFT详细数据（平均孔直径, 孔积分体积）——共 {len(result.nldft_data)} 行，前10行示例：")
    for row in result.nldft_data[:10]:
        print(f"{row.average_pore_diameter}, {row.pore_integral_volume}")
    print()

    if args.csv:
        try:
            write_nldft_csv(result.nldft_data, args.csv)
            print(f"已导出 NLDFT 两列到: {args.csv}")
        except Exception as e:
            print(f"导出 CSV 失败: {e}")

    print("计算结果：")
    print(f"D10积分: {result.d10_int}")
    print(f"D10: {result.d10}")
    print(f"D90积分: {result.d90_int}")
    print(f"D90: {result.d90}")
    if result.d90_d10_ratio > 0:
        print(f"D90 / D10: {result.d90_d10_ratio}")
    else:
        print("D90 / D10: 无法计算（D10为0）")
    
    print()
    print("新增计算结果：")
    print(f"孔容A（最大孔积分体积）: {result.pore_volume_A}")
    print(f"0.5D（最可几孔径×0.5）: {result.d0_5}")
    print(f"0.5D对应体积: {result.volume_0_5D}")
    print(f"＜0.5D（百分比）: {result.less_than_0_5D:.2f}%")
    print(f"1.5D（最可几孔径×1.5）: {result.d1_5}")
    print(f"1.5D对应体积: {result.volume_1_5D}")
    print(f"＞1.5D（百分比）: {result.greater_than_1_5D:.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
