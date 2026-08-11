// arXiv API(export.arxiv.org) 연동을 가정한 목업입니다.
// 실제 연동 시 백엔드가 arXiv API 응답을 아래와 동일한 스키마로 정규화해서
// GET /api/papers/search?q=... 로 내려주면 프론트 코드는 수정할 필요가 없습니다.
const ARXIV_LIBRARY = [
  {
    id: "1706.03762",
    title: "Attention Is All You Need",
    authors: "Vaswani, Shazeer, Parmar et al.",
    year: 2017,
    categories: ["cs.CL", "cs.LG"],
    summary:
      "순환/합성곱 구조 없이 attention만으로 시퀀스 변환을 수행하는 Transformer 아키텍처를 제안합니다. 병렬화가 가능해 학습 속도가 크게 향상되며, 기계번역 등에서 당시 최고 성능을 달성했습니다.",
    pdfUrl: "https://arxiv.org/pdf/1706.03762",
    arxivUrl: "https://arxiv.org/abs/1706.03762",
  },
  {
    id: "2005.11401",
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    authors: "Lewis, Perez, Piktus et al.",
    year: 2020,
    categories: ["cs.CL"],
    summary:
      "파라메트릭 메모리(사전학습 seq2seq)와 비파라메트릭 메모리(외부 문서 인덱스)를 결합한 RAG 구조를 제안합니다. Retriever가 가져온 문서를 조건으로 generator가 답변을 생성합니다.",
    pdfUrl: "https://arxiv.org/pdf/2005.11401",
    arxivUrl: "https://arxiv.org/abs/2005.11401",
  },
  {
    id: "2404.16130",
    title: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
    authors: "Edge, Trinh, Cheng et al.",
    year: 2024,
    categories: ["cs.CL", "cs.AI"],
    summary:
      "문서에서 엔티티-관계 그래프를 사전에 추출하고, 커뮤니티 구조를 활용해 전역적인 질의에도 답할 수 있도록 확장한 GraphRAG 접근을 제안합니다.",
    pdfUrl: "https://arxiv.org/pdf/2404.16130",
    arxivUrl: "https://arxiv.org/abs/2404.16130",
  },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function mockArxivSearch(query) {
  await sleep(280);
  const q = (query || "").trim().toLowerCase();
  if (!q) return ARXIV_LIBRARY;
  return ARXIV_LIBRARY.filter(
    (p) =>
      p.title.toLowerCase().includes(q) ||
      p.authors.toLowerCase().includes(q) ||
      p.id.includes(q)
  );
}

export const DEFAULT_PAPER = ARXIV_LIBRARY[0];
