#!/bin/bash
# tc-pipeline: Step 2 handoff.json 생성
set -e
python3 tools/generate-handoff.py --step 2 \
  --results-dir pipeline/step-1-convert/output/results \
  --tc-dir pipeline/step-2-tc-generate/output
