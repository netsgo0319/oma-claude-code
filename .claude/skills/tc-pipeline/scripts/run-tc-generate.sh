#!/bin/bash
# tc-pipeline: TC 생성 실행
set -e
echo "=== TC Generate ==="

RESULTS_DIR="${1:-pipeline/step-1-convert/output/results}"
SAMPLES_DIR="${2:-pipeline/step-0-preflight/output/samples}"
OUTPUT_DIR="${3:-pipeline/step-2-tc-generate/output/per-file}"

python3 tools/generate-test-cases.py \
  --results-dir "$RESULTS_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --output-dir "$OUTPUT_DIR"

echo "=== TC Generate 완료 ==="
