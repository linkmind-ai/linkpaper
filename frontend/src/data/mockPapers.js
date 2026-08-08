// 백엔드(graph/retrieval)가 준비되기 전까지 사용하는 하드코딩 목업 데이터입니다.
// 실제 연동 시 GET /api/papers 응답 스키마와 맞추면 됩니다.
export const MOCK_PAPERS = [
  {
    id: "p-001",
    title: "Attention Is All You Need",
    authors: "Vaswani et al.",
    year: 2017,
    venue: "NeurIPS",
    tags: ["Transformer", "Attention"],
  },
  {
    id: "p-002",
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    authors: "Lewis et al.",
    year: 2020,
    venue: "NeurIPS",
    tags: ["RAG", "Retrieval"],
  },
  {
    id: "p-003",
    title: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
    authors: "Edge et al.",
    year: 2024,
    venue: "arXiv",
    tags: ["GraphRAG", "Knowledge Graph"],
  },
];

export const MOCK_MODES = [
  {
    id: "paper-qa",
    emoji: "💬",
    label: "Paper Q&A",
    description:
      "선택한 논문의 내용을 기반으로 질의응답을 제공하여 논문의 복잡한 개념과 세부 내용을 이해할 수 있습니다.",
    examples: [
      "이 논문의 핵심 기여는 무엇인가?",
      "제안한 방법의 한계는 뭐야?",
      "실험 설정을 요약해줘",
    ],
  },
  {
    id: "graph-rag-qa",
    emoji: "🌐",
    label: "GraphRAG-based Research Q&A",
    description:
      "관련 논문과 인용 관계가 저장된 지식그래프 기반 GraphRAG를 활용하여, 현재 논문을 더 깊이 이해할 수 있는 심층 질의응답을 제공합니다.",
    examples: [
      "이 논문에 소개된 self-attention 개념을 다른 논문에선 어떻게 설명하고 있지?",
      "이 논문의 한계를 해결한 후속 연구는 무엇인가?",
    ],
  },
  {
    id: "research-flow",
    emoji: "🧭",
    label: "Research Flow Exploration",
    description:
      "선행 연구, 후속 연구, 관련 논문의 연결 관계를 탐색하며 하나의 논문이 연구 분야에서 어떤 위치와 의미를 가지는지 이해할 수 있습니다.",
    examples: [
      "이 연구는 어떤 연구 흐름 속에서 등장했는가?",
      "이 논문 이후 등장한 대표적인 후속 연구 3개를 알려줘",
    ],
  },
];
