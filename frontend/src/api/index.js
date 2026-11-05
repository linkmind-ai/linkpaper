import * as realClient from "./client.js";
import * as mockClient from "./mockClient.js";

// 기본값은 실제 FastAPI 엔드포인트입니다. 백엔드 없이 UI만 확인할 때는
// VITE_USE_MOCK=true 로 목업 데이터를 사용합니다. 컴포넌트/훅 쪽 코드는
// 수정할 필요가 없습니다.
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

export const streamChat = USE_MOCK ? mockClient.streamChat : realClient.streamChat;
export const searchPapers = USE_MOCK ? mockClient.searchPapers : realClient.searchPapers;
export const isMock = USE_MOCK;
