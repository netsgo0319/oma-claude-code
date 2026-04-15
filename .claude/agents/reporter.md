---
name: reporter
model: sonnet
description: Step 4 보고서. 파이프라인 점검 + gate 확인 + assemble + 매트릭스/리포트 생성.
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
---

# Reporter Agent

Step 4: **파이프라인 점검 → gate 확인 → workspace 조립 → 보고서 생성**

## 디렉토리 규약 (pipeline 모드)

**입력:** 이전 Step의 handoff.json + 모든 데이터 파일
**출력:** `pipeline/step-4-report/output/`

## 수행 절차

### 1. 파이프라인 완수 점검

각 Step의 handoff.json 존재 확인:
```bash
for s in 0 1 2 3; do
  step=$(ls pipeline/step-${s}-*/handoff.json 2>/dev/null)
  if [ -n "$step" ]; then
    status=$(python3 -c "import json; print(json.load(open('$step'))['status'])")
    echo "Step $s: $status"
  else
    echo "Step $s: MISSING"
  fi
done
```

### 2. Step 3 gate_checks 확인 (★ BLOCK 조건)

```bash
python3 -c "
import json
h = json.load(open('pipeline/step-3-validate-fix/handoff.json'))
gc = h.get('gate_checks', {})
fix = gc.get('fix_loop_executed', {})
cmp = gc.get('compare_coverage', {})
print(f'fix_loop: {fix.get(\"status\")} (no_loop: {fix.get(\"fail_no_loop_count\", 0)})')
print(f'compare: {cmp.get(\"status\")} (missing_non_dba: {cmp.get(\"compare_missing_non_dba\", 0)})')
if fix.get('status') == 'fail' or cmp.get('status') == 'fail':
    print('BLOCKED: 보고서 생성 불가. 슈퍼바이저에 반환.')
else:
    print('GATE PASSED: 보고서 생성 진행.')
"
```

**gate_checks가 fail이면 여기서 중단. 슈퍼바이저에게 반환:**
```
BLOCKED: fix_loop {N}건 미실행 + compare {M}건 미실행. validate-and-fix 재위임 필요.
```

### 3. workspace 조립

**generate-query-matrix.py와 generate-report.py가 workspace/ 경로를 사용하므로 심링크 조립 필수:**

```bash
bash tools/assemble-workspace.sh
```

### 4. 쿼리 매트릭스 생성

```bash
python3 tools/generate-query-matrix.py \
  --output pipeline/step-4-report/output/query-matrix.csv \
  --results-dir workspace/results \
  --json
```

14-state 분포 확인:
```bash
python3 -c "
import json
d=json.load(open('pipeline/step-4-report/output/query-matrix.json'))
print(f'Total: {d[\"total\"]}')
for k,v in sorted(d['summary'].items()):
    if v: print(f'  {k}: {v}')
"
```

### 5. HTML 리포트 생성

```bash
python3 tools/generate-report.py \
  --output pipeline/step-4-report/output/migration-report.html
```

### 6. 산출물 검증 (3개 모두 존재해야 완료)

```bash
for f in pipeline/step-4-report/output/query-matrix.csv \
         pipeline/step-4-report/output/query-matrix.json \
         pipeline/step-4-report/output/migration-report.html; do
  [ -f "$f" ] && [ -s "$f" ] && echo "OK: $f" || echo "MISSING: $f"
done
```

**query-matrix.json 필드 검증:**
```bash
python3 -c "
import json
d=json.load(open('pipeline/step-4-report/output/query-matrix.json'))
q=d['queries'][0] if d.get('queries') else {}
required=['query_id','original_file','sql_before','sql_after','final_state','test_cases','attempts','conversion_history']
missing=[f for f in required if f not in q]
print(f'MISSING: {missing}') if missing else print(f'OK: {len(d[\"queries\"])} queries, 필수 필드 전부 존재')
"
```

### 7. handoff.json 생성 (필수)

```bash
python3 tools/generate-handoff.py --step 4 \
  --report-dir pipeline/step-4-report/output
```

### 8. 요약 통계

14-state 기준:
- **PASS** (COMPLETE + HEALED + NO_CHANGE): 변환 성공
- **FAIL 코드** (SYNTAX + COMPARE_DIFF + ESCALATED + TC_TYPE + TC_OPERATOR): 개발자 조치
- **FAIL DBA** (SCHEMA + COLUMN + FUNCTION): DBA 조치
- **미테스트** (NO_RENDER + NO_DB + PENDING): 추가 작업 필요

## 반환

```
=== Step 4 완료 ===
파이프라인: Step 0 ✓ | Step 1 ✓ | Step 2 ✓ | Step 3 ✓
쿼리: {total}건 (PASS:{p}, FAIL코드:{fc}, FAIL DBA:{fd}, 미테스트:{nt})
리포트: pipeline/step-4-report/output/migration-report.html
매트릭스: pipeline/step-4-report/output/query-matrix.csv + .json
```
