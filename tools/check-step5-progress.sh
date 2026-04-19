#!/usr/bin/env bash
# Step 5 (Deep Agent Retranslate) 진행 상태 체크.
# Claude Code가 중간에 호출하여 진행 상황을 파악할 수 있다.
set -euo pipefail
cd "$(dirname "$0")/.."

OUTPUT_DIR="${1:-pipeline/step-5-deep-retranslate/output}"

if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Step 5 미시작 (output 디렉토리 없음)"
    exit 0
fi

# 전체 쿼리 수 (디렉토리 수)
total=$(find "$OUTPUT_DIR" -maxdepth 1 -type d ! -name output ! -name '_*' | wc -l)

# 상태별 집계 (query.json의 state 필드)
if [ "$total" -gt 0 ]; then
    echo "== Step 5 Progress ======================================="
    echo " Total queries: $total"
    echo ""

    # 상태별 카운트
    python3 -c "
import json, os, sys
from pathlib import Path
from collections import Counter

output_dir = Path('$OUTPUT_DIR')
states = Counter()
done = 0
for qdir in sorted(output_dir.iterdir()):
    if not qdir.is_dir() or qdir.name.startswith('_'):
        continue
    meta_path = qdir / 'query.json'
    if not meta_path.exists():
        states['no_meta'] += 1
        continue
    try:
        meta = json.loads(meta_path.read_text())
        st = meta.get('state', 'unknown')
        states[st] += 1
        if st in ('done', 'done_no_data', 'data_match', 'translated',
                   'explain_valid', 'schema_mismatch', 'needs_app_config'):
            done += 1
    except Exception:
        states['parse_error'] += 1

total = sum(states.values())
pct = (done / total * 100) if total else 0
print(f' Completed: {done}/{total} ({pct:.1f}%)')
print()
for st, cnt in states.most_common():
    bar = '#' * min(cnt * 40 // max(total, 1), 40)
    print(f'  {st:25s} {cnt:5d}  {bar}')
print()

# 최근 수정된 쿼리 (활발히 처리 중인 것)
import time
recent = []
for qdir in output_dir.iterdir():
    if not qdir.is_dir() or qdir.name.startswith('_'):
        continue
    mtime = max((f.stat().st_mtime for f in qdir.rglob('*') if f.is_file()), default=0)
    if time.time() - mtime < 300:  # 5분 이내
        recent.append((qdir.name, mtime))
if recent:
    recent.sort(key=lambda x: -x[1])
    print(f' Active (last 5 min): {len(recent)} queries')
    for name, mt in recent[:5]:
        ago = int(time.time() - mt)
        print(f'   {name} ({ago}s ago)')
else:
    print(' Active: none (idle or completed)')
" 2>/dev/null || echo " (python3 파싱 실패 — 디렉토리만 확인)"

    echo "========================================================="
else
    echo "Step 5: 0 queries (hydration 전 또는 타겟 없음)"
fi

# handoff 있으면 최종 결과도 표시
HANDOFF="pipeline/step-5-deep-retranslate/handoff.json"
if [ -f "$HANDOFF" ]; then
    echo ""
    echo "-- Handoff (완료) --"
    python3 -c "
import json
h = json.loads(open('$HANDOFF').read())
s = h.get('summary', {})
print(f'  Status: {h.get(\"status\")}')
print(f'  Total: {s.get(\"queries_total\", \"?\")}, Attempted: {s.get(\"queries_attempted\", \"?\")}, Succeeded: {s.get(\"queries_succeeded\", \"?\")}')
nac = s.get('needs_app_config_count', 0)
if nac: print(f'  Needs App Config: {nac}')
trans = s.get('state_transitions', {})
if trans:
    top = sorted(trans.items(), key=lambda x: -x[1])[:5]
    for k, v in top: print(f'    {k}: {v}')
" 2>/dev/null
fi
