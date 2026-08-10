// 백엔드 RAG 파이프라인(랭체인/랭그래프 + Neo4j + Elasticsearch)이 붙기 전까지
// 사용하는 하드코딩 응답입니다. 실제로는 백엔드가 질문 내용을 보고 내부적으로
// (1) 논문 내 QA, (2) 그래프 리트리버 기반 QA, (3) 연구 흐름 탐색 중 하나의 경로로
// 라우팅합니다. 프론트에서는 이 라우팅을 흉내 내기 위해 질문 문구에 포함된 키워드로
// 어떤 목업 응답을 보여줄지만 결정합니다 — 실제 라우팅 로직은 전부 백엔드 책임입니다.
const FLOW_KEYWORDS = ["흐름", "선행 연구", "후속 연구", "연구사", "계보", "위치"];

const answers = {
  qa: {
    text: `이 논문(Attention Is All You Need)의 핵심 기여는 순환(RNN)이나 합성곱(CNN) 구조 없이 오직 **self-attention** 메커니즘만으로 시퀀스 변환 문제를 해결한 Transformer 아키텍처를 제안한 것입니다.

주요 포인트는 다음과 같습니다.

1. **Self-Attention**: 입력 시퀀스 내 모든 토큰 쌍의 관계를 직접 계산하여 장거리 의존성을 효율적으로 포착합니다.
2. **Multi-Head Attention**: 서로 다른 표현 부분공간에서 병렬적으로 attention을 수행해 다양한 관점의 관계를 학습합니다.
3. **병렬화**: RNN과 달리 시퀀스를 순차적으로 처리할 필요가 없어 학습 속도가 크게 향상됩니다.

관련 논문 그래프를 함께 살펴보면, 이 self-attention 개념은 후속 연구에서 확장되어 왔습니다. RAG는 attention을 "외부 문서와의 연결 고리"로 재활용했고, GraphRAG는 attention이 암묵적으로 학습하던 관계를 아예 명시적인 지식그래프로 사전에 추출해 활용합니다.`,
    citations: [
      { id: "2005.11401", label: "RAG (Lewis et al., 2020)", relation: "확장 인용" },
      { id: "2404.16130", label: "GraphRAG (Edge et al., 2024)", relation: "개념 재해석" },
    ],
  },
  flow: {
    text: `이 논문은 시퀀스-투-시퀀스 학습에서 RNN/CNN 기반 인코더-디코더가 갖던 순차 연산의 병목을 해결하려는 연구 흐름 속에서 등장했습니다.

**선행 연구**는 attention을 RNN에 보조 장치로 덧붙이는 방식(예: Bahdanau attention)이 주를 이뤘고, 순차 연산 자체를 없애지는 못했습니다.

이 논문은 attention을 "보조 장치"에서 "유일한 연산자"로 승격시키며 병렬화 가능한 아키텍처를 제시했고, 이후 **후속 연구**들은 이 구조를 사전학습(pre-training) 패러다임과 결합하거나(BERT, GPT 계열), 외부 지식 검색과 결합하는(RAG, GraphRAG) 방향으로 확장되었습니다.

즉 이 논문은 "attention의 역할을 보조에서 핵심으로 전환한 분기점"에 위치합니다.`,
    citations: [
      { id: "2005.11401", label: "RAG (Lewis et al., 2020)", relation: "후속 연구" },
      { id: "2404.16130", label: "GraphRAG (Edge et al., 2024)", relation: "후속 연구" },
    ],
    flow: [
      { stage: "선행 연구", label: "RNN + Bahdanau Attention" },
      { stage: "현재 논문", label: "Transformer (Self-Attention)" },
      { stage: "후속 연구", label: "BERT / RAG / GraphRAG" },
    ],
  },
};

// 백엔드의 내부 라우팅을 시뮬레이션하는 함수. 질문 문구를 보고 어떤 목업 응답을
// 보여줄지 고릅니다. 실제 백엔드에서는 이 판단을 랭그래프 라우팅 노드가 수행합니다.
export function getMockAnswer(message) {
  const isFlowQuery = FLOW_KEYWORDS.some((kw) => message.includes(kw));
  return isFlowQuery ? answers.flow : answers.qa;
}
