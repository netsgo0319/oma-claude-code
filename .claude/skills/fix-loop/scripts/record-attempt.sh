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

# 성공한 수정은 shared-fixes에 기록 (다른 배치 참조용)
if '$RESULT' == 'pass' and '$FIX_APPLIED':
    try:
        from shared_fix_registry import record_fix
        # 에러 카테고리를 패턴 ID로 사용
        record_fix('$ERROR_CAT', '', '',
                   source_query='$QUERY_ID', agent='fix-loop')
        print(f'  → Shared fix recorded: $ERROR_CAT')
    except Exception as e:
        print(f'  → Shared fix record skipped: {e}')
"
