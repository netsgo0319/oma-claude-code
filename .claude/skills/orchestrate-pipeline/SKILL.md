---
name: orchestrate-pipeline
description: 전체 파이프라인 오케스트레이션 — Step 0→1→2→3→4 진행 판단. 슈퍼바이저(CLAUDE.md)가 사용.
allowed-tools:
  - Bash
  - Read
---

# Orchestrate Pipeline

슈퍼바이저가 사용하는 전체 파이프라인 오케스트레이션.
**handoff.json만 읽고 proceed/retry/abort 판단.**

## Step 진행 확인

```bash
for i in 0 1 2 3 4; do
  status=$(bash ${CLAUDE_SKILL_DIR}/scripts/check-step.sh $i)
  echo "Step $i: $status"
done
```

## Step 3→4 Gate 확인 (★ 가장 중요)

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/check-gate.sh
```

**BLOCKED이면 Step 4 진행 금지. validate-and-fix 재위임:**
- fix_loop_executed fail → "수정 루프 0회. 반드시 수정."
- compare_coverage fail → "Compare 미실행. --full 재실행."
- test_coverage fail (NOT_TESTED >50%) → "psql 출력 캡처 실패. 재실행."

## 디스패치 패턴

### Step 1: converter
```
Agent({ subagent_type: "converter", prompt: "
  할당 파일: {파일목록}
  convert-pipeline 스킬을 따라라.
  완료 시 handoff.json 생성." })
```

### Step 2: tc-generator
```
Agent({ subagent_type: "tc-generator", prompt: "
  tc-pipeline 스킬을 따라라.
  완료 시 handoff.json 생성." })
```

### Step 3: validate-and-fix
```
Agent({ subagent_type: "validate-and-fix", prompt: "
  할당 파일: {파일목록}
  validate-pipeline 스킬을 따라라.
  FAIL은 fix-loop 스킬로 수정.
  완료 시 handoff.json 생성 (gate_checks 포함)." })
```

### Step 4: reporter
```
Agent({ subagent_type: "reporter", prompt: "
  report-pipeline 스킬을 따라라.
  gate 확인 후 보고서 생성." })
```

## Retry 로직

| Step | max_retries |
|------|------------|
| 0 | 1 |
| 1 | 2 |
| 2 | 1 |
| 3 | 3 |
| 4 | 2 |

## Compaction 복구

```bash
cat pipeline/supervisor-state.json 2>/dev/null | python3 -m json.tool
```
