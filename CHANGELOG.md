# 更新日志

## 2025-08-26

### 新增功能

1. **样品信息提取**
   - 新增样品名称、仪器型号、测试人员、送检日期字段
   - 智能识别多种格式的样品信息
   - 在前端新增"样品信息"标签页显示提取结果

2. **最可几孔径精确提取**
   - 改进"最可几孔径"提取算法，优先提取靠近NLDFT数据的值
   - 解决PDF中多个"最可几孔径"字段时的选择问题
   - 提高数据提取的准确性和可靠性

### 技术改进

- 新增`extract_sample_info()`函数用于提取样品信息
- 新增`extract_most_probable_near_nldft()`函数用于精确提取最可几孔径
- 更新ProcessResult数据类，增加样品信息字段
- 更新API路由，返回新的样品信息字段
- 更新前端界面，新增样品信息显示标签页

### 文件修改

- `app/core/pdf_processor.py` - 新增样品信息提取和最可几孔径精确提取功能
- `app/api/routes.py` - 更新API返回字段
- `app/templates/index.html` - 新增样品信息标签页
- `app/static/js/main.js` - 更新前端数据处理逻辑
- `README.md` - 更新功能特点说明

## 2025-08-25

### 修复的问题

1. **Chart.js库加载问题**
   - 更新Chart.js版本到4.4.0
   - 添加动态加载机制，如果Chart.js未加载会自动重试
   - 改进错误处理和用户提示

2. **页面标题和描述更新**
   - 标题改为：dBrother - 孔径报告分析工具
   - 更新页面描述为更专业的描述
   - 在header中添加作者信息：Leon (@nicocart)

3. **页脚版权信息**
   - 更新为：© 2025 dBrother

4. **Favicon 404错误修复**
   - 使用内联SVG favicon，避免文件404错误
   - 使用🔬图标作为favicon

### 技术改进

- 改进Chart.js加载检测机制
- 添加更好的错误处理和用户反馈
- 优化页面结构和样式
- 添加作者链接到GitHub个人资料

### 文件修改

- `app/templates/index.html` - 更新页面标题、描述、作者信息和favicon
- `app/static/js/main.js` - 改进Chart.js加载和错误处理
- `CHANGELOG.md` - 新增更新日志文件
