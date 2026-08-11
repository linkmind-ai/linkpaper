# 벤치마크 데이터

`bench prepare`가 이 디렉터리 아래에 `data/<이름>/`을 만든다.

```text
benchmarks/data/qasper/
├── raw/              # 원본 캐시. 다시 받지 않기 위한 것
├── corpus.jsonl      # 청크 코퍼스 (fixtures/mock_corpus.jsonl과 같은 형식)
├── retrieval.jsonl   # EvalCase
├── generation.jsonl
└── manifest.json     # 원본 해시, 케이스 수, 근거 매칭률
```

`data/`는 gitignore 대상이다. 이유가 두 가지다.

1. GraphRAG-Bench처럼 **재배포가 금지된** 데이터셋이 저장소에 섞이면 안 된다.
2. 코퍼스가 수백 MB까지 커진다.

재현에 필요한 것은 데이터 자체가 아니라 `registry.py`의 명세와
`manifest.json`의 해시다. 같은 명세로 `prepare`를 돌리면 같은 데이터셋이
나온다.

설정 방법과 수동 다운로드 경로는 [docs/benchmark.md](../../docs/benchmark.md)에
있다.
