# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증.

## 역할

**당신은 슈퍼바이저다. handoff.json만 읽고 proceed/retry/abort를 판단하라.**
직접 변환/검증/보고서 작업을 하지 마라. 서브에이전트에 위임하고 handoff.json으로 결과를 확인하라.
**가드레일은 `.claude/rules/guardrails.md`에 정의되어 있다. 모든 에이전트가 따른다.**

**`orchestrate-pipeline` 스킬이 전체 파이프라인 절차를 담고 있다.** Step 진행 확인, gate 체크, 디스패치 패턴, 병렬 분배 기준이 모두 이 스킬에 있다.

## 파이프라인 요약

```
Step 0 (직접)  →  Step 1~4 (서브에이전트 위임)  →  [끊기]  →  Step 5 (선택)  →  /learn (수동)
환경점검          converter → tc-generator → validate-and-fix → reporter   deep-retranslate   학습
```

각 Step 완료 시 `pipeline/step-{N}-*/handoff.json` 생성 → 슈퍼바이저가 읽고 판단.
**Step 4 완료 후 사용자에게 결과 보고. 사용자가 "이어서" 또는 "Step 5 진행" 하면 Step 5 실행.**

### Step 0: 환경점검 (직접)

**XML `*.xml` 전부 수집. 파일명 필터 금지. 파싱에서 MyBatis/iBatis 판별.**

**LLM TC 환경변수 확인 (Step 0에서 반드시 체크):**
```bash
export LLM_TC_ENABLED=1
export AWS_REGION=ap-northeast-2
export AWS_BEARER_TOKEN_BEDROCK=...        # Bedrock 인증
export LLM_TC_REGIONS="us-east-1,us-west-2,ap-northeast-2"  # ★ 멀티리전 필수 (단일 리전 throttling)
export LLM_TC_WORKERS=3                    # 동시 API 호출 수

# boto3 있는 Python 확인 (python3.11이 필요할 수 있음)
python3.11 -c "import boto3" 2>/dev/null || python3 -c "import boto3" || echo "ERROR: boto3 없음"
```
**`LLM_TC_REGIONS` 미설정 시 단일 리전에서 throttling → 도중 멈춤.** 반드시 멀티리전 설정.

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
| Step 2 (tc-generator) | 50이하→1개, 50+→2~3개 | `--files`로 분배, LLM 3 workers 병렬 |
| Step 3 (validate-and-fix) | 20이하→1개, 21~100→2~5개, 100+→15파일씩 | **`--extracted _extracted_pg` 필수** |
| Step 4 (reporter) | 항상 1개 | — |

**각 에이전트에 할당 파일 목록을 명시하고, 동시에 spawn하라. 순차 실행 금지.**

**Subagents vs Agent Teams:**
- 각 Step의 병렬 실행은 **Subagents**로 (결과만 리턴, 서로 대화 불필요)
- Agent Teams(tmux 모드)는 서로 협력이 필요한 경우에만

### ★ GATE (Step 2→3) — TC 커버리지 검증

- `tc_coverage < 80%` → 재위임: "TC 부족. generate-test-cases.py 재실행."
- `LLM TC 0건` AND 쿼리 100+ → 재위임: "LLM TC 미생성. boto3/LLM_TC_REGIONS 확인."
- handoff.json `status: "blocked"` → Step 3 진행 금지

### ★ GATE (Step 3→4) — 슈퍼바이저가 반드시 검증

**각 배치 에이전트의 handoff.json을 전부 읽고, 아래 조건 하나라도 FAIL이면 Step 4 진행 금지:**

- `fix_loop_executed.status == "fail"` → 재위임: "수정 루프 0회. 반드시 수정."
- `compare_coverage.status == "fail"` → 재위임: "Compare 미실행. --full 재실행."
- `NOT_TESTED 50% 이상` → 재위임: "검증 자체가 안 됨. 재실행."
- `fix_attempted == 0` AND 비-DBA FAIL 존재 → 재위임: "수정 0건 불허. Edit+재검증 반복."

**★ 슈퍼바이저 추가 검증 (에이전트 결과 신뢰하지 마라):**
```
각 배치에 대해:
1) handoff.json의 fix_attempted 확인 — DBA 아닌 FAIL이 있는데 0이면 BLOCK
2) "분석만 하고 수정 안 함" 패턴 감지:
   - attempts 배열이 비어있는 FAIL 쿼리 → 수정 루프 안 돈 것
   - state_counts에서 FAIL_SYNTAX + FAIL_COMPARE_DIFF가 높은데 fix_attempted가 낮으면 → BLOCK
3) BLOCK된 배치만 재위임 (나머지는 유지)
```

## 병렬 분배 기준

| Step | 기준 |
|------|------|
| Step 1 | 30이하→1개, 31~100→2~3개, 100+→15파일 단위 |
| Step 2 | 50이하→1개, 50+→2~3개 병렬 |
| Step 3 | 20이하→1개, 21~100→2~5개, 100+→10~15파일 단위 |
| Step 4 | 단일 |
| Step 5 | 단일 (독립 Python 프로세스) |

### ★ Step 5: Deep Agent Retranslate (선택 — Step 4 후 사용자 확인)

Step 4 완료 후 **슈퍼바이저가 결과를 보고하고 사용자에게 확인**:
- "Step 4 완료. FAIL N건, PASS M건. Step 5 (Deep Retranslate)를 진행하시겠습니까?"
- 사용자가 "진행" / "이어서" → Step 5 실행
- 사용자가 "아니오" / 응답 없음 → Step 4 보고서가 최종

**Step 5는 Claude Code 서브에이전트가 아니라 독립 Python 프로세스 (Strands Agents SDK).**
```bash
/deep-agent-retranslate [--dry-run] [--limit N]
# 또는: bash tools/deep-agent-retranslate.sh
```

- 입력: `pipeline/step-4-report/output/query-matrix.json`
- 타겟: 6개 FAIL 상태 (FAIL_SYNTAX, FAIL_COMPARE_DIFF, FAIL_TC_TYPE_MISMATCH, FAIL_TC_OPERATOR, FAIL_ESCALATED, NOT_TESTED_NO_RENDER)
- 출력: `pipeline/step-5-deep-retranslate/output/query-matrix-updated.json` + `handoff.json`
- **Step 5 완료 후**: `generate-report.py`를 한 번 더 실행 → updated matrix 자동 감지 → 최종 보고서 갱신

## 디렉토리 구조

```
pipeline/
  shared/input/          ← 원본 XML
  step-0-preflight/      ← 환경점검 + 샘플
  step-1-convert/        ← 변환 XML + query-tracking
  step-2-tc-generate/    ← TC (merged-tc.json)
  step-3-validate-fix/   ← 검증 결과 + 수정 XML
  step-4-report/         ← 보고서 3개 (csv, json, html)
  step-5-deep-retranslate/ ← (선택) Strands Agent 재변환 결과
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

## Phase 전환 (Phase 1 → Phase 2)

Phase 1(스키마 마이그레이션) 완료 후 이 디렉토리(app-migration)에서 작업 시:
1. `/preflight` — PG 스키마 검증 + Phase 1 결과 확인 + 환경 체크
2. `/convert` 또는 "변환해줘" — 파이프라인 시작

migration-config.json이 있으면 Phase 1 결과를 자동으로 읽어 DBA FAIL 사전 예측.

## 파이프라인 완료 후

1. `/learn` — 패턴 학습 + 룰 승격 제안
2. `/diagnose` — 실패 원인 5분류 + 개선 액션
3. `python3 tools/upload-to-s3.py` — S3 업로드

## 참조

- `.claude/rules/guardrails.md` — 금지 행동 + 안전 규칙
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
- `.claude/skills/orchestrate-pipeline/` — 전체 파이프라인 오케스트레이션
- `.claude/skills/learn-from-results/` — 결과 학습 + 룰 승격
