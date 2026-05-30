# app/services/topic_service.py
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.topic import Topic
from app.models.room import ChatRoom
from app.schemas.topic import TopicCreate, TopicUpdate, TopicBulkSave


def _get_room_or_404(db: Session, room_id: int) -> ChatRoom:
    room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def list_topics(db: Session, room_id: int) -> list[Topic]:
    _get_room_or_404(db, room_id)
    return (
        db.query(Topic)
        .filter(Topic.room_id == room_id)
        .order_by(Topic.topic_id)
        .all()
    )


def create_topic(db: Session, room_id: int, body: TopicCreate) -> Topic:
    _get_room_or_404(db, room_id)
    topic = Topic(
        room_id=room_id,
        topic_id=body.topic_id,
        title=body.title,
        structure_type=body.structure_type,
        status=body.status,
        data=body.data,
        decision=body.decision,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def bulk_save_topics(db: Session, room_id: int, body: TopicBulkSave) -> list[Topic]:
    """AI 분석 결과를 통째로 저장 — 기존 토픽은 topic_id 기준으로 upsert."""
    _get_room_or_404(db, room_id)

    existing = {
        t.topic_id: t
        for t in db.query(Topic).filter(Topic.room_id == room_id).all()
    }

    result = []
    for item in body.topics:
        if item.topic_id in existing:
            t = existing[item.topic_id]
            t.title = item.title
            t.structure_type = item.structure_type
            t.status = item.status
            t.data = item.data
            t.decision = item.decision
        else:
            t = Topic(
                room_id=room_id,
                topic_id=item.topic_id,
                title=item.title,
                structure_type=item.structure_type,
                status=item.status,
                data=item.data,
                decision=item.decision,
            )
            db.add(t)
        result.append(t)

    db.commit()
    for t in result:
        db.refresh(t)
    return result


def update_topic(db: Session, room_id: int, topic_id: str, body: TopicUpdate) -> Topic:
    topic = (
        db.query(Topic)
        .filter(Topic.room_id == room_id, Topic.topic_id == topic_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if body.title is not None:
        topic.title = body.title
    if body.status is not None:
        topic.status = body.status
    if body.data is not None:
        topic.data = body.data
    if body.decision is not None:
        topic.decision = body.decision

    db.commit()
    db.refresh(topic)
    return topic


def delete_topic(db: Session, room_id: int, topic_id: str) -> None:
    topic = (
        db.query(Topic)
        .filter(Topic.room_id == room_id, Topic.topic_id == topic_id)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    db.delete(topic)
    db.commit()
