import { MOCK_PAPERS } from "../data/mockPapers.js";
import { getMockAnswer } from "../data/mockResponses.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 실제 client.js의 streamChat과 동일한 시그니처/이벤트 스키마를 갖는
// 목업 async generator입니다. 백엔드 연동 시 api/index.js의 분기만 바꾸면
// 컴포넌트 코드는 전혀 수정할 필요가 없습니다.
export async function* streamChat({ mode, signal }) {
  const answer = getMockAnswer(mode);

  // 토큰 단위로 쪼개서 실제 LLM 스트리밍처럼 보이게 시뮬레이션
  const words = answer.text.split(/(\s+)/);

  for (const word of words) {
    if (signal?.aborted) {
      yield { type: "error", message: "요청이 취소되었습니다." };
      return;
    }
    await sleep(18 + Math.random() * 22);
    yield { type: "token", text: word };
  }

  if (answer.flow) {
    await sleep(200);
    yield { type: "flow", flow: answer.flow };
  }

  if (answer.citations?.length) {
    await sleep(150);
    yield { type: "citations", citations: answer.citations };
  }

  yield { type: "done" };
}

export async function fetchPapers() {
  await sleep(150);
  return MOCK_PAPERS;
}
