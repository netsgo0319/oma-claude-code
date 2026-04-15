#!/bin/bash
# orchestrate-pipeline: Step 3→4 gate 확인
set -e

HANDOFF="pipeline/step-3-validate-fix/handoff.json"
if [ ! -f "$HANDOFF" ]; then
  echo "MISSING: $HANDOFF — Step 3 미완료"
  exit 1
fi

python3 -c "
import json, sys
h = json.load(open('$HANDOFF'))
gc = h.get('gate_checks', {})
blocked = False
for name, check in gc.items():
    status = check.get('status', 'unknown')
    print(f'{name}: {status}')
    if status == 'fail':
        print(f'  BLOCKED: {check.get(\"detail\", \"\")}')
        blocked = True
# NOT_TESTED 비율도 확인
sc = h.get('summary', {}).get('state_counts', {})
total = h.get('summary', {}).get('queries_total', 0)
nt = sum(v for k, v in sc.items() if k.startswith('NOT_TESTED'))
if total > 0 and nt > total * 0.5:
    print(f'test_coverage: fail ({nt}/{total} = {nt*100//total}% NOT_TESTED)')
    blocked = True
if blocked:
    print('RESULT: BLOCKED')
    sys.exit(1)
else:
    print('RESULT: PROCEED')
"
