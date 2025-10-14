from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import os
import shutil
import uuid
import json
import time
from dotenv import load_dotenv
from typing import Optional

from app.core.pdf_processor_v2 import process_pdf

# 加载环境变量
load_dotenv()

router = APIRouter()

# 获取配置
TEMP_DIR = os.getenv("TEMP_DIR", "tmp")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 2097152))  # 默认2MB
STATS_FILE = "stats.json"

# 全局计数器 - 记录总共解析的次数
total_analysis_count = 0

# 读取统计信息
def load_stats():
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            stats = json.load(f)
            return stats
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "total_analysis_count": 0,
            "cpu_time_seconds": 0,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S.%f")
        }

# 保存统计信息
def save_stats(stats):
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"保存统计信息失败: {e}")

# 更新CPU使用时间
def update_cpu_time(additional_seconds):
    stats = load_stats()
    stats["cpu_time_seconds"] = stats.get("cpu_time_seconds", 0) + additional_seconds
    stats["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S.%f")
    save_stats(stats)

# 清理临时文件
def remove_file(file_path: str):
    if os.path.exists(file_path):
        os.unlink(file_path)

@router.post("/analyze")
async def analyze_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    上传PDF文件并分析孔径数据
    """
    global total_analysis_count
    
    # 检查文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只接受PDF文件")
    
    # 检查文件大小
    file_size = 0
    contents = await file.read()
    file_size = len(contents)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大{MAX_FILE_SIZE/1024/1024:.1f}MB）")
    
    # 保存文件到临时目录
    file_id = str(uuid.uuid4())
    file_path = os.path.join(TEMP_DIR, f"{file_id}.pdf")
    
    # 记录开始时间
    start_time = time.time()
    
    try:
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # 处理PDF文件
        result = process_pdf(file_path)
        
        # 计算CPU使用时间
        end_time = time.time()
        cpu_time = end_time - start_time
        
        # 添加任务在响应后删除临时文件
        background_tasks.add_task(remove_file, file_path)
        
        if not result.success:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": result.error_message}
            )
        
        # 成功解析后增加计数器和CPU时间
        total_analysis_count += 1
        update_cpu_time(cpu_time)
        
        # 返回处理结果
        return {
            "success": True,
            "data": {
                "sp_bet": result.sp_bet,
                "mp_bet": result.mp_bet,
                "total_pore_vol": result.total_pore_vol,
                "avg_pore_d": result.avg_pore_d,
                "most_probable": result.most_probable,
                "d10": result.d10,
                "d90": result.d90,
                "d90_d10_ratio": result.d90_d10_ratio,
                "pore_volume_A": result.pore_volume_A,
                "d0_5": result.d0_5,
                "volume_0_5D": result.volume_0_5D,
                "less_than_0_5D": result.less_than_0_5D,
                "d1_5": result.d1_5,
                "volume_1_5D": result.volume_1_5D,
                "greater_than_1_5D": result.greater_than_1_5D,
                "nldft_data": [
                    {"average_pore_diameter": row.average_pore_diameter, 
                     "pore_integral_volume": row.pore_integral_volume}
                    for row in result.nldft_data[:100]  # 限制返回数量，避免响应过大
                ]
            },
            "total_analysis_count": total_analysis_count,
            "cpu_time_seconds": cpu_time
        }
    
    except Exception as e:
        # 确保出错时也删除临时文件
        background_tasks.add_task(remove_file, file_path)
        raise HTTPException(status_code=500, detail=f"处理文件时出错: {str(e)}")

@router.get("/stats")
async def get_stats():
    """
    获取统计信息，包括总解析次数和CPU使用时间
    """
    stats = load_stats()
    return {
        "total_analysis_count": stats.get("total_analysis_count", 0),
        "cpu_time_seconds": stats.get("cpu_time_seconds", 0),
        "last_updated": stats.get("last_updated", "")
    }

