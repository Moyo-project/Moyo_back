# app/main.py
import os
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from starlette.staticfiles import StaticFiles

from app.database import Base, engine, get_db
from app import models
from app.routers import auth as auth_router, friend
from app.routers import invites as invites_router
from app.routers import group as groups_router
from app.routers import post as post_router
from app.routers import image as image_router

from app.routers import rooms, messages  # etc...
from app.websocket import endpoints as ws_endpoints
from app.routers import calendar as calendar_router
from app.routers import topic as topic_router
from app.routers import post as post_router

# ─────────────────────────────
# 1) DB 초기화
Base.metadata.create_all(bind=engine)

# 2) 앱 생성
app = FastAPI(
    title="Auth API Example",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

# ─────────────────────────────
# 🔧 static 경로 설정
BASE_DIR = Path(__file__).resolve().parent          # C:\dev\moyo_back\app
STATIC_DIR = BASE_DIR / "static"                    # C:\dev\moyo_back\app\static
GROUP_UPLOAD_DIR = STATIC_DIR / "group_images"  
PROFILE_DIR = STATIC_DIR / "profile"

# ✅ 폴더 없으면 생성 (여기가 중요)
GROUP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)


# ✅ 그 다음 마운트
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ─────────────────────────────
# 3) CORS
raw_origins = os.getenv("CORS_ORIGINS", "")
origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

# 디버깅용으로 한 번 찍어봐도 됨
print("CORS_ORIGINS:", origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 4) 라우터 연결
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(invites_router.router, prefix="/api/v1")
app.include_router(groups_router.router, prefix="/api/v1")
app.include_router(post_router.router, prefix="/api/v1")
app.include_router(calendar_router.router, prefix="/api/v1")
app.include_router(friend.router, prefix="/api/v1") 
app.include_router(image_router.router, prefix="/api/v1")

# 채팅 라우터
app.include_router(rooms.router)
app.include_router(messages.router)
app.include_router(ws_endpoints.router)

# 토픽 라우터
app.include_router(topic_router.router, prefix="/api/v1")

# 5) 헬스체크
@app.get("/", tags=["system"])
def root():
    return {"ok": True, "message": "Auth API running"}

@app.get("/api/v1/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True, "db": "up"}
