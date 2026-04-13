#!/usr/bin/env python3
"""
Query Validation Matrix Generator
전체 쿼리에 대해 변환/EXPLAIN/비교/힐링 상태를 한눈에 볼 수 있는 CSV+JSON 출력.

Usage:
    python3 tools/generate-query-matrix.py
    python3 tools/generate-query-matrix.py --output workspace/reports/query-matrix.csv --json

Output columns:
    file, query_id, type, complexity,
    conversion: method, status,
    explain: status, source (static/mybatis), error_category, error_detail,
    compare: status, tc_total, tc_pass, tc_fail, fail_reason,
    healing: ticket_id, ticket_status, skip_reason, retry_count,
    mybatis_extracted,
    overall: status, status_detail
"""

import json
import glob
import csv
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter


def classify_explain_error(error):
    """EXPLAIN 에러를 사람이 읽을 수 있는 카테고리로 분류."""
    err = str(error).lower()
    if 'syntax error' in err:
        return 'SYNTAX_ERROR'
    if 'relation' in err and 'does not exist' in err:
        return 'MISSING_TABLE'
    if 'column' in err and 'does not exist' in err:
        return 'MISSING_COLUMN'
    if 'function' in err and 'does not exist' in err:
        return 'MISSING_FUNCTION'
    if 'operator does not exist' in err:
        return 'TYPE_OPERATOR'
    if 'value too long' in err:
        return 'VALUE_TOO_LONG'
    if 'invalid input syntax' in err:
        return 'TYPE_MISMATCH'
    if 'ambiguous' in err:
        return 'AMBIGUOUS'
    return 'OTHER'


OVERALL_LABELS = {
    'COMPLETE': '완료 — 변환+EXPLAIN+비교 모두 통과',
    'EXPLAIN_PASS': '부분통과 — EXPLAIN 통과, 비교 미실행',
    'CONVERTED': '변환완료 — EXPLAIN 미실행',
    'EXPLAIN_FAIL': '실패 — EXPLAIN 문법 에러',
    'COMPARE_FAIL': '실패 — Oracle/PG 결과 불일치',
    'PENDING': '대기 — 변환 미완료',
    'HEALED': '수정완료 — 힐링으로 해결',
    'ESCALATED': '에스컬레이션 — 수동 검토 필요',
}


def main():
    parser = argparse.ArgumentParser(description='Query Validation Matrix')
    parser.add_argument('--output', default='workspace/reports/query-matrix.csv')
    parser.add_argument('--results-dir', default='workspace/results')
    parser.add_argument('--json', action='store_true', help='Also output JSON')
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    rows = []

    # Load validation results (Phase 3)
    val_results = {}
    val_path = results_dir / '_validation' / 'validated.json'
    if val_path.exists():
        vdata = json.load(open(val_path))
        for p in vdata.get('passes', []):
            tid = p if isinstance(p, str) else p.get('test', '')
            val_results[tid] = {'status': 'pass', 'error': ''}
        for f in vdata.get('failures', []):
            tid = f.get('test', f.get('test_id', ''))
            val_results[tid] = {'status': 'fail', 'error': f.get('error', '')[:300]}

    # Load Phase 3.5 validation results
    for p35dir in ['_validation_phase35', '_validation_phase7']:
        p35_path = results_dir / p35dir / 'validated.json'
        if p35_path.exists():
            p35data = json.load(open(p35_path))
            for p in p35data.get('passes', []):
                tid = p if isinstance(p, str) else p.get('test', '')
                if tid not in val_results or val_results[tid]['status'] == 'fail':
                    val_results[tid] = {'status': 'pass', 'error': '', 'source': 'mybatis'}
            for f in p35data.get('failures', []):
                tid = f.get('test', f.get('test_id', ''))
                if tid not in val_results:
                    val_results[tid] = {'status': 'fail', 'error': f.get('error', '')[:300], 'source': 'mybatis'}

    # Load compare results
    compare_results = {}
    for base_dir in ['_validation', '_validation_phase35', '_validation_phase7']:
        for cfile in ['compare_validated.json', 'compare_results.json']:
            cp = results_dir / base_dir / cfile
            if cp.exists():
                cdata = json.load(open(cp))
                for r in cdata.get('results', []):
                    qid = r.get('query_id', '')
                    compare_results.setdefault(qid, []).append(r)

    # Load healing tickets
    healing_map = {}  # {query_id: ticket}
    healing_path = results_dir / '_healing' / 'tickets.json'
    if healing_path.exists():
        hdata = json.load(open(healing_path))
        for t in hdata.get('tickets', []):
            qid = t.get('query_id', '')
            if qid:
                healing_map[qid] = t

    # Load extracted flags
    extracted_queries = set()
    for ef in glob.glob(str(results_dir / '_extracted' / '*-extracted.json')):
        for q in json.load(open(ef)).get('queries', []):
            extracted_queries.add(q.get('query_id', ''))
    pg_extracted = set()
    for ef in glob.glob(str(results_dir / '_extracted_pg' / '*-extracted.json')):
        for q in json.load(open(ef)).get('queries', []):
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

            # --- Conversion ---
            conv_status = 'converted' if q.get('pg_sql') else 'pending'
            if method == 'no_change':
                conv_status = 'no_change'

            # --- EXPLAIN ---
            explain = q.get('explain', {}) or {}
            explain_status = explain.get('status', '')
            explain_error = explain.get('error', '') or ''
            explain_source = explain.get('validation_source', 'static')

            # Also check Phase 3.5
            explain_p35 = q.get('explain_phase35', {}) or {}
            if explain_p35.get('status') == 'pass' and explain_status != 'pass':
                explain_status = 'pass'
                explain_error = ''
                explain_source = 'mybatis'

            # Fallback: check from validation results
            if not explain_status:
                for tid, vr in val_results.items():
                    if qid in tid:
                        explain_status = vr['status']
                        explain_error = vr.get('error', '')
                        explain_source = vr.get('source', 'static')
                        break
                if not explain_status:
                    explain_status = 'not_tested'

            explain_category = classify_explain_error(explain_error) if explain_status == 'fail' else ''

            # --- Compare ---
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
                tc_total = tc_pass = tc_fail = 0
                compare_status = 'not_tested'
                compare_fail_reason = ''

            # --- Healing ---
            ticket = healing_map.get(qid, {})
            ticket_id = ticket.get('ticket_id', '')
            ticket_status = ticket.get('status', '')
            ticket_skip = ticket.get('skip_reason', '')
            ticket_retry = ticket.get('retry_count', 0)

            # --- MyBatis ---
            mybatis = 'both' if (qid in extracted_queries and qid in pg_extracted) else \
                      'oracle_only' if qid in extracted_queries else \
                      'pg_only' if qid in pg_extracted else 'no'

            # --- Overall (사람이 읽을 수 있는 상태) ---
            if ticket_status == 'resolved':
                overall = 'HEALED'
                overall_detail = f'힐링 해결 (retry {ticket_retry}회)' if ticket_skip != 'resolved_by_mybatis_engine' else 'MyBatis 엔진으로 자동 해결'
            elif ticket_status == 'escalated':
                overall = 'ESCALATED'
                overall_detail = f'수동 검토 필요 ({ticket_retry}회 시도 후 실패)'
            elif conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'pass':
                overall = 'COMPLETE'
                overall_detail = OVERALL_LABELS['COMPLETE']
            elif conv_status in ('converted', 'no_change') and explain_status == 'pass':
                overall = 'EXPLAIN_PASS'
                overall_detail = OVERALL_LABELS['EXPLAIN_PASS']
            elif conv_status in ('converted', 'no_change') and explain_status == 'not_tested':
                overall = 'CONVERTED'
                overall_detail = OVERALL_LABELS['CONVERTED']
            elif explain_status == 'fail':
                overall = 'EXPLAIN_FAIL'
                overall_detail = f'{explain_category}: {explain_error}'
            elif compare_status == 'fail':
                overall = 'COMPARE_FAIL'
                overall_detail = f'결과 불일치: {compare_fail_reason}'
            else:
                overall = 'PENDING'
                overall_detail = OVERALL_LABELS['PENDING']

            rows.append({
                'file': fname,
                'query_id': qid,
                'type': qtype,
                'complexity': complexity,
                'conversion_method': method,
                'conversion_status': conv_status,
                'explain_status': explain_status,
                'explain_source': explain_source,
                'explain_error_category': explain_category,
                'explain_error_detail': explain_error,  # 전문 보존 (CSV에서는 자동 escape)
                'compare_status': compare_status,
                'compare_tc_total': tc_total,
                'compare_tc_pass': tc_pass,
                'compare_tc_fail': tc_fail,
                'compare_fail_reason': compare_fail_reason,
                'healing_ticket_id': ticket_id,
                'healing_status': ticket_status,
                'healing_skip_reason': ticket_skip,
                'healing_retry_count': ticket_retry,
                'mybatis_extracted': mybatis,
                'overall_status': overall,
                'overall_detail': overall_detail,
            })

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    fieldnames = [
        'file', 'query_id', 'type', 'complexity',
        'conversion_method', 'conversion_status',
        'explain_status', 'explain_source', 'explain_error_category', 'explain_error_detail',
        'compare_status', 'compare_tc_total', 'compare_tc_pass', 'compare_tc_fail', 'compare_fail_reason',
        'healing_ticket_id', 'healing_status', 'healing_skip_reason', 'healing_retry_count',
        'mybatis_extracted', 'overall_status', 'overall_detail',
    ]

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    overall_counts = Counter(r['overall_status'] for r in rows)
    explain_cats = Counter(r['explain_error_category'] for r in rows if r['explain_error_category'])
    healing_counts = Counter(r['healing_status'] for r in rows if r['healing_status'])

    print(f"Query Matrix: {len(rows)} queries")
    print(f"\n  Overall:")
    for label in ['COMPLETE', 'HEALED', 'EXPLAIN_PASS', 'CONVERTED', 'EXPLAIN_FAIL', 'COMPARE_FAIL', 'ESCALATED', 'PENDING']:
        cnt = overall_counts.get(label, 0)
        if cnt:
            print(f"    {label}: {cnt} ({cnt*100/len(rows):.1f}%) — {OVERALL_LABELS.get(label, '')}")

    if explain_cats:
        print(f"\n  EXPLAIN 에러 카테고리:")
        for cat, cnt in explain_cats.most_common():
            print(f"    {cat}: {cnt}")

    if healing_counts:
        print(f"\n  힐링 티켓:")
        for st, cnt in healing_counts.most_common():
            print(f"    {st}: {cnt}")

    print(f"\nSaved: {args.output}")

    # JSON output
    if args.json:
        json_path = args.output.replace('.csv', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total': len(rows),
                'summary': dict(overall_counts),
                'explain_error_categories': dict(explain_cats),
                'healing_summary': dict(healing_counts),
                'queries': rows,
            }, f, indent=2, ensure_ascii=False)
        print(f"JSON: {json_path}")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-query-matrix', phase='phase_6',
                     detail=f"Matrix: {len(rows)} queries, COMPLETE:{overall_counts.get('COMPLETE',0)}, "
                            f"HEALED:{overall_counts.get('HEALED',0)}, "
                            f"FAIL:{overall_counts.get('EXPLAIN_FAIL',0)+overall_counts.get('COMPARE_FAIL',0)}")
    except Exception:
        pass


if __name__ == '__main__':
    main()
