# LinkPaper Frontend

React + Vite + pnpm 기반 프론트엔드입니다. 백엔드(FastAPI)가 준비되기 전까지는
`VITE_USE_MOCK=true` 로 하드코딩된 목업 데이터/스트리밍으로 전체 UI를 확인할 수 있습니다.

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
cp .env.example .env
pnpm dev
```

`http://localhost:5173` 에서 확인합니다.

## 목업 → 실제 백엔드 전환

1. `.env`에서 `VITE_USE_MOCK=false` 로 변경
2. FastAPI 서버를 `http://localhost:8000` (또는 `vite.config.js`의 proxy target)에서 실행
3. 아래 계약에 맞춰 엔드포인트 2개를 구현하면, **컴포넌트 코드 수정 없이** 그대로 연동됩니다.

### `GET /api/papers/search?q=검색어`

백엔드가 arXiv API(`export.arxiv.org`)를 호출해 아래 스키마로 정규화해서 내려줍니다.
arXiv 호출을 백엔드에서 대신하는 이유는 (1) 브라우저 직접 호출 시 CORS 이슈, (2) 그래프DB
적재 전 정규화 필요, (3) 레이트리밋을 서버에서 관리하기 위해서입니다.

```json
[
  {
    "id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": "Vaswani, Shazeer, Parmar et al.",
    "year": 2017,
    "categories": ["cs.CL", "cs.LG"],
    "summary": "논문 초록...",
    "pdfUrl": "https://arxiv.org/pdf/1706.03762",
    "arxivUrl": "https://arxiv.org/abs/1706.03762"
  }
]
```

쿼리가 비어 있으면(`q=""`) 기본/최근 논문 목록을 반환하도록 구현해주세요. 좌측 사이드바가
처음 마운트될 때 빈 쿼리로 한 번 호출합니다.

### `POST /api/chat/stream` (text/event-stream)

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
