// FastAPI StreamingResponse(text/event-stream)에서 내려오는 청크를 파싱합니다.
// 백엔드 계약(권장): 각 이벤트는 `data: {json}\n\n` 형태의 SSE 라인이며,
// json 페이로드는 { type: "token" | "citations" | "flow" | "done" | "error", ... } 형태를 갖습니다.
export async function* parseSSEStream(readableStream) {
  const reader = readableStream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const dataLine = rawEvent
          .split("\n")
          .find((line) => line.startsWith("data:"));

        if (!dataLine) continue;

        const jsonStr = dataLine.replace(/^data:\s*/, "");
        try {
          yield JSON.parse(jsonStr);
        } catch (err) {
          console.error("SSE 청크 파싱 실패:", jsonStr, err);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
