#!/bin/bash
# report-pipeline: workspace 조립 → query-matrix → HTML 리포트 → handoff
set -e

echo "=== Step 4: Report Pipeline ==="

# 1. Workspace 조립
echo "--- 1. Assemble workspace ---"
bash tools/assemble-workspace.sh

# 2. Query Matrix 생성 (★ 먼저! 보고서의 유일한 데이터 소스)
echo "--- 2. Generate query-matrix ---"
python3 tools/generate-query-matrix.py \
  --output pipeline/step-4-report/output/query-matrix.csv \
  --results-dir workspace/results \
  --input-dir workspace/input \
  --output-dir workspace/output \
  --json

# 3. HTML 리포트 생성 (query-matrix.json 기반)
echo "--- 3. Generate HTML report ---"
python3 tools/generate-report.py \
  --output pipeline/step-4-report/output/migration-report.html

# 4. 산출물 검증
echo "--- 4. Verify outputs ---"
for f in pipeline/step-4-report/output/query-matrix.csv \
         pipeline/step-4-report/output/query-matrix.json \
         pipeline/step-4-report/output/migration-report.html; do
  [ -f "$f" ] && [ -s "$f" ] && echo "  OK: $f" || echo "  MISSING: $f"
done

# 5. Handoff 생성
echo "--- 5. Generate handoff ---"
python3 tools/generate-handoff.py --step 4 \
  --report-dir pipeline/step-4-report/output

echo "=== Report Pipeline 완료 ==="
