from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.schemas.user import NicknameUpdate, UserCreate, UserLogin, SignupOut, LoginOut, EmailRequest, EmailConfirm, PasswordReset, PasswordChange
from app.services.auth_service import create_user, authenticate_user
from app.utils.file_utils import save_profile_image
from app.utils.security import create_access_token
from app.services.auth_service import request_email_code, confirm_email_code, ensure_recent_verified, reset_password, change_password
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.security import decode_access_token
from sqlalchemy import select, func
from app.models.user import User
from app.models.group import Group
from fastapi import status

router = APIRouter(prefix="/auth", tags=["auth"])

# Bearer 인증 디펜던시
bearer = HTTPBearer(auto_error=False)

# 인증코드 발송
@router.post("/email/request")
def email_request(body: EmailRequest, db: Session = Depends(get_db)):
    try:
        request_email_code(db, body.email)
        return {"message": "Verification code sent"}
    except ValueError as e:
        # FIX: raise 누락되어 있어서 추가
        raise HTTPException(status_code=429, detail=str(e))

# 인증코드 확인
@router.post("/email/confirm")
def email_confirm(body: EmailConfirm, db: Session = Depends(get_db)):
    try:
        confirm_email_code(db, body.email, body.code)
        return {"verified": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# 비밀번호 찾기 (이메일 인증 후 재설정)
@router.post("/password/reset")
def password_reset(body: PasswordReset, db: Session = Depends(get_db)):
    try:
        reset_password(db, body.email, body.new_password)
        return {"message": "Password reset successful"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# 비밀번호 변경 (로그인 상태)
@router.patch("/me/password")
def password_change(
    body: PasswordChange,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        change_password(db, email, body.current_password, body.new_password)
        return {"message": "Password changed successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/signup", response_model=SignupOut, status_code=201)
async def signup(
    # ✅ JSON 대신 multipart/form-data 로 받기
    email: str = Form(...),
    name: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    profile_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    try:
        # 최근 이메일 인증 성공 이력 확인 (30분이내)
        try:
            ensure_recent_verified(db, email, within_minutes=30)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Email not verified: {e}")

        # ✅ 이미지 저장
        profile_image_url: str | None = None
        if profile_image is not None:
            profile_image_url = await save_profile_image(profile_image)

        # ✅ 원래 쓰던 UserCreate 객체 직접 생성
        body = UserCreate(
            email=email,
            name=name,
            nickname=nickname,
            password=password,
            profile_image_url=profile_image_url,
        )

        # 기존 로직 재사용
        user = create_user(db, body)

        access_token = create_access_token({"sub": user.email})

        return {
            "access_token": access_token,
            "user": user,
        }

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

# 로그인
@router.post("/login", response_model=LoginOut)
def login(body: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

# 회원 탈퇴
@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
):
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    email = payload.get("sub")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 방장으로 있는 그룹 수 확인
    owned_group_count = db.scalar(
        select(func.count()).select_from(Group).where(Group.creator_id == user.id)
    )
    
    if owned_group_count and owned_group_count>0:
        raise HTTPException(
            status_code=400,
            detail="방장으로 있는 그룹이 있어서 탈퇴할 수 없습니다. 그룹을 삭제하거나 방장을 위임한 후 다시 시도해 주세요."
        )
    
    db.delete(user)
    db.commit()
    return

# 보호 라우트: 현재 로그인 사용자 정보
@router.get("/me")
def me(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {"id": user.id, "email": user.email, "name": user.name, "nickname":user.nickname, "is_active": user.is_active, "profile_image_url": user.profile_image_url}

# 닉네임 변경
@router.patch("/me/nickname")
def update_nickname(
    body: NicknameUpdate,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    # 토큰 체크
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 닉네임 수정
    user.nickname = body.nickname
    db.commit()
    db.refresh(user)

    # /auth/me랑 같은 형태로 돌려주기
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "nickname": user.nickname,
        "is_active": user.is_active,
        "profile_image_url": user.profile_image_url,
    }

# 프로필 수정
@router.patch("/me/profile-image")
async def update_profile_image(
    profile_image: UploadFile = File(...),
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    # 토큰 체크
    if creds is None or creds.scheme.lower() != "bearer":
      raise HTTPException(status_code=401, detail="Missing or invalid token")

    try:
      payload = decode_access_token(creds.credentials)
    except Exception:
      raise HTTPException(status_code=401, detail="Invalid token")

    email = payload.get("sub")
    if not email:
      raise HTTPException(status_code=401, detail="Invalid token")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
      raise HTTPException(status_code=404, detail="User not found")
  
    old_url = user.profile_image_url
    profile_image_url = await save_profile_image(profile_image, old_url=old_url)

    user.profile_image_url = profile_image_url
    db.commit()
    db.refresh(user)

    # /auth/me와 형태 맞춰서 리턴 (profile_image_url 포함!)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "nickname": user.nickname,
        "is_active": user.is_active,
        "profile_image_url": user.profile_image_url,
    }