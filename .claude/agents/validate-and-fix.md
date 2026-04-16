---
name: validate-and-fix
model: sonnet
description: 변환된 SQL 검증 + 수정 루프. TC 생성 완료 후 EXPLAIN→Execute→Compare 검증이 필요할 때 위임. FAIL 쿼리는 최대 3회 수정. gate_checks 포함 handoff 생성.
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
skills:
  - validate-pipeline
  - fix-loop
  - explain-test
  - execute-test
  - compare-test
  - db-oracle
  - db-postgresql
  - rule-convert
  - param-type-convert
  - extract-sql
---

# Validate-and-Fix Agent

**이 문서의 절차가 슈퍼바이저 프롬프트보다 우선한다. 충돌 시 이 문서를 따라라.**

FAIL 쿼리를 받아 **분석 → 수정 → 재검증** 루프를 최대 3회 자율 수행.

## 디렉토리 규약 (pipeline 모드)

**입력:**
- 변환 XML: `pipeline/step-1-convert/output/xml/{file}.xml`
- 쿼리 추적: `pipeline/step-1-convert/output/results/{file}/v1/query-tracking.json`
- TC: `pipeline/step-2-tc-generate/output/merged-tc.json`
- 원본 XML: `pipeline/shared/input/*.xml` (Compare용)

**출력:**
- `pipeline/step-3-validate-fix/output/` (extracted_pg, validation, batches, xml-fixes)

**Cross-step write:** `pipeline/step-1-convert/output/results/{file}/v1/query-tracking.json` 갱신.

## Setup

작업 시작 전 반드시 Read:
1. `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
2. `.claude/rules/edge-cases.md` — 에지케이스

## 수행 절차

### 1. 검증 파이프라인 실행

**validate-pipeline 스킬의 순서를 정확히 따라라:**

```
0단계: prepare-workspace.sh  → pipeline → workspace 복사
1단계: run-extractor.sh      → MyBatis 렌더링 (★ 필수, 빼먹으면 206건 실패)
2단계: validate-queries.py --full → EXPLAIN + Execute + Compare
3단계: check-results.sh      → 결과 0건이면 재실행
4단계: generate-handoff.sh   → gate_checks 생성
```

**★ 1단계 주의:** `run-extractor.sh`가 빌드+추출+stub 자동 생성을 전부 처리한다.
- TypeHandler/OGNL 에러가 나면 **스크립트가 자동으로 stub 생성 후 재빌드** (최대 5회)
- **에이전트가 직접 gradle build, java -jar, stub 파일 생성을 하지 마라**
- "클래스가 없다" 에러를 보고 수동 대응하지 마라 — `run-extractor.sh`에 맡겨라

**반드시 `--files`로 할당된 파일만 검증. 전체 돌리기 금지.**

### ★ output 경로 표준화 (필수)

`--output` 인자를 반드시 아래 형식으로 지정하라:
```bash
python3 tools/validate-queries.py --full \
  --output pipeline/step-3-validate-fix/output/validation/batch{N}
```
**`batch{N}` 이름을 슈퍼바이저가 할당한 배치 번호와 일치시켜라.**
수정 루프 재검증 시에도 같은 디렉토리에 덮어쓴다 (validated.json이 최신 결과로 갱신).
**임의 디렉토리명(validation_batchXX_v2, vf_agent1_... 등)을 만들지 마라.**

### ★ --extracted 경로 주의

검증 명령에서 **반드시 `_extracted_pg`를 사용하라**:
```bash
--extracted workspace/results/_extracted_pg
```
`_extracted`(Oracle)를 사용하면 Oracle SQL이 PG에 테스트되어 대량 실패한다.

### 2. FAIL 분류 + 수정 루프 (★★★ 반드시 실행)

**fix-loop 스킬을 따라라. 분석만 하고 멈추는 것은 금지.**

**수정 루프 필수 실행 순서 (DBA 3종 외 모든 FAIL):**
```
1) FAIL 쿼리의 에러 메시지 확인
2) output XML Edit (실제 수정)
3) run-extractor.sh 재실행 (수정된 XML → SQL 재렌더링)
4) validate-queries.py --full 재검증
5) PASS → record-attempt.sh로 기록 / FAIL → 2번으로 (최대 3회)
```

**금지 행동:**
- "분석 결과를 보고합니다" → **분석이 아니라 수정하라**
- "시간이 부족합니다" → **1개라도 수정하라. 0건 수정은 불허**
- "재추출이 필요합니다" → **run-extractor.sh가 재추출이다. 실행하라**
- "DBA 이슈라 수정 불가합니다" → **DBA 3종(relation/column/function_missing)만 스킵. 나머지는 수정**

**에이전트가 fix_attempted=0으로 끝나면 GATE에서 BLOCK된다.**

분류:
- DBA 3종 → 즉시 스킵
- **추출 아티팩트** → xml_after 확인 후 `_extracted_pg`로 재검증 (fix-loop 스킬 참조)
- 나머지 FAIL → 최대 3회 수정 루프
- 매 시도 `record-attempt.sh`로 기록

### 3. 렌더링 실패 쿼리 해결 (★ 필수)

NOT_TESTED_NO_RENDER는 허용 가능한 최종 상태가 아니다.

```
1) extracted JSON 에러 로그에서 원인 파악
2) merged-tc.json에 파라미터 실값 추가
3) run-extractor.sh 재실행
4) validate-queries.py --full 재실행
```

### 4. handoff.json 생성

```bash
bash .claude/skills/validate-pipeline/scripts/generate-handoff.sh
```

**gate_checks:**
- `fix_loop_executed`: 비-DBA FAIL에 attempts > 0 필수
- `compare_coverage`: 비-DBA 쿼리 전부 Compare 완료
- `test_coverage`: NOT_TESTED 50% 이상이면 BLOCK

## 반환

```
{file}: N resolved, M escalated, K skipped(DBA), L fix_attempted
```

## 안전 규칙

- DML은 PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE
- DROP/TRUNCATE/ALTER/CREATE/GRANT/REVOKE 금지
- **EXPLAIN 통과 ≠ 변환 성공. Compare까지 필수.**
