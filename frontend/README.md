# LinkPaper Frontend

React + Vite + pnpm 기반 프론트엔드입니다. 백엔드(FastAPI)가 준비되기 전까지는
`VITE_USE_MOCK=true` 로 하드코딩된 목업 데이터/스트리밍으로 전체 UI를 확인할 수 있습니다.

## 실행

```bash
pnpm install
cp .env.example .env
pnpm dev
```

`http://localhost:5173` 에서 확인합니다.

## 목업 → 실제 백엔드 전환

1. `.env`에서 `VITE_USE_MOCK=false` 로 변경
2. FastAPI 서버를 `http://localhost:8000` (또는 `vite.config.js`의 proxy target)에서 실행
3. 아래 계약에 맞춰 엔드포인트 2개를 구현하면, **컴포넌트 코드 수정 없이** 그대로 연동됩니다.

### `GET /api/papers`

```json
[
  { "id": "p-001", "title": "...", "authors": "...", "year": 2017, "venue": "...", "tags": ["..."] }
]
```

### `POST /api/chat/stream` (text/event-stream)

요청 본문:

```json
{
  "paperId": "p-001",
  "mode": "paper-qa | graph-rag-qa | research-flow",
  "message": "사용자 질문",
  "history": [{ "role": "user | assistant", "content": "..." }]
}
```

응답은 SSE 스트림이며, 각 라인은 `data: {json}\n\n` 형식입니다. 지원하는 이벤트 타입:

| type | 설명 | payload |
|---|---|---|
| `token` | 답변 텍스트 조각(스트리밍) | `{ "text": "..." }` |
| `citations` | 그래프에서 인용된 논문 노드 | `{ "citations": [{ "id", "label", "relation" }] }` |
| `flow` | Research Flow 모드 전용, 선행/현재/후속 연구 | `{ "flow": [{ "stage", "label" }] }` |
| `done` | 스트림 종료 | `{}` |
| `error` | 에러 발생 | `{ "message": "..." }` |

랭체인/랭그래프 쪽에서 노드 실행 결과를 위 이벤트 스키마로 감싸서 `StreamingResponse`로 흘려보내면 됩니다.

## 폴더 구조

```
src/
├── api/            # 목업/실제 백엔드 호출 (index.js가 스위치 역할)
├── components/
│   ├── Layout/     # 전체 레이아웃 셸
│   ├── Sidebar/    # 논문 선택, 모드 선택, 예시 질문
│   ├── Chat/       # 메시지 리스트/버블, 인용 칩, 흐름 스트립, 입력창
│   └── Feedback/   # 토스트
├── data/           # 하드코딩 목업 데이터
├── store/          # zustand 상태 (채팅, 토스트)
├── styles/         # 디자인 토큰(CSS 변수)
└── utils/          # SSE 파서 등
```

## 디자인 토큰

`src/styles/tokens.css` 에 정의되어 있습니다. 배경은 화이트/아이보리, 강조색은
소프트 퍼플 계열(`--purple-*`)로 통일했고, 토스트/에러 팝업 헤더는 항상 연한
퍼플(`--purple-50` 배경 + `--purple-700` 텍스트)을 사용하도록 고정했습니다.
