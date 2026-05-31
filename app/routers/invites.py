# 10/30 생성 신규 파일
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.invite import (
    InviteCreateIn, InviteOut, InviteVerifyIn, InviteVerifyOut, InviteRedeemIn
)
from app.services.invite_service import create_invite, verify_invite, redeem_invite, get_active_group_invite
from app.deps.auth import current_user
from app.models.user import User
from app.schemas.invite import InviteRotateIn, InviteOut
from app.services.invite_service import rotate_invite
import json

router = APIRouter(prefix="/invites", tags=["invites"], dependencies=[Depends(current_user)])

@router.post("", response_model=InviteOut, status_code=201)
def create(body: InviteCreateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = create_invite(
        db,
        purpose=body.purpose,
        payload=body.payload,
        issuer_user_id=user.id,
        max_uses=body.maxUses,
        ttl_minutes=body.ttlMinutes
    )
    uses_left = None if row.max_uses <= 0 else max(row.max_uses - row.used_count, 0)  # ✅ 무제한은 None로 내려주기
    return {"code": row.code, "purpose": row.purpose, "usesLeft": uses_left,
            "expiresAt": row.expires_at.isoformat() if row.expires_at else None}

@router.post("/verify", response_model=InviteVerifyOut)
def verify(body: InviteVerifyIn, db: Session = Depends(get_db)):
    ok, reason, row = verify_invite(db, body.code)
    if not ok:
        return {"valid": False, "reason": reason}
    # [추가] payload JSON 안전 디코딩
    try:
        payload = json.loads(row.payload) if row.payload else None
    except json.JSONDecodeError:
        payload = None
    uses_left = row.max_uses - row.used_count
    return {
        "valid": True,
        "purpose": row.purpose,
        "payload": payload,
        "usesLeft": uses_left,
    }

@router.post("/redeem", response_model=InviteVerifyOut)
def redeem(body: InviteRedeemIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ok, reason, row = redeem_invite(db, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    try:
        payload = json.loads(row.payload) if row.payload else None
    except json.JSONDecodeError:
        payload = None
    uses_left = row.max_uses - row.used_count
    return {
        "valid": True,
        "purpose": row.purpose,
        "payload": payload,
        "usesLeft": uses_left,
    }

@router.get("/group/{group_id}", response_model=InviteOut | None)
def get_group_invite(group_id: int, db: Session = Depends(get_db)):
    row = get_active_group_invite(db, group_id)
    if not row:
        return None
    uses_left = None if row.max_uses <= 0 else max(row.max_uses - row.used_count, 0)
    return {"code": row.code, "purpose": row.purpose, "usesLeft": uses_left,
            "expiresAt": row.expires_at.isoformat() if row.expires_at else None}

@router.post("/rotate", response_model=InviteOut)
def rotate(body: InviteRotateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    new_row = rotate_invite(db, body.code, user.id)
    if not new_row:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    uses_left = None if new_row.max_uses <= 0 else (new_row.max_uses - new_row.used_count)
    return {
        "code": new_row.code,
        "purpose": new_row.purpose,
        "usesLeft": uses_left if uses_left is not None else 0,  # 프론트가 필요하면 null로 보내도 됨
        "expiresAt": new_row.expires_at.isoformat() if new_row.expires_at else None,
    }
