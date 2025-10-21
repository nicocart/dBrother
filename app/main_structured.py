from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import os

from app.api.routes import router as legacy_router
from app.api.routes_structured import router as structured_router

load_dotenv()

app = FastAPI(title="dBrother - 结构化孔径报告分析工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(legacy_router, prefix="/api")
app.include_router(structured_router, prefix="/api")


def cleanup_temp_files():
    temp_dir = os.getenv("TEMP_DIR", "tmp")
    if not os.path.exists(temp_dir):
        return
    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except OSError:
            pass


@app.on_event("startup")
async def startup_event():
    cleanup_temp_files()


@app.on_event("shutdown")
async def shutdown_event():
    cleanup_temp_files()


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/structured")
async def structured_page(request: Request):
    return templates.TemplateResponse("structured.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main_structured:app", host="0.0.0.0", port=8000, reload=True)

