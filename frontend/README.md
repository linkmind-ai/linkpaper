# LinkPaper Frontend

React + Vite + pnpm 기반 프론트엔드입니다. 기본값으로 실제 백엔드(FastAPI)에 연결되며,
백엔드 없이 UI만 확인할 때는 `VITE_USE_MOCK=true` 로 목업 데이터/스트리밍을 사용합니다.

## 레이아웃

```
┌───────────────┬────╢────────────────────────┬────╢──────────────────────┐
│    Sidebar     │  ⋮ │      Paper Viewer         │  ⋮ │      Chat Panel        │
│  (드래그 가능)  │  ⋮ │      (드래그 가능)         │  ⋮ │  (남은 영역 자동 채움)   │
│                │  ⋮ │                            │  ⋮ │                        │
│ arXiv 검색      │  ⋮ │ 접기/펼치기 가능한 헤더     │  ⋮ │  메시지 스트리밍        │
│ 예시 질문       │  ⋮ │ (arXiv 메타데이터)         │  ⋮ │  인용 노드 칩           │
│                │  ⋮ │ 초록 / PDF 미리보기 탭     │  ⋮ │  흐름 스트립            │
└───────────────┴────╢────────────────────────┴────╢──────────────────────┘
                   드래그 핸들                     드래그 핸들
```

- **순서**: 좌측 메뉴 → 가운데 논문 뷰어 → 우측 채팅
- **패널 간 경계(`⋮` 표시)를 마우스로 드래그**하면 사이드바/논문 뷰어 너비를 조절할 수 있습니다
  (`src/hooks/useResizablePanels.js`). 채팅 패널은 나머지 공간을 자동으로 채웁니다.
- 논문 뷰어 상단의 제목/메타/링크 영역은 우측 상단 화살표 버튼으로 **접고 펼 수** 있어,
  접으면 초록/PDF 본문에 더 넓은 공간을 확보할 수 있습니다.
- 기본 너비와 최소/최대값은 `useResizablePanels.js` 상단의 `SIDEBAR_MIN/MAX`,
  `PAPER_MIN`, `PAPER_DEFAULT` 상수에서 조절합니다.

## 단일 대화 파이프라인 (기능 선택 없음)

과거에는 사이드바에 'Paper Q&A' / 'GraphRAG-based Research Q&A' / 'Research Flow
Exploration'을 사용자가 직접 고르는 기능 선택 UI가 있었지만, **지금은 제거되었습니다.**
백엔드가 단일 파이프라인(랭그래프) 안에서 질문 내용을 보고 다음 중 어떤 방식으로
답할지 내부적으로 라우팅하기 때문입니다.

- 논문 내용만으로 답할 수 있는 질문 → 일반 QA
- 다른 논문과의 관계·개념 비교가 필요한 질문 → 그래프 리트리버 기반 QA
- 연구 흐름/계보를 묻는 질문 → 연구 흐름 탐색

프론트엔드는 어떤 경로로 처리됐는지 **결과로만** 판단합니다. 응답에 `citations`가
포함되면 "그래프 검색으로 근거를 함께 찾았어요" 배지와 인용 칩을, `flow`가 포함되면
연구 흐름 스트립을 표시합니다. 사용자는 그냥 하나의 대화창에서 질문하면 됩니다.

## 실행

```bash
pnpm install
pnpm dev
```

`http://localhost:5173` 에서 확인합니다. FastAPI 서버를 먼저 `http://localhost:8000` 에서
실행해주세요. 전체 실행 방법은 [루트 README](../README.md)를 참고합니다.

## 백엔드 연동

- 브라우저는 `/api/v1`을 호출하고, Vite 개발 서버가 `/api` 요청을 `VITE_BACKEND_ORIGIN`
  (기본값 `http://localhost:8000`)으로 전달합니다.
- 백엔드 없이 확인하려면 `cp .env.example .env` 후 `VITE_USE_MOCK=true` 로 변경합니다.

### `GET /api/v1/papers/search?q=검색어`

백엔드가 Hugging Face Papers 검색 결과를 아래 스키마로 정규화해서 내려줍니다.
`categories`에는 HF AI 키워드 상위 3개가 들어가고, arXiv 논문이 아니면 `pdfUrl`과
`arxivUrl`은 `null`입니다.

```json
[
  {
    "id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": "Ashish Vaswani, Noam Shazeer, Niki Parmar et al.",
    "year": 2017,
    "categories": ["recurrent neural networks", "encoder-decoder configuration"],
    "summary": "논문 초록...",
    "pdfUrl": "https://arxiv.org/pdf/1706.03762",
    "arxivUrl": "https://arxiv.org/abs/1706.03762"
  }
]
```

쿼리가 비어 있으면 최신 Daily Papers 목록을 반환합니다. 좌측 사이드바가 처음 마운트될 때
빈 쿼리로 한 번 호출합니다.

### `POST /api/v1/chat/stream` (text/event-stream)

요청 본문:

```json
{
  "paperId": "1706.03762",
  "message": "사용자 질문",
  "history": [{ "role": "user | assistant", "content": "..." }]
}
```

**`mode` 필드가 없습니다.** 어떤 방식(일반 QA / 그래프 리트리버 QA / 연구 흐름 탐색)으로
답할지는 랭그래프 라우팅 노드가 질문 내용을 보고 전적으로 결정합니다. 그래프 검색을
사용한 경우에만 `citations` 이벤트를, 연구 흐름 경로로 라우팅된 경우에만 `flow` 이벤트를
내려주면 프론트가 자동으로 관련 UI(배지, 인용 칩, 흐름 스트립)를 표시합니다.

응답은 SSE 스트림이며, 각 라인은 `data: {json}\n\n` 형식입니다.

| type | 설명 | payload |
|---|---|---|
| `token` | 답변 텍스트 조각(스트리밍) | `{ "text": "..." }` |
| `citations` | 그래프 리트리버가 실제로 사용된 경우에만 전송 | `{ "citations": [{ "id", "label", "relation" }] }` |
| `flow` | 연구 흐름 경로로 라우팅된 경우에만 전송, 선행/현재/후속 연구 | `{ "flow": [{ "stage", "label" }] }` |
| `done` | 스트림 종료 | `{}` |
| `error` | 에러 발생 | `{ "message": "..." }` |

## 폴더 구조

```
src/
├── api/            # 목업/실제 백엔드 호출 (index.js가 스위치 역할)
├── components/
│   ├── Layout/      # 3단 레이아웃 셸 + 드래그 리사이즈
│   ├── Sidebar/     # arXiv 검색, 예시 질문 (기능 선택 UI 없음)
│   ├── Chat/        # 메시지 리스트/버블, 인용 칩, 흐름 스트립, 입력창
│   ├── PaperViewer/ # 가운데 논문 뷰어 (초록/PDF, 접기/펼치기)
│   └── Feedback/    # 토스트
├── data/            # 하드코딩 목업 데이터 (어시스턴트 소개, arXiv 검색결과, 답변)
├── store/           # zustand 상태 (채팅+논문, 토스트)
├── styles/          # 디자인 토큰(CSS 변수)
└── utils/           # SSE 파서 등
```

## 디자인 토큰

`src/styles/tokens.css` 에 정의되어 있습니다. 배경은 화이트/아이보리, 강조색은
소프트 퍼플 계열(`--purple-*`)로 통일했고, 토스트/에러 팝업 헤더는 항상 연한
퍼플(`--purple-50` 배경 + `--purple-700` 텍스트)을 사용하도록 고정했습니다.
