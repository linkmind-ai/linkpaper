import { Sparkles } from "lucide-react";
import { MOCK_MODES } from "../../data/mockPapers.js";
import { useChatStore } from "../../store/useChatStore.js";
import "./sidebar.css";

export default function ExampleQuestions({ onPick }) {
  const mode = useChatStore((s) => s.mode);
  const current = MOCK_MODES.find((m) => m.id === mode);

  if (!current) return null;

  return (
    <div className="example-questions">
      <span className="sidebar-label">
        <Sparkles size={13} /> 예시 질문
      </span>
      <div className="example-questions__list">
        {current.examples.map((q) => (
          <button
            key={q}
            className="example-chip"
            onClick={() => onPick?.(q)}
            title="클릭하면 입력창에 채워집니다"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
