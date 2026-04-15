#!/bin/bash
# validate-pipeline: 검증 결과 즉시 확인
# --full 실행 후 결과가 비어있으면 에러

set -e

VALIDATION_DIR="${1:-pipeline/step-3-validate-fix/output/validation}"

echo "=== 검증 결과 확인 ==="

python3 -c "
import json, sys
vp = '${VALIDATION_DIR}/validated.json'
try:
    d = json.load(open(vp))
except FileNotFoundError:
    print(f'CRITICAL: {vp} not found! validate-queries.py 실행 실패.')
    sys.exit(1)
except json.JSONDecodeError:
    print(f'CRITICAL: {vp} JSON 파싱 실패!')
    sys.exit(1)

total = d.get('total', 0)
passes = len(d.get('passes', []))
fails = len(d.get('failures', []))
tested = passes + fails
pct = tested * 100 // max(total, 1)
print(f'Total: {total}, Tested: {tested} ({pct}%), Pass: {passes}, Fail: {fails}')

if tested == 0:
    print('CRITICAL: 검증 결과 0건! psql 실행 실패. .env 확인 + search_path 확인.')
    sys.exit(1)
if pct < 50:
    print(f'WARNING: 미테스트 {total-tested}건 ({100-pct}%). 출력 캡처 누락. 재실행 필요.')
    sys.exit(1)
print('OK')
"

echo "=== 확인 완료 ==="
