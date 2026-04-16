#!/usr/bin/env python3
"""
Hook 스크립트: validate-and-fix 에이전트가 수정 루프를 실행했는지 검증.
SubagentStop hook에서 호출. 미실행 시 경고 출력.

Usage (hook에서 자동 호출):
    python3 tools/check-fix-loop-ran.py
"""
import glob
import json
import sys
from pathlib import Path


def check():
    """Step 3 query-tracking에서 non-DBA FAIL에 attempts가 있는지 확인."""
    DBA_STATES = {'FAIL_SCHEMA_MISSING', 'FAIL_COLUMN_MISSING', 'FAIL_FUNCTION_MISSING'}

    tracking_files = glob.glob('pipeline/step-1-convert/output/results/*/v1/query-tracking.json')
    if not tracking_files:
        return  # Step 1 미완료

    total_fails = 0
    fails_no_attempt = 0
    fails_with_attempt = 0

    for tf in tracking_files:
        try:
            data = json.loads(Path(tf).read_text(encoding='utf-8'))
        except Exception:
            continue
        for q in data.get('queries', []):
            fs = q.get('final_state', '')
            if not fs.startswith('FAIL_'):
                continue
            if fs in DBA_STATES:
                continue
            total_fails += 1
            attempts = q.get('attempts', [])
            if attempts:
                fails_with_attempt += 1
            else:
                fails_no_attempt += 1

    if total_fails == 0:
        return

    if fails_no_attempt > 0:
        pct = round(fails_with_attempt / total_fails * 100) if total_fails else 0
        print(f"⚠️  FIX-LOOP CHECK: {fails_no_attempt}/{total_fails} non-DBA FAIL 쿼리에 수정 시도 없음 ({pct}% 수정됨)")
        if fails_with_attempt == 0:
            print(f"❌  수정 루프 0회 — handoff가 blocked 됩니다. Edit+재검증을 수행하세요.")
    else:
        print(f"✅  FIX-LOOP CHECK: {fails_with_attempt}/{total_fails} non-DBA FAIL 모두 수정 시도됨")


if __name__ == '__main__':
    check()
