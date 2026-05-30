import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from openai import APIConnectionError, OpenAI, RateLimitError
from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.room import ChatRoom
from app.models.topic import Topic
from app.models.user import User


ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT_DIR / "prompt"
MODEL = os.getenv("CLOVA_MODEL", "HCX-007")


def _load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise RuntimeError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


ROUTER_PROMPT = _load_prompt("router")
OPINION_PROMPT = _load_prompt("opinion_parser")
TASK_PROMPT = _load_prompt("task_parser")
COLLECTION_PROMPT = _load_prompt("collection_parser")


def _client() -> OpenAI:
    api_key = os.getenv("CLOVA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="CLOVA_API_KEY is not configured")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("CLOVA_BASE_URL", "https://clovastudio.stream.ntruss.com/v1/openai"),
    )


def _extract_json(text: str | None) -> dict[str, Any]:
    if text is None:
        return {}

    raw = text.strip()
    raw = raw.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

    try:
        return json.loads(raw)
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return {}

    return {}


def _call_llm(system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = _client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0,
            )
            return _extract_json(response.choices[0].message.content)
        except RateLimitError as exc:
            last_error = exc
            time.sleep(2**attempt)
        except APIConnectionError as exc:
            last_error = exc
            time.sleep(1 + attempt)

    raise HTTPException(status_code=503, detail=f"AI request failed: {last_error}")


def _message_ref(message: Message, nickname: str | None = None) -> dict[str, Any]:
    return {
        "message_id": f"m{message.id}",
        "sender": nickname or "unknown",
        "text": message.content,
    }


def _get_message_or_404(db: Session, room_id: int, message_id: int) -> Message:
    message = (
        db.query(Message)
        .filter(Message.room_id == room_id, Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _get_room_or_404(db: Session, room_id: int) -> ChatRoom:
    room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def _recent_messages(db: Session, room_id: int, before_id: int, limit: int = 5) -> list[dict[str, Any]]:
    rows = (
        db.query(Message, User.nickname)
        .join(User, Message.user_id == User.id, isouter=True)
        .filter(Message.room_id == room_id, Message.id < before_id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    return [_message_ref(message, nickname) for message, nickname in reversed(rows)]


def _list_topics(db: Session, room_id: int) -> list[Topic]:
    return (
        db.query(Topic)
        .filter(Topic.room_id == room_id)
        .order_by(Topic.id.asc())
        .all()
    )


def _active_topic(topics: list[Topic]) -> Topic | None:
    open_topics = [topic for topic in topics if topic.status == "open"]
    return open_topics[-1] if open_topics else (topics[-1] if topics else None)


def _topic_payload(topic: Topic | None) -> dict[str, Any] | None:
    if topic is None:
        return None
    data = topic.data or {}
    payload = {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "structure_type": topic.structure_type,
        "status": topic.status,
        "items": data.get("items", []),
    }
    if topic.structure_type == "opinion":
        payload["decision"] = topic.decision
    if topic.structure_type == "collection":
        payload["fields"] = data.get("fields", [])
    return payload


def _topic_summary(topic: Topic) -> dict[str, Any]:
    data = topic.data or {}
    items = data.get("items", [])
    summary = {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "structure_type": topic.structure_type,
        "status": topic.status,
    }
    if topic.structure_type == "opinion":
        summary["targets"] = [item.get("target") for item in items if item.get("target")]
    elif topic.structure_type == "task":
        summary["tasks"] = [item.get("task") for item in items if item.get("task")]
    elif topic.structure_type == "collection":
        summary["fields"] = data.get("fields", [])
        summary["participants"] = [
            item.get("participant") for item in items if item.get("participant")
        ]
    return summary


def _next_topic_id(topics: list[Topic]) -> str:
    max_number = 0
    for topic in topics:
        if topic.topic_id.startswith("t") and topic.topic_id[1:].isdigit():
            max_number = max(max_number, int(topic.topic_id[1:]))
    return f"t{max_number + 1}"


def _normalize_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items", [])
    return items if isinstance(items, list) else []


def _normalize_fields(data: dict[str, Any]) -> list[str]:
    fields = data.get("fields", [])
    return fields if isinstance(fields, list) else []


def _append_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _normalize_field_name(field: str) -> str:
    aliases = {
        "phone": "전화번호",
        "phone_number": "전화번호",
        "tel": "전화번호",
        "mobile": "전화번호",
        "email": "이메일",
        "e-mail": "이메일",
        "name": "이름",
        "available_time": "가능시간",
        "availability": "가능시간",
    }
    return aliases.get(field, field)


def _keep_current_sources_only(result: dict[str, Any], message_ref: dict[str, Any]) -> dict[str, Any]:
    allowed_id = message_ref["message_id"]
    cleaned = dict(result)
    cleaned_items = []

    for item in _normalize_items(result):
        next_item = dict(item)
        source_ids = [
            source_id
            for source_id in item.get("source_message_ids", [])
            if source_id == allowed_id
        ]
        next_item["source_message_ids"] = source_ids
        cleaned_items.append(next_item)

    cleaned["items"] = cleaned_items
    if "fields" in cleaned:
        used_fields = []
        for item in cleaned_items:
            if not item.get("source_message_ids"):
                continue
            for field in (item.get("values") or {}).keys():
                field = _normalize_field_name(field)
                if field not in used_fields:
                    used_fields.append(field)
        cleaned["fields"] = used_fields
    return cleaned


def _merge_opinion(data: dict[str, Any], new_items: list[dict[str, Any]]) -> None:
    existing = data.setdefault("items", [])
    for item in new_items:
        target = item.get("target")
        positive = item.get("positive_participants", [])
        negative = item.get("negative_participants", [])
        source_ids = item.get("source_message_ids", [])
        if not target or not source_ids or (not positive and not negative):
            continue

        found = next((old for old in existing if old.get("target") == target), None)
        if found is None:
            found = {
                "target": target,
                "positive_participants": [],
                "negative_participants": [],
                "source_message_ids": [],
            }
            existing.append(found)

        _append_unique(found["positive_participants"], positive)
        _append_unique(found["negative_participants"], negative)
        _append_unique(found["source_message_ids"], source_ids)


def _merge_task(data: dict[str, Any], new_items: list[dict[str, Any]]) -> None:
    existing = data.setdefault("items", [])
    for item in new_items:
        task = item.get("task")
        source_ids = item.get("source_message_ids", [])
        if not task or not source_ids:
            continue

        found = next((old for old in existing if old.get("task") == task), None)
        if found is None:
            found = {
                "task": task,
                "assignees": [],
                "due": {"date": None, "time": None},
                "status": "todo",
                "source_message_ids": [],
            }
            existing.append(found)

        _append_unique(found["assignees"], item.get("assignees", []))
        due = item.get("due") or {}
        if due.get("date") is not None:
            found["due"]["date"] = due["date"]
        if due.get("time") is not None:
            found["due"]["time"] = due["time"]
        if item.get("status") in ["todo", "done", "cancelled"]:
            found["status"] = item["status"]
        _append_unique(found["source_message_ids"], source_ids)


def _merge_collection(
    data: dict[str, Any],
    fields: list[str],
    new_items: list[dict[str, Any]],
) -> None:
    topic_fields = data.setdefault("fields", [])
    _append_unique(topic_fields, [_normalize_field_name(field) for field in fields])
    existing = data.setdefault("items", [])

    for item in new_items:
        participant = item.get("participant")
        values = item.get("values") or {}
        source_ids = item.get("source_message_ids", [])
        if not participant or not values or not source_ids:
            continue

        found = next((old for old in existing if old.get("participant") == participant), None)
        if found is None:
            found = {"participant": participant, "values": {}, "source_message_ids": []}
            existing.append(found)

        for field, value in values.items():
            field = _normalize_field_name(field)
            if field not in topic_fields:
                topic_fields.append(field)
            found["values"][field] = value
        _append_unique(found["source_message_ids"], source_ids)


def _fill_collection_nulls(data: dict[str, Any]) -> None:
    fields = data.setdefault("fields", [])
    for item in data.setdefault("items", []):
        values = item.setdefault("values", {})
        for field in fields:
            values.setdefault(field, None)


def _merge_parser_result(topic: Topic, parser_result: dict[str, Any]) -> bool:
    data = dict(topic.data or {})
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    items = _normalize_items(parser_result)

    if topic.structure_type == "opinion":
        _merge_opinion(data, items)
    elif topic.structure_type == "task":
        _merge_task(data, items)
    elif topic.structure_type == "collection":
        _merge_collection(data, _normalize_fields(parser_result), items)
        _fill_collection_nulls(data)

    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    topic.data = data
    return before != after


def _parser_prompt(structure_type: str) -> str:
    if structure_type == "opinion":
        return OPINION_PROMPT
    if structure_type == "task":
        return TASK_PROMPT
    if structure_type == "collection":
        return COLLECTION_PROMPT
    raise HTTPException(status_code=400, detail=f"Unsupported structure_type: {structure_type}")


def _find_topic(topics: list[Topic], topic_id: str | None) -> Topic | None:
    if not topic_id:
        return None
    return next((topic for topic in topics if topic.topic_id == topic_id), None)


def _create_topic(db: Session, room_id: int, topics: list[Topic], router_result: dict[str, Any]) -> Topic:
    structure_type = router_result.get("structure_type")
    if structure_type not in ["opinion", "task", "collection"]:
        raise HTTPException(status_code=422, detail="AI did not return a valid structure_type")

    data: dict[str, Any] = {"items": []}
    if structure_type == "collection":
        data["fields"] = []

    topic = Topic(
        room_id=room_id,
        topic_id=_next_topic_id(topics),
        title=router_result.get("title") or "새 토픽",
        structure_type=structure_type,
        status="open",
        data=data,
        decision=None if structure_type == "opinion" else None,
    )
    db.add(topic)
    db.flush()
    topics.append(topic)
    return topic


def analyze_message(db: Session, room_id: int, message_id: int) -> tuple[bool, Topic | None, str, str | None]:
    _get_room_or_404(db, room_id)
    message = _get_message_or_404(db, room_id, message_id)
    nickname = message.user.nickname if message.user else None
    message_ref = _message_ref(message, nickname)

    topics = _list_topics(db, room_id)
    active_topic = _active_topic(topics)
    payload = {
        "message": message_ref,
        "recent_messages": _recent_messages(db, room_id, message.id),
        "pending_topic": None,
        "active_topic": _topic_payload(active_topic),
        "topics_summary": [_topic_summary(topic) for topic in topics],
    }
    router_result = _call_llm(ROUTER_PROMPT, payload)
    decision = router_result.get("decision") or "noise"
    reason = router_result.get("reason")

    if decision == "noise":
        return False, None, decision, reason

    if decision == "attach_existing":
        topic = _find_topic(topics, router_result.get("topic_id"))
        if topic is None:
            topic = active_topic
    else:
        topic = _create_topic(db, room_id, topics, router_result)

    if topic is None:
        return False, None, decision, reason

    parser_payload = {
        "current_topic": _topic_payload(topic),
        "recent_messages": payload["recent_messages"],
        "topics_summary": payload["topics_summary"],
        "messages": [message_ref],
    }
    parser_result = _call_llm(_parser_prompt(topic.structure_type), parser_payload)
    parser_result = _keep_current_sources_only(parser_result, message_ref)
    changed = _merge_parser_result(topic, parser_result)

    db.commit()
    db.refresh(topic)
    return changed, topic, decision, reason
