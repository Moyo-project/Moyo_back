# pip install -U langgraph

from typing import TypedDict, Dict, List, Optional, Literal
from langgraph.graph import StateGraph, START, END


# =========================
# 1. State 정의
# =========================

class TopicState(TypedDict):
    title: str
    state_type: str
    options: List[str]
    opinions: List[str]
    decision: Optional[str]


class MoyoState(TypedDict):
    message: str
    topics: Dict[str, TopicState]
    active_topic_id: Optional[str]
    route: str
    action: Optional[str]
    response: str


# =========================
# 2. Topic Router
# =========================

def topic_router(state: MoyoState):
    msg = state["message"]
    topics = state["topics"]

    # 아주 단순한 MVP 규칙
    if "먹" in msg or "피자" in msg or "치킨" in msg:
        topic_id = "topic_food"
        title = "메뉴 정하기"
        state_type = "selection"

    elif "언제" in msg or "시간" in msg or "가능" in msg:
        topic_id = "topic_schedule"
        title = "시간 정하기"
        state_type = "deliberation"

    else:
        topic_id = "topic_general"
        title = "일반 대화"
        state_type = "general"

    route = "new_topic" if topic_id not in topics else "existing_topic"

    return {
        "active_topic_id": topic_id,
        "route": route,
        "response": f"선택된 토픽: {title}"
    }


# =========================
# 3. 새 Topic 생성
# =========================

def create_topic(state: MoyoState):
    topic_id = state["active_topic_id"]
    msg = state["message"]
    topics = dict(state["topics"])

    if topic_id == "topic_food":
        title = "메뉴 정하기"
        state_type = "selection"
    elif topic_id == "topic_schedule":
        title = "시간 정하기"
        state_type = "deliberation"
    else:
        title = "일반 대화"
        state_type = "general"

    topics[topic_id] = {
        "title": title,
        "state_type": state_type,
        "options": [],
        "opinions": [],
        "decision": None,
    }

    return {"topics": topics}


# =========================
# 4. 기존 Topic 업데이트
# =========================

def update_topic_state(state: MoyoState):
    msg = state["message"]
    topic_id = state["active_topic_id"]
    topics = dict(state["topics"])

    topic = dict(topics[topic_id])

    # 메뉴 후보 추출
    if topic["state_type"] == "selection":
        options = set(topic["options"])

        if "피자" in msg:
            options.add("피자")
        if "치킨" in msg:
            options.add("치킨")
        if "햄버거" in msg:
            options.add("햄버거")

        topic["options"] = list(options)

    # 의견 저장
    if "난" in msg or "나는" in msg:
        topic["opinions"].append(msg)

    topics[topic_id] = topic

    return {"topics": topics}


# =========================
# 5. Action 판단
# =========================

def decide_action(state: MoyoState):
    topic_id = state["active_topic_id"]
    topic = state["topics"][topic_id]

    if topic["state_type"] == "selection" and len(topic["options"]) >= 2:
        action = "create_vote"
        response = f"후보가 {topic['options']}로 모였어요. 투표를 만들 수 있어요."

    elif topic["state_type"] == "deliberation":
        action = "summarize_schedule"
        response = "시간 관련 대화로 정리할 수 있어요."

    else:
        action = None
        response = "아직 실행할 기능은 없어요."

    return {
        "action": action,
        "response": response
    }


# =========================
# 6. 분기 함수
# =========================

def route_topic(state: MoyoState) -> Literal["create_topic", "update_topic_state"]:
    if state["route"] == "new_topic":
        return "create_topic"
    return "update_topic_state"


# =========================
# 7. Graph 구성
# =========================

builder = StateGraph(MoyoState)

builder.add_node("topic_router", topic_router)
builder.add_node("create_topic", create_topic)
builder.add_node("update_topic_state", update_topic_state)
builder.add_node("decide_action", decide_action)

builder.add_edge(START, "topic_router")

builder.add_conditional_edges(
    "topic_router",
    route_topic,
    {
        "create_topic": "create_topic",
        "update_topic_state": "update_topic_state",
    }
)

builder.add_edge("create_topic", "update_topic_state")
builder.add_edge("update_topic_state", "decide_action")
builder.add_edge("decide_action", END)

graph = builder.compile()


# =========================
# 8. 테스트 실행
# =========================

state: MoyoState = {
    "message": "",
    "topics": {},
    "active_topic_id": None,
    "route": "",
    "action": None,
    "response": "",
}

messages = [
    "뭐 먹지?",
    "피자 어때?",
    "치킨도 괜찮아",
    "나는 피자",
    "언제 만날까?",
    "난 3시 이후 가능",
]

for msg in messages:
    state["message"] = msg
    state = graph.invoke(state)

    print("\nUSER:", msg)
    print("ACTIVE TOPIC:", state["active_topic_id"])
    print("ACTION:", state["action"])
    print("RESPONSE:", state["response"])
    print("TOPICS:", state["topics"])