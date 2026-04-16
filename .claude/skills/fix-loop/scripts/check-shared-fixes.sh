#!/bin/bash
# fix-loop: 에러 메시지로 shared-fixes에서 알려진 패턴 조회
# Usage: bash check-shared-fixes.sh "error message"
# 매칭되면 패턴 정보 출력 + exit 0, 없으면 exit 1

ERROR_MSG="$1"

python3 -c "
import sys; sys.path.insert(0, 'tools')
try:
    from shared_fix_registry import load_fixes, match_error_to_fix
    fixes = load_fixes()
    if not fixes:
        print('  No shared fixes available')
        sys.exit(1)
    match = match_error_to_fix('$ERROR_MSG', fixes)
    if match:
        print(f'  ★ Known fix: {match[\"pattern_id\"]}')
        print(f'    regex: {match.get(\"regex\", \"\")[:80]}')
        print(f'    replacement: {match.get(\"replacement\", \"\")[:80]}')
        print(f'    source: {match.get(\"source_query\", \"\")} (by {match.get(\"agent\", \"\")})')
        sys.exit(0)
    else:
        print('  No matching shared fix found')
        sys.exit(1)
except ImportError:
    print('  shared_fix_registry not available')
    sys.exit(1)
"
