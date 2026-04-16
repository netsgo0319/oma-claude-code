---
name: orchestrate-pipeline
description: 전체 Oracle→PostgreSQL 마이그레이션 파이프라인 오케스트레이션. 사용자가 '변환해줘', 'migration 시작', 'XML 변환' 등을 요청하거나, Step 0→1→2→3→4 순서를 따라 서브에이전트를 위임하고 handoff.json으로 진행을 판단할 때 사용합니다.
allowed-tools: Bash Read
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

### Step 3: validate-and-fix (Scout → Broadcast)

**3a: Scout (복잡한 파일 선별, 2배치)**
complexity L3/L4 파일 + 패턴 다양한 파일 30개를 2배치로 먼저 실행.
```
Agent({ subagent_type: "validate-and-fix", prompt: "
  할당 파일: {L3/L4 파일 15개}
  validate-pipeline 스킬을 따라라.
  FAIL은 fix-loop 스킬로 수정.
  ★ 수정 성공 시 shared_fix_registry.record_fix()로 패턴 기록.
  완료 시 handoff.json 생성." })
```

**3b: Pre-apply (scout 결과 일괄 적용)**
Scout에서 발견된 수정 패턴을 나머지 파일에 일괄 적용.
```bash
python3 tools/shared_fix_registry.py pre-apply \
  --xml-dir pipeline/step-1-convert/output/xml
```

**3c: Validate 나머지 (N배치 병렬)**
```
Agent({ subagent_type: "validate-and-fix", prompt: "
  할당 파일: {나머지 파일목록}
  validate-pipeline 스킬을 따라라.
  ★ fix-loop 전에 shared-fixes.jsonl 확인 (알려진 패턴 우선 적용).
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

## 체크리스트

```
파이프라인 오케스트레이션:
- [ ] Step 0: 환경점검 (XML 수, Python, psql, sqlplus, Java)
- [ ] Step 1: converter 위임 → handoff.json 확인
- [ ] Step 2: tc-generator 위임 → handoff.json 확인
- [ ] Step 3: validate-and-fix 위임 → gate_checks 확인 (★)
- [ ] GATE: fix_loop=pass AND compare=pass AND NOT_TESTED<50%
- [ ] Step 4: reporter 위임 → 산출물 3개 확인
```

## 참조 문서

- [handoff 스키마](../../schemas/handoff.schema.json)
- [가드레일](../../rules/guardrails.md)
