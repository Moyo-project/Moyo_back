# app/schemas/topic.py
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel
from datetime import datetime


# ── 입력 (저장/업데이트) ────────────────────────────────────────

class TopicCreate(BaseModel):
    topic_id: str
    title: str
    structure_type: Literal["opinion", "task", "collection"]
    status: Literal["open", "closed"] = "open"
    data: dict[str, Any]
    decision: str | None = None


class TopicUpdate(BaseModel):
    title: str | None = None
    status: Literal["open", "closed"] | None = None
    data: dict[str, Any] | None = None
    decision: str | None = None


# ── 출력 ────────────────────────────────────────────────────────

class TopicOut(BaseModel):
    id: int
    room_id: int
    topic_id: str
    title: str
    structure_type: str
    status: str
    data: dict[str, Any]
    decision: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 일괄 저장 (AI 분석 결과를 한 번에 저장할 때) ─────────────────

class TopicBulkSave(BaseModel):
    topics: list[TopicCreate]


class TopicAnalyzeMessageIn(BaseModel):
    message_id: int


class TopicAnalyzeMessageOut(BaseModel):
    changed: bool
    topic: TopicOut | None = None
    decision: str
    reason: str | None = None
