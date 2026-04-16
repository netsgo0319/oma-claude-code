---
name: diagnose-failures
description: 마이그레이션 결과 실패 원인 분석 + 개선 제안. 파이프라인 완료 후 FAIL/NOT_TESTED 쿼리를 분류하고, 근본 원인(변환 버그 vs TC 품질 vs 추출 한계 vs DBA)을 데이터 기반으로 판별합니다. /diagnose로 수동 실행하거나 Step 4 후 자동 수행.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Grep
---

# Diagnose Failures

FAIL/NOT_TESTED 쿼리의 근본 원인을 **데이터 기반으로** 분류하고 개선 액션을 제안.

**★ 추측 금지. 반드시 아래 데이터를 확인하고 판단하라.**

## 실행 방법

```bash
python3 tools/diagnose-failures.py \
  --matrix pipeline/step-4-report/output/query-matrix.json \
  --output pipeline/diagnose/
```

또는 query-matrix.json 없이 tracking에서 직접:
```bash
python3 tools/diagnose-failures.py \
  --results-dir pipeline/step-1-convert/output/results \
  --validation-dir pipeline/step-3-validate-fix/output/validation \
  --output pipeline/diagnose/
```

## 분석 항목

### 1. FAIL 원인 5분류

| 분류 | 판별 기준 | 액션 |
|------|----------|------|
| **변환 버그** | mybatis_extracted≠'no' AND FAIL_SYNTAX AND xml_after에 Oracle패턴 잔존 | converter 재수정 |
| **TC 품질** | Oracle에서도 실패 (oracle_error) OR 타입 불일치 | TC 재생성 (LLM) |
| **추출 한계** | mybatis_extracted='no' AND FAIL_SYNTAX | pre-resolve-includes + 재추출 |
| **DBA 스키마** | FAIL_SCHEMA/COLUMN/FUNCTION_MISSING | DBA에게 DDL 전달 |
| **Compare 불일치** | FAIL_COMPARE_DIFF AND 양쪽 실행 성공 | SQL 로직 검토 |

### 2. NOT_TESTED 원인 3분류

| 분류 | 판별 기준 | 액션 |
|------|----------|------|
| **렌더링 실패** | NOT_TESTED_NO_RENDER | TC 보강 + 재추출 |
| **DML 스킵** | NOT_TESTED_DML_SKIP | 정상 (EXPLAIN 통과됨) |
| **DB 미접속** | NOT_TESTED_NO_DB | 환경 체크 |

### 3. 개선 제안 자동 생성

분석 결과에서 **반복 패턴**을 추출하여 구체적 액션 제안:
- "TRUNC(숫자) 오변환 15건 → converter에 인자 수 분기 룰 추가"
- "cross-file include 미해결 23건 → pre-resolve-includes.py 실행 필요"
- "varchar=integer 타입 불일치 42건 → PG 타입 인식 바인딩 확인"

## 산출물

```
pipeline/diagnose/
  diagnosis-{date}.json       ← 분류별 건수 + 쿼리 목록
  improvement-actions.md      ← 우선순위별 개선 액션
  top-errors.md               ← 에러 메시지 Top 20 (빈도순)
```

## 체크리스트

```
실패 진단:
- [ ] query-matrix.json 또는 tracking 로드
- [ ] FAIL 5분류 실행
- [ ] NOT_TESTED 3분류 실행
- [ ] 반복 패턴 추출
- [ ] 개선 액션 생성
- [ ] 산출물 저장
```

## 참조 문서

- [guardrails — FAIL 분석 규칙](../../rules/guardrails.md)
- [learn-from-results — 패턴 학습](../learn-from-results/SKILL.md)
- [query-matrix 스키마](../../schemas/query-matrix.schema.json)
