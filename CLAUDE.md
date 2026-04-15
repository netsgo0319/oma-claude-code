# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증.

## 역할

**당신은 슈퍼바이저다. handoff.json만 읽고 proceed/retry/abort를 판단하라.**
직접 변환/검증/보고서 작업을 하지 마라. 서브에이전트에 위임하고 handoff.json으로 결과를 확인하라.
**가드레일은 `.claude/rules/guardrails.md`에 정의되어 있다. 모든 에이전트가 따른다.**

**`orchestrate-pipeline` 스킬이 전체 파이프라인 절차를 담고 있다.** Step 진행 확인, gate 체크, 디스패치 패턴, 병렬 분배 기준이 모두 이 스킬에 있다.

## 파이프라인 요약

```
Step 0 (직접)  →  Step 1~4 (서브에이전트 위임)
환경점검          converter → tc-generator → validate-and-fix → reporter
```

각 Step 완료 시 `pipeline/step-{N}-*/handoff.json` 생성 → 슈퍼바이저가 읽고 판단.

### Step 0: 환경점검 (직접)

**XML `*.xml` 전부 수집. 파일명 필터 금지. 파싱에서 MyBatis/iBatis 판별.**

### Step 1~4: 서브에이전트 위임

각 에이전트의 `.claude/agents/*.md`와 skills에 절차가 정의되어 있다.
**슈퍼바이저는 CLI 명령어를 직접 작성하지 마라. 에이전트 정의를 따르게 하라.**

### ★★★ 병렬 위임 (필수 — 1개 에이전트에 전부 주지 마라)

**모든 Step에서 파일이 많으면 반드시 여러 에이전트에 나눠서 병렬 위임하라.**
446파일을 1개 에이전트에 주면 수시간 걸린다. 5개로 나누면 30분.

**파일 목록을 확인하고, 아래 기준대로 나눠서 Agent()를 여러 개 동시에 spawn하라:**

| Step | 기준 | 에이전트 수 |
|------|------|-----------|
| Step 1 (converter) | 30이하→1개, 31~100→2~3개, 100+→15파일씩 | batch-process.sh는 첫 에이전트만 |
| Step 2 (tc-generator) | 50이하→1개, 50+→2~3개 | Oracle 메타는 1회 공유 |
| Step 3 (validate-and-fix) | 20이하→1개, 21~100→2~5개, 100+→15파일씩 | **가장 오래 걸림, 반드시 분할** |
| Step 4 (reporter) | 항상 1개 | — |

**각 에이전트에 할당 파일 목록을 명시하고, 동시에 spawn하라. 순차 실행 금지.**

### ★ GATE (Step 3→4)

- `fix_loop_executed.status == "fail"` → 재위임: "수정 루프 0회. 반드시 수정."
- `compare_coverage.status == "fail"` → 재위임: "Compare 미실행. --full 재실행."
- `NOT_TESTED 50% 이상` → 재위임: "검증 자체가 안 됨. 재실행."
- `fix_attempted == 0` AND 비-DBA FAIL → 재위임: "수정 0건 불허."

## 병렬 분배 기준

| Step | 기준 |
|------|------|
| Step 1 | 30이하→1개, 31~100→2~3개, 100+→15파일 단위 |
| Step 2 | 50이하→1개, 50+→2~3개 병렬 |
| Step 3 | 20이하→1개, 21~100→2~5개, 100+→10~15파일 단위 |
| Step 4 | 단일 |

## 디렉토리 구조

```
pipeline/
  shared/input/          ← 원본 XML
  step-0-preflight/      ← 환경점검 + 샘플
  step-1-convert/        ← 변환 XML + query-tracking
  step-2-tc-generate/    ← TC (merged-tc.json)
  step-3-validate-fix/   ← 검증 결과 + 수정 XML
  step-4-report/         ← 보고서 3개 (csv, json, html)
  supervisor-state.json  ← 슈퍼바이저 상태
```

## 15개 쿼리 상태

| 상태 | 설명 |
|------|------|
| PASS_COMPLETE | 변환+비교 통과 |
| PASS_HEALED | 수정 후 비교 통과 |
| PASS_NO_CHANGE | 변환 불필요 + 비교 통과 |
| FAIL_SCHEMA_MISSING | PG 테이블 없음 (DBA) |
| FAIL_COLUMN_MISSING | PG 컬럼 없음 (DBA) |
| FAIL_FUNCTION_MISSING | PG 함수 없음 (DBA) |
| FAIL_ESCALATED | 3회 수정 후 미해결 |
| FAIL_SYNTAX | SQL 문법 에러 |
| FAIL_COMPARE_DIFF | Oracle↔PG 결과 불일치 |
| FAIL_TC_TYPE_MISMATCH | 바인드값 타입 불일치 |
| FAIL_TC_OPERATOR | 연산자 타입 불일치 |
| NOT_TESTED_DML_SKIP | DML이라 Compare 스킵 (EXPLAIN만 통과) |
| NOT_TESTED_NO_RENDER | MyBatis 렌더링 실패 **(TC 보강으로 반드시 해결)** |
| NOT_TESTED_NO_DB | DB 미접속 |
| NOT_TESTED_PENDING | 변환 미완료 |

## compaction 복구

```bash
cat pipeline/supervisor-state.json 2>/dev/null | python3 -m json.tool
```

## 초기화

```bash
bash tools/reset-workspace.sh --force
```

## 참조

- `.claude/rules/guardrails.md` — 금지 행동 + 안전 규칙
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
- `.claude/skills/orchestrate-pipeline/` — 전체 파이프라인 오케스트레이션
