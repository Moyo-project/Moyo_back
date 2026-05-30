from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer, util
import os
import json
import uuid


# =========================
# 0. 환경 설정
# =========================

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")

CLOVA_API_KEY = os.getenv("CLOVA_API_KEY")

if not CLOVA_API_KEY:
    raise ValueError(
        f"CLOVA_API_KEY를 찾을 수 없습니다. .env 위치 확인: {ROOT_DIR / '.env'}"
    )


# =========================
# 1. 데이터 구조
# =========================

@dataclass
class Message:
    message_id: str
    speaker: str
    text: str
    topic_id: Optional[str] = None
    parent_id: Optional[str] = None


@dataclass
class Topic:
    topic_id: str
    title: str
    summary: str
    message_ids: List[str] = field(default_factory=list)


# =========================
# 2. JSON 파서
# =========================

def extract_json(text: str) -> dict:
    if not text:
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


# =========================
# 3. LLM 기반 Disentangler
# =========================

class ClovaConversationDisentangler:
    def __init__(
        self,
        model_name: str = "HCX-007",
        top_k_topics: int = 5,
        recent_messages_per_topic: int = 5,
        confidence_threshold: float = 0.65,
    ):
        self.client = OpenAI(
            api_key=CLOVA_API_KEY,
            base_url="https://clovastudio.stream.ntruss.com/v1/openai",
        )

        self.model_name = model_name
        self.top_k_topics = top_k_topics
        self.recent_messages_per_topic = recent_messages_per_topic
        self.confidence_threshold = confidence_threshold

        self.embedder = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )

        self.messages: List[Message] = []
        self.topics: Dict[str, Topic] = {}

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _get_message(self, message_id: str) -> Optional[Message]:
        for msg in self.messages:
            if msg.message_id == message_id:
                return msg
        return None

    def _topic_text_for_embedding(self, topic: Topic) -> str:
        recent_texts = []

        for mid in topic.message_ids[-self.recent_messages_per_topic:]:
            msg = self._get_message(mid)
            if msg:
                recent_texts.append(f"{msg.speaker}: {msg.text}")

        return f"""
제목: {topic.title}
요약: {topic.summary}
최근 메시지:
{chr(10).join(recent_texts)}
""".strip()

    def _select_candidate_topics(self, new_text: str):
        if not self.topics:
            return []

        topic_list = list(self.topics.values())

        new_emb = self.embedder.encode(
            new_text,
            convert_to_tensor=True,
        )

        topic_texts = [
            self._topic_text_for_embedding(topic)
            for topic in topic_list
        ]

        topic_embs = self.embedder.encode(
            topic_texts,
            convert_to_tensor=True,
        )

        scores = util.cos_sim(new_emb, topic_embs)[0]

        ranked = sorted(
            zip(topic_list, scores.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        return ranked[:self.top_k_topics]

    def _build_llm_prompt(
        self,
        speaker: str,
        text: str,
        candidate_topics,
    ) -> str:
        topic_blocks = []

        for topic, sim_score in candidate_topics:
            recent_messages = []

            for mid in topic.message_ids[-self.recent_messages_per_topic:]:
                msg = self._get_message(mid)
                if msg:
                    recent_messages.append({
                        "message_id": msg.message_id,
                        "speaker": msg.speaker,
                        "text": msg.text,
                    })

            topic_blocks.append({
                "topic_id": topic.topic_id,
                "title": topic.title,
                "summary": topic.summary,
                "embedding_similarity": round(float(sim_score), 4),
                "recent_messages": recent_messages,
            })

        payload = {
            "new_message": {
                "speaker": speaker,
                "text": text,
            },
            "candidate_topics": topic_blocks,
        }

        prompt = f"""
너는 실시간 채팅방의 메시지를 주제별로 매우 정교하게 분리하는 시스템이다.

목표:
새 메시지가 기존 topic 중 하나에 이어지는지,
아니면 완전히 새로운 topic인지 판단한다.

판단 기준:
1. 단어 유사도보다 대화 의도와 맥락을 우선한다.
2. 같은 목적의 대화면 기존 topic에 연결한다.
   예: "MT 어디 갈까?" → "제주도 괜찮은데" → 같은 topic
3. 세부 선택지가 달라도 같은 논의 흐름이면 같은 topic이다.
   예: "제주도 괜찮은데"와 "부산도 좋아"는 MT 장소 논의이므로 같은 topic
4. 완전히 다른 목적이면 새 topic이다.
   예: "MT 어디 갈까?"와 "오늘 저녁 뭐 먹을래?"는 다른 topic
5. 기존 topic에 연결할 경우, 가장 직접적으로 이어지는 parent_message_id를 고른다.
6. 애매하면 무리해서 붙이지 말고 new_topic으로 판단한다.
7. 반드시 JSON 객체 하나만 출력한다.
8. 설명, 마크다운, 코드블록, JSON 외 텍스트는 출력하지 않는다.

입력:
{json.dumps(payload, ensure_ascii=False, indent=2)}

출력 형식:
{{
  "decision": "attach_existing_topic" 또는 "new_topic",
  "topic_id": "기존 topic_id 또는 null",
  "parent_message_id": "기존 message_id 또는 null",
  "confidence": 0.0,
  "reason": "짧은 판단 이유",
  "new_topic_title": "새 topic이면 제목, 아니면 null",
  "updated_topic_summary": "갱신된 topic 요약"
}}
"""
        return prompt

    def _call_llm(self, prompt: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 실시간 채팅 토픽 분리 시스템이다. "
                        "반드시 JSON 객체 하나만 출력한다."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
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
            return {
                "decision": "new_topic",
                "topic_id": None,
                "parent_message_id": None,
                "confidence": 0.0,
                "reason": "JSON 파싱 실패",
                "new_topic_title": None,
                "updated_topic_summary": None,
            }

        return parsed

    def _create_topic(
        self,
        msg: Message,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> dict:
        topic_id = self._new_id("topic")

        msg.topic_id = topic_id
        msg.parent_id = None

        topic = Topic(
            topic_id=topic_id,
            title=title or msg.text[:30],
            summary=summary or msg.text,
            message_ids=[msg.message_id],
        )

        self.topics[topic_id] = topic

        return {
            "message_id": msg.message_id,
            "speaker": msg.speaker,
            "text": msg.text,
            "decision": "new_topic",
            "topic_id": topic_id,
            "parent_id": None,
            "confidence": 1.0,
            "reason": "새 topic 생성",
            "topic_title": topic.title,
            "topic_summary": topic.summary,
        }

    def _attach_to_topic(
        self,
        msg: Message,
        decision: dict,
    ) -> dict:
        topic_id = decision.get("topic_id")
        topic = self.topics[topic_id]

        msg.topic_id = topic_id
        msg.parent_id = decision.get("parent_message_id")

        topic.message_ids.append(msg.message_id)

        if decision.get("updated_topic_summary"):
            topic.summary = decision["updated_topic_summary"]

        return {
            "message_id": msg.message_id,
            "speaker": msg.speaker,
            "text": msg.text,
            "decision": "attach_existing_topic",
            "topic_id": topic_id,
            "parent_id": msg.parent_id,
            "confidence": decision.get("confidence", 0.0),
            "reason": decision.get("reason"),
            "topic_title": topic.title,
            "topic_summary": topic.summary,
        }

    def add_message(
        self,
        speaker: str,
        text: str,
    ) -> dict:
        msg = Message(
            message_id=self._new_id("msg"),
            speaker=speaker,
            text=text,
        )

        if not self.messages:
            result = self._create_topic(msg)
            self.messages.append(msg)
            return result

        candidate_topics = self._select_candidate_topics(text)

        prompt = self._build_llm_prompt(
            speaker=speaker,
            text=text,
            candidate_topics=candidate_topics,
        )

        decision = self._call_llm(prompt)

        confidence = float(decision.get("confidence", 0.0) or 0.0)

        if (
            decision.get("decision") == "attach_existing_topic"
            and decision.get("topic_id") in self.topics
            and confidence >= self.confidence_threshold
        ):
            result = self._attach_to_topic(msg, decision)
        else:
            result = self._create_topic(
                msg=msg,
                title=decision.get("new_topic_title") or text[:30],
                summary=decision.get("updated_topic_summary") or text,
            )

        self.messages.append(msg)
        return result

    def print_topics(self):
        print("\n================ TOPICS ================")

        for topic_id, topic in self.topics.items():
            print(f"\n[{topic_id}] {topic.title}")
            print(f"summary: {topic.summary}")

            for mid in topic.message_ids:
                msg = self._get_message(mid)
                if not msg:
                    continue

                parent = msg.parent_id if msg.parent_id else "-"
                print(f"  - ({msg.speaker}) {msg.text} | parent={parent}")

    def export_state(self) -> dict:
        return {
            "topics": [
                {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "summary": topic.summary,
                    "messages": [
                        {
                            "message_id": msg.message_id,
                            "speaker": msg.speaker,
                            "text": msg.text,
                            "parent_id": msg.parent_id,
                        }
                        for mid in topic.message_ids
                        if (msg := self._get_message(mid)) is not None
                    ],
                }
                for topic in self.topics.values()
            ]
        }


# =========================
# 4. 실행 테스트
# =========================

if __name__ == "__main__":
    disentangler = ClovaConversationDisentangler(
        model_name="HCX-007",
        top_k_topics=5,
        recent_messages_per_topic=5,
        confidence_threshold=0.65,
    )

    messages = [
        ("민지", "MT 어디로 갈까?"),
        ("서연", "제주도 괜찮은데"),
        ("지훈", "근데 예산은 얼마 정도야?"),
        ("하은", "나는 부산도 좋아"),
        ("민지", "부산이면 숙소가 좀 싸려나?"),
        ("준호", "오늘 저녁 뭐 먹을래?"),
        ("서연", "치킨 먹고 싶다"),
        ("지훈", "MT는 1박 2일로 가는 거야?"),
        ("하은", "치킨 말고 떡볶이도 괜찮음"),
        ("민지", "제주도는 비행기값이 좀 부담될 듯"),
    ]

    for speaker, text in messages:
        result = disentangler.add_message(
            speaker=speaker,
            text=text,
        )
        print("\n[처리 결과]")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    disentangler.print_topics()

    output_path = BASE_DIR / "conversation_disentanglement_result.json"
    output_path.write_text(
        json.dumps(disentangler.export_state(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n저장 완료: {output_path}")