# PDF孔径分析工具

一个基于FastAPI和pdfminer.six的PDF孔径分析工具，可以从PDF报告中提取和分析孔径数据。

## 功能特点

- 上传PDF文件并自动提取孔径分析数据
- 智能提取样品信息（样品名称、仪器型号、测试人员、送检日期）
- 精确提取靠近NLDFT数据的"最可几孔径"值
- 计算D10/D90、孔容A等关键指标
- 可视化展示NLDFT孔径分布
- 导出分析数据为CSV格式
- 响应式设计，适配各种设备

## 技术栈

- **前端**：HTML5、CSS3、jQuery、Bootstrap 5、Chart.js
- **后端**：FastAPI、pdfminer.six
- **部署**：Vercel

## 安装与运行

### 本地开发环境

1. 克隆项目并安装依赖：

```bash
git clone <repository-url>
cd dBrother
pip install -r requirements.txt
```

2. 运行应用：

```bash
uvicorn app.main:app --reload
```

3. 访问应用：

打开浏览器，访问 http://localhost:8000

### Vercel部署

项目已配置好Vercel部署文件，可以直接部署到Vercel平台。

## 使用说明

1. 在首页拖放或选择PDF文件（文件大小限制为2MB）
2. 系统会自动分析PDF并提取孔径数据
3. 查看基本数据、高级分析结果和图表
4. 可以下载原始NLDFT数据为CSV格式

## 项目结构

```
dBrother/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── pdf_processor.py
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css
│   │   └── js/
│   │       └── main.js
│   ├── templates/
│   │   └── index.html
│   ├── __init__.py
│   └── main.py
├── tmp/
├── .env.example
├── requirements.txt
├── vercel.json
└── README.md
```

## 注意事项

- 临时文件存储在`/tmp`目录中，处理完成后会自动清理
- 文件大小限制为2MB
- 支持的文件格式仅为PDF

## 许可证

MIT

