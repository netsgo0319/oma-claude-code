#!/bin/bash
# fix-loop: 수정 시도 기록
# Usage: bash record-attempt.sh <tracking_dir> <query_id> <error_category> <error_detail> <fix_applied> <result>

TRACKING_DIR="$1"
QUERY_ID="$2"
ERROR_CAT="$3"
ERROR_DETAIL="$4"
FIX_APPLIED="$5"
RESULT="$6"

python3 -c "
import sys; sys.path.insert(0, 'tools')
from tracking_utils import TrackingManager
tm = TrackingManager('$TRACKING_DIR')
n = tm.add_attempt('$QUERY_ID',
    error_category='$ERROR_CAT',
    error_detail='$ERROR_DETAIL',
    fix_applied='$FIX_APPLIED',
    result='$RESULT')
print(f'Attempt #{n} recorded for $QUERY_ID → $RESULT')
"
