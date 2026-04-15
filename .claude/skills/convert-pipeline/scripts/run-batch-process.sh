#!/bin/bash
# convert-pipeline: 전체 파싱+룰변환 (최초 1회)
set -e
echo "=== Batch Process (parse + analyze + convert) ==="

INPUT_DIR=${INPUT_DIR:-pipeline/shared/input}
OUTPUT_DIR=${OUTPUT_DIR:-pipeline/step-1-convert/output/xml}
RESULTS_DIR=${RESULTS_DIR:-pipeline/step-1-convert/output/results}

# 이미 output이 있으면 스킵
if ls "$OUTPUT_DIR"/*.xml >/dev/null 2>&1; then
  echo "  Output XML already exists. Skipping batch-process."
  echo "  To re-run: rm -rf $OUTPUT_DIR/*.xml"
  exit 0
fi

INPUT_DIR="$INPUT_DIR" OUTPUT_DIR="$OUTPUT_DIR" RESULTS_DIR="$RESULTS_DIR" \
  bash tools/batch-process.sh --all --parallel 8

echo "  Output: $(ls $OUTPUT_DIR/*.xml 2>/dev/null | wc -l) files"
echo "=== Batch Process 완료 ==="
