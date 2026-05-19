# Moyo AI Agent 스펙 문서

> 작성일: 2026-05-19
> 대상 마일스톤: 2026-06 중간 발표 시연
> 작성자: 캡스톤디자인 팀 "소유"

---

## 1. 목표

Moyo의 그룹 채팅 안에서 **대화 흐름을 실시간으로 이해하고 적절한 협업 작업(투표·일정·요약 등)을 자동 제안·실행**하는 AI 에이전트를 추가한다.

핵심 차별점은 두 가지다.

1. **멘션 없는 트리거** — 사용자가 `@AI`를 부르지 않아도 키워드·누적량·침묵을 감지해 자연스럽게 개입한다.
2. **온디바이스 1차 처리 + 마스킹된 클라우드 호출** — 채팅 전체를 외부 서버로 전송하지 않고, 브라우저에서 1차 분류·키워드 추출 후 필요한 경우에만 마스킹된 텍스트를 LLM API로 전송한다.

---

## 2. 시스템 개요

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite, 브라우저)                              │
│                                                               │
│  ┌─────────────┐  ┌──────────────────────────┐                │
│  │ ChatRoomPanel│ │  AgentObserver (신규)     │                │
│  │              │ │  - 키워드/패턴 감지        │                │
│  │              │ │  - 침묵 타이머           │                │
│  │              │ │  - 누적 카운터           │                │
│  └─────┬───────┘ └──────────┬───────────────┘                │
│        │                    │                                 │
│        │             ┌──────▼─────────────┐                   │
│        │             │ OnDeviceNLP (신규)  │                   │
│        │             │ - WebLLM / Trans-  │                   │
│        │             │   formers.js       │                   │
│        │             │ - 1차 의도 분류      │                   │
│        │             │ - PII 마스킹         │                   │
│        │             └──────┬─────────────┘                   │
│        │                    │                                 │
│        ▼                    ▼                                 │
│  ┌─────────────────────────────────────────┐                  │
│  │  AgentSuggestionCard (신규 UI)            │                │
│  │  - 투표 만들기 / 일정 정리 / 요약 보기     │                │
│  └────────────────┬────────────────────────┘                  │
└───────────────────┼──────────────────────────────────────────┘
                    │ WebSocket (기존) + REST (/agent/*)
                    ▼
┌──────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                            │
│                                                               │
│  ┌────────────────────┐   ┌──────────────────────────────┐   │
│  │ /ws/rooms/{room_id}│   │ /agent/* (신규 라우터)         │   │
│  │ (기존, 변경 최소)    │   │  - POST /agent/analyze        │   │
│  └─────────┬──────────┘   │  - POST /agent/vote           │   │
│            │              │  - POST /agent/schedule        │   │
│            │              │  - POST /agent/summarize       │   │
│            │              └────────────┬──────────────────┘   │
│            │                           │                       │
│            ▼                           ▼                       │
│  ┌──────────────────────────────────────────────────┐         │
│  │  agent_service.py (신규)                          │         │
│  │  - CLOVA Studio API 호출 (마스킹된 입력만)          │         │
│  │  - Function Calling/Structured Outputs 기반 응답    │         │
│  └─────────────────────────┬────────────────────────┘         │
│                            │                                   │
│  ┌─────────────────────────▼────────────────────────┐         │
│  │  MariaDB                                          │         │
│  │  - agent_suggestions (신규)                        │         │
│  │  - votes / vote_options / vote_responses (신규)    │         │
│  │  - schedule_polls (신규)                           │         │
│  │  - room_summaries (신규)                           │         │
│  └──────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 트리거 설계 (멘션 없음)

세 가지 트리거를 병행 운영한다.

### 3.1 키워드/패턴 트리거 (즉시 반응)

| 카테고리 | 키워드/패턴 예시 | 발화 의도 |
|---------|-----------------|----------|
| 의사결정 | "뭐 먹지", "어디서", "골라줘", "추천", "~할까 ~할까" | 투표 |
| 일정 | "언제", "몇 시", "다음주 \w요일", "\d+시 (이후\|전\|쯤)", "오전/오후" | 일정 조율 |
| 정보 누락 | "아까 뭐였더라", "다시 알려줘", "지난번에" | 요약/검색 |

- 정규식 + 형태소 분석(온디바이스)으로 1차 필터링.
- 매치 시 **온디바이스 분류기**가 confidence 점수를 부여 (임계치 0.6 이상만 제안 카드 표시).

### 3.2 누적 메시지 트리거 (요약)

- 마지막 AI 개입 시점 이후 **30개 메시지** 누적되면 "요약해드릴까요?" 카드 표시.
- 새 멤버가 방에 입장하면 최근 1시간 메시지를 즉시 요약 제안.

### 3.3 침묵 감지 트리거 (의사결정 정체)

- 키워드 트리거에서 "후보가 2개 이상 언급된 의사결정 발화" 감지 후 **5분간 응답이 없으면** → "투표로 정리할까요?" 자동 제안.
- 누군가 일정 표현을 던졌는데 응답 없이 새 토픽이 시작되면 → "미해결 일정이 있어요" 알림.

> ❗ 모든 트리거는 **제안(카드)** 단계에서 멈춘다. 사용자가 카드를 탭해야 실제 동작(투표 생성, API 호출 등)이 일어난다. AI 폭주 방지.

---

## 4. 프라이버시 모델 (온디바이스 우선)

### 4.1 처리 계층

```
[원문 메시지] ──▶ [온디바이스 NLP] ──▶ [의도 분류 / 엔티티 추출]
                                       │
                          ┌────────────┴───────────┐
                  로컬에서 처리 가능?              불가능 (복잡)
                          │                         │
                          ▼                         ▼
              [로컬 응답 카드 생성]          [PII 마스킹] ─▶ [CLOVA Studio API]
                                                            │
                                                            ▼
                                                    [구조화 응답]
```

### 4.2 온디바이스 처리 대상 (외부 전송 0)

- 키워드/패턴 매칭
- 한국어 형태소 분석 (한국어 토크나이저 WASM)
- 시간 표현 파싱 ("3시 이후", "다음주 화요일")
- 음식·장소 후보 추출 (NER, 경량 모델)
- 의도 분류 (분류 헤드만 — 5~10MB 수준)

**모델 후보**: 
- [Transformers.js](https://huggingface.co/docs/transformers.js) + `distiluse-base-multilingual-cased` (임베딩)
- [WebLLM](https://webllm.mlc.ai/) + Qwen2.5-0.5B (보조, 선택)
- 자체 학습 KoBERT 경량 분류기 (가능하면)

### 4.3 클라우드 전송이 필요한 경우 (마스킹 후 CLOVA Studio API)

| 작업 | 클라우드 필요 사유 |
|------|------------------|
| 대화 요약 (10개 메시지 이상) | 온디바이스 LLM은 품질 한계 |
| 일정 충돌 분석 + 자연어 설명 | 추론 깊이 필요 |
| 모호한 의도 분류 (confidence < 0.6) | fallback |

**마스킹 규칙** (전송 전 클라이언트에서 수행):

| 종류 | 원문 → 마스킹 |
|------|-------------|
| 사람 이름 | `이유정` → `USER_1` (방 내 일관성 유지) |
| 전화번호 | `010-xxxx-xxxx` → `[PHONE]` |
| 이메일 | `*@*.*` → `[EMAIL]` |
| 정확한 주소 | `용인시 기흥구 ...` → `[ADDRESS]` |
| 금액 | `38,400원` → `[AMOUNT]` (선택) |

마스킹 매핑 테이블은 **세션 메모리에만 보관**, 응답 수신 후 역치환(unmask).

### 4.4 사용자 동의

- 그룹 채팅방 설정 화면에 토글: 
  - "AI 기능 사용" (기본 ON)
  - "마스킹 후 외부 AI(HyperCLOVA X) 호출 허용" (기본 OFF — 명시적 옵트인)
- OFF 시 온디바이스 기능만 동작 (요약 품질 저하 경고 표시).

---

## 5. 데이터 모델 (DB 변경)

기존 `messages`, `chat_rooms`, `room_members`, `groups`, `users`는 **변경 없음**. 다음 테이블만 신규 추가.

### 5.1 `agent_suggestions` — AI가 띄운 제안 카드

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| room_id | BIGINT FK | chat_rooms.id |
| trigger_message_id | BIGINT FK NULL | messages.id (트리거된 발화) |
| suggestion_type | ENUM | `vote`, `schedule`, `summary` |
| payload | JSON | 타입별 페이로드 (후보 목록, 시간 범위 등) |
| status | ENUM | `pending`, `accepted`, `dismissed`, `expired` |
| confidence | FLOAT | 트리거 신뢰도 |
| created_at | DATETIME | |
| resolved_at | DATETIME NULL | |

### 5.2 `votes` / `vote_options` / `vote_responses`

```sql
votes (id, room_id, creator_id [NULL이면 AI 생성], question, created_at, closed_at)
vote_options (id, vote_id, label, order_idx)
vote_responses (id, vote_id, option_id, user_id, created_at, UNIQUE(vote_id, user_id))
```

### 5.3 `schedule_polls` / `schedule_slots` / `schedule_responses`

```sql
schedule_polls (id, room_id, creator_id, title, date_range_start, date_range_end, created_at, closed_at)
schedule_slots (id, poll_id, start_at, end_at)
schedule_responses (id, slot_id, user_id, availability ENUM('yes','no','maybe'))
```

### 5.4 `room_summaries`

| 컬럼 | 타입 |
|------|------|
| id | BIGINT PK |
| room_id | BIGINT FK |
| from_message_id | BIGINT FK |
| to_message_id | BIGINT FK |
| summary_text | TEXT |
| created_at | DATETIME |

---

## 6. 백엔드 API 명세

신규 라우터 `app/routers/agent.py`. 모든 엔드포인트는 JWT 인증 필수 (`Depends(get_current_user)`).

### 6.1 분석 fallback 엔드포인트

`POST /agent/analyze`

온디바이스 분류기의 confidence가 낮을 때만 호출.

```json
// Request
{
  "room_id": 12,
  "masked_messages": [
    {"role": "USER_1", "content": "오늘 뭐 먹지", "ts": "..."},
    {"role": "USER_2", "content": "피자 어때", "ts": "..."}
  ],
  "task_hint": "decision"
}

// Response
{
  "intent": "vote",
  "confidence": 0.92,
  "extracted": {
    "question": "오늘 뭐 먹을까요?",
    "options": ["피자", "치킨"]
  }
}
```

### 6.2 투표 생성/응답

```
POST   /agent/vote                생성 (AI 또는 사용자)
GET    /agent/vote/{vote_id}      현황 조회
POST   /agent/vote/{vote_id}/respond
POST   /agent/vote/{vote_id}/close
```

생성 후 자동으로 해당 채팅방에 시스템 메시지(`user_id=NULL`, `content`=투표 카드 메타) 브로드캐스트.

### 6.3 일정 조율

```
POST   /agent/schedule            폴 생성
POST   /agent/schedule/{id}/respond
GET    /agent/schedule/{id}/recommend   AI 추천 시간 (CLOVA Studio 호출, 마스킹)
```

### 6.4 요약

```
POST   /agent/summarize           { room_id, from_message_id, to_message_id? }
GET    /agent/summary/recent?room_id=...
```

---

## 7. 프론트엔드 변경

### 7.1 신규 파일

```
src/
├── agent/
│   ├── AgentObserver.ts         # 전역 메시지 옵저버 (싱글톤)
│   ├── triggers/
│   │   ├── keywordTrigger.ts    # 키워드/패턴 감지
│   │   ├── accumulationTrigger.ts # 누적 카운트
│   │   └── silenceTrigger.ts    # 침묵 타이머
│   ├── nlp/
│   │   ├── onDeviceClassifier.ts # Transformers.js 래퍼
│   │   ├── piiMasker.ts          # 마스킹/언마스킹
│   │   └── timeParser.ts         # 한국어 시간 표현 파서
│   └── api.ts                    # /agent/* 호출
├── components/
│   ├── AgentSuggestionCard.tsx   # 채팅창 위에 뜨는 제안 카드
│   ├── VoteCard.tsx              # 인라인 투표 UI
│   ├── ScheduleCard.tsx          # 인라인 일정 폴 UI
│   └── SummaryDrawer.tsx         # 요약 사이드 패널
└── store/slices/
    └── agentSlice.ts             # 제안/투표 상태
```

### 7.2 기존 변경 지점

- `useChatSocket.ts`: 메시지 수신 시 `AgentObserver.observe(msg)` 호출 추가 (한 줄).
- `ChatRoomPanel.tsx`: 메시지 목록 위에 `<AgentSuggestionCard />` 슬롯 + 시스템 메시지(`user_id == null`) 렌더링 분기 추가.

### 7.3 의존성 추가

```json
{
  "@xenova/transformers": "^2.x",   // 온디바이스 NLP
  "chrono-node": "^2.x",             // 자연어 날짜 파서 (한국어 보조)
  "date-fns": "^3.x"                 // 이미 있을 수 있음
}
```

WebLLM(선택)은 별도 dynamic import로 로딩, 모델 크기 때문에 사용자 명시적 활성화 시에만.

---

## 8. HyperCLOVA X / CLOVA Studio API 사용 패턴 (백엔드)

### 8.1 모델 선택

- **HCX-DASH-002**: 의도 분류 fallback, 후보 추출, 짧은 요약 등 빠른 응답이 필요한 기본 모델.
- **HCX-007**: 복잡한 일정 충돌 분석, 긴 대화 요약, 추론 품질이 중요한 작업.
- **HCX-005**: 이미지 입력이 필요한 확장 기능이 생길 때만 사용. 현재 채팅 텍스트 기반 MVP에는 제외.

모델명은 CLOVA Studio 콘솔/API 문서의 최신 제공 모델명을 기준으로 환경변수에서 교체 가능하게 둔다.

### 8.2 API 호출 방식

- 백엔드는 `app/services/agent_service.py`에서 CLOVA Studio Chat Completions v3 API를 호출한다.
- 인증 키는 서버 환경변수(`CLOVA_STUDIO_API_KEY`)로만 관리하고 프론트엔드에는 노출하지 않는다.
- 네트워크 전송 데이터는 클라이언트에서 마스킹된 메시지와 작업 힌트만 포함한다.
- 응답은 가능하면 JSON Schema 기반 Structured Outputs를 사용하고, 기능 실행이 필요한 경우 Function Calling을 사용한다.

### 8.3 Function Calling / Structured Outputs로 구조화 출력

자유 텍스트 응답 대신 함수/스키마 정의로 강제:

```python
functions = [
  {
    "name": "create_vote",
    "description": "후보가 있는 의사결정 발화에서 투표 생성",
    "input_schema": {
      "type": "object",
      "properties": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["question", "options"]
    }
  },
  {
    "name": "extract_schedule",
    "description": "일정 발화에서 가능 시간대 추출",
    "input_schema": { ... }
  },
  {
    "name": "summarize",
    "description": "긴 대화 요약",
    "input_schema": { ... }
  }
]
```

### 8.4 비용 가드

- 방당 일일 CLOVA Studio 호출 횟수 상한 (예: 50회).
- 사용자당 분당 호출 상한 (예: 5회).
- 한도 초과 시 온디바이스 fallback으로 그레이스풀 디그레이드.
- `maxTokens`는 작업별로 작게 설정한다. 의도 분류는 256~512, 요약은 1,024~2,048부터 시작한다.
- 입력/출력 토큰을 모두 로깅해 방 단위 사용량을 확인하고, 일일 예산 초과 시 클라우드 기능을 일시 중지한다.

---

## 9. 사용자 흐름 예시

### 시나리오 1: 점심 메뉴 결정

```
[14:01] 유정: 오늘 점심 뭐 먹지
[14:01] 소연: 음 글쎄
[14:02] 상권: 피자 어때
[14:02] 유정: 치킨도 좋고
[14:02] 소연: 파스타도 괜찮은데
[14:03] (5분 무응답)

▼ AI 카드 자동 표시 (침묵 트리거 + 키워드 트리거 결합)
┌─────────────────────────────────────┐
│ 🗳️  투표로 정리할까요?                  │
│   질문: 오늘 점심 뭐 먹을까요?           │
│   후보: 피자 / 치킨 / 파스타            │
│   [만들기]  [수정]  [무시]             │
└─────────────────────────────────────┘
```

- 후보 추출까지는 **온디바이스 NER**에서 처리.
- "만들기" 탭 시 `POST /agent/vote` → 채팅창에 인라인 투표 카드 등장.

### 시나리오 2: 새 멤버 합류

```
[새 멤버 입장]
▼ AI 카드 (누적 트리거)
┌─────────────────────────────────────┐
│ 📋 최근 대화 요약 보기                  │
│   지난 1시간 동안 32개 메시지가 있었어요. │
│   [요약 보기]  [건너뛰기]              │
└─────────────────────────────────────┘
```

- "요약 보기" 클릭 → 마스킹된 메시지를 `/agent/summarize`로 전송 → 사이드 드로워에 요약 표시 (전체 채팅창에 뿌리지 않음, 본인만 봄).

---

## 10. 마일스톤 (5월 ~ 6월)

| 주차 | 일정 | 담당 | 산출물 |
|------|-----|------|--------|
| 5/3주 | 키워드 트리거 + 정규식 라이브러리 | 신소연 | `keywordTrigger.ts` |
| 5/3주 | DB 마이그레이션 (4개 테이블) + `/agent/vote` REST | 이유정 | alembic 마이그레이션, 라우터 |
| 5/4주 | Transformers.js 통합 + 의도 분류 | 신소연 | `onDeviceClassifier.ts` |
| 5/4주 | `AgentSuggestionCard` + `VoteCard` UI | 이유정 | 컴포넌트 |
| 6/1주 | CLOVA Studio API 연동 (요약) + 마스킹 | 신소연 + 이유정 | `agent_service.py`, `piiMasker.ts` |
| 6/1주 | 침묵 트리거 + 누적 트리거 | 신소연 | `silenceTrigger.ts`, `accumulationTrigger.ts` |
| 6/2주 | 일정 조율 (`ScheduleCard` + 추천 API) | 이유정 + 신소연 | 폴 UI, `/agent/schedule/recommend` |
| 6/3주 | 통합 테스트 + 발표 시나리오 리허설 | 전원 | 데모 시나리오 |
| 6/4주 | 발표 자료, 영상, 시연 | 정상권 + 전원 | 발표 |

**Cut line (시간 부족 시 우선 포기 순)**: 일정 추천 AI → 침묵 트리거 → 새 멤버 자동 요약. 투표/키워드 트리거/요약 수동 호출은 절대 사수.

---

## 11. 리스크 & 대응

| 리스크 | 영향 | 대응 |
|-------|------|------|
| 온디바이스 모델 로딩 시간 (수 초~수십 초) | UX | 첫 채팅방 진입 시 비동기 워밍업, 로딩 인디케이터 |
| 한국어 NER 품질 부족 | 후보 추출 오류 | 정규식 + 화이트리스트(음식 사전) 병행 |
| CLOVA Studio API 응답 지연 | 채팅 흐름 끊김 | 비동기 처리 + "AI가 정리 중..." 토스트 |
| 마스킹 누락으로 PII 유출 | 프라이버시 | 마스킹 규칙 단위 테스트 필수, 화이트박스 토글 (사용자가 마스킹 결과 미리보기) |
| AI 카드 과다 노출 → 피로감 | UX | 동일 방에 동시 최대 1개 카드, 10분 쿨다운 |
| CLOVA Studio API 비용 폭주 | 예산 | §8.4 비용 가드, 일일 토큰 상한 알림 |

---

## 12. 비고: 보고서와의 매핑

| 보고서 항목 | 본 스펙 대응 |
|-----------|-------------|
| "대화 내용 구조화" | §5 `agent_suggestions`, §7.1 `AgentObserver` |
| "대화 유형 분류" | §4.2 온디바이스 분류기 + §8 HyperCLOVA X Function Calling/Structured Outputs |
| "유형에 따른 기능 추천" | §3 트리거 + §9 시나리오 |
| "형태소 분석, NER, 임베딩, LLM" | §4.2 (전부 온디바이스 1차) + §8 (LLM은 fallback) |
| "투표/일정/요약" | §6 API 명세 |
| "비동기 처리 구조" | §6 REST + §11 비동기 토스트 |
| "AI가 채팅 경험을 방해하지 않게" | §3 제안 카드만 표시, §11 쿨다운 |

---

## 13. 다음 단계 (스펙 확정 후)

1. 이 문서에 대한 팀 리뷰 (5/20 회의 안건)
2. alembic 마이그레이션 PR 생성 (이유정)
3. Transformers.js 모델 후보 PoC (신소연) — 한국어 의도 분류 정확도 측정
4. CLOVA Studio API 키 발급 + 백엔드 환경변수 설정 (이유정)
5. 마스킹 규칙 단위 테스트 작성 (신소연)
