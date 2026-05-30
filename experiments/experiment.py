import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")

client = OpenAI(
    api_key=os.getenv("CLOVA_API_KEY"),
    base_url="https://clovastudio.stream.ntruss.com/v1/openai",
)

MODEL = "HCX-007"

# =========================
# Utils
# =========================

def call_llm(system_prompt: str, user_payload: dict) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        temperature=0,
    )

    text = response.choices[0].message.content

    print("\n[LLM RAW 출력]")
    print(text)

    parsed = extract_json(text)

    if not parsed:
        print("\n[JSON 파싱 실패]")
    
    return parsed


def extract_json(text: str) -> dict:
    if text is None:
        return {}

    raw = text.strip()

    raw = raw.replace("```json", "")
    raw = raw.replace("```JSON", "")
    raw = raw.replace("```", "")
    raw = raw.strip()

    try:
        return json.loads(raw)
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(raw[start:end + 1])
        except Exception as e:
            print("[JSON 부분 파싱 실패]", e)
            print(raw[start:end + 1])

    return {}


def new_topic_id(state: dict) -> str:
    return f"t{len(state['topics']) + 1}"


def normalize_items(data: dict) -> list:
    items = data.get("items", [])
    return items if isinstance(items, list) else []


def normalize_fields(data: dict) -> list:
    fields = data.get("fields", [])
    return fields if isinstance(fields, list) else []


# =========================
# Prompt Loader
# =========================

PROMPT_DIR = ROOT_DIR / "prompt"


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"

    if not path.exists():
        raise FileNotFoundError(f"프롬프트 없음: {path}")

    return path.read_text(
        encoding="utf-8"
    )


ROUTER_PROMPT = load_prompt("router")

OPINION_PROMPT = load_prompt(
    "opinion_parser"
)

TASK_PROMPT = load_prompt(
    "task_parser"
)

COLLECTION_PROMPT = load_prompt(
    "collection_parser"
)


# =========================
# State
# =========================

def initial_state() -> dict:
    return {
        "pending_topic": None,
        "topics": [],
        "message_history": [],
        "active_topic_id": None,
        "active_structure_type": None,
        "mode": "routing",
    }


def get_active_topic(state: dict) -> dict | None:
    topic_id = state.get("active_topic_id")
    for topic in state["topics"]:
        if topic["topic_id"] == topic_id:
            return topic
    return None


def get_recent_messages(state: dict, limit: int = 5) -> list:
    return state.get("message_history", [])[-limit:]


def summarize_topic(topic: dict) -> dict:
    summary = {
        "topic_id": topic.get("topic_id"),
        "title": topic.get("title"),
        "structure_type": topic.get("structure_type"),
        "status": topic.get("status"),
    }

    structure_type = topic.get("structure_type")
    items = topic.get("items", [])

    if structure_type == "opinion":
        summary["targets"] = [item.get("target") for item in items if item.get("target")]
    elif structure_type == "task":
        summary["tasks"] = [item.get("task") for item in items if item.get("task")]
    elif structure_type == "collection":
        summary["fields"] = topic.get("fields", [])
        summary["participants"] = [
            item.get("participant") for item in items if item.get("participant")
        ]

    return summary


def get_topics_summary(state: dict) -> list:
    return [summarize_topic(topic) for topic in state.get("topics", [])]


def has_collection_signal(text: str) -> bool:
    cues = [
        "연락처", "번호", "전화번호", "이메일", "메일",
        "이름", "가능시간", "가능 시간", "가능한 시간",
    ]
    return any(cue in text for cue in cues)


def has_task_signal(text: str) -> bool:
    cues = [
        "할게", "맡을게", "예약", "준비", "마감",
        "담당", "장보기", "조사", "구매", "정리",
    ]
    return any(cue in text for cue in cues)


def normalize_field_name(field: str) -> str:
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


def create_topic_from_pending(state: dict, router_result: dict) -> dict:
    topic_id = new_topic_id(state)
    pending = state["pending_topic"]

    title = (
        router_result.get("title")
        or pending.get("title")
        or "새 토픽"
    )

    structure_type = (
        router_result.get("structure_type")
        or pending.get("structure_type")
    )

    topic = {
        "topic_id": topic_id,
        "title": title,
        "structure_type": structure_type,
        "items": [],
        "status": "open",
    }

    if structure_type == "opinion":
        topic["decision"] = None
    elif structure_type == "collection":
        topic["fields"] = []

    pending_messages = pending.get("messages", [])

    state["topics"].append(topic)
    state["pending_topic"] = None
    state["active_topic_id"] = topic_id
    state["active_structure_type"] = structure_type
    state["mode"] = "parse"

    parse_messages(state, topic, pending_messages)

    return topic


def start_or_update_pending(state: dict, message: dict, router_result: dict):
    if state["pending_topic"] is None:
        state["pending_topic"] = {
            "title": router_result.get("title"),
            "structure_type": router_result.get("structure_type"),
            "confidence": router_result.get("confidence", 0),
            "message_count": 1,
            "message_ids": [message["message_id"]],
            "messages": [message],
        }
    else:
        state["pending_topic"]["message_count"] += 1
        state["pending_topic"]["message_ids"].append(message["message_id"])
        state["pending_topic"]["messages"].append(message)

        if router_result.get("confidence", 0) > state["pending_topic"].get("confidence", 0):
            state["pending_topic"]["confidence"] = router_result.get("confidence", 0)
            state["pending_topic"]["title"] = router_result.get("title") or state["pending_topic"].get("title")
            state["pending_topic"]["structure_type"] = router_result.get("structure_type") or state["pending_topic"].get("structure_type")


def should_confirm_pending(state: dict, router_result: dict, message_text: str) -> bool:
    pending = state.get("pending_topic")
    if not pending:
        return False

    confidence = router_result.get("confidence", 0)
    message_count = pending.get("message_count", 0)

    strong_triggers = [
        "좋다", "싫다", "어디", "뭐 먹지", "투표",
        "할게", "맡을게", "예약", "준비", "마감", "담당",
        "보내줘", "알려줘", "연락처", "번호", "전화번호",
        "이메일", "메일", "가능 시간", "가능시간",
    ]

    has_strong_trigger = any(t in message_text for t in strong_triggers)

    return (
        (message_count >= 2 and confidence >= 0.7)
        or (has_strong_trigger and confidence >= 0.75)
        or router_result.get("decision") == "confirm_topic"
    )


def append_unique(target: list, values: list):
    for value in values:
        if value not in target:
            target.append(value)


def merge_opinion_items(topic: dict, new_items: list):
    existing = topic.setdefault("items", [])

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

        append_unique(found["positive_participants"], positive)
        append_unique(found["negative_participants"], negative)
        append_unique(found["source_message_ids"], source_ids)


def merge_task_items(topic: dict, new_items: list):
    existing = topic.setdefault("items", [])

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
                "due": {
                    "date": None,
                    "time": None,
                },
                "status": "todo",
                "source_message_ids": [],
            }
            existing.append(found)

        append_unique(found["assignees"], item.get("assignees", []))

        due = item.get("due") or {}
        if due.get("date") is not None:
            found["due"]["date"] = due["date"]
        if due.get("time") is not None:
            found["due"]["time"] = due["time"]

        if item.get("status") in ["todo", "done", "cancelled"]:
            found["status"] = item["status"]

        append_unique(found["source_message_ids"], source_ids)


def merge_collection_items(topic: dict, fields: list, new_items: list):
    topic_fields = topic.setdefault("fields", [])
    append_unique(topic_fields, [normalize_field_name(field) for field in fields])

    existing = topic.setdefault("items", [])

    for item in new_items:
        participant = item.get("participant")
        values = item.get("values") or {}
        source_ids = item.get("source_message_ids", [])
        if not participant or not values or not source_ids:
            continue

        found = next((old for old in existing if old.get("participant") == participant), None)
        if found is None:
            found = {
                "participant": participant,
                "values": {},
                "source_message_ids": [],
            }
            existing.append(found)

        for field, value in values.items():
            field = normalize_field_name(field)
            if field not in topic_fields:
                topic_fields.append(field)
            found["values"][field] = value

        append_unique(found["source_message_ids"], source_ids)


def fill_collection_nulls(topic: dict):
    if topic.get("structure_type") != "collection":
        return

    fields = topic.setdefault("fields", [])
    for item in topic.setdefault("items", []):
        values = item.setdefault("values", {})
        for field in fields:
            values.setdefault(field, None)


def merge_parser_result(topic: dict, result: dict):
    structure_type = topic.get("structure_type")
    items = normalize_items(result)

    if structure_type == "opinion":
        merge_opinion_items(topic, items)
    elif structure_type == "task":
        merge_task_items(topic, items)
    elif structure_type == "collection":
        merge_collection_items(topic, normalize_fields(result), items)


def has_mergeable_delta(topic: dict, result: dict) -> bool:
    structure_type = topic.get("structure_type")

    for item in normalize_items(result):
        source_ids = item.get("source_message_ids", [])
        if not source_ids:
            continue

        if structure_type == "opinion":
            has_opinion = item.get("positive_participants") or item.get("negative_participants")
            if item.get("target") and has_opinion:
                return True
        elif structure_type == "task":
            if item.get("task"):
                return True
        elif structure_type == "collection":
            if item.get("participant") and item.get("values"):
                return True

    return False


def keep_current_sources_only(result: dict, messages: list) -> dict:
    allowed_ids = {message["message_id"] for message in messages}
    cleaned = dict(result)
    cleaned_items = []

    for item in normalize_items(result):
        next_item = dict(item)
        source_ids = [
            source_id
            for source_id in item.get("source_message_ids", [])
            if source_id in allowed_ids
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
                field = normalize_field_name(field)
                if field not in used_fields:
                    used_fields.append(field)
        cleaned["fields"] = used_fields
    return cleaned


# =========================
# Pipeline
# =========================

def route_message(state: dict, message: dict):
    payload = {
        "message": message,
        "recent_messages": get_recent_messages(state),
        "pending_topic": state.get("pending_topic"),
        "active_topic": get_active_topic(state),
        "topics_summary": get_topics_summary(state),
    }

    result = call_llm(ROUTER_PROMPT, payload)
    decision = result.get("decision")

    print("\n[Router 결과]")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if decision == "noise":
        return

    if decision in ["new_pending", "continue_pending"]:
        start_or_update_pending(state, message, result)

        if should_confirm_pending(state, result, message["text"]):
            topic = create_topic_from_pending(state, result)
            print(f"[Topic 확정] {topic['topic_id']} / {topic['title']} / {topic['structure_type']}")

        return

    if decision == "confirm_topic":
        if state.get("pending_topic") is None:
            start_or_update_pending(state, message, result)

        topic = create_topic_from_pending(state, result)
        print(f"[Topic 확정] {topic['topic_id']} / {topic['title']} / {topic['structure_type']}")
        return

    if decision == "attach_existing":
        topic_id = result.get("topic_id")
        for topic in state["topics"]:
            if topic["topic_id"] == topic_id:
                state["active_topic_id"] = topic_id
                state["active_structure_type"] = topic["structure_type"]
                state["mode"] = "parse"
                parse_messages(state, topic, [message])
                return


def parse_messages(state: dict, topic: dict, messages: list):
    if not messages:
        return

    structure_type = topic["structure_type"]

    if structure_type == "opinion":
        prompt = OPINION_PROMPT
    elif structure_type == "task":
        prompt = TASK_PROMPT
    elif structure_type == "collection":
        prompt = COLLECTION_PROMPT
    else:
        state["mode"] = "routing"
        return

    payload = {
        "current_topic": topic,
        "recent_messages": get_recent_messages(state),
        "topics_summary": get_topics_summary(state),
        "messages": messages,
    }

    result = call_llm(prompt, payload)

    print("\n[Parser 결과]")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    result = keep_current_sources_only(result, messages)

    if result.get("same_topic") is False:
        if has_mergeable_delta(topic, result):
            merge_parser_result(topic, result)
            return

        state["mode"] = "routing"
        state["active_topic_id"] = None
        state["active_structure_type"] = None

        for msg in messages:
            route_message(state, msg)
        return

    merge_parser_result(topic, result)


def process_message(state: dict, message: dict):
    print("\n==============================")
    print(f"[입력] {message['sender']}: {message['text']}")

    try:
        if state["mode"] == "routing":
            route_message(state, message)
            return

        active_topic = get_active_topic(state)

        if active_topic is None:
            state["mode"] = "routing"
            route_message(state, message)
            return

        if active_topic.get("structure_type") != "collection" and has_collection_signal(message["text"]):
            state["mode"] = "routing"
            state["active_topic_id"] = None
            state["active_structure_type"] = None
            route_message(state, message)
            return

        if active_topic.get("structure_type") != "task" and has_task_signal(message["text"]):
            state["mode"] = "routing"
            state["active_topic_id"] = None
            state["active_structure_type"] = None
            route_message(state, message)
            return

        parse_messages(state, active_topic, [message])
    finally:
        state.setdefault("message_history", []).append(message)


# =========================
# Test
# =========================

if __name__ == "__main__":
    state = initial_state()

    messages = [
        {
            "message_id": "m1",
            "sender": "소연",
            "text": "우리 저녁 뭐 먹지?",
        },
        {
            "message_id": "m2",
            "sender": "민수",
            "text": "나는 치킨 좋아",
        },
        {
            "message_id": "m3",
            "sender": "지윤",
            "text": "나는 피자가 더 좋아",
        },
        {
            "message_id": "m4",
            "sender": "소연",
            "text": "그럼 치킨이랑 피자로 투표할까?",
        },
        {
            "message_id": "m5",
            "sender": "민수",
            "text": "아 그리고 숙소 예약은 내가 할게",
        },
        {
            "message_id": "m6",
            "sender": "지윤",
            "text": "나는 장보기 맡을게",
        },
        {
            "message_id": "m7",
            "sender": "소연",
            "text": "연락처도 모아두자",
        },
        {
            "message_id": "m8",
            "sender": "민수",
            "text": "내 번호는 010-1111-2222",
        },
        {
            "message_id": "m9",
            "sender": "지윤",
            "text": "나는 jiyoon@example.com",
        },
    ]

    for msg in messages:
        process_message(state, msg)

    for topic in state["topics"]:
        fill_collection_nulls(topic)

    output = {
        "topics": state["topics"]
    }

    output_path = BASE_DIR / "moyo_pipeline_result.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n\n========== 최종 TOPICS ==========")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n저장 완료: {output_path}")
