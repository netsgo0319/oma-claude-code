---
name: learn-from-results
description: 마이그레이션 결과 학습. 사용자가 '/learn', '학습', '패턴 분석', '룰 승격' 등을 요청할 때 사용합니다. query-matrix.json에서 반복 패턴을 추출하고, 에지케이스→룰 승격 후보를 제안합니다. 파이프라인 완료 후 수동 실행.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Edit
---

# Learn from Results

마이그레이션 실행 결과를 분석하여 반복 패턴 추출 + 룰 승격 제안.

**수동 실행 전용** — 파이프라인 완료 후 필요할 때 `/learn` 으로 호출.

## 분석 실행

```bash
python3 tools/learn-from-results.py \
  --matrix pipeline/step-4-report/output/query-matrix.json \
  --rules .claude/rules/oracle-pg-rules.md \
  --edge-cases .claude/rules/edge-cases.md \
  --output pipeline/learning/
```

## 분석 대상

| 소스 | 추출 내용 |
|------|----------|
| PASS_HEALED 쿼리 | fix attempts에서 성공한 변환 패턴 |
| FAIL_ESCALATED 쿼리 | 3회 실패 → 신규 에지케이스 후보 |
| FAIL_SYNTAX/COMPARE_DIFF | 반복 에러 유형 분류 |
| conversion_history | 기존 룰 적용 현황 (효과 측정) |

## 승격 기준

| 조건 | 액션 |
|------|------|
| 같은 패턴 3회+ (누적) + regex 치환 가능 | `oracle-to-pg-converter.py` 룰 추가 제안 |
| 같은 패턴 3회+ (누적) + LLM 판단 필요 | `oracle-pg-rules.md` 가이드 추가 제안 |
| 1~2회 등장 | `edge-cases.md` 기록 |
| FAIL_ESCALATED 반복 | DBA 에스컬레이션 대상 |

## 산출물

```
pipeline/learning/
  run-{date}.json          ← 이번 실행 분석 결과
  cumulative.json          ← 패턴별 누적 카운트 (실행마다 갱신)
  promotion-candidates.md  ← 승격 후보 마크다운 (사람이 검토)
```

## 산출물 확인 + 반영

분석 결과를 확인하고, 필요시 룰 반영:

```bash
# 1. 승격 후보 확인
cat pipeline/learning/promotion-candidates.md

# 2. 누적 패턴 확인
python3 -c "
import json
c = json.load(open('pipeline/learning/cumulative.json'))
for p, info in sorted(c['patterns'].items(), key=lambda x: -x[1]['count']):
    print(f\"{info['count']:3d}x  {info['status']:12s}  {p}\")
"
```

승격 후보 중 반영할 것은 직접 수정:
- **regex 치환 가능** → `tools/oracle-to-pg-converter.py`의 `_RULES` 배열에 추가
- **가이드 필요** → `.claude/rules/oracle-pg-rules.md`에 룰 추가
- **에지케이스** → `.claude/rules/edge-cases.md`에 기록

## 참조 문서

- [oracle-pg-rules](.claude/rules/oracle-pg-rules.md)
- [edge-cases](.claude/rules/edge-cases.md)
- [query-matrix 스키마](../../schemas/query-matrix.schema.json)
