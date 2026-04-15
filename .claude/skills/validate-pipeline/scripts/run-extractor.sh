#!/bin/bash
# validate-pipeline: MyBatis 렌더링 (동적 SQL → 실행 가능 SQL)
# run-extractor.sh 래퍼 — 결과를 pipeline 경로로 복사까지

set -e

echo "=== MyBatis Extractor 실행 ==="

# extractor 실행
bash tools/run-extractor.sh --skip-build --validate

# 결과를 pipeline 경로로 복사
mkdir -p pipeline/step-3-validate-fix/output/extracted_pg
cp workspace/results/_extracted_pg/*.json pipeline/step-3-validate-fix/output/extracted_pg/ 2>/dev/null || true

echo "  extracted: $(ls pipeline/step-3-validate-fix/output/extracted_pg/*.json 2>/dev/null | wc -l) files"
echo "=== Extractor 완료 ==="
