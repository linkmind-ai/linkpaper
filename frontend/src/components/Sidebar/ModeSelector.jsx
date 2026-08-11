import { MOCK_MODES } from "../../data/mockPapers.js";
import { useChatStore } from "../../store/useChatStore.js";
import "./sidebar.css";

export default function ModeSelector() {
  const mode = useChatStore((s) => s.mode);
  const setMode = useChatStore((s) => s.setMode);

  return (
    <div className="mode-selector">
      <span className="sidebar-label">기능 선택</span>
      <div className="mode-selector__list">
        {MOCK_MODES.map((m) => (
          <button
            key={m.id}
            className={`mode-card ${mode === m.id ? "is-active" : ""}`}
            onClick={() => setMode(m.id)}
          >
            <div className="mode-card__head">
              <span className="mode-card__emoji" aria-hidden>
                {m.emoji}
              </span>
              <span className="mode-card__label">{m.label}</span>
            </div>
            <p className="mode-card__desc">{m.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
