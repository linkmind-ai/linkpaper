# 평가

LinkPaper GraphRAG 파이프라인의 검색·생성·추출 품질과 운영 지표를 측정한다.

백엔드 구현 여부와 무관하게 동작하는 것이 이 하네스의 설계 목표다. 기본
타깃은 외부 의존성이 없는 BM25 베이스라인이므로 API 키, 실행 중인 컨테이너,
네트워크 없이도 전체 파이프라인이 돌아간다. 백엔드가 준비되면 타깃만 바꿔서
같은 지표로 비교한다.

지표 정의와 백엔드 응답 계약은 [docs/evaluation.md](../docs/evaluation.md)를
참고한다.

## 빠른 실행

```bash
cd evaluation
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

linkpaper-eval run --config configs/retrieval.yaml
linkpaper-eval run --config configs/generation.yaml
linkpaper-eval run --config configs/extraction.yaml
```

설치 없이 실행하려면 `PYTHONPATH=src python -m linkpaper_eval ...`를 쓴다.

테스트는 `pytest`로 실행한다.

## 구조

```text
evaluation/
├── configs/            # 스위트별 설정. 실행의 재현 단위다
├── datasets/           # 평가 케이스 (JSONL)
├── fixtures/           # 오프라인 베이스라인이 검색할 코퍼스
├── baselines/          # 게이트 비교 기준. 커밋 대상이다
├── runs/               # 실행 산출물. gitignore 대상이다
├── src/linkpaper_eval/
│   ├── schemas.py      # 평가 팀과 백엔드 사이의 데이터 계약
│   ├── datasets.py     # 데이터셋 로딩과 무결성 해시
│   ├── config.py       # 설정 로딩, 환경변수 치환, 설정 해시
│   ├── targets/        # 평가 대상 어댑터
│   ├── metrics/        # 검색·생성·추출·운영 지표
│   ├── judges.py       # 결정적 심판과 LLM 심판
│   ├── runner.py       # 실행 오케스트레이션
│   ├── gates.py        # 회귀 게이트 판정
│   ├── report.py       # 마크다운 리포트 생성
│   └── cli.py          # 명령행 진입점
└── tests/
```

## 스위트

| 스위트 | 측정 대상 | 핵심 지표 |
|---|---|---|
| `retrieval` | 검색과 범위 라우팅 | `recall@k`, `ndcg@k`, `mrr`, `routing.accuracy` |
| `generation` | 답변과 근거 | `groundedness_lexical`, `citation_validity`, `citation_recall` |
| `extraction` | 지식그래프 트리플 | `triple_f1`, `relaxed_f1`, `entity_coverage` |

`operational.*`(지연시간 p50/p95, 오류율)은 모든 스위트에서 함께 수집한다.
품질이 좋아져도 p95가 서비스 한계를 넘으면 배포할 수 없기 때문이다.

## 타깃

`--target` 이름으로 평가 대상을 바꾼다. 지표 계산은 동일하므로 결과를 직접
비교할 수 있다.

```bash
linkpaper-eval run --config configs/retrieval.yaml --target baseline   # 기본값
linkpaper-eval run --config configs/retrieval.yaml --target http       # 백엔드 API
```

- `baseline` — 순수 파이썬 BM25. 외부 의존성이 없고 결정적이다.
- `http` — 백엔드 `POST /api/v1/conversations/{id}/messages` 호출.

베이스라인은 단순한 하한선 역할을 한다. 그래프 확장과 벡터 검색을 붙였는데
BM25보다 낮게 나온다면 파이프라인에 문제가 있다는 신호다.

백엔드 라우트가 아직 `501`을 반환하므로 `--target http`는 현재 오류율 1.0을
보고한다. 크래시가 아니라 정상 동작이며, 구현 진척이 지표로 드러난다.

## 회귀 게이트

평가를 리포트로만 두면 아무도 보지 않게 된다. 게이트는 기준 미달과 회귀를
종료 코드 1로 바꿔서 CI에서 막는다.

```yaml
gates:
  retrieval.recall@5:
    min: 0.55            # 절대 하한
    max_regression: 0.03 # 베이스라인 대비 허용 하락폭
  operational.error_rate:
    max: 0.05
```

`max_regression`은 절대 기준을 정하기 어려운 초기 단계에서 "적어도 나빠지지는
않는다"를 보장한다. `error_rate`나 `latency`처럼 낮을수록 좋은 지표는 방향을
자동으로 뒤집어 판정한다.

지표가 이번 실행에 아예 없으면 통과가 아니라 실패로 처리한다. 지표가 조용히
사라져서 게이트가 무력화되는 상황을 막기 위해서다.

베이스라인 갱신은 의도적인 변경일 때만 한다.

```bash
linkpaper-eval run --config configs/retrieval.yaml --run-id 2026-07-28-a
linkpaper-eval baseline --config configs/retrieval.yaml --run-id 2026-07-28-a
```

## 데이터셋

JSONL 한 줄이 케이스 하나다.

```json
{
  "case_id": "ret-005",
  "question": "Which architecture is BERT built on top of?",
  "paper_id": "arxiv:1810.04805",
  "gold_chunk_ids": ["arxiv:1810.04805:chunk:0:f7a8b9c0"],
  "gold_paper_ids": ["arxiv:1810.04805", "arxiv:1706.03762"],
  "grades": {"arxiv:1810.04805:chunk:0:f7a8b9c0": 3},
  "expected_scope": "global",
  "tags": ["global", "citation"]
}
```

- `grades`는 nDCG용 등급 관련도다. 생략하면 정답 청크를 관련도 1로 본다.
- `expected_scope`는 "선택 논문만으로 답변 가능한가" 판단의 정답이다.
- `tags`는 태그별 집계에 쓴다. 질문 유형별 약점을 찾는 용도다.

`chunk_id`는 neo4j-schema.md 7.2절의 형식을 따른다. 정답 ID에 오타가 있으면
Recall이 조용히 0이 되므로, 테스트가 코퍼스 존재 여부를 검증한다.

현재 데이터셋은 파이프라인 검증용 샘플이다. 실제 평가 규모로 쓰려면 케이스를
확장해야 하며, 특히 `global`·`follow-up` 태그를 늘려야 한다.

## 현재 베이스라인 결과

BM25 베이스라인의 검색 성능은 질문 유형에 따라 크게 갈린다.

| 태그 | Recall@5 |
|---|---:|
| `local` (선택 논문 내부) | 0.94 |
| `global` (코퍼스 확장 필요) | 0.38 |
| `follow-up` (후속 연구 탐색) | 0.25 |

라우팅 정확도는 0.67이다. 단순 검색으로는 "이 논문의 한계를 해결한 후속
연구는?" 같은 질문을 풀지 못한다는 뜻이며, 이 격차가 GraphRAG가 메워야 할
부분이다. PROJECT_SPEC의 문제의식과 정확히 일치한다.

## 알려진 한계

- `groundedness_lexical`은 근거 문장을 그대로 복사하는 추출식 답변에서 1.0이
  나온다. 환각의 상한을 재는 대리 지표일 뿐이므로 `answer_token_f1`,
  `must_include`와 함께 봐야 한다.
- 어간 추출을 하지 않아 `improves`와 `improve`를 다른 토큰으로 센다. 절대값
  대신 실행 간 상대 변화를 본다.
- 한국어 질의는 어절 단위로만 처리한다. 형태소 분석기나 다국어 임베딩 도입
  전까지는 `korean` 태그 점수가 낮게 나오는 것이 정상이다.
- LLM 심판(`judge.type: openai`)은 점수에 분산이 있으므로 CI 게이트 기준으로
  쓰지 않는다. 기본값은 결정적 심판이다.
