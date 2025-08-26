#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from core.pdf_processor import extract_value_near

# 测试
test_text = """
比表面积分析报告
单点BET比表面积: 123.45 (m^2/g)
多点BET比表面积: 125.67 (m^2/g)

孔径分析报告
最可几孔径: 5.23 (nm)

NLDFT详细数据
孔径范围    平均孔径    孔微分体积    孔积分体积
1.0-2.0     1.5         0.123         0.456
2.0-3.0     2.5         0.234         0.789
3.0-4.0     3.5         0.345         1.234

最可几孔径: 3.45 (nm)

其他数据
最可几孔径: 7.89 (nm)
"""

print("测试1: 不使用参考关键词")
result1 = extract_value_near(test_text, "最可几孔径", r"nm", 1000)

print("\n测试2: 使用参考关键词")
result2 = extract_value_near(test_text, "最可几孔径", r"nm", 1000, "NLDFT详细数据")

print(f"\n结果对比:")
print(f"不使用参考关键词: {result1}")
print(f"使用参考关键词: {result2}")

if result2 == "3.45":
    print("✅ 测试通过！成功提取到靠近NLDFT详细数据的最可几孔径")
else:
    print("❌ 测试失败！未能正确提取到目标值")
