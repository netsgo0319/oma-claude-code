#!/usr/bin/env python3
"""
Query Validation Matrix Generator
전체 쿼리에 대해 변환/EXPLAIN/비교/재시도 상태를 한눈에 볼 수 있는 CSV+JSON 출력.

Usage:
    python3 tools/generate-query-matrix.py
    python3 tools/generate-query-matrix.py --output workspace/reports/query-matrix.csv --json

Output columns:
    file, query_id, type, complexity,
    conversion: method, status,
    explain: status, source (static/mybatis), error_category, error_detail,
    compare: status, tc_total, tc_pass, tc_fail, fail_reason,
    attempt: count, summary,
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
from collections import Counter, OrderedDict


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
    # 성공
    'PASS_COMPLETE': '변환+비교 통과',
    'PASS_HEALED': '수정 후 비교 통과',
    'PASS_NO_CHANGE': '변환 불필요 + 비교 통과',
    # 실패 — 재시도 후
    'FAIL_ESCALATED': '최대 재시도 후 미해결',
    'FAIL_SYNTAX': 'SQL 문법 에러',
    'FAIL_COMPARE_DIFF': 'Oracle↔PG 행수 불일치',
    # 실패 — DBA 필요
    'FAIL_SCHEMA_MISSING': 'PG 테이블 없음 (DBA)',
    'FAIL_COLUMN_MISSING': 'PG 컬럼 없음 (DBA)',
    'FAIL_FUNCTION_MISSING': 'PG 함수 없음 (DBA)',
    # 실패 — TC/바인드
    'FAIL_TC_TYPE_MISMATCH': '바인드값 타입/길이 불일치',
    'FAIL_TC_OPERATOR': '연산자 타입 불일치',
    # 미테스트
    'NOT_TESTED_NO_RENDER': 'MyBatis 렌더링 실패',
    'NOT_TESTED_NO_DB': 'DB 미접속/비교 미실행',
    'NOT_TESTED_PENDING': '변환 미완료',
}


def main():
    parser = argparse.ArgumentParser(description='Query Validation Matrix')
    parser.add_argument('--output', default='workspace/reports/query-matrix.csv')
    parser.add_argument('--results-dir', default='workspace/results')
    parser.add_argument('--json', action='store_true', help='Also output JSON')
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    rows = []

    # Load validation results — glob all _validation* directories (supports batch splits)
    # test_id format: "filename.queryId.variant" → extract bare queryId
    def _extract_bare_qid(test_id):
        """Extract bare query_id from test_id like 'file.queryId.variant'."""
        parts = test_id.split('.')
        if len(parts) >= 2:
            return parts[-2]  # second-to-last part = queryId
        return test_id

    val_results = {}       # keyed by full test_id
    val_by_qid = {}        # keyed by bare query_id (best result wins)
    for vp in sorted(results_dir.glob('_validation*/**/validated.json')):
        val_dir = vp.parent
        vdata = json.load(open(vp))
        source = 'mybatis' if 'phase35' in val_dir.name else 'static'
        for p in vdata.get('passes', []):
            tid = p if isinstance(p, str) else p.get('test', '')
            entry = {'status': 'pass', 'error': '', 'source': source}
            # pass가 기존 fail을 덮어씀 (더 좋은 결과 우선)
            if tid not in val_results or val_results[tid]['status'] == 'fail':
                val_results[tid] = entry
            bare = _extract_bare_qid(tid)
            if bare not in val_by_qid or val_by_qid[bare]['status'] == 'fail':
                val_by_qid[bare] = entry
        for f in vdata.get('failures', []):
            tid = f.get('test', f.get('test_id', ''))
            entry = {'status': 'fail', 'error': f.get('error', '')[:300], 'source': source}
            if tid not in val_results:
                val_results[tid] = entry
            bare = _extract_bare_qid(tid)
            if bare not in val_by_qid:
                val_by_qid[bare] = entry

    # Load compare results — glob all _validation* directories
    # Also index by bare query_id (compare_results uses query_id or test_id)
    compare_results = {}
    for cp in sorted(results_dir.glob('_validation*/**/compare_validated.json')):
        cdata = json.load(open(cp))
        for r in cdata.get('results', []):
            raw_qid = r.get('query_id', r.get('test_id', ''))
            bare = _extract_bare_qid(raw_qid) if '.' in raw_qid else raw_qid
            compare_results.setdefault(bare, []).append(r)
    for cp in sorted(results_dir.glob('_validation*/**/compare_results.json')):
        cdata = json.load(open(cp))
        for r in cdata.get('results', []):
            raw_qid = r.get('query_id', r.get('test_id', ''))
            bare = _extract_bare_qid(raw_qid) if '.' in raw_qid else raw_qid
            compare_results.setdefault(bare, []).append(r)

    # Load test-cases.json files (keyed by query_id)
    test_cases_by_qid = {}
    for tc_file in glob.glob(str(results_dir / '*/v*/test-cases.json')):
        try:
            tc_data = json.load(open(tc_file))
        except Exception:
            continue
        for qtc in tc_data.get('query_test_cases', []):
            qid = qtc.get('query_id', '')
            if qid:
                cases = []
                for tc in qtc.get('test_cases', []):
                    cases.append({
                        'name': tc.get('case_id', tc.get('description', '')),
                        'params': tc.get('binds', {}),
                        'source': tc.get('source', ''),
                    })
                test_cases_by_qid[qid] = cases

    # Load extracted flags
    extracted_queries = set()
    for ef in glob.glob(str(results_dir / '_extracted' / '*-extracted.json')):
        for q in json.load(open(ef)).get('queries', []):
            extracted_queries.add(q.get('query_id', ''))
    pg_extracted = set()
    for ef in glob.glob(str(results_dir / '_extracted_pg' / '*-extracted.json')):
        for q in json.load(open(ef)).get('queries', []):
            pg_extracted.add(q.get('query_id', ''))

    # Build matrix from query-tracking.json — latest version per file only
    # {file_dir: {version_num: path}} → pick highest version
    tracking_by_dir = {}
    for tf in sorted(glob.glob(str(results_dir / '*/v*/query-tracking.json'))):
        tf_path = Path(tf)
        file_dir = tf_path.parent.parent.name  # e.g. "UserMapper.xml"
        ver_dir = tf_path.parent.name  # e.g. "v1", "v2"
        ver_num = int(ver_dir.replace('v', '')) if ver_dir.startswith('v') and ver_dir[1:].isdigit() else 0
        if file_dir not in tracking_by_dir or ver_num > tracking_by_dir[file_dir][0]:
            tracking_by_dir[file_dir] = (ver_num, tf)

    for file_dir, (ver_num, tf) in sorted(tracking_by_dir.items()):
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

            # Fallback: check from validation results (bare query_id lookup)
            # query-tracking.json에 결과가 없거나 빈 값이면 validated.json에서 보충
            if not explain_status or explain_status == 'not_tested':
                vr = val_by_qid.get(qid)
                if vr:
                    explain_status = vr['status']
                    explain_error = vr.get('error', '')
                    explain_source = vr.get('source', 'static')
                elif not explain_status:
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

            # --- Attempts (from query-tracking.json attempts array) ---
            attempts = q.get('attempts', [])
            attempt_count = len(attempts)
            attempt_summary = '; '.join(
                a.get('summary', a.get('error', ''))[:80] for a in attempts[-3:]
            ) if attempts else ''

            # --- MyBatis ---
            mybatis = 'both' if (qid in extracted_queries and qid in pg_extracted) else \
                      'oracle_only' if qid in extracted_queries else \
                      'pg_only' if qid in pg_extracted else 'no'

            # --- 최종 상태 (14개 flat, 하나의 쿼리 = 하나의 상태) ---

            # 성공
            if attempt_count > 0 and explain_status == 'pass' and compare_status == 'pass':
                overall = 'PASS_HEALED'
                overall_detail = f'수정 {attempt_count}회 후 비교 통과'
            elif conv_status == 'no_change' and explain_status == 'pass' and compare_status == 'pass':
                overall = 'PASS_NO_CHANGE'
                overall_detail = 'Oracle 패턴 없어 변환 불필요, 비교 통과'
            elif conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'pass':
                overall = 'PASS_COMPLETE'
                overall_detail = '변환+비교 통과'

            # 실패 — DBA 필요
            elif explain_category == 'MISSING_TABLE':
                overall = 'FAIL_SCHEMA_MISSING'
                overall_detail = f'PG 테이블 없음: {explain_error[:150]}'
            elif explain_category == 'MISSING_COLUMN':
                overall = 'FAIL_COLUMN_MISSING'
                overall_detail = f'PG 컬럼 없음: {explain_error[:150]}'
            elif explain_category == 'MISSING_FUNCTION':
                overall = 'FAIL_FUNCTION_MISSING'
                overall_detail = f'PG 함수 없음: {explain_error[:150]}'

            # 실패 — 재시도 후 (explain 또는 compare 어느 쪽이든 5회 이상 실패)
            elif attempt_count >= 5 and (explain_status == 'fail' or compare_status == 'fail'):
                overall = 'FAIL_ESCALATED'
                detail = explain_error[:150] if explain_status == 'fail' else compare_fail_reason[:150]
                overall_detail = f'{attempt_count}회 시도 후 실패: {detail}'
            elif compare_status == 'fail':
                overall = 'FAIL_COMPARE_DIFF'
                overall_detail = f'Oracle↔PG 불일치: {compare_fail_reason[:150]}'
            elif explain_status == 'fail' and explain_category == 'SYNTAX_ERROR':
                overall = 'FAIL_SYNTAX'
                overall_detail = f'SQL 문법 에러: {explain_error[:150]}'

            # 실패 — TC/바인드 문제
            elif explain_category == 'TYPE_MISMATCH':
                overall = 'FAIL_TC_TYPE_MISMATCH'
                overall_detail = f'바인드값 타입/길이 불일치: {explain_error[:150]}'
            elif explain_category == 'TYPE_OPERATOR':
                overall = 'FAIL_TC_OPERATOR'
                overall_detail = f'연산자 타입 불일치: {explain_error[:150]}'

            # 기타 실패 — 특수 카테고리
            elif explain_status == 'fail' and explain_category == 'VALUE_TOO_LONG':
                overall = 'FAIL_TC_TYPE_MISMATCH'
                overall_detail = f'값 길이 초과: {explain_error[:150]}'
            elif explain_status == 'fail' and explain_category == 'AMBIGUOUS':
                overall = 'FAIL_SYNTAX'
                overall_detail = f'컬럼 모호성: {explain_error[:150]}'

            # 기타 실패
            elif explain_status == 'fail':
                overall = 'FAIL_SYNTAX'
                overall_detail = f'{explain_category}: {explain_error[:150]}'

            # 미테스트
            elif conv_status in ('converted', 'no_change') and explain_status == 'not_tested' and mybatis == 'no':
                overall = 'NOT_TESTED_NO_RENDER'
                overall_detail = 'MyBatis 렌더링 실패 (동적 SQL 평가 불가)'
            elif conv_status in ('converted', 'no_change') and explain_status == 'not_tested':
                overall = 'NOT_TESTED_NO_DB'
                overall_detail = 'DB 미접속 또는 --full 미실행'
            elif conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'not_tested':
                overall = 'NOT_TESTED_NO_DB'
                overall_detail = 'EXPLAIN 통과했지만 Oracle↔PG 비교 미실행'
            elif conv_status == 'pending':
                overall = 'NOT_TESTED_PENDING'
                overall_detail = '변환 미완료'
            else:
                overall = 'NOT_TESTED_PENDING'
                overall_detail = f'상태 미분류: conv={conv_status} explain={explain_status} compare={compare_status}'

            # --- Extra fields for JSON export (not in CSV) ---
            sql_before = q.get('oracle_sql', '') or ''
            sql_after = q.get('pg_sql', '') or ''
            raw_attempts = q.get('attempts', []) or []
            # Normalize attempts into the spec format
            json_attempts = []
            for idx, att in enumerate(raw_attempts, 1):
                err = att.get('error', '') or ''
                json_attempts.append(OrderedDict([
                    ('attempt', idx),
                    ('error_category', classify_explain_error(err) if err else None),
                    ('error_detail', err if err else None),
                    ('fix_applied', att.get('fix', att.get('summary', '')) or ''),
                    ('result', att.get('status', att.get('result', 'unknown'))),
                ]))
            json_test_cases = test_cases_by_qid.get(qid, [])
            conv_history = q.get('conversion_history', []) or []

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
                'attempt_count': attempt_count,
                'attempt_summary': attempt_summary,
                'mybatis_extracted': mybatis,
                'overall_status': overall,
                'overall_detail': overall_detail,
                # JSON-only fields (excluded from CSV fieldnames)
                '_sql_before': sql_before,
                '_sql_after': sql_after,
                '_conversion_history': conv_history,
                '_attempts': json_attempts,
                '_test_cases': json_test_cases,
            })

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    fieldnames = [
        'file', 'query_id', 'type', 'complexity',
        'conversion_method', 'conversion_status',
        'explain_status', 'explain_source', 'explain_error_category', 'explain_error_detail',
        'compare_status', 'compare_tc_total', 'compare_tc_pass', 'compare_tc_fail', 'compare_fail_reason',
        'attempt_count', 'attempt_summary',
        'mybatis_extracted', 'overall_status', 'overall_detail',
    ]

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    overall_counts = Counter(r['overall_status'] for r in rows)
    explain_cats = Counter(r['explain_error_category'] for r in rows if r['explain_error_category'])

    # Group by prefix for summary
    pass_count = sum(v for k, v in overall_counts.items() if k.startswith('PASS_'))
    fail_count = sum(v for k, v in overall_counts.items() if k.startswith('FAIL_'))
    not_tested = sum(v for k, v in overall_counts.items() if k.startswith('NOT_TESTED'))

    print(f"Query Matrix: {len(rows)} queries")
    print(f"\n  PASS: {pass_count} | FAIL: {fail_count} | NOT_TESTED: {not_tested}")
    print(f"\n  상세:")
    display_order = [
        'PASS_COMPLETE', 'PASS_HEALED', 'PASS_NO_CHANGE',
        'FAIL_SCHEMA_MISSING', 'FAIL_COLUMN_MISSING', 'FAIL_FUNCTION_MISSING',
        'FAIL_ESCALATED', 'FAIL_SYNTAX', 'FAIL_COMPARE_DIFF',
        'FAIL_TC_TYPE_MISMATCH', 'FAIL_TC_OPERATOR',
        'NOT_TESTED_NO_RENDER', 'NOT_TESTED_NO_DB', 'NOT_TESTED_PENDING',
    ]
    for label in display_order:
        cnt = overall_counts.get(label, 0)
        if cnt:
            desc = OVERALL_LABELS.get(label, '')
            print(f"    {label}: {cnt} — {desc}")

    if explain_cats:
        print(f"\n  EXPLAIN 에러 카테고리:")
        for cat, cnt in explain_cats.most_common():
            print(f"    {cat}: {cnt}")

    print(f"\nSaved: {args.output}")

    # JSON output
    if args.json:
        json_path = args.output.replace('.csv', '.json')
        # Build per-query detailed entries with exact field order from spec
        json_queries = []
        for r in rows:
            entry = OrderedDict([
                ('query_id', r['query_id']),
                ('original_file', r['file']),
                ('sql_before', r['_sql_before']),
                ('sql_after', r['_sql_after']),
                ('final_state', r['overall_status']),
                ('final_state_detail', r['overall_detail']),
                ('conversion_method', r['conversion_method']),
                ('conversion_history', r['_conversion_history']),
                ('test_cases', r['_test_cases']),
                ('attempts', r['_attempts']),
                ('explain_status', r['explain_status']),
                ('compare_status', r['compare_status']),
                ('complexity', r['complexity']),
            ])
            json_queries.append(entry)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(OrderedDict([
                ('generated_at', datetime.now().isoformat()),
                ('total', len(rows)),
                ('summary', dict(overall_counts)),
                ('explain_error_categories', dict(explain_cats)),
                ('queries', json_queries),
            ]), f, indent=2, ensure_ascii=False)
        print(f"JSON: {json_path}")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('STEP_END', agent='generate-query-matrix', step='step_4',
                     detail=f"Matrix: {len(rows)} queries, PASS:{pass_count}, "
                            f"FAIL:{fail_count}, NOT_TESTED:{not_tested}")
    except Exception:
        pass


if __name__ == '__main__':
    main()
