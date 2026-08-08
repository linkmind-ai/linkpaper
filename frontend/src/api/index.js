import * as realClient from "./client.js";
import * as mockClient from "./mockClient.js";

// VITE_USE_MOCK=false 로 바꾸고 백엔드를 띄우면 아래 스위치 하나로
// 실제 FastAPI 엔드포인트를 사용하도록 전환됩니다. 컴포넌트/훅 쪽 코드는
// 수정할 필요가 없습니다.
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

export const streamChat = USE_MOCK ? mockClient.streamChat : realClient.streamChat;
export const fetchPapers = USE_MOCK ? mockClient.fetchPapers : realClient.fetchPapers;
export const isMock = USE_MOCK;
