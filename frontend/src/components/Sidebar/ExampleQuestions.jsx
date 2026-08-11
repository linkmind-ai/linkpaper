import { Sparkles } from "lucide-react";
import { EXAMPLE_QUESTIONS } from "../../data/mockAssistant.js";
import "./sidebar.css";

export default function ExampleQuestions({ onPick }) {
  return (
    <div className="example-questions">
      <span className="sidebar-label">
        <Sparkles size={13} /> 예시 질문
      </span>
      <div className="example-questions__list">
        {EXAMPLE_QUESTIONS.map((q) => (
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
