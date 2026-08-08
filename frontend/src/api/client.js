import { parseSSEStream } from "../utils/sse.js";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

/**
 * 백엔드(FastAPI)의 스트리밍 챗 엔드포인트를 호출합니다.
 * 백엔드 팀과 맞출 계약(초안):
 *
 *   POST {API_BASE}/chat/stream
 *   Content-Type: application/json
 *   Body: { paperId, mode, message, history }
 *
 *   Response: text/event-stream, 각 이벤트는
 *     data: {"type":"token","text":"..."}
 *     data: {"type":"citations","citations":[{id,label,relation}]}
 *     data: {"type":"flow","flow":[{stage,label}]}   // research-flow 모드에서만
 *     data: {"type":"done"}
 *     data: {"type":"error","message":"..."}
 *
 * 이 함수는 async generator이므로 mockClient.js의 인터페이스와 동일하게
 * 소비할 수 있습니다 (frontend/src/api/index.js 참고).
 */
export async function* streamChat({ paperId, mode, message, history, signal }) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paperId, mode, message, history }),
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

export async function fetchPapers() {
  const response = await fetch(`${API_BASE}/papers`);
  if (!response.ok) {
    throw new Error(`논문 목록을 불러오지 못했습니다 (status ${response.status}).`);
  }
  return response.json();
}
