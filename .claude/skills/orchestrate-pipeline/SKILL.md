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

## 에이전트 진행 모니터링

서브에이전트 spawn 후 대기 중 주기적으로 실행하여 사용자에게 진행 상태를 보여줘라:

```bash
echo "=== 에이전트 진행 상태 ==="
# Step 1: 변환 완료 파일 수
echo "Step 1 변환:"
ls pipeline/step-1-convert/output/xml/*.xml 2>/dev/null | wc -l | xargs -I{} echo "  변환 XML: {} 파일"

# Step 2: TC 생성 현황
echo "Step 2 TC:"
python3 -c "
import json, glob
tc_files = glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json')
total_tcs = 0
for f in tc_files:
    try: total_tcs += sum(len(v) for v in json.load(open(f)).values())
    except: pass
print(f'  TC 파일: {len(tc_files)}, TC 총: {total_tcs}건')
" 2>/dev/null

# Step 3: 검증 배치 현황
echo "Step 3 검증:"
for d in pipeline/step-3-validate-fix/output/validation/batch*/; do
  [ -d "$d" ] || continue
  if [ -f "$d/validated.json" ]; then
    python3 -c "import json;d=json.load(open('${d}validated.json'));print(f'  $(basename $d): PASS={d.get(\"pass\",0)} FAIL={d.get(\"fail\",0)}')" 2>/dev/null
  else
    echo "  $(basename $d): 진행 중..."
  fi
done
```

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
- [ ] Step 5: 실패 진단 (/diagnose) → 개선 액션 확인
- [ ] (선택) /learn → 패턴 학습 + 룰 승격
```

### Step 5: 실패 진단 (Step 4 완료 후 자동 또는 /diagnose)
```bash
python3 tools/diagnose-failures.py \
  --matrix pipeline/step-4-report/output/query-matrix.json \
  --output pipeline/diagnose/
```
FAIL/NOT_TESTED 근본 원인 5+3분류 → 우선순위별 개선 액션 생성.
`improvement-actions.md`를 읽고 다음 실행에 반영.

## 참조 문서

- [handoff 스키마](../../schemas/handoff.schema.json)
- [가드레일](../../rules/guardrails.md)
