#!/bin/bash
# convert-pipeline: Step 1 handoff.json 생성
set -e
python3 tools/generate-handoff.py --step 1 \
  --results-dir pipeline/step-1-convert/output/results
