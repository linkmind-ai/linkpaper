import { useState, useRef, useImperativeHandle, forwardRef } from "react";
import { ArrowUp, Square } from "lucide-react";
import { useChatStore } from "../../store/useChatStore.js";
import "./chat.css";

const ChatInput = forwardRef(function ChatInput(_, ref) {
  const [value, setValue] = useState("");
  const textareaRef = useRef(null);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);

  useImperativeHandle(ref, () => ({
    fill: (text) => {
      setValue(text);
      textareaRef.current?.focus();
    },
  }));

  const handleSend = () => {
    if (!value.trim() || isStreaming) return;
    sendMessage(value);
    setValue("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input">
      <textarea
        ref={textareaRef}
        className="chat-input__textarea"
        placeholder="논문에 대해 질문해보세요… (Shift+Enter로 줄바꿈)"
        rows={3}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      {isStreaming ? (
        <button
          className="chat-input__btn chat-input__btn--stop"
          onClick={stopStreaming}
          aria-label="생성 중지"
        >
          <Square size={14} fill="currentColor" />
        </button>
      ) : (
        <button
          className="chat-input__btn"
          onClick={handleSend}
          disabled={!value.trim()}
          aria-label="메시지 전송"
        >
          <ArrowUp size={16} />
        </button>
      )}
    </div>
  );
});

export default ChatInput;
