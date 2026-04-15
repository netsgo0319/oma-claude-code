#!/bin/bash
# orchestrate-pipeline: Step N handoff 확인
# Usage: bash check-step.sh <step_number>
STEP=$1

HANDOFF=$(ls pipeline/step-${STEP}-*/handoff.json 2>/dev/null | head -1)
if [ -z "$HANDOFF" ]; then
  echo "NOT_STARTED"
  exit 1
fi

STATUS=$(python3 -c "import json; print(json.load(open('$HANDOFF'))['status'])" 2>/dev/null)
echo "$STATUS"
