# app/websocket/endpoints.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from app.websocket.manager import manager
from app.database import get_db
from app.models.message import Message
from app.models.user import User
from app.deps.auth_ws import get_current_user_ws

router = APIRouter()

@router.websocket("/ws/rooms/{room_id}")
async def websocket_room(
    websocket: WebSocket,
    room_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_ws),
):
    await manager.connect(room_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            content = data.get("content")

            if not content:
                continue

            reply_to_id: int | None = data.get("reply_to_id")

            # reply_to_id가 같은 방 메시지인지 검증
            if reply_to_id is not None:
                parent = db.get(Message, reply_to_id)
                if parent is None or parent.room_id != room_id:
                    reply_to_id = None

            msg = Message(
                room_id=room_id,
                user_id=user.id,
                content=content,
                reply_to_id=reply_to_id,
            )
            db.add(msg)
            db.commit()
            db.refresh(msg)

            reply_to_payload = None
            if reply_to_id is not None:
                parent = db.get(Message, reply_to_id)
                if parent:
                    parent_user = db.get(User, parent.user_id) if parent.user_id else None
                    reply_to_payload = {
                        "id": parent.id,
                        "content": parent.content,
                        "user_nickname": parent_user.nickname if parent_user else None,
                    }

            payload = {
                "id": msg.id,
                "room_id": room_id,
                "user_id": user.id,
                "nickname": user.nickname,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "reply_to_id": reply_to_id,
                "reply_to": reply_to_payload,
            }

            await manager.broadcast(room_id, payload)

    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"[WS] ERROR in room {room_id}: {e}")
        manager.disconnect(room_id, websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
