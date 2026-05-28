from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageOut, ReplyToInfo

router = APIRouter(prefix="/api/v1/messages", tags=["Messages"])


@router.get("/rooms/{room_id}", response_model=list[MessageOut])
def get_messages(
    room_id: int,
    db: Session = Depends(get_db),
):
    MsgUser = aliased(User)
    ParentMsg = aliased(Message)
    ParentUser = aliased(User)

    stmt = (
        select(Message, MsgUser.nickname, ParentMsg, ParentUser.nickname)
        .join(MsgUser, Message.user_id == MsgUser.id, isouter=True)
        .join(ParentMsg, Message.reply_to_id == ParentMsg.id, isouter=True)
        .join(ParentUser, ParentMsg.user_id == ParentUser.id, isouter=True)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
        .limit(100)
    )
    rows = db.execute(stmt).all()

    result: list[MessageOut] = []
    for msg, nickname, parent_msg, parent_nickname in rows:
        reply_to = None
        if parent_msg is not None:
            reply_to = ReplyToInfo(
                id=parent_msg.id,
                content=parent_msg.content,
                user_nickname=parent_nickname,
            )
        result.append(
            MessageOut(
                id=msg.id,
                room_id=msg.room_id,
                user_id=msg.user_id,
                content=msg.content,
                created_at=msg.created_at,
                user_nickname=nickname,
                reply_to_id=msg.reply_to_id,
                reply_to=reply_to,
            )
        )
    return result