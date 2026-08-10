# LinkPaper Evaluation

> 상태: Draft
>
> 범위: 평가 지표 정의, 데이터셋 형식, 백엔드 응답 계약, 회귀 게이트 운영

## 1. 목적

이 문서는 평가 팀이 무엇을 어떻게 측정하는지, 그리고 다른 팀이 평가를 받기
위해 무엇을 지켜야 하는지를 정의한다.

핵심 원칙은 두 가지다.

1. **측정 대상과 측정 도구를 분리한다.** 평가 하네스는 백엔드 패키지를
   임포트하지 않는다. 어댑터 하나만 바꾸면 어떤 구현이든 같은 지표로 비교할
   수 있다.
2. **평가는 실행 가능해야 한다.** 리포트로만 존재하는 평가는 읽히지 않는다.
   기준 미달과 회귀는 CI 실패로 이어진다.

구현은 [`evaluation/`](../evaluation/README.md)에 있다. 데이터 계약은
[Data & Retrieval Architecture](./data-architecture/data-retrieval-architecture.md),
그래프 스키마는 [Neo4j Graph Schema](./data-architecture/neo4j-schema.md)를
기준으로 한다.

## 2. 평가 스위트

### 2.1 Retrieval

검색기가 정답 근거를 상위에 올리는지, 그리고 검색 범위를 올바르게 고르는지를
측정한다.

| 지표 | 정의 | 왜 보는가 |
|---|---|---|
| `retrieval.recall@k` | 정답 청크 중 상위 k에 포함된 비율 | 근거가 컨텍스트에 들어가야 답변이 가능하다 |
| `retrieval.precision@k` | 상위 k 중 정답 비율 | 컨텍스트 낭비와 노이즈 정도 |
| `retrieval.ndcg@k` | 등급 관련도 기반 순위 품질 | 정답을 몇 번째로 올렸는지까지 반영 |
| `retrieval.mrr` | 첫 정답 순위의 역수 | 상위 노출 성능 |
| `retrieval.hit@k` | 상위 k에 정답이 하나라도 있는지 | 최소 성공 여부 |
| `routing.accuracy` | 선택 논문 범위 판단 정확도 | LinkPaper의 핵심 분기 |

`routing.accuracy`가 이 프로젝트에서 특히 중요하다. PROJECT_SPEC의 사용자
플로는 "선택한 논문만으로 답변 가능한가"에서 갈리는데, 이 판단이 틀리면
검색이 아무리 좋아도 잘못된 범위에서 찾는다. 잘못된 방향의 오류는 서로 성격이
다르므로 태그별 집계로 나눠 본다.

- `selected`로 잘못 판단: 관련 논문을 놓치고 불완전하게 답한다.
- `global`로 잘못 판단: 불필요한 확장으로 지연시간과 비용이 늘고 노이즈가 는다.

### 2.2 Generation

답변이 근거에 충실한지, 인용이 실제로 존재하는지를 측정한다.

| 지표 | 정의 |
|---|---|
| `generation.groundedness_lexical` | 답변 토큰 중 근거 텍스트에 존재하는 비율 |
| `generation.citation_validity` | 인용한 `chunkId`가 검색 결과에 실재하는 비율 |
| `generation.citation_precision` / `citation_recall` | 정답 근거 대비 인용 정확도와 회수율 |
| `generation.answer_token_f1` | 정답 문자열과의 토큰 F1 |
| `generation.must_include` | 반드시 언급해야 할 표현의 포함률 |
| `judge.faithfulness` / `judge.relevance` | 심판 점수 |

`citation_validity`는 프런트엔드와 직접 연결된다. 존재하지 않는 `chunkId`를
인용하면 근거 링크가 깨지므로 게이트 기준을 0.95로 높게 잡는다.

`groundedness_lexical`만으로는 품질을 판단할 수 없다. 근거 문장을 그대로
복사하면 1.0이 나오기 때문이다. 반드시 `answer_token_f1`과 함께 본다.

### 2.3 Extraction

지식그래프 트리플 추출 정확도를 측정한다. 정답 트리플은 neo4j-schema.md
6.2절의 관계 allowlist를 따른다.

| 지표 | 정의 |
|---|---|
| `extraction.triple_precision` / `recall` / `f1` | 주어·술어·목적어 완전 일치 |
| `extraction.relaxed_*` | 주어·목적어만 일치 (술어 무시) |
| `extraction.entity_coverage` | 정답 엔티티 중 추출된 비율 |
| `extraction.evidence_attachment` | 근거 `chunkId`가 붙은 트리플 비율 |

엄격 점수와 완화 점수의 차이가 진단에 쓰인다. 차이가 크면 엔티티는 잘
잡지만 관계 타입을 혼동한다는 뜻이므로, 추출 프롬프트에서 allowlist 정의를
다듬어야 한다. 두 점수가 함께 낮으면 엔티티 정규화 쪽 문제다.

`evidence_attachment`는 품질이 아니라 스키마 준수 검사다. LLM 추출 관계는
`chunkId`와 `confidence`를 필수로 가져야 하므로 1.0 미만이면 적재 단계에서
스키마 위반이 발생한다.

### 2.4 Operational

모든 스위트에서 함께 수집한다.

`operational.latency_ms_p50` / `p95` / `error_rate` / `case_count`

품질 지표가 좋아져도 p95가 서비스 한계를 넘으면 배포할 수 없다. 인프라
용량 산정 근거로도 쓴다.

## 3. 데이터셋 형식

JSONL 한 줄이 케이스 하나다. 필드는
`evaluation/src/linkpaper_eval/schemas.py`의 `EvalCase`가 정본이다.

```json
{
  "case_id": "ret-006",
  "question": "What limitation of RAG motivated later graph based methods?",
  "paper_id": "arxiv:2005.11401",
  "gold_chunk_ids": ["arxiv:2005.11401:chunk:7:c7d8e9f0"],
  "gold_paper_ids": ["arxiv:2005.11401", "arxiv:2404.16130"],
  "grades": {"arxiv:2005.11401:chunk:7:c7d8e9f0": 3},
  "expected_scope": "global",
  "gold_answer": "…",
  "must_include": ["global"],
  "gold_triples": [{"subject": "…", "predicate": "IMPROVES_ON", "object": "…"}],
  "tags": ["global", "follow-up"]
}
```

식별자는 그래프 스키마와 동일한 형식을 쓴다.

- `paperId`: `arxiv:1706.03762`
- `chunkId`: `<paperId>:chunk:<chunkIndex>:<contentHash-prefix>`

데이터셋 파일 해시를 실행 매니페스트에 기록하므로, 점수 변화가 시스템 변경
때문인지 데이터 변경 때문인지 구분할 수 있다.

## 4. 백엔드 응답 계약

`--target http`로 평가하려면 백엔드가 아래 형태로 응답해야 한다. 평가에
필요한 최소 계약이며, 서비스 응답에 다른 필드가 더 있어도 무방하다.

`POST /api/v1/conversations/{conversation_id}/messages`

요청:

```json
{ "paper_id": "arxiv:1706.03762", "content": "질문 텍스트" }
```

응답:

```json
{
  "answer": "생성된 답변 텍스트",
  "scope": "selected",
  "citations": ["arxiv:1706.03762:chunk:3:e5f6a7b8"],
  "retrieved": [
    {
      "paperId": "arxiv:1706.03762",
      "chunkId": "arxiv:1706.03762:chunk:3:e5f6a7b8",
      "text": "근거 청크 본문",
      "scope": "selected",
      "retrievalSource": "qdrant_vector",
      "rank": 1,
      "score": 0.91,
      "section": "Model Architecture",
      "matchedEntityIds": ["method:multi-head-attention"]
    }
  ],
  "triples": [
    {
      "subject": "model:transformer",
      "predicate": "USES_METHOD",
      "object": "method:multi-head-attention",
      "chunkId": "arxiv:1706.03762:chunk:3:e5f6a7b8",
      "confidence": 0.9
    }
  ],
  "usage": { "promptTokens": 0, "completionTokens": 0, "costUsd": 0.0 }
}
```

계약에서 중요한 부분은 다음과 같다.

| 필드 | 없으면 못 재는 것 |
|---|---|
| `retrieved[]` | 검색 지표 전체. 답변만으로는 Recall을 계산할 수 없다 |
| `scope` | `routing.accuracy` |
| `citations[]` | 인용 정확도와 근거 링크 검증 |
| `retrieved[].text` | 근거 충실도 |
| `usage` | 비용 회계 |

`retrieved`는 최종 컨텍스트에 들어간 근거를 순위대로 담는다. `rank`가 있으면
그 순서를, 없으면 배열 순서를 신뢰한다. `snake_case`와 `camelCase`를 모두
허용하므로 백엔드 컨벤션에 맞추면 된다.

평가 요청은 `conversation_id`를 매번 새로 만들어 이전 대화 이력이 결과에
섞이지 않게 한다.

## 5. 회귀 게이트

```yaml
gates:
  retrieval.recall@5:
    min: 0.55
    max_regression: 0.03
  operational.error_rate:
    max: 0.05
```

- `min` / `max`: 서비스가 만족해야 할 절대 기준
- `max_regression`: 베이스라인 대비 허용 하락폭

`error_rate`, `latency`, `cost`가 이름에 들어간 지표는 낮을수록 좋으므로
회귀 방향을 자동으로 뒤집어 판정한다.

지표가 이번 실행 결과에 없으면 실패로 처리한다. 지표가 조용히 사라져서
게이트가 무력화되는 상황을 막기 위해서다.

현재 게이트 기준은 BM25 베이스라인 점수를 바탕으로 한 잠정값이다. GraphRAG
파이프라인이 붙고 실제 분포를 확인한 뒤 조정한다.

## 6. 실행 산출물

`evaluation/runs/<run_id>/`에 저장한다.

| 파일 | 내용 |
|---|---|
| `manifest.json` | 실행 ID, 타깃, 데이터셋 해시, 설정 해시, git SHA, 심판 |
| `metrics.json` | 집계 지표와 태그별 집계 |
| `cases.jsonl` | 케이스별 지표, 답변, 인용, 검색 결과, 오류 |
| `report.md` | PR에 붙일 수 있는 마크다운 리포트 |

`runs/`는 gitignore 대상이다. 베이스라인(`baselines/`)은 게이트 기준이므로
반드시 커밋한다.

## 7. 팀 인터페이스

| 담당 | 평가 팀에 필요한 것 | 평가 팀이 제공하는 것 |
|---|---|---|
| Backend/GraphRAG | 4장 응답 계약 준수, `retrieved`와 `scope` 노출 | 검색·라우팅·근거 충실도 회귀 리포트 |
| Graph DB | 확정된 `chunkId`·`entityId` 형식, 관계 allowlist | 트리플 추출 정확도, 엔티티 커버리지 |
| Data/PM | 정답 라벨링 대상 논문 선정, 질문 유형 정의 | 태그별 취약 구간 분석 |
| Infrastructure | 평가 환경 재현 수단 | p50/p95 지연시간, 오류율 |
| Frontend | 근거 링크에 필요한 필드 확인 | `citation_validity` 지표 |

## 8. 현재 상태와 다음 단계

완료

- 3개 스위트(retrieval, generation, extraction)와 운영 지표
- 오프라인 BM25 베이스라인 타깃, 백엔드 HTTP 타깃
- 회귀 게이트, 베이스라인 관리, 마크다운 리포트
- 샘플 데이터셋과 단위·통합 테스트

다음 단계

1. 백엔드 응답 계약 합의 후 `--target http` 실측
2. 데이터셋 확장. 특히 `global`, `follow-up` 유형
3. 실제 분포 확인 후 게이트 기준 재설정
4. 한국어 질의 처리 방식 확정 후 `korean` 태그 기준 마련
5. 검색 결과 융합·reranker 도입 시 비교 실험 설계
