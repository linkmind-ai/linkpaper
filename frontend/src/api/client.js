import { parseSSEStream } from "../utils/sse.js";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

/**
 * 백엔드가 arXiv API(export.arxiv.org)를 직접 호출/정규화해서 내려주는 것을 가정한 엔드포인트.
 * 계약(초안): GET {API_BASE}/papers/search?q=검색어
 *   → [{ id, title, authors, year, categories, summary, pdfUrl, arxivUrl }]
 *
 * arXiv 검색을 백엔드에서 프록시하는 이유:
 *   - export.arxiv.org는 브라우저 직접 호출 시 CORS 이슈가 있을 수 있음
 *   - 응답을 그래프DB에 적재하기 전 정규화가 필요함
 *   - API 요청 빈도 제어(레이트리밋)를 서버에서 관리하는 게 안전함
 */
export async function searchPapers(query) {
  const params = new URLSearchParams(query ? { q: query } : {});
  const response = await fetch(`${API_BASE}/papers/search?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`논문을 검색하지 못했습니다 (status ${response.status}).`);
  }
  return response.json();
}

/**
 * 백엔드(FastAPI)의 스트리밍 챗 엔드포인트를 호출합니다.
 * 백엔드 팀과 맞출 계약(초안):
 *
 *   POST {API_BASE}/chat/stream
 *   Content-Type: application/json
 *   Body: { paperId, message, history }
 *
 *   프론트에서 기능/모드를 지정하지 않습니다. 백엔드가 단일 파이프라인(랭그래프) 안에서
 *   질문 내용을 보고 (1) 논문 내 QA, (2) 그래프 리트리버 기반 QA, (3) 연구 흐름 탐색 중
 *   어떤 경로로 처리할지 내부적으로 라우팅합니다.
 *
 *   Response: text/event-stream, 각 이벤트는
 *     data: {"type":"token","text":"..."}
 *     data: {"type":"citations","citations":[{id,label,relation}]}  // 그래프 리트리버가 실제로 쓰였을 때만
 *     data: {"type":"flow","flow":[{stage,label}]}                  // 연구 흐름 경로로 라우팅되었을 때만
 *     data: {"type":"done"}
 *     data: {"type":"error","message":"..."}
 */
export async function* streamChat({ paperId, message, history, signal }) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paperId, message, history }),
    signal,
  });

  if (!response.ok || !response.body) {
    yield {
      type: "error",
      message: `서버 오류가 발생했습니다 (status ${response.status}).`,
    };
    return;
  }

  yield* parseSSEStream(response.body);
}
