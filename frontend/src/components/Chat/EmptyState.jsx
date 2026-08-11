import { ASSISTANT_INFO } from "../../data/mockAssistant.js";
import "./chat.css";

export default function EmptyState() {
  return (
    <div className="empty-state">
      <span className="empty-state__emoji">{ASSISTANT_INFO.emoji}</span>
      <h2 className="empty-state__title">{ASSISTANT_INFO.label}</h2>
      <p className="empty-state__desc">{ASSISTANT_INFO.description}</p>
      <p className="empty-state__hint">
        왼쪽의 예시 질문을 눌러보거나, 아래 입력창에 궁금한 점을 물어보세요.
      </p>
    </div>
  );
}
