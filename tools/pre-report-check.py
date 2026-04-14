#!/usr/bin/env python3
"""
Phase 6.5: Pre-Report Checklist
Phase 7 리포트 생성 전 파이프라인 완료 상태를 점검한다.
FAIL 항목이 있으면 리포트 생성을 차단하고 미완료 항목을 보고한다.

Usage:
    python3 tools/pre-report-check.py
    python3 tools/pre-report-check.py --fix  # 자동 수정 가능한 것은 수정

Exit code:
    0 = 전부 PASS → Phase 7 진행 가능
    1 = FAIL 있음 → 해결 후 재실행
"""

import json
import os
import sys
import glob
import argparse
from pathlib import Path
from datetime import datetime


def check(name, passed, detail=''):
    status = 'PASS' if passed else 'FAIL'
    icon = '✓' if passed else '✗'
    print(f"  [{icon}] {name}" + (f" — {detail}" if detail else ''))
    return passed


def main():
    parser = argparse.ArgumentParser(description='Phase 6.5: Pre-Report Checklist')
    parser.add_argument('--workspace', default='.', help='Project root')
    parser.add_argument('--fix', action='store_true', help='Auto-fix what is possible')
    args = parser.parse_args()

    ws = Path(args.workspace) / 'workspace'
    results = ws / 'results'
    val_dir = results / '_validation'
    healing_dir = results / '_healing'
    samples_dir = results / '_samples'

    passed_all = True
    total = 0
    failed = 0
    warnings = 0

    def run(name, ok, detail='', warn=False):
        nonlocal passed_all, total, failed, warnings
        total += 1
        if not check(name, ok, detail):
            if warn:
                warnings += 1
            else:
                failed += 1
                passed_all = False

    print("=" * 60)
    print("  Phase 6.5: Pre-Report Checklist")
    print("=" * 60)

    # ─── 1. 입력 완전성 ───
    print("\n[입력 완전성]")
    xml_files = list((ws / 'input').glob('**/*.xml')) if (ws / 'input').exists() else []
    run("XML 파일 존재", len(xml_files) > 0, f"{len(xml_files)}개")

    output_files = list((ws / 'output').glob('**/*.xml')) if (ws / 'output').exists() else []
    run("Output XML 존재", len(output_files) > 0, f"{len(output_files)}개")
    run("Input/Output 수 일치", len(xml_files) == len(output_files),
        f"input={len(xml_files)}, output={len(output_files)}" if len(xml_files) != len(output_files) else '')

    # XML valid check
    import xml.etree.ElementTree as ET
    broken = []
    for f in output_files:
        try:
            ET.parse(f)
        except ET.ParseError:
            broken.append(f.name)
    run("Output XML 전부 valid", len(broken) == 0,
        f"깨진 파일: {', '.join(broken[:3])}" if broken else '')

    # ─── 2. 샘플 데이터 ───
    print("\n[샘플 데이터]")
    sample_files = list(samples_dir.glob('*.json')) if samples_dir.exists() else []
    run("샘플 데이터 수집됨", len(sample_files) > 0, f"{len(sample_files)}개 테이블")

    zero_samples = 0
    for sf in sample_files:
        try:
            d = json.load(open(sf))
            if isinstance(d, dict) and d.get('row_count', 0) == 0:
                zero_samples += 1
        except Exception:
            pass
    run("샘플 0건 테이블 과다 아님", zero_samples < len(sample_files) * 0.5,
        f"{zero_samples}개 테이블 0건" if zero_samples else '', warn=True)

    # ─── 3. 검증 3단계 ───
    print("\n[검증 3단계 (EXPLAIN → Execute → Compare)]")
    explain_exists = (val_dir / 'explain_results.txt').exists()
    execute_exists = (val_dir / 'execute_results.txt').exists()
    oracle_exists = (val_dir / 'oracle_results.txt').exists()
    validated_exists = (val_dir / 'validated.json').exists()
    compare_exists = (val_dir / 'compare_validated.json').exists()

    run("EXPLAIN 실행됨", explain_exists, 'explain_results.txt')
    run("PG Execute 실행됨", execute_exists,
        'execute_results.txt 없음 — EXPLAIN만 하고 끝냈을 가능성' if not execute_exists else '')
    run("Oracle Compare 실행됨", oracle_exists,
        'oracle_results.txt 없음 — Oracle 비교 안 함' if not oracle_exists else '')
    run("validated.json 생성됨", validated_exists)
    run("compare_validated.json 생성됨", compare_exists,
        '--parse-results를 Execute/Oracle 후 실행했는지 확인' if not compare_exists else '')

    # Check validated.json has passes list
    if validated_exists:
        vdata = json.load(open(val_dir / 'validated.json'))
        has_passes = 'passes' in vdata and len(vdata.get('passes', [])) > 0
        run("validated.json에 pass 목록 있음", has_passes,
            f"pass={vdata.get('pass',0)}, fail={vdata.get('fail',0)}")

    # ─── 4. 힐링 ───
    print("\n[힐링 (Phase 4)]")
    tickets_exists = (healing_dir / 'tickets.json').exists()
    run("generate-healing-tickets.py 실행됨", tickets_exists,
        'tickets.json 없음 — 수기 summary만 있을 수 있음' if not tickets_exists else '')

    if tickets_exists:
        hdata = json.load(open(healing_dir / 'tickets.json'))
        tickets = hdata.get('tickets', [])
        dba_cats = {'relation_missing', 'column_missing'}
        open_actionable = [t for t in tickets if t.get('status') == 'open' and t.get('category') not in dba_cats]
        run("힐링 가능 open 티켓 = 0", len(open_actionable) == 0,
            f"{len(open_actionable)}건 힐링 미실행 (최소 3회 필요)" if open_actionable else '')

        # Check retry counts
        low_retry = [t for t in tickets if t.get('category') not in dba_cats
                     and t.get('status') not in ('resolved', 'skipped')
                     and t.get('retry_count', 0) < 3]
        run("힐링 가능 티켓 최소 3회 시도", len(low_retry) == 0,
            f"{len(low_retry)}건이 3회 미만 시도" if low_retry else '')
    else:
        # Check if summary was hand-written
        summary_exists = (healing_dir / 'summary.json').exists()
        if summary_exists and not tickets_exists:
            run("수기 summary 아닌지", False, 'summary.json은 있지만 tickets.json 없음 — 도구 미실행')

    # ─── 5. 트래킹 정합성 ───
    print("\n[트래킹 정합성]")
    tracking_files = list(results.glob('*/v*/query-tracking.json'))
    total_q = 0
    null_explain = 0
    for tf in tracking_files:
        try:
            d = json.load(open(tf))
            qs = d.get('queries', [])
            if isinstance(qs, dict):
                qs = list(qs.values())
            total_q += len(qs)
            for q in qs:
                if q.get('explain') is None:
                    null_explain += 1
        except Exception:
            pass
    run("query-tracking.json에 explain 기록됨",
        null_explain < total_q * 0.5,
        f"{null_explain}/{total_q} 쿼리가 explain=null" if null_explain else f'{total_q} 쿼리 추적 중')

    # Compare results in tracking
    if compare_exists:
        cdata = json.load(open(val_dir / 'compare_validated.json'))
        both_zero = sum(1 for r in cdata.get('results', [])
                        if r.get('match') and r.get('oracle_rows') == 0 and r.get('pg_rows') == 0)
        total_cmp = len(cdata.get('results', []))
        run("양쪽 0건 비교 과다 아님", both_zero < total_cmp * 0.5 if total_cmp else True,
            f"{both_zero}/{total_cmp}건이 양쪽 0 — Oracle 접속 정보 확인 필요" if both_zero > total_cmp * 0.3 else '',
            warn=True)

    # ─── 6. query-matrix ───
    print("\n[리포트 데이터]")
    qm_path = ws / 'reports' / 'query-matrix.json'
    run("query-matrix.json 생성됨", qm_path.exists() or total_q > 0,
        'generate-query-matrix.py 실행 필요' if not qm_path.exists() else '')

    # Auto-fix: generate query-matrix if missing
    if args.fix and not qm_path.exists() and total_q > 0:
        print("    → 자동 수정: generate-query-matrix.py 실행")
        os.system('python3 tools/generate-query-matrix.py --json')

    # ─── Summary ───
    print("\n" + "=" * 60)
    if passed_all:
        print(f"  ✓ 전체 PASS ({total}건 점검, {warnings}건 경고)")
        print("  → Phase 7 리포트 생성 가능")
    else:
        print(f"  ✗ FAIL {failed}건 / 경고 {warnings}건 (총 {total}건 점검)")
        print("  → 위 FAIL 항목 해결 후 재실행하세요")
    print("=" * 60)

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='pre-report-check', phase='phase_6.5',
                     detail=f"Checklist: {total} checks, {failed} FAIL, {warnings} WARN")
    except Exception:
        pass

    return 0 if passed_all else 1


if __name__ == '__main__':
    sys.exit(main())
