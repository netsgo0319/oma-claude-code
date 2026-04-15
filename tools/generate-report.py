#!/usr/bin/env python3
"""
Comprehensive Drill-Down HTML Viewer for Oracle-to-PostgreSQL Migration.

Generates a single self-contained HTML file with interactive tabs,
collapsible file/query details, SQL diff view, and activity timeline.

Usage:
    python3 tools/generate-report.py
    python3 tools/generate-report.py --output workspace/reports/migration-report.html

Data sources (auto-discovered):
    workspace/progress.json                        pipeline status
    workspace/results/*/v*/query-tracking.json     per-query tracking
    workspace/results/*/v*/parsed.json             parse results
    workspace/results/_validation/validated.json   EXPLAIN validation
    workspace/results/_validation/execute_validated.json  execution validation
    workspace/results/_extracted/*-extracted.json   MyBatis extraction
    workspace/logs/activity-log.jsonl              activity log
    workspace/input/*.xml / workspace/output/*.xml file sizes
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from html import escape


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl(path):
    entries = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return entries


def count_xml_queries(xml_path):
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(xml_path)
        root = tree.getroot()
        count = 0
        for tag in ['select', 'insert', 'update', 'delete']:
            count += len(root.findall(f'.//{tag}'))
        return count
    except Exception:
        return 0


def file_size_str(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024*1024):.1f} MB"


def _derive_progress(ws):
    """Derive pipeline progress from existing result files when progress.json is missing."""
    progress = {'_pipeline': {'phases': {}}, 'files': {}}
    results_dir = ws / 'results'
    if not results_dir.exists():
        return progress

    for d in sorted(results_dir.iterdir()):
        if d.is_dir() and not d.name.startswith('_'):
            fname = d.name + '.xml' if not d.name.endswith('.xml') else d.name
            fdata = {'status': 'pending', 'queries_total': 0}

            # Check what exists
            for vdir in sorted(d.glob('v*')):
                if (vdir / 'parsed.json').exists():
                    parsed = load_json(vdir / 'parsed.json')
                    if parsed:
                        fdata['status'] = 'parsed'
                        fdata['queries_total'] = parsed.get('metadata', {}).get('total_queries', 0)
                        fdata['oraclePatterns'] = {}
                        for q in parsed.get('queries', []):
                            for p in q.get('oracle_patterns', []):
                                fdata['oraclePatterns'][p] = fdata['oraclePatterns'].get(p, 0) + 1
                        progress['_pipeline']['phases']['phase_1'] = {'status': 'done'}

                if (vdir / 'conversion-report.json').exists():
                    fdata['status'] = 'converted'
                    progress['_pipeline']['phases']['phase_2'] = {'status': 'done'}

                if (vdir / 'query-tracking.json').exists():
                    tracking = load_json(vdir / 'query-tracking.json')
                    if tracking:
                        queries = tracking.get('queries', [])
                        fdata['queries_total'] = len(queries)
                        pass_q = sum(1 for q in queries if q.get('status') == 'success')
                        fail_q = sum(1 for q in queries if q.get('status') in ('failed', 'escalated'))
                        fdata['queries_pass'] = pass_q
                        fdata['queries_fail'] = fail_q

            progress['files'][fname] = fdata

    # Phase 0: if any results exist, phase 0 must have run
    if progress['files']:
        progress['_pipeline']['phases']['phase_0'] = {'status': 'done'}

    # Phase 2.5: test-cases.json
    if any((ws / 'results').glob('*/v*/test-cases.json')):
        progress['_pipeline']['phases']['phase_2.5'] = {'status': 'done'}

    # Phase 3: validation
    val_dir = ws / 'results' / '_validation'
    if val_dir.exists() and (val_dir / 'validated.json').exists():
        progress['_pipeline']['phases']['phase_3'] = {'status': 'done'}

    # MyBatis extraction results
    ext_dir = ws / 'results' / '_extracted'
    if ext_dir.exists() and list(ext_dir.glob('*-extracted.json')):
        progress['_pipeline']['phases']['phase_3.5'] = {'status': 'done'}

    # MyBatis extraction validation (separate dir, backward compat)
    for d35 in ['_validation_phase35']:
        if (ws / 'results' / d35 / 'validated.json').exists():
            progress['_pipeline']['phases']['phase_3.5'] = {'status': 'done'}

    # Step 4: report — 이 함수가 실행 중이면 Step 4가 진행 중이므로 항상 done
    # (migration-report.html은 이 함수가 만드는 것이라 아직 없을 수 있음)
    progress['_pipeline']['phases']['phase_4'] = {'status': 'done'}

    return progress


def collect_data(base_dir):
    """query-matrix.json을 단일 소스로 보고서 데이터를 구성한다.
    query-matrix.json이 없으면 에러. 반드시 generate-query-matrix.py --json을 먼저 실행."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'progress': None,
        'files': {},
        'tracking': {},
        'validation': None,
        'execution': None,
        'comparison': None,
        'query_matrix': None,
        'extracted': [],
        'activity_log': [],
        'input_files': [],
        'output_files': [],
        'summary': {},
    }

    ws = Path(base_dir) / 'workspace'

    # ★ 핵심: query-matrix.json이 유일한 데이터 소스
    qm_path = ws / 'reports' / 'query-matrix.json'
    # pipeline 모드 fallback
    if not qm_path.exists():
        qm_path = Path('pipeline/step-4-report/output/query-matrix.json')
    if not qm_path.exists():
        print("ERROR: query-matrix.json not found. Run generate-query-matrix.py --json first.")
        # Fallback: 기존 로직으로 derive (하위 호환)
        return _collect_data_legacy(base_dir)

    qm_data = load_json(qm_path)
    if not qm_data or 'queries' not in qm_data:
        print("ERROR: query-matrix.json is empty or malformed.")
        return _collect_data_legacy(base_dir)

    data['query_matrix'] = qm_data

    # 1. Step progress — query-matrix.json의 step_progress 또는 handoff에서
    step_progress = qm_data.get('step_progress', {})
    progress = {'_pipeline': {'phases': {}}, 'files': {}}
    for step_key, sp in step_progress.items():
        progress['_pipeline']['phases'][step_key] = {'status': sp.get('status', 'unknown')}
    data['progress'] = progress

    # 2. File stats — query-matrix.json의 file_stats에서
    file_stats = {fs['file']: fs for fs in qm_data.get('file_stats', [])}

    # Input/Output XML 기본 정보 — 파일 시스템에서 보충 (크기/줄수)
    for xml_dir_key, data_key in [('input', 'input_files'), ('output', 'output_files')]:
        xml_dir = ws / xml_dir_key
        if xml_dir.exists():
            for xml_file in sorted(xml_dir.glob('*.xml')):
                try:
                    data[data_key].append({
                        'name': xml_file.name,
                        'size_bytes': xml_file.stat().st_size,
                        'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
                        'queries': count_xml_queries(xml_file),
                    })
                except Exception:
                    pass

    # 3. Per-file tracking — query-matrix.json의 queries를 파일별로 그룹화
    files_data = {}
    for q in qm_data.get('queries', []):
        fname = q.get('original_file', '')
        if not fname:
            continue
        fname_base = fname.replace('.xml', '') if fname.endswith('.xml') else fname

        if fname_base not in files_data:
            files_data[fname_base] = {
                'name': fname_base,
                'versions': {'v1': {'query-tracking': {'file': fname, 'queries': []}}},
            }
        # 쿼리 데이터를 tracking 형식으로 변환
        qdata = {
            'query_id': q.get('query_id', ''),
            'type': '',
            'oracle_sql': q.get('sql_before', ''),
            'pg_sql': q.get('sql_after', ''),
            'xml_before': q.get('xml_before', ''),
            'xml_after': q.get('xml_after', ''),
            'conversion_method': q.get('conversion_method', ''),
            'complexity': q.get('complexity', ''),
            'status': 'success' if q.get('final_state', '').startswith('PASS_') else 'failed',
            'final_state': q.get('final_state', ''),
            'final_state_detail': q.get('final_state_detail', ''),
            'explain': {'status': q.get('explain_status', '')},
            'compare_results': q.get('compare_detail', [{'match': q.get('compare_status') == 'pass'}] if q.get('compare_status') != 'not_tested' else []),
            'attempts': q.get('attempts', []),
            'conversion_history': q.get('conversion_history', []),
            'test_cases': q.get('test_cases', []),
            'oracle_patterns': [],
        }
        files_data[fname_base]['versions']['v1']['query-tracking']['queries'].append(qdata)

        # tracking map에도 추가
        if fname not in data['tracking']:
            data['tracking'][fname] = {'file': fname, 'queries': []}
        data['tracking'][fname]['queries'].append(qdata)

    data['files'] = files_data

    # 4. Validation summary — query-matrix.json에서 derive
    total_q = qm_data.get('total', 0)
    summary_counts = qm_data.get('summary', {})
    pass_count = sum(v for k, v in summary_counts.items() if k.startswith('PASS_'))
    fail_count = sum(v for k, v in summary_counts.items() if k.startswith('FAIL_'))
    data['validation'] = {
        'total': total_q,
        'pass': pass_count,
        'fail': fail_count,
        'passes': [q['query_id'] for q in qm_data['queries'] if q.get('explain_status') == 'pass'],
        'failures': [{'test': q['query_id'], 'error': q.get('final_state_detail', '')}
                     for q in qm_data['queries'] if q.get('explain_status') == 'fail'],
    }

    # 5. Comparison — query-matrix.json에서 derive
    compare_results = []
    for q in qm_data.get('queries', []):
        if q.get('compare_status') != 'not_tested':
            compare_results.append({
                'query_id': q['query_id'],
                'match': q.get('compare_status') == 'pass',
            })
    data['comparison'] = {'results': compare_results} if compare_results else None

    # 6. Activity log — 유일하게 query-matrix.json 외부에서 읽는 데이터
    data['activity_log'] = load_jsonl(ws / 'logs' / 'activity-log.jsonl')

    # 7. Summary — query-matrix.json에서 derive
    qm_summary = qm_data.get('summary', {})
    data['summary'] = {
        'total_input_files': len(data['input_files']),
        'total_output_files': len(data['output_files']),
        'total_input_lines': sum(f.get('lines', 0) for f in data['input_files']),
        'total_output_lines': sum(f.get('lines', 0) for f in data['output_files']),
        'total_input_queries': sum(f.get('queries', 0) for f in data['input_files']),
        'total_output_queries': sum(f.get('queries', 0) for f in data['output_files']),
        'oracle_patterns': qm_data.get('oracle_patterns', {}),
        'complexity_dist': qm_data.get('complexity_distribution', {}),
        'conversion_methods': qm_data.get('conversion_methods', {}),
        'validation_pass': sum(v for k, v in qm_summary.items() if k.startswith('PASS_')),
        'validation_fail': sum(v for k, v in qm_summary.items() if k.startswith('FAIL_')),
        'validation_total': qm_data.get('total', 0),
        'compare_match': sum(1 for q in qm_data['queries'] if q.get('compare_status') == 'pass'),
        'compare_fail': sum(1 for q in qm_data['queries'] if q.get('compare_status') == 'fail'),
        'compare_total': sum(1 for q in qm_data['queries'] if q.get('compare_status') != 'not_tested'),
    }

    return data


def _collect_data_legacy(base_dir):
    """query-matrix.json이 없을 때 기존 방식으로 데이터 수집 (하위 호환)."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'progress': None, 'files': {}, 'tracking': {}, 'validation': None,
        'execution': None, 'comparison': None, 'query_matrix': None,
        'extracted': [], 'activity_log': [], 'input_files': [], 'output_files': [], 'summary': {},
    }
    ws = Path(base_dir) / 'workspace'

    data['progress'] = load_json(ws / 'progress.json') or _derive_progress(ws)

    for xml_dir_key, data_key in [('input', 'input_files'), ('output', 'output_files')]:
        xml_dir = ws / xml_dir_key
        if xml_dir.exists():
            for xml_file in sorted(xml_dir.glob('*.xml')):
                try:
                    data[data_key].append({
                        'name': xml_file.name,
                        'size_bytes': xml_file.stat().st_size,
                        'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
                        'queries': count_xml_queries(xml_file),
                    })
                except Exception:
                    pass

    results_dir = ws / 'results'
    if results_dir.exists():
        for d in sorted(results_dir.iterdir()):
            if d.is_dir() and not d.name.startswith('_'):
                fname = d.name
                file_data = {'name': fname, 'versions': {}}
                for vdir in sorted(d.glob('v*')):
                    vdata = {}
                    tracking_path = vdir / 'query-tracking.json'
                    if tracking_path.exists():
                        tracking = load_json(tracking_path)
                        if tracking:
                            vdata['query-tracking'] = tracking
                            xml_name = fname + '.xml' if not fname.endswith('.xml') else fname
                            data['tracking'][xml_name] = tracking
                    file_data['versions'][vdir.name] = vdata
                data['files'][fname] = file_data

    data['activity_log'] = load_jsonl(ws / 'logs' / 'activity-log.jsonl')
    data['summary'] = compute_summary(data)
    return data


def compute_summary(data):
    s = {
        'total_input_files': len(data['input_files']),
        'total_output_files': len(data['output_files']),
        'total_input_lines': sum(f['lines'] for f in data['input_files']),
        'total_output_lines': sum(f['lines'] for f in data['output_files']),
        'total_input_queries': sum(f['queries'] for f in data['input_files']),
        'total_output_queries': sum(f['queries'] for f in data['output_files']),
        'oracle_patterns': {},
        'complexity_dist': {},
        'conversion_methods': {'rule': 0, 'llm': 0, 'manual': 0},
        'validation_pass': 0, 'validation_fail': 0, 'validation_total': 0,
        'execution_pass': 0, 'execution_fail': 0, 'execution_total': 0,
        'compare_match': 0, 'compare_fail': 0, 'compare_warn': 0, 'compare_total': 0,
    }

    # From progress.json
    if data['progress'] and 'files' in data['progress']:
        for fname, fdata in data['progress']['files'].items():
            for p, count in fdata.get('oraclePatterns', {}).items():
                s['oracle_patterns'][p] = s['oracle_patterns'].get(p, 0) + count
            for level, count in fdata.get('complexity', {}).items():
                s['complexity_dist'][level] = s['complexity_dist'].get(level, 0) + count

    # From parsed.json files
    for fname, fdata in data['files'].items():
        for vname, vdata in fdata.get('versions', {}).items():
            parsed = vdata.get('parsed')
            if parsed:
                for q in parsed.get('queries', []):
                    for p in q.get('oracle_patterns', q.get('patterns', [])):
                        s['oracle_patterns'][p] = s['oracle_patterns'].get(p, 0) + 1
                    method = q.get('method', 'rule')
                    if method in s['conversion_methods']:
                        s['conversion_methods'][method] += 1
                    # complexity
                    comp = q.get('complexity', '')
                    if comp:
                        s['complexity_dist'][comp] = s['complexity_dist'].get(comp, 0) + 1

    # From complexity-scores.json (direct summary)
    if not s['complexity_dist']:
        for fname, fdata in data['files'].items():
            for vname, vdata in fdata.get('versions', {}).items():
                comp_data = vdata.get('complexity-scores')
                if comp_data:
                    # Method 1: summary field {L0: 5, L1: 3, ...}
                    summary = comp_data.get('summary', {})
                    if isinstance(summary, dict):
                        for level, count in summary.items():
                            if isinstance(level, str) and level.startswith('L'):
                                s['complexity_dist'][level] = s['complexity_dist'].get(level, 0) + count
                    # Method 2: queries array [{query_id, level, ...}]
                    if not s['complexity_dist']:
                        for q in comp_data.get('queries', comp_data.get('scores', [])):
                            if isinstance(q, dict):
                                level = q.get('level', '')
                                if level:
                                    s['complexity_dist'][level] = s['complexity_dist'].get(level, 0) + 1

    # From query-tracking
    tracking_queries_total = 0
    tracking_success = 0
    tracking_fail = 0
    for fname, tracking in data['tracking'].items():
        if tracking and 'queries' in tracking:
            for q in tracking['queries']:
                tracking_queries_total += 1
                st = q.get('status', '')
                if st == 'success':
                    tracking_success += 1
                elif st in ('failed', 'escalated'):
                    tracking_fail += 1
                method = q.get('conversion_method', '')
                if method in s['conversion_methods']:
                    s['conversion_methods'][method] += 1
    s['tracking_total'] = tracking_queries_total
    s['tracking_success'] = tracking_success
    s['tracking_fail'] = tracking_fail

    # Validation
    if data['validation']:
        s['validation_pass'] = data['validation'].get('pass', 0)
        s['validation_fail'] = data['validation'].get('fail', 0)
        s['validation_total'] = data['validation'].get('total', 0)

    if data['execution']:
        s['execution_pass'] = data['execution'].get('pass', 0)
        s['execution_fail'] = data['execution'].get('fail', 0)
        s['execution_total'] = data['execution'].get('total', 0)

    if data.get('comparison'):
        comp = data['comparison']
        s['compare_match'] = comp.get('pass', comp.get('matched', 0))
        s['compare_fail'] = comp.get('fail', comp.get('mismatched', 0))
        s['compare_warn'] = comp.get('warn', 0)
        s['compare_total'] = comp.get('total', 0)

    # Extracted
    s['extracted_files'] = len(data['extracted'])
    s['extracted_queries'] = sum(e['total_queries'] for e in data['extracted'])
    s['extracted_variants'] = sum(e['total_variants'] for e in data['extracted'])
    s['extracted_multi_branch'] = sum(e['multi_branch'] for e in data['extracted'])

    # Migration readiness
    total_q = s['total_input_queries']
    if total_q > 0:
        compare_match = s.get('compare_match', 0)
        compare_fail = s.get('compare_fail', 0)
        needs_manual = compare_fail
        # Escalated from compare (PKG_CRYPTO etc)
        escalated = 0
        if data.get('comparison') and data['comparison'].get('results'):
            for r in data['comparison']['results']:
                if not r.get('match', False):
                    err = str(r.get('pg_error', '') or r.get('ora_error', '') or r.get('reason', ''))
                    if 'does not exist' in err or 'pkg_crypto' in err.lower():
                        escalated += 1
        # Best available: compare > EXPLAIN
        if s.get('compare_total'):
            s['truly_done'] = compare_match
        else:
            s['truly_done'] = s.get('validation_pass', 0)
        s['needs_manual'] = needs_manual
        s['escalated_queries'] = escalated
        # Readiness = pass / tested (not pass / total)
        # Queries not tested (no TC, dynamic SQL) are "unverified", not "failed"
        tested = s.get('compare_total') or s.get('validation_total') or 0
        s['tested_queries'] = tested
        s['unverified_queries'] = total_q - tested
        s['readiness_pct'] = round(s['truly_done'] * 100 / tested) if tested > 0 else 0
    else:
        s['truly_done'] = 0
        s['needs_manual'] = 0
        s['escalated_queries'] = 0
        s['readiness_pct'] = 0

    return s


def build_embedded_data(data):
    """Build the JSON blob that gets embedded in the HTML."""
    embedded = {
        'generated_at': data['generated_at'],
        'summary': data['summary'],
        'progress': data.get('progress') or {},
        'pipeline': (data.get('progress') or {}).get('_pipeline', {}),
        'input_files': data['input_files'],
        'output_files': data['output_files'],
        'activity_log': data['activity_log'],
        'extracted': data['extracted'],
        'validation': data.get('validation'),
        'execution': data.get('execution'),
        'comparison': data.get('comparison'),
        'query_matrix': data.get('query_matrix'),
        'files': {},
    }

    # Build compare lookup by query_id
    compare_by_query = {}
    if data.get('comparison') and isinstance(data['comparison'], dict):
        for cr in data['comparison'].get('results', []):
            qid = cr.get('query_id', '')
            compare_by_query.setdefault(qid, []).append(cr)

    input_map = {f['name']: f for f in data['input_files']}
    output_map = {f['name']: f for f in data['output_files']}
    progress_files = (data.get('progress') or {}).get('files', {})

    # Build per-file data merging all sources
    all_filenames = set()
    for f in data['input_files']:
        all_filenames.add(f['name'])
    for f in data['output_files']:
        all_filenames.add(f['name'])
    for fname in data['files']:
        xml_name = fname + '.xml' if not fname.endswith('.xml') else fname
        all_filenames.add(xml_name)
    for fname in progress_files:
        all_filenames.add(fname)

    for xml_name in sorted(all_filenames):
        base_name = xml_name.replace('.xml', '')
        inp = input_map.get(xml_name, {})
        out = output_map.get(xml_name, {})
        prog = progress_files.get(xml_name, {})
        file_results = data['files'].get(base_name, {})

        # Get queries from query-tracking, fallback to parsed.json
        queries = []
        tracking = data['tracking'].get(xml_name)
        if tracking and 'queries' in tracking:
            queries = tracking['queries']
        else:
            # Fallback to parsed.json queries
            for vname, vdata in file_results.get('versions', {}).items():
                parsed = vdata.get('parsed')
                if parsed and 'queries' in parsed:
                    for q in parsed['queries']:
                        queries.append({
                            'query_id': q.get('id', q.get('query_id', '')),
                            'type': q.get('type', 'select'),
                            'status': q.get('status', 'parsed'),
                            'complexity': q.get('complexity'),
                            'conversion_method': q.get('method', 'rule'),
                            'oracle_patterns': q.get('oraclePatterns', q.get('patterns', q.get('oracle_patterns', []))),
                            'oracle_sql': (q.get('oracle_sql', q.get('sql_raw', '')) or '')[:2000],
                            'pg_sql': (q.get('pg_sql', '') or '')[:2000],
                            'rules_applied': q.get('rules_applied', []),
                            'explain': q.get('explain'),
                            'execution': q.get('execution'),
                            'test_cases': q.get('test_cases', []),
                            'timing': q.get('timing', {}),
                            'history': q.get('history', []),
                            'notes': q.get('notes', ''),
                        })
                    break  # Only use the latest version

        # Merge compare results into per-query data
        for q in queries:
            qid = q.get('query_id', q.get('id', ''))
            if qid in compare_by_query:
                q['compare_results'] = compare_by_query[qid]
                # Update status based on compare results
                all_match = all(cr.get('match', False) for cr in compare_by_query[qid])
                any_error = any(cr.get('pg_error') or cr.get('ora_error') or cr.get('oracle_error')
                                for cr in compare_by_query[qid])
                if any_error:
                    q['compare_status'] = 'error'
                elif all_match:
                    q['compare_status'] = 'match'
                else:
                    q['compare_status'] = 'mismatch'

        # Count pass/fail — "converted" is intermediate, not success
        pass_count = sum(1 for q in queries if q.get('status') in ('success', 'pass', 'validated'))
        fail_count = sum(1 for q in queries if q.get('status') in ('failed', 'escalated', 'fail', 'needs_llm_review'))
        # Also count compare failures
        compare_fail = sum(1 for q in queries if q.get('compare_status') in ('error', 'mismatch'))
        compare_pass = sum(1 for q in queries if q.get('compare_status') == 'match')

        embedded['files'][xml_name] = {
            'name': xml_name,
            'input_lines': inp.get('lines', 0),
            'input_size': inp.get('size_bytes', 0),
            'output_lines': out.get('lines', 0),
            'output_size': out.get('size_bytes', 0),
            'total_queries': prog.get('totalQueries', len(queries)),
            'converted_queries': prog.get('convertedQueries', 0) or sum(1 for q in queries if q.get('status') in ('converted', 'success', 'pass', 'validated') or q.get('conversion_method') not in (None, '')),
            'status': prog.get('status', 'unknown'),
            'phase': prog.get('phase', 0),
            'oracle_patterns': prog.get('oraclePatterns', {}),
            'complexity': prog.get('complexity', {}),
            'pass_count': pass_count,
            'fail_count': fail_count,
            'compare_pass': compare_pass,
            'compare_fail': compare_fail,
            'queries': queries,
        }

    # Phase timeline from progress._pipeline
    pipeline = (data.get('progress') or {}).get('_pipeline', {})
    embedded['pipeline'] = pipeline

    return embedded


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OMA Migration Report</title>
<style>
:root{--bg:#0f172a;--card:#1e293b;--card2:#283548;--border:#334155;--text:#e2e8f0;--dim:#94a3b8;--accent:#3b82f6;--accent2:#60a5fa;--success:#22c55e;--warn:#eab308;--fail:#ef4444;--orange:#f97316;--purple:#a855f7;--mono:'SF Mono','Fira Code','Cascadia Code',monospace;--sans:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--sans);background:var(--bg);color:var(--text);line-height:1.6}
.container{max-width:1400px;margin:0 auto;padding:12px 20px}
/* Header */
.hdr{text-align:center;padding:20px 0 12px;border-bottom:1px solid var(--border);margin-bottom:16px}
.hdr h1{font-size:24px;font-weight:700}.hdr .sub{color:var(--dim);font-size:12px;margin-top:4px}
/* Tabs */
.tabs{display:flex;gap:2px;background:var(--card);border-radius:10px 10px 0 0;padding:4px 4px 0;border:1px solid var(--border);border-bottom:none}
.tab-btn{padding:10px 24px;background:transparent;border:none;color:var(--dim);font-size:13px;font-weight:600;cursor:pointer;border-radius:8px 8px 0 0;transition:all .2s}
.tab-btn:hover{color:var(--text);background:rgba(255,255,255,.05)}
.tab-btn.active{color:var(--accent2);background:var(--bg);border-bottom:2px solid var(--accent)}
.tab-content{display:none;padding:20px;background:var(--bg);border:1px solid var(--border);border-top:none;border-radius:0 0 10px 10px;min-height:400px}
.tab-content.active{display:block}
/* Cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.card .lbl{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
.card .val{font-size:26px;font-weight:700;margin-top:2px}
.card .det{font-size:11px;color:var(--dim);margin-top:2px}
.val.ok{color:var(--success)}.val.wn{color:var(--warn)}.val.fl{color:var(--fail)}
/* Section */
.sec{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:16px}
.sec h2{font-size:16px;font-weight:600;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
/* Bars */
.bar-row{display:flex;align-items:center;margin-bottom:5px}
.bar-lbl{width:140px;font-size:12px;font-family:var(--mono);flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{flex:1;height:18px;background:rgba(255,255,255,.05);border-radius:4px;margin:0 10px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width .3s}
.bar-val{width:55px;text-align:right;font-size:12px;font-family:var(--mono);color:var(--dim)}
/* Phase bars */
.phase-row{display:flex;align-items:center;margin-bottom:8px;padding:8px 12px;background:var(--card2);border-radius:8px}
.phase-name{width:120px;font-size:13px;font-weight:600;flex-shrink:0}
.phase-bar{flex:1;height:22px;background:rgba(255,255,255,.05);border-radius:4px;margin:0 12px;overflow:hidden;position:relative}
.phase-fill{height:100%;border-radius:4px;transition:width .5s}
.phase-fill.done{background:var(--success)}.phase-fill.running{background:var(--accent);animation:pulse 1.5s infinite}
.phase-fill.pending{background:var(--border)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.phase-info{width:200px;font-size:12px;color:var(--dim);text-align:right}
.phase-badge{display:inline-block;padding:1px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:6px}
.badge-done{background:rgba(34,197,94,.15);color:var(--success)}
.badge-run{background:rgba(59,130,246,.15);color:var(--accent2)}
.badge-pending{background:rgba(148,163,184,.1);color:var(--dim)}
/* Two columns */
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.cols2{grid-template-columns:1fr}}
/* File list */
.file-item{border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden}
.file-hdr{display:flex;align-items:center;padding:10px 14px;cursor:pointer;background:var(--card);transition:background .2s;gap:10px}
.file-hdr:hover{background:var(--card2)}
.file-arrow{font-size:10px;color:var(--dim);transition:transform .2s;width:16px}
.file-item.open .file-arrow{transform:rotate(90deg)}
.file-name{font-family:var(--mono);font-size:13px;font-weight:600;flex:1}
.file-stats{display:flex;gap:8px;font-size:11px}
.file-stats span{padding:2px 8px;border-radius:4px;font-weight:600}
.file-body{display:none;padding:0 14px 14px;background:var(--bg)}
.file-item.open .file-body{display:block}
/* Query item */
.q-item{border:1px solid var(--border);border-radius:6px;margin-top:8px;overflow:hidden}
.q-hdr{display:flex;align-items:center;padding:8px 12px;cursor:pointer;background:var(--card2);gap:8px;font-size:12px}
.q-hdr:hover{background:rgba(255,255,255,.05)}
.q-arrow{font-size:9px;color:var(--dim);transition:transform .2s;width:14px}
.q-item.open .q-arrow{transform:rotate(90deg)}
.q-id{font-family:var(--mono);font-weight:600;flex:1}
.q-badge{padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700}
.q-body{display:none;padding:10px 12px;background:var(--bg);font-size:12px}
.q-item.open .q-body{display:block}
/* SQL blocks */
.sql-container{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}
@media(max-width:768px){.sql-container{grid-template-columns:1fr}}
.sql-block{background:#0c1222;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.sql-block-hdr{padding:4px 10px;background:var(--card2);font-size:10px;font-weight:700;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
.sql-block pre{padding:10px;font-family:var(--mono);font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-all;overflow-x:auto;max-height:300px;overflow-y:auto}
/* SQL highlighting */
.kw{color:#60a5fa}.fn{color:#34d399}.str{color:#fb923c}.num{color:#c084fc}.cm{color:#64748b;font-style:italic}
/* Detail rows */
.q-detail{margin:6px 0;display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap}
.q-detail .dlbl{color:var(--dim);font-size:11px;min-width:80px;flex-shrink:0}
.q-detail .dval{font-size:11px;font-family:var(--mono)}
.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;margin-right:4px;margin-bottom:2px}
.tag-pattern{background:rgba(96,165,250,.15);color:var(--accent2)}
.tag-rule{background:rgba(52,211,153,.15);color:#34d399}
/* History */
.hist-item{display:flex;gap:8px;padding:3px 0;font-size:11px;align-items:center}
.hist-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
/* Timeline */
.tl-item{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.03);font-size:12px}
.tl-time{width:70px;font-family:var(--mono);color:var(--dim);flex-shrink:0}
.tl-type{width:120px;font-weight:600;flex-shrink:0}
.tl-msg{flex:1;color:var(--dim)}
/* Log viewer */
.log-filters{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.log-filter-btn{padding:4px 12px;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--dim);font-size:11px;cursor:pointer;transition:all .2s}
.log-filter-btn.active{border-color:var(--accent);color:var(--accent2);background:rgba(59,130,246,.1)}
.log-search{padding:6px 12px;border:1px solid var(--border);border-radius:4px;background:var(--card);color:var(--text);font-size:12px;flex:1;max-width:300px}
.log-entry{padding:6px 10px;border-bottom:1px solid rgba(255,255,255,.03);font-size:11px;font-family:var(--mono);display:flex;gap:8px}
.log-entry.hidden{display:none}
.log-ts{color:var(--dim);width:70px;flex-shrink:0}.log-evt{width:110px;flex-shrink:0;font-weight:600}.log-msg{flex:1;word-break:break-all;color:var(--dim)}
.log-evt.error{color:var(--fail)}.log-evt.decision{color:var(--accent2)}.log-evt.warning{color:var(--warn)}
/* Refresh toggle */
.refresh-toggle{position:fixed;bottom:16px;right:16px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-size:11px;color:var(--dim);cursor:pointer;z-index:100;display:flex;align-items:center;gap:6px}
.refresh-toggle.on{border-color:var(--success);color:var(--success)}
.refresh-dot{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.refresh-toggle.on .refresh-dot{background:var(--success);animation:pulse 1.5s infinite}
/* Tables */
table{width:100%;border-collapse:collapse;margin-top:6px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--border);font-size:12px}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;background:var(--card2)}
/* Filter buttons (Files tab) */
.filter-btn{padding:4px 12px;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--dim);font-size:11px;cursor:pointer;transition:all .2s}
.filter-btn.active{border-color:var(--accent);color:var(--accent2);background:rgba(59,130,246,.1)}
/* Status colors */
.st-success,.st-converted,.st-pass{color:var(--success)}.st-failed,.st-fail,.st-escalated{color:var(--fail)}
.st-running,.st-validating,.st-converting{color:var(--accent2)}.st-parsed,.st-analyzed,.st-pending{color:var(--dim)}
.st-needs_llm_review{color:var(--orange)}.st-retry_1,.st-retry_2,.st-retry_3{color:var(--warn)}
</style>
</head>
<body>
<div class="container">
<div class="hdr">
  <h1>Oracle &rarr; PostgreSQL Migration Report</h1>
  <div class="sub" id="gen-time"></div>
</div>

<div class="tabs" id="tabs">
  <button class="tab-btn active" data-tab="overview">Overview</button>
  <button class="tab-btn" data-tab="explorer">Explorer</button>
  <button class="tab-btn" data-tab="dba">DBA</button>
  <button class="tab-btn" data-tab="log">Log</button>
</div>

<!-- ========== OVERVIEW TAB ========== -->
<div class="tab-content active" id="tab-overview">
  <div id="summary-cards" class="cards"></div>
</div>

<!-- ========== EXPLORER TAB (3-panel navigation) ========== -->
<div class="tab-content" id="tab-explorer">
  <div style="margin-bottom:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <input id="exp-search" placeholder="검색: 파일명, 쿼리ID, SQL..." style="flex:1;min-width:200px;padding:8px 12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:var(--fg);font-size:13px" oninput="expRenderFiles()">
    <select id="exp-status" onchange="expRenderFiles()" style="padding:6px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:var(--fg)">
      <option value="">전체</option><option value="pass">PASS</option><option value="fail">FAIL</option><option value="not_tested">미테스트</option>
    </select>
    <select id="exp-type" onchange="expRenderFiles()" style="padding:6px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:var(--fg)">
      <option value="">전체</option><option value="select">SELECT</option><option value="insert">INSERT</option><option value="update">UPDATE</option><option value="delete">DELETE</option>
    </select>
    <span id="exp-count" style="color:var(--dim);font-size:12px"></span>
  </div>
  <div style="display:flex;gap:1px;height:calc(100vh - 180px);min-height:400px">
    <div id="exp-panel-files" style="width:25%;overflow-y:auto;background:rgba(255,255,255,.02);border-radius:6px;padding:4px"></div>
    <div id="exp-panel-queries" style="width:25%;overflow-y:auto;background:rgba(255,255,255,.02);border-radius:6px;padding:4px"></div>
    <div id="exp-panel-detail" style="width:50%;overflow-y:auto;background:rgba(255,255,255,.02);border-radius:6px;padding:8px"></div>
  </div>
</div>

<!-- ========== DBA TAB ========== -->
<div class="tab-content" id="tab-dba">
  <div class="sec" id="dba-content"></div>
</div>

<!-- ========== LOG TAB ========== -->
<div class="tab-content" id="tab-log">
  <div class="sec">
    <h2>Activity Log</h2>
    <div class="log-filters">
      <button class="log-filter-btn active" data-filter="all">All</button>
      <button class="log-filter-btn" data-filter="error">Error</button>
      <button class="log-filter-btn" data-filter="decision">Decision</button>
      <button class="log-filter-btn" data-filter="warning">Warning</button>
      <input type="text" class="log-search" id="log-search" placeholder="Search log...">
    </div>
    <div id="log-list" style="max-height:600px;overflow-y:auto"></div>
  </div>
</div>

</div><!-- /container -->

<div class="refresh-toggle" id="refresh-toggle" title="Auto-refresh every 5s">
  <span class="refresh-dot"></span> Auto-refresh
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

// ========== Helpers ==========
function esc(s){if(!s)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function fmtSize(b){if(!b)return '-';if(b<1024)return b+' B';if(b<1048576)return(b/1024).toFixed(1)+' KB';return(b/1048576).toFixed(1)+' MB'}
function fmtMs(ms){if(ms==null)return '-';if(ms<1000)return ms+'ms';return(ms/1000).toFixed(1)+'s'}
function statusClass(s){return 'st-'+(s||'pending').replace(/\s/g,'_')}
function statusIcon(s){
  if(!s)return '';
  s=String(s);
  // 14-state (final_state from query-matrix.json)
  if(s.startsWith('PASS_'))return '<span style="color:var(--success)" title="'+s+'">&#10003;</span>';
  if(s==='FAIL_SCHEMA_MISSING'||s==='FAIL_COLUMN_MISSING'||s==='FAIL_FUNCTION_MISSING')return '<span style="color:var(--warn)" title="'+s+' (DBA)">&#9888;</span>';
  if(s.startsWith('FAIL_'))return '<span style="color:var(--fail)" title="'+s+'">&#10007;</span>';
  if(s.startsWith('NOT_TESTED'))return '<span style="color:var(--dim)" title="'+s+'">&#9679;</span>';
  // Legacy internal status fallback
  if(['success','pass','validated','complete'].includes(s))return '<span style="color:var(--success)" title="통과">&#10003;</span>';
  if(s==='converted')return '<span style="color:var(--accent2)" title="변환 완료">&#8594;</span>';
  if(['failed','fail','escalated'].includes(s))return '<span style="color:var(--fail)" title="실패">&#10007;</span>';
  if(s.startsWith('retry'))return '<span style="color:var(--warn)" title="재시도 중">&#8635;</span>';
  return '<span style="color:var(--dim)" title="대기">&#9679;</span>';
}
function statusLabel(s){
  const labels={
    'PASS_COMPLETE':'PASS','PASS_HEALED':'HEALED','PASS_NO_CHANGE':'NO CHANGE',
    'FAIL_SCHEMA_MISSING':'DBA:스키마','FAIL_COLUMN_MISSING':'DBA:컬럼','FAIL_FUNCTION_MISSING':'DBA:함수',
    'FAIL_ESCALATED':'ESCALATED','FAIL_SYNTAX':'SYNTAX','FAIL_COMPARE_DIFF':'COMPARE DIFF',
    'FAIL_TC_TYPE_MISMATCH':'TYPE MISMATCH','FAIL_TC_OPERATOR':'OPERATOR',
    'NOT_TESTED_DML_SKIP':'DML SKIP','NOT_TESTED_NO_RENDER':'NO RENDER','NOT_TESTED_NO_DB':'NO DB','NOT_TESTED_PENDING':'PENDING',
    // legacy
    'success':'완료','failed':'실패','escalated':'에스컬레이션','converted':'변환완료','pending':'대기'
  };
  return labels[s]||s;
}
function highlightSQL(sql){
  if(!sql)return '<span style="color:var(--dim)">N/A</span>';
  let s=esc(sql);
  // keywords
  s=s.replace(/\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|ON|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|UNION|ALL|INSERT|INTO|UPDATE|SET|DELETE|CREATE|ALTER|DROP|TABLE|INDEX|VIEW|AS|IS|NULL|LIKE|BETWEEN|EXISTS|CASE|WHEN|THEN|ELSE|END|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|DISTINCT|COUNT|WITH|RECURSIVE|VALUES|RETURNING|FETCH|FIRST|ROWS|ONLY|MINUS|INTERSECT|MERGE|USING|MATCHED)\b/gi,
    function(m){return '<span class="kw">'+m+'</span>'});
  // functions
  s=s.replace(/\b(NVL2?|COALESCE|DECODE|SYSDATE|SYSTIMESTAMP|CURRENT_TIMESTAMP|TO_CHAR|TO_DATE|TO_NUMBER|TRUNC|ROUND|SUBSTR|INSTR|LENGTH|REPLACE|TRIM|UPPER|LOWER|ROWNUM|ROW_NUMBER|RANK|DENSE_RANK|LISTAGG|STRING_AGG|SYS_CONNECT_BY_PATH|CONNECT_BY_ROOT|LEVEL|REGEXP_LIKE|REGEXP_REPLACE|NVL2|GREATEST|LEAST|ABS|MOD|CEIL|FLOOR|MAX|MIN|SUM|AVG)\b/gi,
    function(m){return '<span class="fn">'+m+'</span>'});
  // strings
  s=s.replace(/'([^']*)'/g,"<span class=\"str\">'$1'</span>");
  // numbers
  s=s.replace(/\b(\d+\.?\d*)\b/g,'<span class="num">$1</span>');
  // comments
  s=s.replace(/(\/\*[\s\S]*?\*\/)/g,'<span class="cm">$1</span>');
  s=s.replace(/(--[^\n]*)/g,'<span class="cm">$1</span>');
  return s;
}

// ========== Tab navigation ==========
document.querySelectorAll('.tab-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-'+btn.dataset.tab).classList.add('active');
  });
});

// ========== Toggle helpers ==========
function toggleItem(el){el.classList.toggle('open')}

// ========== Render Overview ==========
function renderOverview(){
  const S=DATA.summary;
  document.getElementById('gen-time').textContent='Generated: '+(DATA.generated_at||'').replace('T',' ').substring(0,19)+' | OMA Migration Accelerator';

  // 14개 flat 상태 집계
  let qm=DATA.query_matrix||{};
  let qmS=qm.summary||{};
  let totalQ=qm.total||S.total_input_queries||0;

  // Group by prefix
  let pass=0, fail=0, notTested=0;
  for(let [k,v] of Object.entries(qmS)){
    if(k.startsWith('PASS_'))pass+=v;
    else if(k.startsWith('FAIL_'))fail+=v;
    else if(k.startsWith('NOT_TESTED'))notTested+=v;
  }
  let failDba=(qmS.FAIL_SCHEMA_MISSING||0)+(qmS.FAIL_COLUMN_MISSING||0)+(qmS.FAIL_FUNCTION_MISSING||0);
  let failCode=fail-failDba;

  document.getElementById('summary-cards').innerHTML=
    `<div class="card"><div class="lbl">파일</div><div class="val">${S.total_input_files}</div><div class="det">${S.total_input_lines?S.total_input_lines.toLocaleString():'-'} lines</div></div>`+
    `<div class="card"><div class="lbl">전체 쿼리</div><div class="val">${totalQ}</div></div>`+
    `<div class="card"><div class="lbl" style="color:var(--success)">PASS</div><div class="val ok">${pass}</div><div class="det">${Object.entries(qmS).filter(([k])=>k.startsWith('PASS_')).map(([k,v])=>k.replace('PASS_','')+':'+v).join(' ')}</div></div>`+
    `<div class="card"><div class="lbl" style="color:var(--fail)">FAIL (코드)</div><div class="val fl">${failCode}</div><div class="det">${Object.entries(qmS).filter(([k])=>k.startsWith('FAIL_')&&!k.includes('SCHEMA')&&!k.includes('COLUMN')&&!k.includes('FUNCTION')).map(([k,v])=>k.replace('FAIL_','')+':'+v).join(' ')}</div></div>`+
    `<div class="card"><div class="lbl" style="color:var(--warn)">FAIL (DBA)</div><div class="val wn">${failDba}</div><div class="det">${Object.entries(qmS).filter(([k])=>k.includes('SCHEMA')||k.includes('COLUMN')||k.includes('FUNCTION')).map(([k,v])=>k.replace('FAIL_','')+':'+v).join(' ')}</div></div>`+
    `<div class="card"><div class="lbl" style="color:var(--dim)">미테스트</div><div class="val">${notTested}</div><div class="det">${Object.entries(qmS).filter(([k])=>k.startsWith('NOT_TESTED')).map(([k,v])=>k.replace('NOT_TESTED_','')+':'+v).join(' ')}</div></div>`;

  // 15-state breakdown table
  let stateDescriptions = {
    'PASS_COMPLETE': '변환+비교 통과',
    'PASS_HEALED': '수정 후 비교 통과',
    'PASS_NO_CHANGE': '변환 불필요 + 비교 통과',
    'FAIL_SCHEMA_MISSING': 'PG 테이블 없음 (DBA)',
    'FAIL_COLUMN_MISSING': 'PG 컬럼 없음 (DBA)',
    'FAIL_FUNCTION_MISSING': 'PG 함수 없음 (DBA)',
    'FAIL_ESCALATED': '3회 수정 후 미해결',
    'FAIL_SYNTAX': 'SQL 문법 에러',
    'FAIL_COMPARE_DIFF': 'Oracle↔PG 결과 불일치',
    'FAIL_TC_TYPE_MISMATCH': '바인드값 타입 불일치',
    'FAIL_TC_OPERATOR': '연산자 타입 불일치',
    'NOT_TESTED_DML_SKIP': 'DML이라 Compare 스킵 (EXPLAIN만 통과)',
    'NOT_TESTED_NO_RENDER': 'MyBatis 렌더링 실패',
    'NOT_TESTED_NO_DB': 'DB 미접속',
    'NOT_TESTED_PENDING': '변환 미완료'
  };
  let stateGroups = {
    'PASS': ['PASS_COMPLETE','PASS_HEALED','PASS_NO_CHANGE'],
    'FAIL (코드)': ['FAIL_SYNTAX','FAIL_COMPARE_DIFF','FAIL_TC_TYPE_MISMATCH','FAIL_TC_OPERATOR','FAIL_ESCALATED'],
    'FAIL (DBA)': ['FAIL_SCHEMA_MISSING','FAIL_COLUMN_MISSING','FAIL_FUNCTION_MISSING'],
    'NOT_TESTED': ['NOT_TESTED_DML_SKIP','NOT_TESTED_NO_RENDER','NOT_TESTED_NO_DB','NOT_TESTED_PENDING']
  };
  let stateTableHtml='<div style="margin-top:16px"><h3 style="margin-bottom:8px">15-State 상세 분류</h3>';
  stateTableHtml+='<table style="font-size:12px;width:100%"><tr><th>그룹</th><th>상태</th><th style="text-align:right">건수</th><th>설명</th></tr>';
  let stateSum=0;
  for(let [group, states] of Object.entries(stateGroups)){
    let groupTotal=0;
    let groupColor=group.startsWith('PASS')?'var(--success)':group.includes('DBA')?'var(--warn)':group.startsWith('FAIL')?'var(--fail)':'var(--dim)';
    for(let st of states){
      let cnt=qmS[st]||0;
      groupTotal+=cnt;
      stateSum+=cnt;
      if(cnt>0){
        stateTableHtml+=`<tr><td style="color:${groupColor};font-weight:bold">${esc(group)}</td>`;
        stateTableHtml+=`<td><code>${esc(st)}</code></td>`;
        stateTableHtml+=`<td style="text-align:right;font-weight:bold">${cnt}</td>`;
        stateTableHtml+=`<td style="color:var(--dim)">${esc(stateDescriptions[st]||'')}</td></tr>`;
      }
    }
  }
  let matchMsg=stateSum===totalQ?'<span style="color:var(--success)">일치</span>':'<span style="color:var(--fail)">불일치!</span>';
  stateTableHtml+=`<tr style="border-top:2px solid rgba(255,255,255,.1)"><td colspan="2" style="font-weight:bold">합계</td><td style="text-align:right;font-weight:bold">${stateSum} / ${totalQ}</td><td>${matchMsg}</td></tr>`;
  stateTableHtml+='</table></div>';
  document.getElementById('summary-cards').insertAdjacentHTML('afterend',stateTableHtml);
}

function renderActionItems(){
  let html='<div class="sec"><div class="file-item"><div class="file-hdr" onclick="toggleItem(this.parentElement)" style="cursor:pointer">';
  html+='<span class="file-arrow">&#9654;</span>';
  html+='<h2 style="display:inline;margin:0">Action Items</h2></div>';
  html+='<div class="file-body">';
  // Build action items from validation results
  let actions=[];
  // (action items from validation results can be added here)
  if(actions.length===0){html+='<p style="color:var(--dim)">No action items</p>';}
  else{
    html+='<table><tr><th>담당</th><th>카테고리</th><th>건수</th><th>심각도</th><th>조치</th></tr>';
    for(let a of actions){
      let sevCls=a.severity==='critical'?'style="color:var(--fail);font-weight:bold"':a.severity==='high'?'style="color:var(--fail)"':'';
      html+=`<tr><td><strong>${esc(a.who)}</strong></td><td>${esc(a.category)}</td><td>${a.count}</td><td ${sevCls}>${esc(a.severity||'')}</td><td style="font-size:12px">${esc(a.action)}</td></tr>`;
    }
    html+='</table>';
  }
  html+='</div></div></div>';
  // Insert before phase-progress
  let pp=document.getElementById('phase-progress');
  pp.insertAdjacentHTML('beforebegin',html);
}

function renderPhaseBars(){
  const pipeline=DATA.pipeline||(DATA.progress||{})._pipeline||{};
  const phases=pipeline.phases||{};
  const progress=DATA.progress||{};
  // Core phases to display (in order)
  const displayPhases=[
    'phase_0','phase_1','phase_2','phase_2.5',
    'phase_3','phase_3.5','phase_4'
  ];
  const phaseLabels={
    'phase_0':'Step 0: Pre-flight','phase_1':'Step 1: Parse+Convert',
    'phase_2':'Step 1: LLM Convert','phase_2.5':'Step 2: TC Generate',
    'phase_3':'Step 3: Validate+Fix','phase_3.5':'Step 3: MyBatis Extract',
    'phase_4':'Step 4: Report'
  };
  // Merge aliases into phases (sub-phases count toward parent)
  const aliases={'phase_1.5':'phase_1','phase_2_rule':'phase_2','phase_2_llm':'phase_2',
    'phase_3_compare':'phase_3','phase_3_explain':'phase_3','phase_3_5':'phase_3.5',
    'phase_5_old':'phase_4','phase_6_old':'phase_3.5','phase_5':'phase_4','phase_6':'phase_4'};
  for(let [alias,target] of Object.entries(aliases)){
    if(phases[alias]&&phases[alias].status==='done'&&!phases[target]){
      phases[target]=phases[alias];
    }
  }

  let currentPhase=progress.currentPhase||0;
  let html='';

  if(Object.keys(phases).length>0){
    for(let pid of displayPhases){
      let pd=phases[pid]||{};
      let st=pd.status||'pending';
      if(st==='done'||st==='completed')st='done';
      let dur=pd.duration_ms?fmtMs(pd.duration_ms):'';
      let cls=st==='done'?'done':st==='running'?'running':'pending';
      let badge=st==='done'?'<span class="phase-badge badge-done">DONE</span>':
                st==='running'?'<span class="phase-badge badge-run">RUNNING</span>':
                '<span class="phase-badge badge-pending">PENDING</span>';
      let pct=st==='done'?100:st==='running'?50:0;
      html+=`<div class="phase-row"><span class="phase-name">${phaseLabels[pid]||pid}</span>`+
        `<div class="phase-bar"><div class="phase-fill ${cls}" style="width:${pct}%"></div></div>`+
        `<span class="phase-info">${dur} ${badge}</span></div>`;
    }
  }else{
    // Fallback: show all phases with pending status
    for(let pid of displayPhases){
      html+=`<div class="phase-row"><span class="phase-name">${phaseLabels[pid]||pid}</span>`+
        `<div class="phase-bar"><div class="phase-fill pending" style="width:0%"></div></div>`+
        `<span class="phase-info"><span class="phase-badge badge-pending">PENDING</span></span></div>`;
    }
  }
  document.getElementById('phase-bars').innerHTML=html;
}

function renderBars(containerId,obj,defaultColor){
  let sorted=Object.entries(obj).sort((a,b)=>b[1]-a[1]);
  if(sorted.length===0){document.getElementById(containerId).innerHTML='<div style="color:var(--dim);font-size:13px">No data yet</div>';return;}
  let max=sorted[0][1]||1;
  let html='';
  for(let [name,count] of sorted.slice(0,15)){
    let pct=Math.min(100,Math.round(count/max*100));
    html+=`<div class="bar-row"><span class="bar-lbl">${esc(name)}</span>`+
      `<div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${defaultColor}"></div></div>`+
      `<span class="bar-val">${count.toLocaleString()}</span></div>`;
  }
  document.getElementById(containerId).innerHTML=html;
}

function renderBarsOrdered(containerId,obj,order,colors){
  if(Object.keys(obj).length===0){document.getElementById(containerId).innerHTML='<div style="color:var(--dim);font-size:13px">No data yet</div>';return;}
  let max=Math.max(...Object.values(obj),1);
  let html='';
  for(let level of order){
    let cnt=obj[level]||0;
    let pct=Math.min(100,Math.round(cnt/max*100));
    let color=colors[level]||'var(--accent)';
    html+=`<div class="bar-row"><span class="bar-lbl">${level}</span>`+
      `<div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>`+
      `<span class="bar-val">${cnt}</span></div>`;
  }
  document.getElementById(containerId).innerHTML=html;
}

function renderValidationSec(){
  let html='';
  // Overview에는 최종 실패/미해결 건만 표시 (성공한 것은 안 보임)
  if(DATA.validation){
    let v=DATA.validation;
    let fail=v.fail||0;
    if(fail>0 && v.failures && v.failures.length){
      html+=`<div class="sec"><h2>미해결 EXPLAIN 실패 (${fail}건)</h2>`;
      html+=`<p style="font-size:11px;color:var(--dim)">최종적으로 해결되지 않은 실패 건. 힐링 완료된 건은 제외.</p>`;
      html+='<table style="margin-top:10px"><tr><th>쿼리</th><th>에러</th></tr>';
      for(let f of v.failures.slice(0,50)){
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(f.test||'')}</td><td style="color:var(--fail);font-size:11px">${esc(String(f.error||'').substring(0,250))}</td></tr>`;
      }
      if(v.failures.length>50)html+=`<tr><td colspan="2" style="color:var(--dim)">... +${v.failures.length-50}건 (전체: validated.json)</td></tr>`;
      html+='</table></div>';
    }
  }
  if(DATA.execution){
    let e=DATA.execution;
    let fail=e.fail||0;
    if(fail>0 && e.failures && e.failures.length){
      html+=`<div class="sec"><h2>미해결 실행 실패 (${fail}건)</h2>`;
      html+='<table style="margin-top:10px"><tr><th>쿼리</th><th>에러</th></tr>';
      for(let f of e.failures.slice(0,30)){
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(f.test||'')}</td><td style="color:var(--fail);font-size:11px">${esc(String(f.error||'').substring(0,150))}</td></tr>`;
      }
      html+='</table></div>';
    }
  }
  if(DATA.comparison){
    let c=DATA.comparison;
    let fail=c.fail||c.mismatched||0;
    // 불일치 건만 표시 (MATCH는 Overview에서 안 보임)
    let failResults=(c.results||[]).filter(r=>!r.match);
    if(failResults.length){
      html+=`<div class="sec"><h2>Oracle↔PG 불일치 (${failResults.length}건)</h2>`;
      html+='<table style="margin-top:10px"><tr><th>쿼리</th><th>Oracle</th><th>PG</th><th>사유</th></tr>';
      for(let r of failResults){
        let detail=r.reason||r.oracle_error||r.ora_error||r.pg_error||'';
        let oraR=r.oracle_rows!=null?r.oracle_rows:'?';
        let pgR=r.pg_rows!=null?r.pg_rows:'?';
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(r.query_id||'')}</td><td>${oraR}행</td><td>${pgR}행</td><td style="font-size:11px;color:var(--fail)">${esc(String(detail).substring(0,150))}</td></tr>`;
      }
      html+='</table>';
    }
    if(c.warnings&&c.warnings.length){
      html+='<h3 style="margin-top:12px;color:var(--dim)">Integrity Guard Warnings</h3>';
      html+='<table><tr><th>Code</th><th>Severity</th><th>Query</th><th>Message</th></tr>';
      for(let w of c.warnings){
        let sevCls=w.severity==='critical'?'fl':w.severity==='high'?'wn':'';
        html+=`<tr><td>${esc(w.code||'')}</td><td class="${sevCls}">${esc(w.severity||'')}</td><td>${esc(w.query_id||'')}</td><td>${esc(w.message||'')}</td></tr>`;
      }
      html+='</table>';
    }
    html+='</div>';
  }
  // Escalated queries from progress
  let pipeline=DATA.pipeline||(DATA.progress||{})._pipeline||{};
  let summary=pipeline.summary||{};
  if(summary.escalated>0){
    html+=`<div class="sec"><h2>Escalated Queries (Manual Review Required)</h2>`;
    html+=`<p><span class="phase-badge" style="background:rgba(239,68,68,.15);color:var(--fail)">${summary.escalated} queries escalated (max retries reached)</span></p>`;
    // List escalated files
    let files=DATA.progress?.files||DATA.files||{};
    let escList=[];
    for(let [fname,fdata] of Object.entries(files)){
      let esc_q=fdata.queries_escalated||0;
      if(esc_q>0)escList.push({file:fname,count:esc_q});
    }
    if(escList.length){
      html+='<table><tr><th>File</th><th>Escalated Queries</th></tr>';
      for(let e of escList)html+=`<tr><td style="font-family:var(--mono)">${esc(e.file)}</td><td>${e.count}</td></tr>`;
      html+='</table>';
    }
    html+='</div>';
  }
  // Query Matrix Summary
  if(DATA.query_matrix){
    let qm=DATA.query_matrix;
    let s=qm.summary||{};
    html+=`<div class="sec"><h2>Query Validation Matrix</h2>`;
    html+=`<p>Total: ${qm.total||0} queries</p>`;
    html+=`<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">`;
    for(let [k,v] of Object.entries(s)){
      let bg=k.startsWith('PASS_')?'rgba(34,197,94,.15)':k.includes('FAIL')?'rgba(239,68,68,.15)':'rgba(148,163,184,.1)';
      let col=k.startsWith('PASS_')?'var(--success)':k.includes('FAIL')?'var(--fail)':'var(--dim)';
      html+=`<span class="phase-badge" style="background:${bg};color:${col}">${k}: ${v}</span>`;
    }
    html+=`</div></div>`;
  }
  // EXPLAIN failures by category
  if(DATA.validation&&DATA.validation.failure_categories){
    let cats=DATA.validation.failure_categories;
    if(Object.keys(cats).length>0){
      html+=`<div class="sec"><h2>EXPLAIN Failure Categories</h2>`;
      html+=`<table><tr><th>Category</th><th>Count</th><th>Action</th></tr>`;
      let actions={'SYNTAX_ERROR':'Step 3 검증+수정 대상','MISSING_OBJECT':'DBA 스키마 이관 필요','TYPE_MISMATCH':'TC 바인드값 또는 타입 캐스트 수정','PERMISSION':'DB 권한 확인','OTHER':'수동 분석 필요'};
      for(let [k,v] of Object.entries(cats).sort((a,b)=>b[1]-a[1])){
        html+=`<tr><td>${esc(k)}</td><td>${v}</td><td style="font-size:11px;color:var(--dim)">${esc(actions[k]||'')}</td></tr>`;
      }
      html+=`</table></div>`;
    }
  }
  document.getElementById('validation-sec').innerHTML=html;
}

function renderExtractionSec(){
  if(!DATA.extracted||DATA.extracted.length===0){document.getElementById('extraction-sec').innerHTML='';return;}
  let html='<div class="sec"><h2>MyBatis Extraction</h2>';
  html+='<table><tr><th>File</th><th>Queries</th><th>Variants</th><th>Multi-Branch</th><th>DTO Replacements</th></tr>';
  for(let e of DATA.extracted){
    let dto=(e.dto_replacements||[]).slice(0,3).join(', ');
    if((e.dto_replacements||[]).length>3)dto+=' +'+(e.dto_replacements.length-3)+' more';
    html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(e.source||e.file)}</td><td>${e.total_queries}</td><td>${e.total_variants}</td><td>${e.multi_branch}</td><td style="font-size:11px;color:var(--dim)">${esc(dto)}</td></tr>`;
  }
  html+='</table></div>';
  document.getElementById('extraction-sec').innerHTML=html;
}

// ========== Render Files Tab ==========
let fileFilter='all'; // 'all', 'fail', 'escalated', 'pass'
function setFileFilter(f,el){fileFilter=f;renderFiles();document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));if(el)el.classList.add('active');}
function renderFiles(){
  let files=DATA.files||{};
  let names=Object.keys(files).sort();
  if(names.length===0){document.getElementById('file-list').innerHTML='<div style="color:var(--dim)">No files found</div>';return;}
  // Filter buttons
  let html='<div style="margin-bottom:12px;display:flex;gap:6px">';
  html+=`<button class="filter-btn phase-badge ${fileFilter==='all'?'active':''}" onclick="setFileFilter('all',this)" style="cursor:pointer">All (${names.length})</button>`;
  let failNames=names.filter(n=>(files[n].fail_count||0)>0);
  html+=`<button class="filter-btn phase-badge ${fileFilter==='fail'?'active':''}" onclick="setFileFilter('fail',this)" style="cursor:pointer;background:rgba(239,68,68,.15);color:var(--fail)">Fail (${failNames.length})</button>`;
  let passNames=names.filter(n=>(files[n].fail_count||0)===0&&(files[n].pass_count||0)>0);
  html+=`<button class="filter-btn phase-badge ${fileFilter==='pass'?'active':''}" onclick="setFileFilter('pass',this)" style="cursor:pointer;background:rgba(34,197,94,.15);color:var(--success)">Pass (${passNames.length})</button>`;
  html+=`</div>`;
  // Apply filter
  if(fileFilter==='fail')names=failNames;
  else if(fileFilter==='pass')names=passNames;
  for(let name of names){
    let f=files[name];
    let queries=f.queries||[];
    let total=f.total_queries||queries.length;
    let pass=f.pass_count||0;
    let fail=f.fail_count||0;
    let cmpPass=f.compare_pass||0;
    let cmpFail=f.compare_fail||0;
    let status=f.status||'unknown';

    let cmpBg=cmpFail>0?'background:rgba(239,68,68,.15);color:var(--fail)':cmpPass>0?'background:rgba(34,197,94,.15);color:var(--success)':'background:rgba(148,163,184,.1);color:var(--dim)';
    let passBg=pass>0?'background:rgba(34,197,94,.15);color:var(--success)':'background:rgba(148,163,184,.1);color:var(--dim)';
    let failBg=fail>0?'background:rgba(239,68,68,.15);color:var(--fail)':'background:rgba(148,163,184,.1);color:var(--dim)';

    html+=`<div class="file-item" id="file-${esc(name.replace(/[^a-zA-Z0-9]/g,'_'))}">`;
    html+=`<div class="file-hdr" onclick="toggleItem(this.parentElement)">`;
    html+=`<span class="file-arrow">&#9654;</span>`;
    html+=`<span class="file-name">${esc(name)}</span>`;
    html+=`<div class="file-stats">`;
    html+=`<span style="background:rgba(255,255,255,.05);color:var(--dim)">${total} queries</span>`;
    if(cmpPass+cmpFail>0){html+=`<span style="${cmpBg}">${cmpPass}/${cmpPass+cmpFail} match</span>`;}
    else{html+=`<span style="${passBg}">${pass} converted</span>`;}
    if(cmpFail>0){html+=`<span style="${failBg}">${cmpFail} mismatch</span>`;}
    else if(fail>0){html+=`<span style="${failBg}">${fail} fail</span>`;};
    html+=`</div></div>`;
    html+=`<div class="file-body">`;

    // File meta
    html+=`<div style="display:flex;gap:16px;margin-bottom:8px;font-size:11px;color:var(--dim)">`;
    html+=`<span>Input: ${f.input_lines} lines (${fmtSize(f.input_size)})</span>`;
    html+=`<span>Output: ${f.output_lines} lines (${fmtSize(f.output_size)})</span>`;
    let patterns=Object.entries(f.oracle_patterns||{}).sort((a,b)=>b[1]-a[1]).slice(0,5).map(([k,v])=>k+':'+v).join(', ');
    if(patterns)html+=`<span>Patterns: ${esc(patterns)}</span>`;
    html+=`</div>`;

    // Query list
    for(let q of queries){
      let qid=q.query_id||q.id||'';
      // 14-state (final_state from query-matrix) > internal status fallback
      let qStatus=q.final_state||q.overall_status||q.status||'pending';
      let comp=q.complexity||'-';
      let method=q.conversion_method||q.method||'rule';
      let oraclePatterns=q.oracle_patterns||[];
      let oracleSQL=q.oracle_sql||q.sql_before||q.sql_raw||'';
      let pgSQL=q.pg_sql||q.sql_after||'';
      let xmlBefore=q.xml_before||'';
      let xmlAfter=q.xml_after||'';
      let rules=q.rules_applied||[];
      let explain=q.explain||null;
      let execution=q.execution||null;
      let testCases=q.test_cases||[];
      let timing=q.timing||{};
      let history=q.history||[];

      // Status badge color — 14-state 기반
      let stColor='var(--dim)';
      if(qStatus.startsWith('PASS_'))stColor='var(--success)';
      else if(qStatus==='FAIL_SCHEMA_MISSING'||qStatus==='FAIL_COLUMN_MISSING'||qStatus==='FAIL_FUNCTION_MISSING')stColor='var(--warn)';
      else if(qStatus.startsWith('FAIL_'))stColor='var(--fail)';
      else if(qStatus.startsWith('NOT_TESTED'))stColor='var(--dim)';
      // legacy fallback
      else if(['success','converted','pass'].includes(qStatus))stColor='var(--success)';
      else if(['failed','fail','escalated'].includes(qStatus))stColor='var(--fail)';

      let methodColor=method==='llm'?'var(--purple)':method==='no_change'?'var(--dim)':'var(--success)';
      if(method==='no_change')method='no change';
      if(method==='none')method='no change';

      html+=`<div class="q-item"><div class="q-hdr" onclick="toggleItem(this.parentElement)">`;
      html+=`<span class="q-arrow">&#9654;</span>`;
      html+=`${statusIcon(qStatus)} `;
      html+=`<span class="q-id">${esc(qid)}</span>`;
      html+=`<span class="q-badge" style="background:rgba(148,163,184,.1);color:var(--dim)">${esc(comp)}</span>`;
      html+=`<span class="q-badge" style="background:rgba(168,85,247,.1);color:${methodColor}">${esc(method)}</span>`;
      html+=`<span class="q-badge" style="color:${stColor}">${statusLabel(qStatus)}</span>`;
      html+=`</div>`;

      // Query body (hidden by default)
      html+=`<div class="q-body">`;

      // MyBatis XML blocks (변환 전후 XML 태그 포함)
      if(xmlBefore||xmlAfter){
        html+=`<div class="sql-container">`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">Oracle MyBatis XML</div><pre>${esc(xmlBefore)}</pre></div>`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">PostgreSQL MyBatis XML</div><pre>${esc(xmlAfter)}</pre></div>`;
        html+=`</div>`;
      }

      // Rendered SQL blocks (MyBatis 렌더링 후 실제 실행 SQL)
      if(oracleSQL||pgSQL){
        html+=`<div class="sql-container">`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">Oracle SQL (렌더링)</div><pre>${highlightSQL(oracleSQL)}</pre></div>`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">PostgreSQL SQL (렌더링)</div><pre>${highlightSQL(pgSQL)}</pre></div>`;
        html+=`</div>`;
      }

      // Patterns
      if(oraclePatterns.length>0){
        html+=`<div class="q-detail"><span class="dlbl">Patterns:</span><span class="dval">`;
        for(let p of oraclePatterns)html+=`<span class="tag tag-pattern">${esc(p)}</span>`;
        html+=`</span></div>`;
      }

      // Rules
      if(rules.length>0){
        html+=`<div class="q-detail"><span class="dlbl">Rules:</span><span class="dval">`;
        for(let r of rules)html+=`<span class="tag tag-rule">${esc(r)}</span>`;
        html+=`</span></div>`;
      }

      // Notes
      if(q.notes){
        html+=`<div class="q-detail"><span class="dlbl">Notes:</span><span class="dval" style="color:var(--dim)">${esc(q.notes)}</span></div>`;
      }

      // EXPLAIN
      if(explain){
        let exIcon=explain.status==='pass'?'<span style="color:var(--success)">&#10003;</span>':'<span style="color:var(--fail)">&#10007;</span>';
        html+=`<div class="q-detail"><span class="dlbl">EXPLAIN:</span><span class="dval">${exIcon} ${esc(explain.status||'')}`;
        if(explain.plan_summary)html+=` (${esc(explain.plan_summary)})`;
        if(explain.duration_ms)html+=` ${fmtMs(explain.duration_ms)}`;
        if(explain.error)html+=` <span style="color:var(--fail)">${esc(String(explain.error).substring(0,120))}</span>`;
        html+=`</span></div>`;
      }

      // Execution
      if(execution){
        let exIcon=execution.status==='pass'||execution.status==='success'?'<span style="color:var(--success)">&#10003;</span>':'<span style="color:var(--fail)">&#10007;</span>';
        html+=`<div class="q-detail"><span class="dlbl">Execution:</span><span class="dval">${exIcon} ${esc(execution.status||'')}`;
        if(execution.row_count!=null)html+=` ${execution.row_count} rows`;
        if(execution.duration_ms)html+=` ${fmtMs(execution.duration_ms)}`;
        if(execution.error)html+=` <span style="color:var(--fail)">${esc(String(execution.error).substring(0,120))}</span>`;
        html+=`</span></div>`;
      }

      // Test cases
      if(testCases.length>0){
        html+=`<div class="q-detail"><span class="dlbl">Test Cases:</span><div class="dval">`;
        for(let tc of testCases){
          let matchIcon=tc.match===true?'<span style="color:var(--success)">&#10003;</span>':
                        tc.match===false?'<span style="color:var(--fail)">&#10007;</span>':
                        '<span style="color:var(--dim)">-</span>';
          let warn=tc.warnings?` <span style="color:var(--warn)">${esc(tc.warnings)}</span>`:'';
          html+=`<div style="margin-bottom:2px">${matchIcon} ${esc(tc.case_id||'')}`;
          if(tc.oracle_result!=null)html+=`: Oracle ${tc.oracle_result}`;
          if(tc.pg_result!=null)html+=` / PG ${tc.pg_result}`;
          html+=`${warn}</div>`;
        }
        html+=`</div></div>`;
      }

      // Compare results per query
      let compResults=q.compare_results||[];
      if(compResults.length>0){
        html+=`<div class="q-detail"><span class="dlbl">Compare:</span><div class="dval">`;
        for(let cr of compResults){
          let icon=cr.match?'<span style="color:var(--success)">&#10003; MATCH</span>':'<span style="color:var(--fail)">&#10007; DIFF</span>';
          let oraR=cr.oracle_rows!=null?cr.oracle_rows:(cr.ora_rows!=null?cr.ora_rows:'?');
          let pgR=cr.pg_rows!=null?cr.pg_rows:'?';
          let errDetail=cr.reason||cr.pg_error||cr.ora_error||cr.oracle_error||'';
          html+=`<div style="margin-bottom:3px">${icon} ${esc(cr.case||'')} Oracle:${oraR} PG:${pgR}`;
          if(errDetail){
            let errStr=String(errDetail).substring(0,150);
            // Categorize and recommend
            if(/schema.*does not exist|pkg_crypto/i.test(errStr)){
              html+=` <span style="color:var(--fail)">[Missing Package]</span> <span style="color:var(--warn);font-size:10px">ACTION: pgcrypto 확장 또는 커스텀 함수 생성 필요</span>`;
            }else if(/relation.*does not exist/i.test(errStr)){
              html+=` <span style="color:var(--fail)">[Missing Table]</span> <span style="color:var(--warn);font-size:10px">ACTION: 테이블 존재 여부 확인, 권한 점검</span>`;
            }else if(/DPY-|bind|parameter/i.test(errStr)){
              html+=` <span style="color:var(--fail)">[Bind Error]</span> <span style="color:var(--warn);font-size:10px">ACTION: 바인드 파라미터 타입 확인 (dict→list 변환 등)</span>`;
            }else{
              html+=` <span style="color:var(--fail)">${esc(errStr)}</span>`;
            }
          }
          html+=`</div>`;
        }
        html+=`</div></div>`;
      }

      // Timing
      let timingKeys=Object.keys(timing).filter(k=>k.endsWith('_ms'));
      if(timingKeys.length>0){
        html+=`<div class="q-detail"><span class="dlbl">Timing:</span><span class="dval">`;
        html+=timingKeys.map(k=>k.replace('_ms','')+': '+fmtMs(timing[k])).join(', ');
        html+=`</span></div>`;
      }

      // History
      if(history.length>0){
        html+=`<div class="q-detail"><span class="dlbl">History:</span><div class="dval">`;
        for(let h of history){
          let dotColor=h.status==='converted'?'var(--success)':h.status==='failed'?'var(--fail)':'var(--dim)';
          html+=`<div class="hist-item"><span class="hist-dot" style="background:${dotColor}"></span>`;
          html+=`v${h.version||'?'} ${esc(h.status||'')}`;
          if(h.agent)html+=` (${esc(h.agent)})`;
          if(h.error)html+=` <span style="color:var(--fail)">${esc(String(h.error).substring(0,80))}</span>`;
          if(h.timestamp)html+=` <span style="color:var(--dim)">${esc(String(h.timestamp).substring(11,19))}</span>`;
          html+=`</div>`;
        }
        html+=`</div></div>`;
      }

      html+=`</div></div>`; // /q-body /q-item
    }

    html+=`</div></div>`; // /file-body /file-item
  }
  document.getElementById('file-list').innerHTML=html;
}

// ========== Render Timeline Tab ==========
function renderTimeline(){
  let log=DATA.activity_log||[];
  if(log.length===0){document.getElementById('timeline-list').innerHTML='<div style="color:var(--dim)">No activity log found</div>';return;}
  let html='';
  for(let entry of log){
    let ts=entry.ts||entry.timestamp||'';
    if(typeof ts==='number') ts=new Date(ts*1000).toLocaleString();
    else if(typeof ts==='string'&&ts.includes('T')) ts=ts.replace('T',' ').substring(0,19);
    let evt=entry.event||entry.action||entry.type||'';
    let msg=entry.message||entry.detail||entry.msg||'';
    if(typeof msg==='object')msg=JSON.stringify(msg).substring(0,150);
    let evtColor='var(--dim)';
    let evtLower=evt.toLowerCase();
    if(evtLower.includes('start'))evtColor='var(--accent2)';
    else if(evtLower.includes('end')||evtLower.includes('done'))evtColor='var(--success)';
    else if(evtLower.includes('error')||evtLower.includes('fail'))evtColor='var(--fail)';
    else if(evtLower.includes('warn'))evtColor='var(--warn)';
    html+=`<div class="tl-item"><span class="tl-time">${esc(String(ts))}</span>`;
    html+=`<span class="tl-type" style="color:${evtColor}">${esc(evt)}</span>`;
    html+=`<span class="tl-msg">${esc(String(msg).substring(0,200))}</span></div>`;
  }
  document.getElementById('timeline-list').innerHTML=html;
}

// ========== Render DBA Tab ==========
function renderDBA(){
  let qm=DATA.query_matrix||{};
  let dbaObjects=qm.dba_objects||[];
  let zeroData=qm.dba_zero_rows||{};
  let bothZero=zeroData.both_zero||[];
  let oraZero=zeroData.oracle_only_zero||[];
  let pgZero=zeroData.pg_only_zero||[];
  let html='';

  // 1. Missing Objects (테이블/컬럼/함수)
  html+='<h2>Missing Objects — DBA 조치 필요</h2>';
  if(dbaObjects.length===0){
    html+='<p style="color:var(--dim)">누락 오브젝트 없음</p>';
  } else {
    html+='<table style="width:100%;border-collapse:collapse;font-size:12px">';
    html+='<tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:6px">Type</th><th style="text-align:left;padding:6px">Name</th><th style="text-align:left;padding:6px">Action</th><th style="text-align:left;padding:6px">Affected Queries</th></tr>';
    for(let obj of dbaObjects){
      let typeColor=obj.type==='table'?'var(--fail)':obj.type==='column'?'var(--warn)':'var(--purple)';
      let qList=obj.affected_queries.map(q=>`<span style="font-family:var(--mono);font-size:10px">${esc(q.query_id)}</span>`).join(', ');
      html+=`<tr style="border-bottom:1px solid rgba(255,255,255,.05)">`;
      html+=`<td style="padding:6px"><span style="color:${typeColor};font-weight:700">${obj.type.toUpperCase()}</span></td>`;
      html+=`<td style="padding:6px;font-family:var(--mono)">${esc(obj.name)}</td>`;
      html+=`<td style="padding:6px;font-family:var(--mono);font-size:11px;color:var(--accent2)">${esc(obj.action)}</td>`;
      html+=`<td style="padding:6px">${obj.affected_queries.length}건 — ${qList}</td>`;
      html+=`</tr>`;
    }
    html+='</table>';

    // Summary by type
    let tables=dbaObjects.filter(o=>o.type==='table');
    let columns=dbaObjects.filter(o=>o.type==='column');
    let functions=dbaObjects.filter(o=>o.type==='function');
    html+=`<div style="margin-top:12px;font-size:12px;color:var(--dim)">`;
    html+=`Total: ${dbaObjects.length} objects (`;
    if(tables.length) html+=`${tables.length} tables, `;
    if(columns.length) html+=`${columns.length} columns, `;
    if(functions.length) html+=`${functions.length} functions`;
    html+=`)</div>`;
  }

  // 2. 0건 쿼리 (3가지 분류)
  function renderZeroSection(title, color, desc, items){
    html+=`<h2 style="margin-top:24px;color:${color}">${title}</h2>`;
    if(!items||items.length===0){
      html+='<p style="color:var(--dim)">해당 없음</p>';
      return;
    }
    html+=`<p style="font-size:12px;color:var(--dim)">${items.length}건 — ${desc}</p>`;
    html+='<table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:8px">';
    html+='<tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px">Query</th><th style="text-align:left;padding:4px">File</th><th style="text-align:right;padding:4px">Oracle</th><th style="text-align:right;padding:4px">PG</th></tr>';
    for(let q of items){
      html+=`<tr style="border-bottom:1px solid rgba(255,255,255,.03)">`;
      html+=`<td style="padding:4px;font-family:var(--mono)">${esc(q.query_id)}</td>`;
      html+=`<td style="padding:4px;font-size:10px;color:var(--dim)">${esc(q.file)}</td>`;
      html+=`<td style="padding:4px;text-align:right">${q.oracle_rows}</td>`;
      html+=`<td style="padding:4px;text-align:right">${q.pg_rows}</td>`;
      html+=`</tr>`;
    }
    html+='</table>';
  }

  renderZeroSection('양쪽 모두 0건','var(--warn)','TC 바인드값 또는 데이터 확인 필요',bothZero);
  renderZeroSection('Oracle만 0건 (PG에는 데이터 있음)','var(--orange)','Oracle 데이터 누락 또는 TC 바인드 불일치',oraZero);
  renderZeroSection('PG만 0건 (Oracle에는 데이터 있음)','var(--fail)','변환 오류 가능성 — SQL 검토 필요',pgZero);

  document.getElementById('dba-content').innerHTML=html;
}

// ========== Render Log Tab ==========
function renderLog(){
  let log=DATA.activity_log||[];
  if(log.length===0){document.getElementById('log-list').innerHTML='<div style="color:var(--dim)">No activity log found</div>';return;}
  let html='';
  for(let i=0;i<log.length;i++){
    let entry=log[i];
    let ts=entry.ts||entry.timestamp||'';
    if(typeof ts==='number') ts=new Date(ts*1000).toLocaleString();
    else if(typeof ts==='string'&&ts.includes('T')) ts=ts.replace('T',' ').substring(0,19);
    let evt=entry.event||entry.action||entry.type||'';
    let msg=entry.message||entry.detail||entry.msg||'';
    if(typeof msg==='object')msg=JSON.stringify(msg).substring(0,200);
    let evtLower=evt.toLowerCase();
    let evtClass='';
    if(evtLower.includes('error')||evtLower.includes('fail'))evtClass='error';
    else if(evtLower.includes('decision'))evtClass='decision';
    else if(evtLower.includes('warn'))evtClass='warning';
    html+=`<div class="log-entry" data-type="${evtClass}" data-text="${esc((evt+' '+msg).toLowerCase())}">`;
    html+=`<span class="log-ts">${esc(String(ts))}</span>`;
    html+=`<span class="log-evt ${evtClass}">${esc(evt)}</span>`;
    html+=`<span class="log-msg">${esc(String(msg).substring(0,300))}</span></div>`;
  }
  document.getElementById('log-list').innerHTML=html;

  // Filter buttons
  document.querySelectorAll('.log-filter-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.log-filter-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      filterLog();
    });
  });
  document.getElementById('log-search').addEventListener('input',filterLog);
}

function filterLog(){
  let activeFilter=document.querySelector('.log-filter-btn.active');
  let filter=activeFilter?activeFilter.dataset.filter:'all';
  let search=(document.getElementById('log-search').value||'').toLowerCase();
  document.querySelectorAll('#log-list .log-entry').forEach(el=>{
    let type=el.dataset.type||'';
    let text=el.dataset.text||'';
    let matchFilter=(filter==='all')||type===filter;
    let matchSearch=!search||text.includes(search);
    el.classList.toggle('hidden',!(matchFilter&&matchSearch));
  });
}

// ========== Auto-refresh ==========
let refreshInterval=null;
document.getElementById('refresh-toggle').addEventListener('click',function(){
  this.classList.toggle('on');
  if(this.classList.contains('on')){
    refreshInterval=setInterval(()=>{
      // In a real scenario this would refetch progress.json
      // Since the HTML is static, this is a placeholder
      console.log('Auto-refresh tick (static report - no-op)');
    },5000);
  }else{
    clearInterval(refreshInterval);
    refreshInterval=null;
  }
});

// ========== Init (try-catch per section so one failure doesn't block others) ==========
try{renderOverview();}catch(e){console.error('renderOverview:',e);}
try{renderFiles();}catch(e){console.error('renderFiles:',e);}
try{renderTimeline();}catch(e){console.error('renderTimeline:',e);}

// ========== Explorer 3-Panel Navigation ==========
var expSelectedFile=null, expSelectedQuery=null;
try{expRenderFiles();}catch(e){console.error('expRenderFiles:',e);}

function expRenderFiles(){
  let files=DATA.files||{};
  let search=((document.getElementById('exp-search')||{}).value||'').toLowerCase();
  let statusF=(document.getElementById('exp-status')||{}).value||'';
  let typeF=(document.getElementById('exp-type')||{}).value||'';
  let names=Object.keys(files).sort();
  let html='', total=0, shown=0;

  for(let name of names){
    let f=files[name];
    let queries=f.queries||[];
    total+=queries.length;
    // Filter queries
    let filtered=queries.filter(q=>{
      let qid=(q.query_id||q.id||'').toLowerCase();
      let fs=q.final_state||'';
      if(search && !name.toLowerCase().includes(search) && !qid.includes(search)
         && !(q.oracle_sql||'').toLowerCase().includes(search)) return false;
      if(statusF==='pass' && !fs.startsWith('PASS_')) return false;
      if(statusF==='fail' && !fs.startsWith('FAIL_')) return false;
      if(statusF==='not_tested' && !fs.startsWith('NOT_TESTED')) return false;
      if(typeF && (q.type||'')!==typeF) return false;
      return true;
    });
    if(filtered.length===0) continue;
    shown+=filtered.length;
    let passC=filtered.filter(q=>(q.final_state||'').startsWith('PASS_')).length;
    let failC=filtered.filter(q=>(q.final_state||'').startsWith('FAIL_')).length;
    let sel=expSelectedFile===name?'background:rgba(99,102,241,.2);':'';
    let bar=failC>0?`<span style="color:var(--fail)">${failC}F</span> `:'';
    bar+=passC>0?`<span style="color:var(--success)">${passC}P</span>`:'';
    html+=`<div onclick="expSelectFile('${esc(name)}')" style="padding:6px 8px;cursor:pointer;border-radius:4px;margin-bottom:2px;font-size:12px;${sel}border-left:3px solid ${failC>0?'var(--fail)':passC>0?'var(--success)':'var(--dim)'}">`;
    html+=`<div style="font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(name.replace('.xml',''))}</div>`;
    html+=`<div style="color:var(--dim)">${filtered.length}q ${bar}</div>`;
    html+=`</div>`;
  }
  document.getElementById('exp-panel-files').innerHTML=html||'<p style="color:var(--dim)">없음</p>';
  document.getElementById('exp-count').textContent=`${shown}/${total}`;
  if(!expSelectedFile && names.length) expSelectFile(names[0]);
}

function expSelectFile(name){
  expSelectedFile=name;
  expSelectedQuery=null;
  expRenderFiles();  // re-highlight
  let f=(DATA.files||{})[name];
  if(!f){document.getElementById('exp-panel-queries').innerHTML='';return;}
  let queries=f.queries||[];
  let html='';
  for(let q of queries){
    let qid=q.query_id||q.id||'';
    let fs=q.final_state||'';
    let icon=fs.startsWith('PASS_')?'<span style="color:var(--success)">&#10003;</span>':fs.startsWith('FAIL_')?'<span style="color:var(--fail)">&#10007;</span>':'<span style="color:var(--dim)">&#9679;</span>';
    let method=q.conversion_method||q.method||'';
    let sel=expSelectedQuery===qid?'background:rgba(99,102,241,.2);':'';
    html+=`<div onclick="expSelectQuery('${esc(name)}','${esc(qid)}')" style="padding:5px 8px;cursor:pointer;border-radius:4px;margin-bottom:1px;font-size:12px;${sel}">`;
    html+=`${icon} <strong>${esc(qid)}</strong> <span style="color:var(--dim)">${esc((q.type||'').toUpperCase())} ${esc(method)}</span>`;
    html+=`</div>`;
  }
  document.getElementById('exp-panel-queries').innerHTML=html;
  if(queries.length) expSelectQuery(name, queries[0].query_id||queries[0].id||'');
}

function expSelectQuery(fname, qid){
  expSelectedQuery=qid;
  // Re-highlight query list
  let items=document.getElementById('exp-panel-queries').children;
  for(let it of items) it.style.background=it.querySelector('strong')?.textContent===qid?'rgba(99,102,241,.2)':'';

  let f=(DATA.files||{})[fname];
  if(!f) return;
  let q=(f.queries||[]).find(x=>(x.query_id||x.id)===qid);
  if(!q){document.getElementById('exp-panel-detail').innerHTML='';return;}

  let html='';

  // Find this query's overall_status from query_matrix
  let qmQueries=(DATA.query_matrix||{}).queries||[];
  let qmEntry=qmQueries.find(x=>x.query_id===qid)||{};
  let finalStatus=qmEntry.final_state||q.final_state||'NOT_TESTED_PENDING';
  let finalDetail=qmEntry.final_state_detail||q.final_state_detail||'';
  let stColor=finalStatus.startsWith('PASS_')?'var(--success)':finalStatus.startsWith('FAIL_')?'var(--fail)':'var(--dim)';

  // Header with status badge
  html+=`<h3 style="margin:0 0 4px">${esc(qid)} <span style="color:var(--dim);font-weight:normal">${esc((q.type||'').toUpperCase())} / ${esc(q.conversion_method||q.method||'')}</span></h3>`;
  html+=`<div style="padding:6px 10px;background:rgba(255,255,255,.03);border-radius:6px;margin-bottom:8px;border-left:3px solid ${stColor}">`;
  html+=`<strong style="color:${stColor}">${esc(finalStatus)}</strong>`;
  if(finalDetail)html+=`<div style="font-size:11px;color:var(--dim);margin-top:2px">${esc(finalDetail)}</div>`;
  html+=`</div>`;

  // SQL side-by-side
  let oraSQL=q.oracle_sql||'';
  let pgSQL=q.pg_sql||'';
  if(oraSQL||pgSQL){
    html+=`<div style="display:flex;gap:4px;margin-bottom:8px">`;
    html+=`<div style="flex:1;background:rgba(0,0,0,.2);padding:6px;border-radius:4px;overflow:auto;max-height:200px"><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Oracle</div><pre style="font-size:11px;margin:0;white-space:pre-wrap">${esc(oraSQL)}</pre></div>`;
    html+=`<div style="flex:1;background:rgba(0,0,0,.2);padding:6px;border-radius:4px;overflow:auto;max-height:200px"><div style="font-size:10px;color:var(--dim);margin-bottom:4px">PostgreSQL</div><pre style="font-size:11px;margin:0;white-space:pre-wrap">${esc(pgSQL)}</pre></div>`;
    html+=`</div>`;
  }

  // EXPLAIN
  let explain=q.explain||{};
  if(explain.status){
    let col=explain.status==='pass'?'var(--success)':'var(--fail)';
    html+=`<div style="padding:6px 8px;background:rgba(255,255,255,.03);border-radius:4px;margin-bottom:6px;border-left:3px solid ${col}">`;
    html+=`<strong>EXPLAIN:</strong> <span style="color:${col}">${esc(explain.status)}</span>`;
    if(explain.error)html+=`<div style="color:var(--fail);font-size:11px;margin-top:4px">${esc(String(explain.error))}</div>`;
    html+=`</div>`;
  }

  // Conversion History (LLM 변환 이력)
  let convHistory=q.conversion_history||qmEntry.conversion_history||[];
  if(convHistory.length){
    html+=`<div style="margin:8px 0"><strong>변환 이력 (${convHistory.length})</strong></div>`;
    html+=`<table style="font-size:11px"><tr><th>패턴</th><th>접근법</th><th>신뢰도</th><th>비고</th></tr>`;
    for(let ch of convHistory){
      let confCol=ch.confidence==='high'?'var(--success)':ch.confidence==='medium'?'var(--warn)':'var(--fail)';
      html+=`<tr><td><code>${esc(ch.pattern||'-')}</code></td>`;
      html+=`<td style="font-size:10px">${esc(String(ch.approach||'-').substring(0,120))}</td>`;
      html+=`<td style="color:${confCol}">${esc(ch.confidence||'-')}</td>`;
      html+=`<td style="font-size:10px;color:var(--dim)">${esc(String(ch.notes||'').substring(0,100))}</td></tr>`;
    }
    html+=`</table>`;
  }

  // TC별 결과 (바인드값 + Oracle + PG + MATCH)
  let compResults=q.compare_results||qmEntry.compare_detail||[];
  let tcs=q.test_cases||qmEntry.test_cases||[];
  let allTCs=[...compResults,...tcs]; // merge both sources
  if(compResults.length||tcs.length){
    html+=`<div style="margin:8px 0"><strong>TC 결과:</strong></div>`;
    html+=`<table style="font-size:11px"><tr><th>TC</th><th>바인드 변수</th><th>Oracle</th><th>PG</th><th>결과</th><th>사유</th></tr>`;

    // Compare results first (have Oracle/PG row counts)
    for(let cr of compResults){
      let icon=cr.match?'<span style="color:var(--success)">MATCH</span>':'<span style="color:var(--fail)">DIFF</span>';
      let oraR=cr.oracle_rows!=null?cr.oracle_rows+'행':'?';
      let pgR=cr.pg_rows!=null?cr.pg_rows+'행':'?';
      let reason=cr.reason||cr.warning||'';
      let binds=cr.binds?JSON.stringify(cr.binds).substring(0,60):'';
      html+=`<tr><td>${esc(cr.case||cr.test_id||'')}</td><td style="font-family:var(--mono)">${esc(binds)}</td>`;
      html+=`<td>${oraR}</td><td>${pgR}</td><td>${icon}</td>`;
      html+=`<td style="color:var(--dim)">${esc(String(reason).substring(0,100))}</td></tr>`;
    }

    // Test cases that don't have compare results (just bind values)
    let compQids=new Set(compResults.map(c=>c.case||c.test_id));
    for(let tc of tcs){
      let tcName=tc.case_id||tc.name||'';
      if(compQids.has(tcName))continue; // already shown above
      let binds=tc.binds||tc.params||{};
      let bindStr=Object.entries(binds).map(([k,v])=>k+'='+v).join(', ').substring(0,60);
      html+=`<tr><td>${esc(tcName)}</td><td style="font-family:var(--mono)">${esc(bindStr)}</td>`;
      html+=`<td>-</td><td>-</td><td style="color:var(--dim)">미실행</td><td></td></tr>`;
    }
    html+=`</table>`;
  }

  // Attempt History (from query-tracking.json attempts array)
  let attempts=q.attempts||[];
  if(attempts.length){
    html+=`<div style="margin-top:8px"><strong>Attempt History (${attempts.length})</strong></div>`;
    html+=`<table style="font-size:11px;margin-top:4px"><tr><th>#</th><th>Time</th><th>Error Category</th><th>Error Detail</th><th>Fix Applied</th><th>Result</th></tr>`;
    for(let i=0;i<attempts.length;i++){
      let a=attempts[i];
      let resCol=(a.result||'')==='pass'?'var(--success)':(a.result||'')==='fail'?'var(--fail)':'var(--dim)';
      let ats=a.ts?new Date(a.ts*1000).toLocaleTimeString():(a.timestamp||'-');
      html+=`<tr><td>${i+1}</td><td style="color:var(--dim)">${esc(String(ats))}</td>`;
      html+=`<td>${esc(a.error_category||'-')}</td>`;
      html+=`<td style="font-size:10px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(a.error_detail||'')}">${esc(String(a.error_detail||'-').substring(0,80))}</td>`;
      html+=`<td style="font-size:10px">${esc(String(a.fix_applied||'-').substring(0,120))}</td>`;
      html+=`<td style="color:${resCol};font-weight:bold">${esc(a.result||'-')}</td></tr>`;
    }
    html+=`</table>`;
  }

  document.getElementById('exp-panel-detail').innerHTML=html;
}
try{renderDBA();}catch(e){console.error("renderDBA:",e);}
try{renderLog();}catch(e){console.error("renderLog:",e);}


</script>
</body>
</html>'''


def render_html(data):
    """Render the full HTML report by embedding data into the template."""
    embedded = build_embedded_data(data)
    # Slim down embedded data for HTML — full data is in query-matrix.json
    # Target: < 10 MB HTML.  Full SQL/XML lives in query-matrix.json file.
    TRUNCATE_LIMIT = 200
    TRUNCATE_SUFFIX = '\n-- ... (truncated, see query-matrix.json)'
    SQL_FIELDS = ('xml_before', 'xml_after', 'sql_before', 'sql_after',
                  'oracle_sql', 'pg_sql', 'sql_raw', 'original_sql', 'converted_sql')

    def _slim_test_cases(tcs):
        """Keep at most 2 TCs, each with only name and param count."""
        if not tcs or not isinstance(tcs, list):
            return tcs
        slimmed = []
        for tc in tcs[:2]:
            slim = {'name': tc.get('name', '')}
            params = tc.get('params')
            if params and isinstance(params, dict):
                slim['param_count'] = len(params)
            slimmed.append(slim)
        if len(tcs) > 2:
            slimmed.append({'name': f'... +{len(tcs) - 2} more'})
        return slimmed

    # 1) Slim down query_matrix queries — Explorer uses files section for SQL
    #    Keep only metadata + final_state in query_matrix (used by Overview/DBA tabs)
    qm = embedded.get('query_matrix')
    if qm and 'queries' in qm:
        for q in qm['queries']:
            for field in SQL_FIELDS:
                q.pop(field, None)
            q['test_cases'] = _slim_test_cases(q.get('test_cases'))
            ch = q.get('conversion_history')
            if ch and isinstance(ch, list):
                q['conversion_history'] = [{'pattern': c.get('pattern', ''), 'approach': c.get('approach', '')} for c in ch[:5]]

    # 2) Slim down per-file queries — keep SQL preview for Explorer detail view
    DROP_FIELDS = {'parameters', 'dynamic_elements', 'rules_applied', 'timing',
                   'layer', 'confidence', 'execution', 'test_cases', 'history'}
    for fname, fdata in embedded.get('files', {}).items():
        for q in fdata.get('queries', []):
            for field in SQL_FIELDS:
                val = q.get(field, '')
                if val and len(str(val)) > 300:
                    q[field] = str(val)[:300] + TRUNCATE_SUFFIX
            for field in DROP_FIELDS:
                q.pop(field, None)
            att = q.get('attempts', [])
            if att and isinstance(att, list) and len(att) > 3:
                q['attempts'] = att[:3]

    # 3) Slim down extracted variants
    extracted = embedded.get('extracted')
    if extracted and isinstance(extracted, dict):
        eq = extracted.get('queries')
        if isinstance(eq, dict):
            for variants in eq.values():
                if isinstance(variants, list):
                    for v in variants:
                        for field in ('sql', 'rendered_sql', 'original_sql'):
                            val = v.get(field, '')
                            if val and len(val) > TRUNCATE_LIMIT:
                                v[field] = val[:TRUNCATE_LIMIT] + TRUNCATE_SUFFIX

    # 4) Slim down validation/execution detail errors
    for section_key in ('validation', 'execution'):
        section = embedded.get(section_key)
        if section and isinstance(section, dict):
            results = section.get('results', [])
            if isinstance(results, list):
                for r in results:
                    for field in ('sql', 'query', 'error'):
                        val = r.get(field, '')
                        if isinstance(val, str) and len(val) > TRUNCATE_LIMIT:
                            r[field] = val[:TRUNCATE_LIMIT] + TRUNCATE_SUFFIX
    json_blob = json.dumps(embedded, ensure_ascii=False, separators=(',', ':'))
    return HTML_TEMPLATE.replace('__DATA_PLACEHOLDER__', json_blob)


def main():
    parser = argparse.ArgumentParser(description='Generate self-contained HTML migration report')
    parser.add_argument('--output', default='workspace/reports/migration-report.html',
                        help='Output HTML path')
    parser.add_argument('--base-dir', default='.', help='Project base directory')
    args = parser.parse_args()

    print("Collecting data...")
    data = collect_data(args.base_dir)

    print("Rendering HTML...")
    html = render_html(data)

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)

    s = data['summary']
    print(f"\nReport generated: {args.output}")
    print(f"  Files: {s['total_input_files']} input, {s['total_output_files']} output")
    print(f"  Queries: {s['total_input_queries']} input, {s['total_output_queries']} output")
    print(f"  Oracle patterns: {sum(s['oracle_patterns'].values()):,} ({len(s['oracle_patterns'])} types)")
    if s.get('validation_total'):
        print(f"  EXPLAIN: {s['validation_pass']}/{s['validation_total']} passed")
    if s.get('execution_total'):
        print(f"  Execution: {s['execution_pass']}/{s['execution_total']} passed")
    if s.get('compare_total'):
        print(f"  Compare: {s['compare_match']}/{s['compare_total']} matched, {s['compare_fail']} mismatch, {s.get('compare_warn', 0)} warn")
    if s.get('extracted_queries'):
        print(f"  MyBatis: {s['extracted_queries']} queries, {s['extracted_variants']} variants")

    fsize = os.path.getsize(args.output)
    print(f"  File size: {fsize:,} bytes")


if __name__ == '__main__':
    main()
