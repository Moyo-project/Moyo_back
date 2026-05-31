# 10/30 생성 신규 파일
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
import json
from app.models.invite import InviteCode
from app.utils.invite import new_code

PURPOSE_GROUP_JOIN = "group_join"

def _unique_code(db: Session, length: int = 8) -> str:
    while True:
        code = new_code(length)
        exists = db.scalar(select(InviteCode.id).where(InviteCode.code == code))
        if not exists:
            return code

def create_invite(db: Session, purpose: str, payload: dict | None,
                  issuer_user_id: int | None, max_uses: int | None, ttl_minutes: int | None) -> InviteCode:
    code = _unique_code(db, 8)
    # None이면 기본 1회, 0은 무제한이라 그대로 둠
    if max_uses is None:
        max_uses = 1
    # 만료 계산: None 또는 0 이면 만료 없음
    if ttl_minutes is not None and ttl_minutes > 0:
        expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    else:
        expires = None
    row = InviteCode(
        code=code,
        purpose=purpose,
        payload=json.dumps(payload) if payload else None,
        issuer_user_id=issuer_user_id,
        max_uses=max_uses,
        used_count=0,
        expires_at=expires,
        revoked_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """DB에서 naive로 올라온 datetime도 UTC aware로 맞춰줍니다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def verify_invite(db: Session, code: str):
    row = db.scalar(select(InviteCode).where(InviteCode.code == code))
    if not row:
        return (False, "NOT_FOUND", None)
    if row.revoked_at:
        return (False, "REVOKED", row)
    now = datetime.now(timezone.utc)
    exp = _as_aware_utc(row.expires_at)
    if exp and exp < now:
        return (False, "EXPIRED", row)
    # max_uses <= 0 이면 무제한으로 취급
    if row.max_uses > 0 and row.used_count >= row.max_uses:
        return (False, "EXHAUSTED", row)
    return (True, None, row)

def redeem_invite(db: Session, code: str):
    ok, reason, row = verify_invite(db, code)
    if not ok:
        return (False, reason, None)
    if row.max_uses > 0:
        row.used_count += 1
    db.commit()
    db.refresh(row)
    return (True, None, row)

# [추가] 재발급(rotate) 유스케이스 추가
def get_active_group_invite(db: Session, group_id: int) -> InviteCode | None:
    """그룹의 현재 유효한 초대코드를 반환합니다 (없으면 None)."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(InviteCode)
        .where(
            InviteCode.purpose == PURPOSE_GROUP_JOIN,
            InviteCode.payload.contains(f'"groupId": {group_id}'),
            InviteCode.revoked_at.is_(None),
        )
        .order_by(InviteCode.created_at.desc())
    ).all()
    for row in rows:
        exp = _as_aware_utc(row.expires_at)
        if exp and exp < now:
            continue
        if row.max_uses > 0 and row.used_count >= row.max_uses:
            continue
        return row
    return None

def rotate_invite(db: Session, old_code: str, issuer_user_id: int | None):
    row = db.scalar(select(InviteCode).where(InviteCode.code == old_code))
    if not row:
        return None
    # 기존 코드 회수
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    # 동일한 목적/페이로드로 새 코드 발급 (무제한/무기한이면 그대로)
    payload = json.loads(row.payload) if row.payload else None
    # 남은 TTL 계산(지났으면 0으로 보정 ⇒ 만료 없음)
    if row.expires_at is None:
        ttl_left = 0
    else:
        ttl_left = int((_as_aware_utc(row.expires_at) - datetime.now(timezone.utc)).total_seconds() // 60)
        if ttl_left < 0:
            ttl_left = 0
    new_row = create_invite(
        db,
        purpose=row.purpose,
        payload=payload,
        issuer_user_id=issuer_user_id,
        max_uses=row.max_uses,
        ttl_minutes=ttl_left,
    )
    return new_row
