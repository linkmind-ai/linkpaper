import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle } from "lucide-react";
import GraphCitationPill from "./GraphCitationPill.jsx";
import FlowStrip from "./FlowStrip.jsx";
import StreamingCursor from "./StreamingCursor.jsx";
import "./chat.css";

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <div className={`message-row ${isUser ? "is-user" : "is-assistant"}`}>
      <div className={`message-bubble ${isUser ? "is-user" : "is-assistant"}`}>
        {message.status === "error" ? (
          <div className="message-error">
            <AlertTriangle size={14} />
            <span>답변을 생성하지 못했습니다. 다시 시도해주세요.</span>
          </div>
        ) : (
          <>
            <div className="message-bubble__content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content || ""}
              </ReactMarkdown>
              {message.status === "streaming" && <StreamingCursor />}
            </div>

            {message.flow && <FlowStrip flow={message.flow} />}

            {message.citations?.length > 0 && (
              <div className="citation-row">
                {message.citations.map((c) => (
                  <GraphCitationPill key={c.id} citation={c} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
