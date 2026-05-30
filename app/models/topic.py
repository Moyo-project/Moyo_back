# app/models/topic.py
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, index=True)

    topic_id = Column(String(50), nullable=False)       # "t1", "t2" ...
    title = Column(String(255), nullable=False)
    structure_type = Column(String(20), nullable=False)  # "opinion" | "task" | "collection"
    status = Column(String(20), nullable=False, default="open")  # "open" | "closed"

    # opinion: {items: [{target, positive_participants, negative_participants, source_message_ids}]}
    # task:    {items: [{task, assignees, due, status, source_message_ids}]}
    # collection: {fields: [...], items: [{participant, values, source_message_ids}]}
    data = Column(JSON, nullable=False, default=dict)

    # opinion 전용: 최종 결정
    decision = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    room = relationship("ChatRoom", back_populates="topics")
