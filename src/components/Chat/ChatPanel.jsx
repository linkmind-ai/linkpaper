import { useRef, forwardRef, useImperativeHandle } from "react";
import { Eraser } from "lucide-react";
import { MOCK_MODES } from "../../data/mockPapers.js";
import { useChatStore } from "../../store/useChatStore.js";
import MessageList from "./MessageList.jsx";
import ChatInput from "./ChatInput.jsx";
import "./chat.css";

const ChatPanel = forwardRef(function ChatPanel(_, ref) {
  const mode = useChatStore((s) => s.mode);
  const papers = useChatStore((s) => s.papers);
  const selectedPaperId = useChatStore((s) => s.selectedPaperId);
  const messages = useChatStore((s) => s.messagesByMode[s.mode]);
  const clearCurrentThread = useChatStore((s) => s.clearCurrentThread);

  const inputRef = useRef(null);
  const currentMode = MOCK_MODES.find((m) => m.id === mode);
  const selectedPaper = papers.find((p) => p.id === selectedPaperId);

  useImperativeHandle(ref, () => ({
    fillInput: (text) => inputRef.current?.fill(text),
  }));

  return (
    <section className="chat-panel">
      <header className="chat-panel__header">
        <div className="chat-panel__header-main">
          <span className="chat-panel__mode-badge">
            {currentMode?.emoji} {currentMode?.label}
          </span>
          {selectedPaper && (
            <span className="chat-panel__paper-title">
              {selectedPaper.title}
            </span>
          )}
        </div>
        <button
          className="chat-panel__clear-btn"
          onClick={clearCurrentThread}
          title="이 대화 지우기"
        >
          <Eraser size={14} />
          지우기
        </button>
      </header>

      <MessageList messages={messages} />
      <ChatInput ref={inputRef} />
    </section>
  );
});

export default ChatPanel;
