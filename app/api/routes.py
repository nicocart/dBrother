from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import os
import shutil
import uuid
from dotenv import load_dotenv
from typing import Optional

from app.core.pdf_processor import process_pdf

# 加载环境变量
load_dotenv()

router = APIRouter()

# 获取配置
TEMP_DIR = os.getenv("TEMP_DIR", "tmp")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 2097152))  # 默认2MB

# 全局计数器 - 记录总共解析的次数
total_analysis_count = 0

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
    
    try:
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # 处理PDF文件
        result = process_pdf(file_path)
        
        # 添加任务在响应后删除临时文件
        background_tasks.add_task(remove_file, file_path)
        
        if not result.success:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": result.error_message}
            )
        
        # 成功解析后增加计数器
        total_analysis_count += 1
        
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
            "total_analysis_count": total_analysis_count
        }
    
    except Exception as e:
        # 确保出错时也删除临时文件
        background_tasks.add_task(remove_file, file_path)
        raise HTTPException(status_code=500, detail=f"处理文件时出错: {str(e)}")

@router.get("/stats")
async def get_stats():
    """
    获取统计信息，包括总解析次数
    """
    return {
        "total_analysis_count": total_analysis_count
    }

