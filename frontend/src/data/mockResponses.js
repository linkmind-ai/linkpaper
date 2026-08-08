// 백엔드 RAG 파이프라인(랭체인/랭그래프 + Neo4j + Elasticsearch)이 붙기 전까지
// 사용하는 하드코딩 응답입니다. 실제 연동 시 이 텍스트/citations 구조를
// 백엔드 스트리밍 청크 스키마로 그대로 대체하면 됩니다.

const baseAnswer = {
  "paper-qa": {
    text: `이 논문(Attention Is All You Need)의 핵심 기여는 순환(RNN)이나 합성곱(CNN) 구조 없이 오직 **self-attention** 메커니즘만으로 시퀀스 변환 문제를 해결한 Transformer 아키텍처를 제안한 것입니다.

주요 포인트는 다음과 같습니다.

1. **Self-Attention**: 입력 시퀀스 내 모든 토큰 쌍의 관계를 직접 계산하여 장거리 의존성을 효율적으로 포착합니다.
2. **Multi-Head Attention**: 서로 다른 표현 부분공간에서 병렬적으로 attention을 수행해 다양한 관점의 관계를 학습합니다.
3. **병렬화**: RNN과 달리 시퀀스를 순차적으로 처리할 필요가 없어 학습 속도가 크게 향상됩니다.

한계로는 시퀀스 길이에 대해 attention 계산 비용이 제곱으로 증가한다는 점이 있습니다.`,
    citations: [],
  },
  "graph-rag-qa": {
    text: `지식그래프에서 이 논문과 연결된 2개의 관련 논문을 함께 살펴본 결과, self-attention 개념은 후속 연구에서 다음과 같이 확장/재해석되고 있습니다.

- **RAG 논문(Lewis et al., 2020)**은 self-attention을 시퀀스 내부 관계 포착 도구로 보기보다, retriever가 가져온 외부 문서와 generator 사이의 연결 고리를 만드는 데 활용합니다. 즉 "문맥 내 관계"에서 "외부 지식과의 관계"로 attention의 역할이 확장된 것입니다.
- **GraphRAG(Edge et al., 2024)**은 한 걸음 더 나아가, attention이 암묵적으로 학습하던 개체 간 관계를 아예 명시적인 그래프 구조(엔티티-관계)로 사전에 추출해 활용합니다. 이는 attention의 "암묵적 관계 학습"을 "명시적 관계 저장"으로 대체하려는 시도로 볼 수 있습니다.

즉, 원 논문의 self-attention이 "모델 내부의 관계 계산"이었다면, 후속 연구들은 이를 "모델 외부의 지식 구조와 어떻게 연결할 것인가"라는 문제로 확장해왔습니다.`,
    citations: [
      { id: "p-002", label: "RAG (Lewis et al., 2020)", relation: "확장 인용" },
      { id: "p-003", label: "GraphRAG (Edge et al., 2024)", relation: "개념 재해석" },
    ],
  },
  "research-flow": {
    text: `이 논문은 시퀀스-투-시퀀스 학습에서 RNN/CNN 기반 인코더-디코더가 갖던 순차 연산의 병목을 해결하려는 연구 흐름 속에서 등장했습니다.

**선행 연구**는 attention을 RNN에 보조 장치로 덧붙이는 방식(예: Bahdanau attention)이 주를 이뤘고, 순차 연산 자체를 없애지는 못했습니다.

이 논문은 attention을 "보조 장치"에서 "유일한 연산자"로 승격시키며 병렬화 가능한 아키텍처를 제시했고, 이후 **후속 연구**들은 이 구조를 사전학습(pre-training) 패러다임과 결합하거나(BERT, GPT 계열), 외부 지식 검색과 결합하는(RAG, GraphRAG) 방향으로 확장되었습니다.

즉 이 논문은 "attention의 역할을 보조에서 핵심으로 전환한 분기점"에 위치합니다.`,
    citations: [
      { id: "p-002", label: "RAG (Lewis et al., 2020)", relation: "후속 연구" },
      { id: "p-003", label: "GraphRAG (Edge et al., 2024)", relation: "후속 연구" },
    ],
    flow: [
      { stage: "선행 연구", label: "RNN + Bahdanau Attention" },
      { stage: "현재 논문", label: "Transformer (Self-Attention)" },
      { stage: "후속 연구", label: "BERT / RAG / GraphRAG" },
    ],
  },
};

export function getMockAnswer(modeId) {
  return baseAnswer[modeId] ?? baseAnswer["paper-qa"];
}
