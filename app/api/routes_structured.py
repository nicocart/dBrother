import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.core.pdf_structured_extractor import process_pdf_structured

load_dotenv()

router = APIRouter(prefix="/structured", tags=["structured"])

TEMP_DIR = os.getenv("TEMP_DIR", "tmp")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 2097152))
STATS_FILE = "structured_stats.json"


def ensure_temp_dir() -> None:
    os.makedirs(TEMP_DIR, exist_ok=True)


def remove_file(file_path: str) -> None:
    if os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except OSError:
            pass


def load_stats() -> dict:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"total_analysis_count": 0, "cpu_time_seconds": 0.0, "last_updated": ""}


def save_stats(stats: dict) -> None:
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def update_cpu_time_and_counter(cpu_time: float) -> dict:
    stats = load_stats()
    stats["total_analysis_count"] = stats.get("total_analysis_count", 0) + 1
    stats["cpu_time_seconds"] = stats.get("cpu_time_seconds", 0.0) + cpu_time
    stats["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_stats(stats)
    return stats


def validate_pdf_upload(file: UploadFile, contents: bytes) -> None:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受PDF文件")
    if len(contents) > MAX_FILE_SIZE:
        limit_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大{limit_mb:.1f}MB）")


@router.post("/analyze")
async def analyze_pdf_structured(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    ensure_temp_dir()
    contents = await file.read()
    validate_pdf_upload(file, contents)

    file_id = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(TEMP_DIR, file_id)

    start_time = time.time()
    try:
        with open(file_path, "wb") as fh:
            fh.write(contents)

        result = process_pdf_structured(file_path)
        cpu_time = time.time() - start_time

        background_tasks.add_task(remove_file, file_path)

        if not result.success:
            return JSONResponse(status_code=400, content={"success": False, "error": result.error_message})

        stats = update_cpu_time_and_counter(cpu_time)

        response_payload = {
            "success": True,
            "data": {
                "sp_bet": result.sp_bet,
                "mp_bet": result.mp_bet,
                "total_pore_vol": result.total_pore_vol,
                "avg_pore_d": result.avg_pore_d,
                "most_probable": result.most_probable,
                "raw_text": result.raw_text,
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
                    {
                        "average_pore_diameter": row.average_pore_diameter,
                        "pore_integral_volume": row.pore_integral_volume,
                    }
                    for row in result.nldft_data[:200]
                ],
            },
            "cpu_time_seconds": cpu_time,
            "total_analysis_count": stats.get("total_analysis_count", 0),
        }
        return response_payload
    except HTTPException:
        background_tasks.add_task(remove_file, file_path)
        raise
    except Exception as exc:
        background_tasks.add_task(remove_file, file_path)
        raise HTTPException(status_code=500, detail=f"结构化通道处理失败: {exc}")


@router.get("/stats")
async def get_structured_stats():
    stats = load_stats()
    return {
        "total_analysis_count": stats.get("total_analysis_count", 0),
        "cpu_time_seconds": stats.get("cpu_time_seconds", 0.0),
        "last_updated": stats.get("last_updated", ""),
    }
