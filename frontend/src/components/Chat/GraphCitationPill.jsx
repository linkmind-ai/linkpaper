import "./chat.css";

// GraphRAG의 특성을 시각적으로 드러내는 시그니처 요소.
// 인용된 논문을 "노드"처럼 표현해, 답변이 그래프에서 끌어온 근거임을 암시합니다.
export default function GraphCitationPill({ citation }) {
  return (
    <button className="citation-pill" title={citation.relation}>
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
        <circle cx="2.5" cy="9.5" r="1.6" fill="var(--purple-300)" />
        <circle cx="9.5" cy="2.5" r="1.8" fill="var(--purple-500)" />
        <line
          x1="3.6"
          y1="8.4"
          x2="8.2"
          y2="3.6"
          stroke="var(--purple-300)"
          strokeWidth="1"
        />
      </svg>
      <span className="citation-pill__label">{citation.label}</span>
      <span className="citation-pill__relation">{citation.relation}</span>
    </button>
  );
}
