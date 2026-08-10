import { useRef, forwardRef, useImperativeHandle } from "react";
import { Eraser } from "lucide-react";
import { ASSISTANT_INFO } from "../../data/mockAssistant.js";
import { useChatStore } from "../../store/useChatStore.js";
import MessageList from "./MessageList.jsx";
import ChatInput from "./ChatInput.jsx";
import "./chat.css";

const ChatPanel = forwardRef(function ChatPanel(_, ref) {
  const selectedPaper = useChatStore((s) => s.selectedPaper);
  const messages = useChatStore((s) => s.messages);
  const clearThread = useChatStore((s) => s.clearThread);

  const inputRef = useRef(null);

  useImperativeHandle(ref, () => ({
    fillInput: (text) => inputRef.current?.fill(text),
  }));

  return (
    <section className="chat-panel">
      <header className="chat-panel__header">
        <div className="chat-panel__header-main">
          <span className="chat-panel__mode-badge">
            {ASSISTANT_INFO.emoji} {ASSISTANT_INFO.label}
          </span>
          {selectedPaper && (
            <span className="chat-panel__paper-ref">
              arXiv:{selectedPaper.id}
            </span>
          )}
        </div>
        <button
          className="chat-panel__clear-btn"
          onClick={clearThread}
          title="대화 지우기"
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
