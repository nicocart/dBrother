# 结构化解析通道说明

本项目新增 `pdfplumber` 驱动的结构化解析，实现“表格优先、正则兜底”之外的另一套解耦方案。原有接口与页面保持不变，如需试用新通道请参考以下步骤。

## 环境准备

1. 安装额外依赖：

   ```bash
   pip install -r requirements-structured.txt
   ```

2. 如需部署到 Vercel 等平台，请确保构建脚本中也包含 `pdfplumber`。

## 启动新入口

```bash
uvicorn app.main_structured:app --host 0.0.0.0 --port 8000 --reload
```

访问 `http://localhost:8000/structured` 可进入全新前端页面。旧地址 `/` 仍然提供原有上传与正则解析能力。

## API 说明

- `POST /api/structured/analyze`：结构化解析上传接口，响应字段与旧通道保持一致。
- `GET /api/structured/stats`：返回结构化通道的解析次数与 CPU 时间，占位文件为 `structured_stats.json`。

## 解析流程概览

1. 通过 `pdfplumber` 的 `find_tables` + `extract` 获得带坐标的表格。
2. 在首个汇总表中检索：
   - `单点BET比表面积`
   - `多点BET比表面积`
   - `最高单点吸附总孔体积`
   - `单点总孔吸附平均孔直径`
3. 在测试信息表中获取 `最可几孔径`。
4. 在 `NLDFT` 详细表中提取 `(平均孔径, 孔积分体积)` 列表。
5. 计算 D10/D90、孔容 A 以及 0.5D / 1.5D 对应的体积分布。

若 PDF 中未检测到表格或关键字段，将返回错误信息并提示回退到原始通道。

## 统计与清理

- 结构化通道的解析统计保存在 `structured_stats.json`。
- 临时文件仍存放于 `TEMP_DIR`（默认 `tmp/`），在完成请求后即时清理。

## 下一步建议

- 引入任务队列，分别跑正则与表格两套解析并对比结果差异。
- 针对典型报告整理回归样例，配合 `pytest` 做端到端验证。
- 评估 `pymupdf` 方案，作为性能优化的潜在替换。

