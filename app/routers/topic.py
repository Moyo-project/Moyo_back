# app/routers/topic.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import current_user
from app.models.user import User
from app.schemas.topic import TopicCreate, TopicUpdate, TopicOut, TopicBulkSave
from app.services import topic_service

router = APIRouter(prefix="/rooms/{room_id}/topics", tags=["topics"])


@router.get("", response_model=list[TopicOut])
def list_topics(
    room_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return topic_service.list_topics(db, room_id)


@router.post("", response_model=TopicOut, status_code=201)
def create_topic(
    room_id: int,
    body: TopicCreate,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return topic_service.create_topic(db, room_id, body)


@router.post("/bulk", response_model=list[TopicOut], status_code=200)
def bulk_save_topics(
    room_id: int,
    body: TopicBulkSave,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """AI 분석 결과를 한 번에 upsert."""
    return topic_service.bulk_save_topics(db, room_id, body)


@router.patch("/{topic_id}", response_model=TopicOut)
def update_topic(
    room_id: int,
    topic_id: str,
    body: TopicUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return topic_service.update_topic(db, room_id, topic_id, body)


@router.delete("/{topic_id}", status_code=204)
def delete_topic(
    room_id: int,
    topic_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    topic_service.delete_topic(db, room_id, topic_id)
