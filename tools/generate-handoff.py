#!/usr/bin/env python3
"""
Pipeline Handoff Generator
각 Step 완료 시 호출하여 handoff.json을 생성한다.
슈퍼바이저는 이 파일만 읽고 proceed/retry/abort를 판단한다.

Usage:
    # Step 0
    python3 tools/generate-handoff.py --step 0 --input-dir pipeline/shared/input

    # Step 1
    python3 tools/generate-handoff.py --step 1 \
        --results-dir pipeline/step-1-convert/output/results

    # Step 2
    python3 tools/generate-handoff.py --step 2 \
        --results-dir pipeline/step-1-convert/output/results \
        --tc-dir pipeline/step-2-tc-generate/output

    # Step 3
    python3 tools/generate-handoff.py --step 3 \
        --results-dir pipeline/step-1-convert/output/results \
        --validation-dir pipeline/step-3-validate-fix/output/validation \
        --batches-dir pipeline/step-3-validate-fix/output/batches

    # Step 4
    python3 tools/generate-handoff.py --step 4 \
        --report-dir pipeline/step-4-report/output
"""

import json
import glob
import os
import sys
import argparse
import time
from pathlib import Path
from collections import Counter


STEP_NAMES = {
    0: 'step-0-preflight',
    1: 'step-1-convert',
    2: 'step-2-tc-generate',
    3: 'step-3-validate-fix',
    4: 'step-4-report',
}

NEXT_STEPS = {
    0: ('step-1-convert', 'proceed'),
    1: ('step-2-tc-generate', 'proceed'),
    2: ('step-3-validate-fix', 'proceed'),
    3: ('step-4-report', 'proceed'),
    4: (None, 'complete'),
}

DBA_STATES = {'FAIL_SCHEMA_MISSING', 'FAIL_COLUMN_MISSING', 'FAIL_FUNCTION_MISSING'}


def classify_explain_error(error):
    """EXPLAIN 에러 카테고리 분류 (generate-query-matrix.py와 동일 로직)."""
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
    if 'invalid input syntax' in err:
        return 'TYPE_MISMATCH'
    return 'OTHER'


def is_dba_error(error):
    """DBA 3종 에러인지 판별."""
    cat = classify_explain_error(error)
    return cat in ('MISSING_TABLE', 'MISSING_COLUMN', 'MISSING_FUNCTION')


def load_all_tracking(results_dir):
    """모든 query-tracking.json을 로드하여 (latest version per file) 쿼리 목록 반환."""
    results_dir = Path(results_dir)
    tracking_by_dir = {}
    for tf in sorted(results_dir.glob('*/v*/query-tracking.json')):
        file_dir = tf.parent.parent.name
        ver_dir = tf.parent.name
        ver_num = int(ver_dir.replace('v', '')) if ver_dir.startswith('v') and ver_dir[1:].isdigit() else 0
        if file_dir not in tracking_by_dir or ver_num > tracking_by_dir[file_dir][0]:
            tracking_by_dir[file_dir] = (ver_num, tf)

    all_queries = []
    files_seen = set()
    for file_dir, (ver_num, tf) in sorted(tracking_by_dir.items()):
        try:
            tdata = json.load(open(tf))
        except Exception:
            continue
        files_seen.add(file_dir)
        queries = tdata.get('queries', [])
        if isinstance(queries, dict):
            queries = list(queries.values())
        for q in queries:
            q['_source_file'] = file_dir
            q['_tracking_path'] = str(tf)
        all_queries.extend(queries)
    return all_queries, files_seen


def load_validation_results(validation_dir, batches_dir=None):
    """validated.json + compare_validated.json 로드."""
    val_dir = Path(validation_dir) if validation_dir else None
    passes = set()
    failures = {}  # qid -> error

    # Main validation dir
    for vp in _find_validated_files(val_dir):
        vdata = json.load(open(vp))
        for p in vdata.get('passes', []):
            tid = p if isinstance(p, str) else p.get('test', '')
            passes.add(_bare_qid(tid))
        for f in vdata.get('failures', []):
            tid = f.get('test', f.get('test_id', ''))
            bare = _bare_qid(tid)
            if bare not in passes:
                failures[bare] = f.get('error', '')

    # Batch dirs
    if batches_dir and Path(batches_dir).exists():
        for bd in sorted(Path(batches_dir).iterdir()):
            if bd.is_dir():
                for vp in _find_validated_files(bd):
                    vdata = json.load(open(vp))
                    for p in vdata.get('passes', []):
                        tid = p if isinstance(p, str) else p.get('test', '')
                        passes.add(_bare_qid(tid))
                    for f in vdata.get('failures', []):
                        tid = f.get('test', f.get('test_id', ''))
                        bare = _bare_qid(tid)
                        if bare not in passes:
                            failures[bare] = f.get('error', '')

    # Compare results
    compare = {}  # qid -> [results]
    for cp in _find_compare_files(val_dir, batches_dir):
        cdata = json.load(open(cp))
        for r in cdata.get('results', []):
            raw_qid = r.get('query_id', r.get('test_id', ''))
            bare = _bare_qid(raw_qid) if '.' in raw_qid else raw_qid
            compare.setdefault(bare, []).append(r)

    return passes, failures, compare


def _find_validated_files(d):
    if d and d.exists():
        for f in sorted(d.glob('**/validated.json')):
            yield f


def _find_compare_files(val_dir, batches_dir):
    for d in [val_dir, Path(batches_dir) if batches_dir else None]:
        if d and d.exists():
            for f in sorted(d.glob('**/compare_validated.json')):
                yield f
            for f in sorted(d.glob('**/compare_results.json')):
                yield f


def _bare_qid(test_id):
    parts = str(test_id).split('.')
    if len(parts) >= 2:
        return parts[-2]
    return str(test_id)


def classify_state(q, explain_passes, explain_failures, compare_results):
    """14-state 분류 (generate-query-matrix.py와 동일 로직)."""
    qid = q.get('query_id', '')
    method = q.get('conversion_method', '')
    # conv_status: pg_sql 존재 OR status 필드로 판별 (둘 다 확인)
    tracking_status = q.get('status', '')
    if method == 'no_change':
        conv_status = 'no_change'
    elif q.get('pg_sql') or tracking_status in ('converted', 'success', 'validated'):
        conv_status = 'converted'
    else:
        conv_status = 'pending'

    # Explain — explain 중첩 객체 + validated.json fallback
    explain = q.get('explain', {}) or {}
    explain_status = explain.get('status', '')
    explain_error = explain.get('error', '') or ''
    # explain_phase35 (MyBatis 렌더링 검증)도 확인
    explain_p35 = q.get('explain_phase35', {}) or {}
    if explain_p35.get('status') == 'pass' and explain_status != 'pass':
        explain_status = 'pass'
        explain_error = ''
    if not explain_status or explain_status == 'not_tested':
        if qid in explain_passes:
            explain_status = 'pass'
        elif qid in explain_failures:
            explain_status = 'fail'
            explain_error = explain_failures[qid]

    explain_cat = classify_explain_error(explain_error) if explain_status == 'fail' else ''

    # Compare
    cmp_results = compare_results.get(qid, [])
    # query-tracking 내장 compare_results도 확인
    if not cmp_results:
        tracking_cmp = q.get('compare_results', [])
        if tracking_cmp:
            cmp_results = tracking_cmp
    if cmp_results:
        if isinstance(cmp_results, list):
            tc_fail = sum(1 for c in cmp_results if isinstance(c, dict) and not c.get('match', False))
        elif isinstance(cmp_results, dict):
            tc_fail = 0 if cmp_results.get('match', False) else 1
        else:
            tc_fail = 0
        compare_status = 'pass' if tc_fail == 0 else 'fail'
    else:
        compare_status = 'not_tested'

    # attempts OR history (스키마는 history, 실제로는 attempts도 사용)
    attempts = q.get('attempts', []) or q.get('history', [])
    attempt_count = len(attempts)
    mybatis = bool(q.get('_has_extracted'))

    # Classification (same priority as generate-query-matrix.py)
    if attempt_count > 0 and explain_status == 'pass' and compare_status == 'pass':
        return 'PASS_HEALED'
    if conv_status == 'no_change' and explain_status == 'pass' and compare_status == 'pass':
        return 'PASS_NO_CHANGE'
    if conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'pass':
        return 'PASS_COMPLETE'

    if explain_cat == 'MISSING_TABLE':
        return 'FAIL_SCHEMA_MISSING'
    if explain_cat == 'MISSING_COLUMN':
        return 'FAIL_COLUMN_MISSING'
    if explain_cat == 'MISSING_FUNCTION':
        return 'FAIL_FUNCTION_MISSING'

    if attempt_count >= 3 and (explain_status == 'fail' or compare_status == 'fail'):
        return 'FAIL_ESCALATED'
    if compare_status == 'fail':
        return 'FAIL_COMPARE_DIFF'
    if explain_status == 'fail' and explain_cat == 'SYNTAX_ERROR':
        return 'FAIL_SYNTAX'
    if explain_cat == 'TYPE_MISMATCH':
        return 'FAIL_TC_TYPE_MISMATCH'
    if explain_cat == 'TYPE_OPERATOR':
        return 'FAIL_TC_OPERATOR'
    if explain_status == 'fail':
        return 'FAIL_SYNTAX'

    # DML이면서 Compare 스킵
    qtype = q.get('type', '')
    if conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'not_tested' and qtype in ('insert', 'update', 'delete'):
        return 'NOT_TESTED_DML_SKIP'
    if conv_status in ('converted', 'no_change') and explain_status == 'not_tested' and not mybatis:
        return 'NOT_TESTED_NO_RENDER'
    if conv_status in ('converted', 'no_change') and explain_status == 'not_tested':
        return 'NOT_TESTED_NO_DB'
    if conv_status in ('converted', 'no_change') and explain_status == 'pass' and compare_status == 'not_tested':
        return 'NOT_TESTED_NO_DB'
    if conv_status == 'pending':
        return 'NOT_TESTED_PENDING'
    return 'NOT_TESTED_PENDING'


# ── Step-specific generators ──

def generate_step0(args):
    input_dir = Path(args.input_dir or 'pipeline/shared/input')
    samples_dir = Path('pipeline/step-0-preflight/output/samples')
    xml_files = sorted(f.name for f in input_dir.glob('*.xml'))
    total_lines = 0
    for xf in input_dir.glob('*.xml'):
        try:
            total_lines += sum(1 for _ in open(xf, errors='ignore'))
        except Exception:
            pass

    sample_count = len(list(samples_dir.glob('*.json'))) if samples_dir.exists() else 0
    env_path = Path('pipeline/step-0-preflight/output/env-check.json')
    env_checks = json.load(open(env_path)) if env_path.exists() else {}

    return {
        'summary': {
            'xml_file_count': len(xml_files),
            'xml_files': xml_files,
            'total_lines': total_lines,
            'env_checks': env_checks,
            'sample_tables_collected': sample_count,
            'java_src_dir': os.environ.get('JAVA_SRC_DIR'),
            'custom_binds_exists': Path('pipeline/shared/custom-binds.json').exists(),
        },
        'outputs': {
            'samples_dir': 'pipeline/step-0-preflight/output/samples/',
            'env_check': 'pipeline/step-0-preflight/output/env-check.json',
            'input_dir': 'pipeline/shared/input/',
        },
    }


def generate_step1(args):
    results_dir = Path(args.results_dir)
    queries, files_seen = load_all_tracking(results_dir)
    xml_dir = Path('pipeline/step-1-convert/output/xml')
    xml_count = len(list(xml_dir.glob('*.xml'))) if xml_dir.exists() else 0

    methods = Counter(q.get('conversion_method', '') for q in queries)
    complexity = Counter(q.get('complexity', '') for q in queries)
    unconverted = sum(1 for q in queries if not q.get('pg_sql') and q.get('conversion_method') != 'no_change')

    return {
        'summary': {
            'files_processed': xml_count,
            'files_total': xml_count,
            'queries_total': len(queries),
            'queries_rule_converted': methods.get('rule', 0),
            'queries_llm_converted': methods.get('llm', 0),
            'queries_no_change': methods.get('no_change', 0),
            'queries_unconverted': unconverted,
            'complexity_distribution': dict(complexity),
        },
        'outputs': {
            'xml_dir': 'pipeline/step-1-convert/output/xml/',
            'results_dir': 'pipeline/step-1-convert/output/results/',
            'extracted_oracle_dir': 'pipeline/step-1-convert/output/extracted_oracle/',
        },
    }


def generate_step2(args):
    tc_dir = Path(args.tc_dir or 'pipeline/step-2-tc-generate/output')
    merged_tc_path = tc_dir / 'merged-tc.json'
    merged = {}
    if merged_tc_path.exists():
        merged = json.load(open(merged_tc_path))

    total_tcs = sum(len(v) for v in merged.values())
    queries_with_tc = sum(1 for v in merged.values() if v)
    queries_without_tc = 0

    # Count queries from step-1 tracking
    results_dir = Path(args.results_dir) if args.results_dir else None
    if results_dir:
        all_q, _ = load_all_tracking(results_dir)
        total_queries = len(all_q)
        queries_without_tc = total_queries - queries_with_tc

    # Source distribution (approximate from TC names)
    source_dist = Counter()
    for qid, tcs in merged.items():
        for tc in tcs:
            if isinstance(tc, dict):
                src = tc.get('source', 'INFERRED')
                source_dist[src] += 1

    return {
        'summary': {
            'queries_with_tc': queries_with_tc,
            'queries_without_tc': queries_without_tc,
            'total_test_cases': total_tcs,
            'tc_source_distribution': dict(source_dist),
        },
        'outputs': {
            'merged_tc': 'pipeline/step-2-tc-generate/output/merged-tc.json',
            'per_file_tc_dir': 'pipeline/step-2-tc-generate/output/per-file/',
        },
    }


def generate_step3(args):
    results_dir = Path(args.results_dir)
    validation_dir = args.validation_dir
    batches_dir = args.batches_dir

    # 배치 디렉토리 자동 탐색 — --batches-dir 미지정이면 validation-dir 형제에서 찾기
    if not batches_dir:
        # pipeline/step-3-validate-fix/output/batches/ 또는 workspace/results/ 내 _validation_batch-*
        for candidate in [
            'pipeline/step-3-validate-fix/output/batches',
            'workspace/results',  # _validation_batch-* 형태
        ]:
            if Path(candidate).exists():
                # batches/ 하위에 batch-* 디렉토리가 있는지
                if list(Path(candidate).glob('batch-*')):
                    batches_dir = candidate
                    break
                # _validation_batch-* 형태
                if list(Path(candidate).glob('_validation_batch*')):
                    batches_dir = candidate
                    break

    # results-dir에도 _validation*이 있으면 validation_dir로 사용
    if not validation_dir:
        for candidate in [
            'pipeline/step-3-validate-fix/output/validation',
            str(results_dir / '_validation'),
        ]:
            if Path(candidate).exists() and list(Path(candidate).glob('**/validated.json')):
                validation_dir = candidate
                break

    queries, files_seen = load_all_tracking(results_dir)
    passes, failures, compare = load_validation_results(validation_dir, batches_dir)

    # Classify all queries
    state_counts = Counter()
    no_loop_queries = []
    for q in queries:
        qid = q.get('query_id', '')
        state = classify_state(q, passes, failures, compare)
        state_counts[state] += 1

        # Gate check: FAIL without fix loop (non-DBA)
        attempts = q.get('attempts', []) or q.get('history', [])
        explain = q.get('explain', {}) or {}
        explain_err = explain.get('error', '') or ''
        is_dba = is_dba_error(explain_err)
        # validated.json의 에러도 확인 (tracking에 explain이 없을 수 있음)
        if not is_dba and qid in failures:
            is_dba = is_dba_error(failures[qid])
        is_fail = state.startswith('FAIL_') and state not in DBA_STATES
        if is_fail and len(attempts) == 0 and not is_dba:
            no_loop_queries.append(qid)

    # Counts
    explain_pass = sum(1 for q in queries if (q.get('explain', {}) or {}).get('status') == 'pass' or q.get('query_id', '') in passes)
    explain_fail = sum(1 for q in queries if (q.get('explain', {}) or {}).get('status') == 'fail' or q.get('query_id', '') in failures)
    explain_not_tested = len(queries) - explain_pass - explain_fail

    compare_qids = set(compare.keys())
    compare_pass = sum(1 for qid, results in compare.items() if all(r.get('match', False) for r in results))
    compare_fail = sum(1 for qid, results in compare.items() if any(not r.get('match', False) for r in results))
    compare_not_tested = len(queries) - len(compare_qids)

    total_attempts = sum(len(q.get('attempts', [])) for q in queries)
    fix_resolved = state_counts.get('PASS_HEALED', 0)
    fix_escalated = state_counts.get('FAIL_ESCALATED', 0)
    dba_skipped = sum(state_counts.get(s, 0) for s in DBA_STATES)

    # Gate: compare coverage
    # Also include tracking-embedded compare_results in compare_qids
    for q in queries:
        qid = q.get('query_id', '')
        if qid not in compare_qids and q.get('compare_results'):
            compare_qids.add(qid)
    compare_target = len(queries) - dba_skipped
    compare_done = len(compare_qids)
    # Non-DBA queries without compare (DML is exempt — EXPLAIN-only is acceptable)
    DML_TYPES = {'insert', 'update', 'delete'}
    compare_missing_non_dba = 0
    for q in queries:
        qid = q.get('query_id', '')
        qtype = (q.get('type', 'select') or 'select').lower()
        state = classify_state(q, passes, failures, compare)
        if state not in DBA_STATES and qid not in compare_qids and qtype not in DML_TYPES:
            # Only count if explain passed (can't compare if explain failed)
            if (q.get('explain', {}) or {}).get('status') == 'pass' or qid in passes:
                compare_missing_non_dba += 1

    # Tracking files updated (those with attempts)
    tracking_updated = list(set(
        q['_tracking_path'] for q in queries
        if q.get('attempts') and '_tracking_path' in q
    ))

    handoff = {
        'summary': {
            'queries_total': len(queries),
            'explain_pass': explain_pass,
            'explain_fail': explain_fail,
            'explain_not_tested': explain_not_tested,
            'compare_pass': compare_pass,
            'compare_fail': compare_fail,
            'compare_not_tested': compare_not_tested,
            'fix_attempted': total_attempts,
            'fix_resolved': fix_resolved,
            'fix_escalated': fix_escalated,
            'dba_skipped': dba_skipped,
            'state_counts': dict(state_counts),
        },
        'gate_checks': {
            'fix_loop_executed': {
                'status': 'fail' if no_loop_queries else 'pass',
                'fail_no_loop_count': len(no_loop_queries),
                'fail_no_loop_queries': no_loop_queries[:20],
                'detail': f'Non-DBA FAIL without attempts: {len(no_loop_queries)}' if no_loop_queries
                          else 'All non-DBA FAIL queries have attempts > 0',
            },
            'compare_coverage': {
                'status': 'fail' if compare_missing_non_dba > 0 else 'pass',
                'compare_target': compare_target,
                'compare_done': compare_done,
                'compare_missing_non_dba': compare_missing_non_dba,
                'detail': f'Compare missing (non-DBA, explain pass): {compare_missing_non_dba}'
                          if compare_missing_non_dba > 0 else 'All non-DBA queries have Compare results',
            },
            'render_coverage': {
                'status': 'warn' if state_counts.get('NOT_TESTED_NO_RENDER', 0) > 0 else 'pass',
                'no_render_count': state_counts.get('NOT_TESTED_NO_RENDER', 0),
                'detail': f'MyBatis 렌더링 실패 {state_counts.get("NOT_TESTED_NO_RENDER", 0)}건 — TC 보강 필요'
                          if state_counts.get('NOT_TESTED_NO_RENDER', 0) > 0
                          else 'All queries rendered successfully',
            },
            'test_coverage': {
                'status': 'fail' if (sum(v for k, v in state_counts.items() if k.startswith('NOT_TESTED')) > len(queries) * 0.5) else 'pass',
                'not_tested_count': sum(v for k, v in state_counts.items() if k.startswith('NOT_TESTED')),
                'not_tested_pct': round(sum(v for k, v in state_counts.items() if k.startswith('NOT_TESTED')) / max(len(queries), 1) * 100, 1),
                'detail': f'NOT_TESTED {sum(v for k,v in state_counts.items() if k.startswith("NOT_TESTED"))}건 '
                          f'({round(sum(v for k,v in state_counts.items() if k.startswith("NOT_TESTED"))/max(len(queries),1)*100,1)}%) — '
                          f'50% 초과 시 psql 출력 캡처 실패 의심. 재실행 필요.'
                          if sum(v for k, v in state_counts.items() if k.startswith('NOT_TESTED')) > len(queries) * 0.5
                          else f'NOT_TESTED {sum(v for k,v in state_counts.items() if k.startswith("NOT_TESTED"))}건 — 정상 범위',
            },
        },
        'outputs': {
            'extracted_pg_dir': 'pipeline/step-3-validate-fix/output/extracted_pg/',
            'validation_dir': 'pipeline/step-3-validate-fix/output/validation/',
            'batch_dirs': sorted(str(p) for p in Path(batches_dir).iterdir() if p.is_dir()) if batches_dir and Path(batches_dir).exists() else [],
            'fixed_xml_dir': 'pipeline/step-3-validate-fix/output/xml-fixes/',
            'tracking_files_updated': tracking_updated,
        },
    }

    # Warnings
    warnings = []
    nt_render = state_counts.get('NOT_TESTED_NO_RENDER', 0)
    nt_pending = state_counts.get('NOT_TESTED_PENDING', 0)
    if nt_render:
        warnings.append(f'NOT_TESTED_NO_RENDER: {nt_render} queries (MyBatis rendering failed)')
    if nt_pending:
        warnings.append(f'NOT_TESTED_PENDING: {nt_pending} queries (unconverted)')
    handoff['_warnings'] = warnings

    # Blockers
    blockers = []
    if no_loop_queries:
        blockers.append(f'Fix loop not executed for {len(no_loop_queries)} non-DBA FAIL queries')
    if compare_missing_non_dba > 0:
        blockers.append(f'Compare not executed for {compare_missing_non_dba} non-DBA queries')
    # NOT_TESTED 50% 이상이면 검증 자체가 실패한 것
    not_tested_total = sum(v for k, v in state_counts.items() if k.startswith('NOT_TESTED'))
    if len(queries) > 0 and not_tested_total > len(queries) * 0.5:
        blockers.append(f'NOT_TESTED {not_tested_total}/{len(queries)} ({round(not_tested_total/len(queries)*100,1)}%) — psql 출력 캡처 실패 의심. 재실행 필요.')
    handoff['_blockers'] = blockers

    # Recommendation
    if blockers:
        handoff['_recommendation'] = 'retry'
    else:
        handoff['_recommendation'] = 'proceed'

    return handoff


def generate_step4(args):
    report_dir = Path(args.report_dir or 'pipeline/step-4-report/output')
    csv_path = report_dir / 'query-matrix.csv'
    json_path = report_dir / 'query-matrix.json'
    html_path = report_dir / 'migration-report.html'

    files_ok = all(p.exists() and p.stat().st_size > 0 for p in [csv_path, json_path, html_path])

    # Read matrix JSON for summary
    summary = {'total_queries': 0, 'pass_count': 0, 'fail_code_count': 0,
               'fail_dba_count': 0, 'not_tested_count': 0, 'pass_rate_percent': 0}
    fields_present = True
    required_fields = ['query_id', 'original_file', 'sql_before', 'sql_after',
                       'final_state', 'test_cases', 'attempts', 'conversion_history']

    if json_path.exists():
        try:
            mdata = json.load(open(json_path))
            total = mdata.get('total', 0)
            sc = mdata.get('summary', {})
            pass_count = sum(v for k, v in sc.items() if k.startswith('PASS_'))
            fail_dba = sum(sc.get(s, 0) for s in ['FAIL_SCHEMA_MISSING', 'FAIL_COLUMN_MISSING', 'FAIL_FUNCTION_MISSING'])
            fail_code = sum(v for k, v in sc.items() if k.startswith('FAIL_')) - fail_dba
            not_tested = sum(v for k, v in sc.items() if k.startswith('NOT_TESTED'))
            summary = {
                'total_queries': total,
                'pass_count': pass_count,
                'fail_code_count': fail_code,
                'fail_dba_count': fail_dba,
                'not_tested_count': not_tested,
                'pass_rate_percent': round(pass_count / total * 100, 1) if total else 0,
            }
            # Check required fields
            if mdata.get('queries'):
                first_q = mdata['queries'][0]
                missing = [f for f in required_fields if f not in first_q]
                if missing:
                    fields_present = False
        except Exception:
            pass

    # 필드 완성도 체크
    field_completeness = {}
    if json_path.exists():
        try:
            mdata = json.load(open(json_path))
            check_fields = ['query_id', 'original_file', 'type', 'xml_before', 'xml_after',
                            'sql_before', 'sql_after', 'final_state', 'conversion_method',
                            'explain_status', 'compare_status', 'complexity',
                            'conversion_history', 'test_cases', 'attempts']
            total_q = len(mdata.get('queries', []))
            for field in check_fields:
                empty = sum(1 for q in mdata.get('queries', [])
                            if not q.get(field) and q.get(field) != 0)
                field_completeness[field] = round((total_q - empty) / max(total_q, 1) * 100, 1)
        except Exception:
            pass

    return {
        'summary': summary,
        'outputs': {
            'query_matrix_csv': str(csv_path),
            'query_matrix_json': str(json_path),
            'migration_report_html': str(html_path),
        },
        'validation': {
            'all_files_exist_and_nonempty': files_ok,
            'json_required_fields_present': fields_present,
            'required_fields': required_fields,
            'field_completeness': field_completeness,
        },
    }


def main():
    parser = argparse.ArgumentParser(description='Generate pipeline handoff.json')
    parser.add_argument('--step', type=int, required=True, choices=[0, 1, 2, 3, 4])
    parser.add_argument('--output', help='Output handoff.json path (default: pipeline/step-N-name/handoff.json)')
    parser.add_argument('--input-dir', help='Step 0: input XML directory')
    parser.add_argument('--results-dir', help='Step 1-3: query-tracking results directory')
    parser.add_argument('--tc-dir', help='Step 2: TC output directory')
    parser.add_argument('--validation-dir', help='Step 3: validation output directory')
    parser.add_argument('--batches-dir', help='Step 3: batch validation directories')
    parser.add_argument('--report-dir', help='Step 4: report output directory')
    parser.add_argument('--started-at', type=int, help='Step start timestamp (Unix)')
    args = parser.parse_args()

    step_name = STEP_NAMES[args.step]
    output_path = args.output or f'pipeline/{step_name}/handoff.json'
    started_at = args.started_at or int(time.time()) - 60  # default: 1 min ago

    # Generate step-specific data
    generators = {0: generate_step0, 1: generate_step1, 2: generate_step2,
                  3: generate_step3, 4: generate_step4}
    step_data = generators[args.step](args)

    # Build handoff
    completed_at = int(time.time())
    next_step, default_rec = NEXT_STEPS[args.step]
    recommendation = step_data.pop('_recommendation', default_rec)
    warnings = step_data.pop('_warnings', [])
    blockers = step_data.pop('_blockers', [])

    status = 'failed' if blockers else 'success'

    handoff = {
        'step': step_name,
        'step_number': args.step,
        'status': status,
        'started_at': started_at,
        'completed_at': completed_at,
        'duration_ms': (completed_at - started_at) * 1000,
        'blockers': blockers,
        'warnings': warnings,
        'next_step': next_step,
        'next_step_recommendation': recommendation,
    }
    handoff.update(step_data)

    # Write
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(handoff, f, indent=2, ensure_ascii=False)
    print(f'Handoff: {output_path} ({status})')

    # Print summary
    if 'gate_checks' in handoff:
        gc = handoff['gate_checks']
        fix_status = gc['fix_loop_executed']['status']
        cmp_status = gc['compare_coverage']['status']
        print(f'  Gate: fix_loop={fix_status}, compare_coverage={cmp_status}')
        if fix_status == 'fail' or cmp_status == 'fail':
            print(f'  BLOCKED: {"; ".join(blockers)}')

    if 'summary' in handoff:
        s = handoff['summary']
        if 'queries_total' in s:
            print(f'  Queries: {s["queries_total"]}')
        if 'state_counts' in s:
            sc = s['state_counts']
            p = sum(v for k, v in sc.items() if k.startswith('PASS_'))
            f_count = sum(v for k, v in sc.items() if k.startswith('FAIL_'))
            n = sum(v for k, v in sc.items() if k.startswith('NOT_'))
            print(f'  PASS: {p} | FAIL: {f_count} | NOT_TESTED: {n}')

    # Log activity
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('HANDOFF_GENERATED', agent='generate-handoff',
                     step=step_name, detail=f'status={status}')
    except Exception:
        pass


if __name__ == '__main__':
    main()
