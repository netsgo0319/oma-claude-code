#!/bin/bash
# validate-pipeline: Step 3 handoff.json 생성
# gate_checks (fix_loop + compare_coverage + test_coverage + render_coverage) 포함

set -e

echo "=== Handoff 생성 ==="

python3 tools/generate-handoff.py --step 3 \
  --results-dir pipeline/step-1-convert/output/results \
  --validation-dir pipeline/step-3-validate-fix/output/validation \
  --batches-dir pipeline/step-3-validate-fix/output/batches

echo "=== Handoff 완료 ==="
