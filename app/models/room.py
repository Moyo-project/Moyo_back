# app/models/room.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    DateTime,
    func,
    UniqueConstraint,  # ✅ 추가
)
from sqlalchemy.orm import relationship
from app.database import Base


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # ✅ 그룹 연결 (그룹 하나당 채팅방 하나)
    group_id = Column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # ✅ 한 그룹당 하나의 채팅방만 허용
    __table_args__ = (
        UniqueConstraint("group_id", name="uq_chatroom_group"),
    )

    # 관계들
    members = relationship("RoomMember", back_populates="room")
    messages = relationship("Message", back_populates="room")
    topics = relationship("Topic", back_populates="room", cascade="all, delete-orphan")

    # 선택 사항: Group 모델에 back_populates 있으면 같이 연결
    # group = relationship("Group", back_populates="chat_room")
    group = relationship("Group", back_populates="chat_room")


class RoomMember(Base):
    __tablename__ = "room_members"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("chat_rooms.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    room = relationship("ChatRoom", back_populates="members")
    user = relationship("User")
