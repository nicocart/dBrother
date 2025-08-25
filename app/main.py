from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
from dotenv import load_dotenv

from app.api.routes import router as api_router

# 加载环境变量
load_dotenv()

app = FastAPI(title="dBrother - 孔径报告分析工具")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 设置模板
templates = Jinja2Templates(directory="app/templates")

# 包含API路由
app.include_router(api_router, prefix="/api")

# 创建临时目录
temp_dir = os.getenv("TEMP_DIR", "tmp")
os.makedirs(temp_dir, exist_ok=True)

# 清理临时文件的函数
def cleanup_temp_files():
    temp_dir = os.getenv("TEMP_DIR", "tmp")
    if os.path.exists(temp_dir):
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"清理临时文件时出错: {e}")

# 启动事件
@app.on_event("startup")
async def startup_event():
    cleanup_temp_files()

# 关闭事件
@app.on_event("shutdown")
async def shutdown_event():
    cleanup_temp_files()

# 主页路由
@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

