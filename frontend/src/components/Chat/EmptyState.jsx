import { MOCK_MODES } from "../../data/mockPapers.js";
import { useChatStore } from "../../store/useChatStore.js";
import "./chat.css";

export default function EmptyState() {
  const mode = useChatStore((s) => s.mode);
  const current = MOCK_MODES.find((m) => m.id === mode);

  return (
    <div className="empty-state">
      <span className="empty-state__emoji">{current?.emoji}</span>
      <h2 className="empty-state__title">{current?.label}</h2>
      <p className="empty-state__desc">{current?.description}</p>
      <p className="empty-state__hint">
        왼쪽의 예시 질문을 눌러보거나, 아래 입력창에 궁금한 점을 물어보세요.
      </p>
    </div>
  );
}
