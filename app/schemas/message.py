# app/schemas/message.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReplyToInfo(BaseModel):
    id: int
    content: str
    user_nickname: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageBase(BaseModel):
    content: str


class MessageCreate(MessageBase):
    room_id: int


class MessageOut(MessageBase):
    id: int
    room_id: int
    user_id: int | None
    created_at: datetime
    user_nickname: str | None = None
    reply_to_id: int | None = None
    reply_to: ReplyToInfo | None = None

    model_config = ConfigDict(from_attributes=True)
