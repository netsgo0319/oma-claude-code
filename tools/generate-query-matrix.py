#!/usr/bin/env python3
"""
Query Validation Matrix Generator
전체 쿼리에 대해 3개 항목(변환/EXPLAIN/비교)의 완료 여부를 CSV로 출력.

Usage:
    python3 tools/generate-query-matrix.py
    python3 tools/generate-query-matrix.py --output workspace/reports/query-matrix.csv

Output columns:
    file, query_id, type, complexity, conversion_method, conversion_status,
    explain_status, explain_error,
    compare_status, compare_tc_total, compare_tc_pass, compare_tc_fail, compare_fail_reason,
    mybatis_extracted, overall_status
"""

import json
import glob
import csv
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description='Query Validation Matrix')
    parser.add_argument('--output', default='workspace/reports/query-matrix.csv')
    parser.add_argument('--results-dir', default='workspace/results')
    parser.add_argument('--json', action='store_true', help='Also output JSON')
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    rows = []

    # Load validation results
    val_results = {}  # {test_id: 'pass'/'fail'}
    val_path = results_dir / '_validation' / 'validated.json'
    if val_path.exists():
        vdata = json.load(open(val_path))
        for f in vdata.get('failures', []):
            tid = f.get('test', f.get('test_id', ''))
            val_results[tid] = {'status': 'fail', 'error': f.get('error', '')[:200]}

    # Load compare results
    compare_results = {}  # {query_id: [{case, match, oracle_rows, pg_rows, error}]}
    for cfile in ['compare_validated.json', 'compare_results.json']:
        cp = results_dir / '_validation' / cfile
        if cp.exists():
            cdata = json.load(open(cp))
            for r in cdata.get('results', []):
                qid = r.get('query_id', '')
                compare_results.setdefault(qid, []).append(r)
            break
    # Phase 3.5 compare
    for cfile in ['compare_validated.json', 'compare_results.json']:
        cp = results_dir / '_validation_phase7' / cfile
        if cp.exists():
            cdata = json.load(open(cp))
            for r in cdata.get('results', []):
                qid = r.get('query_id', '')
                compare_results.setdefault(qid, []).append(r)

    # Load extracted flags
    extracted_queries = set()
    for ef in glob.glob(str(results_dir / '_extracted' / '*-extracted.json')):
        edata = json.load(open(ef))
        for q in edata.get('queries', []):
            extracted_queries.add(q.get('query_id', ''))
    pg_extracted = set()
    for ef in glob.glob(str(results_dir / '_extracted_pg' / '*-extracted.json')):
        edata = json.load(open(ef))
        for q in edata.get('queries', []):
            pg_extracted.add(q.get('query_id', ''))

    # Build matrix from query-tracking.json
    for tf in sorted(glob.glob(str(results_dir / '*/v*/query-tracking.json'))):
        try:
            tdata = json.load(open(tf))
        except Exception:
            continue

        fname = tdata.get('file', '')
        queries = tdata.get('queries', [])
        if isinstance(queries, dict):
            queries = list(queries.values())

        for q in queries:
            qid = q.get('query_id', '')
            qtype = q.get('type', '')
            complexity = q.get('complexity', '')
            method = q.get('conversion_method', '')
            status = q.get('status', '')

            # 1. Conversion status
            conv_status = 'converted' if q.get('pg_sql') else 'pending'
            if method == 'no_change':
                conv_status = 'no_change'

            # 2. EXPLAIN status
            explain = q.get('explain', {}) or {}
            explain_status = explain.get('status', '')
            explain_error = explain.get('error', '') or ''
            if not explain_status:
                # Check from validation results
                for tid, vr in val_results.items():
                    if qid in tid:
                        explain_status = vr['status']
                        explain_error = vr.get('error', '')
                        break
                if not explain_status:
                    explain_status = 'not_tested'

            # 3. Compare status
            cmp_results = compare_results.get(qid, [])
            if cmp_results:
                tc_total = len(cmp_results)
                tc_pass = sum(1 for c in cmp_results if c.get('match', False))
                tc_fail = tc_total - tc_pass
                fail_reasons = []
                for c in cmp_results:
                    if not c.get('match', False):
                        reason = c.get('reason', c.get('pg_error', c.get('ora_error', c.get('oracle_error', ''))))
                        if reason:
                            fail_reasons.append(str(reason)[:100])
                compare_status = 'pass' if tc_fail == 0 else 'fail'
                compare_fail_reason = '; '.join(fail_reasons[:3])
            else:
                tc_total = 0
                tc_pass = 0
                tc_fail = 0
                compare_status = 'not_tested'
                compare_fail_reason = ''

            # 4. MyBatis extracted
            mybatis = 'both' if (qid in extracted_queries and qid in pg_extracted) else \
                      'oracle_only' if qid in extracted_queries else \
                      'pg_only' if qid in pg_extracted else 'no'

            # 5. Overall
            if conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'pass':
                overall = 'COMPLETE'
            elif conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'not_tested':
                overall = 'EXPLAIN_ONLY'
            elif conv_status in ('converted', 'no_change') and explain_status == 'not_tested':
                overall = 'CONVERTED_ONLY'
            elif explain_status == 'fail':
                overall = 'EXPLAIN_FAIL'
            elif compare_status == 'fail':
                overall = 'COMPARE_FAIL'
            else:
                overall = 'PENDING'

            rows.append({
                'file': fname,
                'query_id': qid,
                'type': qtype,
                'complexity': complexity,
                'conversion_method': method,
                'conversion_status': conv_status,
                'explain_status': explain_status,
                'explain_error': explain_error[:200],
                'compare_status': compare_status,
                'compare_tc_total': tc_total,
                'compare_tc_pass': tc_pass,
                'compare_tc_fail': tc_fail,
                'compare_fail_reason': compare_fail_reason[:300],
                'mybatis_extracted': mybatis,
                'overall_status': overall,
            })

    # Fallback: if no tracking files, build from parsed.json
    if not rows:
        for pf in sorted(glob.glob(str(results_dir / '*/v*/parsed.json'))):
            pdata = json.load(open(pf))
            fname = pdata.get('source_file', '')
            for q in pdata.get('queries', []):
                rows.append({
                    'file': fname,
                    'query_id': q.get('query_id', ''),
                    'type': q.get('type', ''),
                    'complexity': '',
                    'conversion_method': '',
                    'conversion_status': 'pending',
                    'explain_status': 'not_tested',
                    'explain_error': '',
                    'compare_status': 'not_tested',
                    'compare_tc_total': 0,
                    'compare_tc_pass': 0,
                    'compare_tc_fail': 0,
                    'compare_fail_reason': '',
                    'mybatis_extracted': 'no',
                    'overall_status': 'PENDING',
                })

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    fieldnames = ['file', 'query_id', 'type', 'complexity', 'conversion_method',
                  'conversion_status', 'explain_status', 'explain_error',
                  'compare_status', 'compare_tc_total', 'compare_tc_pass', 'compare_tc_fail',
                  'compare_fail_reason', 'mybatis_extracted', 'overall_status']

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    from collections import Counter
    overall_counts = Counter(r['overall_status'] for r in rows)
    print(f"Query Matrix: {len(rows)} queries")
    print(f"  COMPLETE (변환+EXPLAIN+비교 모두 OK): {overall_counts.get('COMPLETE', 0)}")
    print(f"  EXPLAIN_ONLY (변환+EXPLAIN OK, 비교 미실행): {overall_counts.get('EXPLAIN_ONLY', 0)}")
    print(f"  CONVERTED_ONLY (변환만, EXPLAIN 미실행): {overall_counts.get('CONVERTED_ONLY', 0)}")
    print(f"  EXPLAIN_FAIL: {overall_counts.get('EXPLAIN_FAIL', 0)}")
    print(f"  COMPARE_FAIL: {overall_counts.get('COMPARE_FAIL', 0)}")
    print(f"  PENDING: {overall_counts.get('PENDING', 0)}")
    print(f"\nSaved: {args.output}")

    # JSON output
    if args.json:
        json_path = args.output.replace('.csv', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total': len(rows),
                'summary': dict(overall_counts),
                'queries': rows,
            }, f, indent=2, ensure_ascii=False)
        print(f"JSON: {json_path}")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-query-matrix', phase='phase_6',
                     detail=f"Matrix: {len(rows)} queries, COMPLETE:{overall_counts.get('COMPLETE',0)}, "
                            f"EXPLAIN_ONLY:{overall_counts.get('EXPLAIN_ONLY',0)}, "
                            f"FAIL:{overall_counts.get('EXPLAIN_FAIL',0)+overall_counts.get('COMPARE_FAIL',0)}")
    except Exception:
        pass


if __name__ == '__main__':
    main()
