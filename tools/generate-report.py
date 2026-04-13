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
    workspace/results/_extracted/*-extracted.json   Phase 3.5 MyBatis extraction
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

    # Phase 3.5: extracted
    ext_dir = ws / 'results' / '_extracted'
    if ext_dir.exists() and list(ext_dir.glob('*-extracted.json')):
        progress['_pipeline']['phases']['phase_3.5'] = {'status': 'done'}

    # Phase 3.5 validation (separate dir)
    for d35 in ['_validation_phase35', '_validation_phase7']:
        if (ws / 'results' / d35 / 'validated.json').exists():
            progress['_pipeline']['phases']['phase_3.5'] = {'status': 'done'}

    # Phase 4: healing
    if (ws / 'results' / '_healing' / 'tickets.json').exists():
        progress['_pipeline']['phases']['phase_4'] = {'status': 'done'}

    # Phase 5: learning (edge-cases updated)
    for rules_dir in [ws.parent / '.claude' / 'rules', ws.parent / '.kiro' / 'steering']:
        ec = rules_dir / 'edge-cases.md'
        if ec.exists():
            progress['_pipeline']['phases']['phase_5'] = {'status': 'done'}
            break

    # Phase 6: DBA review
    if (ws / 'results' / '_dba_review' / 'review-result.json').exists():
        progress['_pipeline']['phases']['phase_6'] = {'status': 'done'}

    # Phase 7: report — 이 함수가 실행 중이면 Phase 7이 진행 중이므로 항상 done
    # (migration-report.html은 이 함수가 만드는 것이라 아직 없을 수 있음)
    progress['_pipeline']['phases']['phase_7'] = {'status': 'done'}

    return progress


def collect_data(base_dir):
    """Collect all available data from the workspace."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'progress': None,
        'files': {},
        'tracking': {},
        'validation': None,
        'execution': None,
        'comparison': None,
        'validation_phase7': None,
        'comparison_phase7': None,
        'dba_review': None,
        'healing': None,
        'query_matrix': None,
        'extracted': [],
        'activity_log': [],
        'input_files': [],
        'output_files': [],
        'summary': {},
    }

    ws = Path(base_dir) / 'workspace'

    # 1. Progress
    data['progress'] = load_json(ws / 'progress.json')
    # If progress.json doesn't exist or has incomplete phases, supplement from result files
    if data['progress'] is None:
        data['progress'] = _derive_progress(ws)
    else:
        # Merge derived phases into existing progress (fill gaps)
        derived = _derive_progress(ws)
        existing_phases = data['progress'].setdefault('_pipeline', {}).setdefault('phases', {})
        for pid, pdata in derived.get('_pipeline', {}).get('phases', {}).items():
            if pid not in existing_phases:
                existing_phases[pid] = pdata
        # Fix current_phase_name if missing
        if not data['progress'].get('_pipeline', {}).get('current_phase_name'):
            data['progress']['_pipeline']['current_phase_name'] = derived.get('_pipeline', {}).get('current_phase_name', '')
        # Supplement file data (oraclePatterns, queries_total) if missing
        derived_files = derived.get('files', {})
        existing_files = data['progress'].setdefault('files', {})
        for fname, fdata in derived_files.items():
            if fname not in existing_files:
                existing_files[fname] = fdata
            else:
                # Fill missing fields
                for k, v in fdata.items():
                    if k not in existing_files[fname] or not existing_files[fname][k]:
                        existing_files[fname][k] = v

    # 2. Input/Output XML files
    for xml_file in sorted((ws / 'input').glob('*.xml')) if (ws / 'input').exists() else []:
        data['input_files'].append({
            'name': xml_file.name,
            'size_bytes': xml_file.stat().st_size,
            'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
            'queries': count_xml_queries(xml_file),
        })

    for xml_file in sorted((ws / 'output').glob('*.xml')) if (ws / 'output').exists() else []:
        data['output_files'].append({
            'name': xml_file.name,
            'size_bytes': xml_file.stat().st_size,
            'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
            'queries': count_xml_queries(xml_file),
        })

    # 3. Per-file results + query-tracking.json
    results_dir = ws / 'results'
    if results_dir.exists():
        for d in sorted(results_dir.iterdir()):
            if d.is_dir() and not d.name.startswith('_'):
                fname = d.name
                file_data = {'name': fname, 'versions': {}}

                for vdir in sorted(d.glob('v*')):
                    vname = vdir.name
                    vdata = {}
                    for json_name in ['parsed.json', 'conversion-report.json',
                                      'complexity-scores.json', 'dependency-graph.json',
                                      'conversion-order.json', 'test-cases.json']:
                        jp = vdir / json_name
                        if jp.exists():
                            vdata[json_name.replace('.json', '')] = load_json(jp)

                    # query-tracking.json
                    tracking_path = vdir / 'query-tracking.json'
                    if tracking_path.exists():
                        tracking = load_json(tracking_path)
                        if tracking:
                            vdata['query-tracking'] = tracking
                            # Merge into top-level tracking map
                            xml_name = fname + '.xml' if not fname.endswith('.xml') else fname
                            if xml_name not in data['tracking']:
                                data['tracking'][xml_name] = tracking
                            else:
                                # Prefer latest version
                                data['tracking'][xml_name] = tracking

                    file_data['versions'][vname] = vdata

                data['files'][fname] = file_data

    # 4. Validation (all result files)
    val_dir = ws / 'results' / '_validation'
    if val_dir.exists():
        data['validation'] = load_json(val_dir / 'validated.json')
        data['execution'] = load_json(val_dir / 'execute_validated.json')
        data['comparison'] = load_json(val_dir / 'compare_validated.json')
        # Also try Kiro-generated compare_results.json
        if data['comparison'] is None:
            data['comparison'] = load_json(val_dir / 'compare_results.json')

    # 4b. Phase 3.5 validation (separate directory)
    val7_dir = ws / 'results' / '_validation_phase35'
    if val7_dir.exists():
        data['validation_phase7'] = load_json(val7_dir / 'validated.json')
        data['comparison_phase7'] = load_json(val7_dir / 'compare_validated.json')
        if data['comparison_phase7'] is None:
            data['comparison_phase7'] = load_json(val7_dir / 'compare_results.json')

    # 4c. DBA Review (Phase 6)
    dba_dir = ws / 'results' / '_dba_review'
    if dba_dir.exists():
        data['dba_review'] = load_json(dba_dir / 'review-result.json')

    # 4d. Healing tickets (Phase 4)
    healing_dir = ws / 'results' / '_healing'
    if healing_dir.exists():
        data['healing'] = load_json(healing_dir / 'tickets.json')

    # 4e. Query Matrix
    qm_path = ws / 'reports' / 'query-matrix.json'
    if qm_path.exists():
        data['query_matrix'] = load_json(qm_path)

    # 5. Extracted (Phase 3.5)
    ext_dir = ws / 'results' / '_extracted'
    if ext_dir.exists():
        for jf in sorted(ext_dir.glob('*-extracted.json')):
            ej = load_json(jf)
            if ej and 'queries' in ej:
                data['extracted'].append({
                    'file': jf.name,
                    'source': ej.get('source_file', ''),
                    'total_queries': ej.get('metadata', {}).get('total_queries', 0),
                    'total_variants': ej.get('metadata', {}).get('total_variants', 0),
                    'multi_branch': ej.get('metadata', {}).get('multi_branch_queries', 0),
                    'dto_replacements': ej.get('dto_replacements', []),
                })

    # 6. Activity log
    data['activity_log'] = load_jsonl(ws / 'logs' / 'activity-log.jsonl')

    # 7. Compute summary
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

    # Phase 3.5 validation
    if data.get('validation_phase7'):
        v7 = data['validation_phase7']
        s['phase7_explain_pass'] = v7.get('pass', 0)
        s['phase7_explain_fail'] = v7.get('fail', 0)
        s['phase7_explain_total'] = v7.get('total', 0)
    if data.get('comparison_phase7'):
        c7 = data['comparison_phase7']
        s['phase7_compare_match'] = c7.get('pass', c7.get('matched', 0))
        s['phase7_compare_fail'] = c7.get('fail', c7.get('mismatched', 0))
        s['phase7_compare_total'] = c7.get('total', 0)

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
        # Best available: Phase 3.5 compare > Phase 3 compare > Phase 3.5 EXPLAIN > Phase 3 EXPLAIN
        if s.get('phase7_compare_total'):
            s['truly_done'] = s.get('phase7_compare_match', 0)
        elif s.get('compare_total'):
            s['truly_done'] = compare_match
        elif s.get('phase7_explain_total'):
            s['truly_done'] = s.get('phase7_explain_pass', 0)
        else:
            s['truly_done'] = s.get('validation_pass', 0)
        s['needs_manual'] = needs_manual
        s['escalated_queries'] = escalated
        # Readiness = pass / tested (not pass / total)
        # Queries not tested (no TC, dynamic SQL) are "unverified", not "failed"
        tested = s.get('phase7_compare_total') or s.get('compare_total') or s.get('phase7_explain_total') or s.get('validation_total') or 0
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
        'validation_phase7': data.get('validation_phase7'),
        'comparison_phase7': data.get('comparison_phase7'),
        'dba_review': data.get('dba_review'),
        'healing': data.get('healing'),
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
.log-evt.error{color:var(--fail)}.log-evt.decision{color:var(--accent2)}.log-evt.learning{color:var(--purple)}.log-evt.warning{color:var(--warn)}
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
  <button class="tab-btn" data-tab="files">Query Detail</button>
  <button class="tab-btn" data-tab="tickets">Tickets</button>
  <button class="tab-btn" data-tab="timeline">Timeline</button>
  <button class="tab-btn" data-tab="log">Log</button>
</div>

<!-- ========== OVERVIEW TAB ========== -->
<div class="tab-content active" id="tab-overview">
  <div id="summary-cards" class="cards"></div>
  <div id="phase-progress" class="sec"><h2>Phase Progress</h2><div id="phase-bars"></div></div>
  <div class="cols2">
    <div class="sec"><h2>Oracle Pattern Distribution</h2><div id="pattern-bars"></div></div>
    <div class="sec"><h2>Complexity Distribution</h2><div id="complexity-bars"></div>
      <div style="margin-top:10px;font-size:11px;color:var(--dim)">
        L0: Standard SQL &middot; L1: Simple swap &middot; L2: Multi-pattern &middot; L3: Structural change &middot; L4: Complex + dynamic
      </div>
    </div>
  </div>
  <div id="validation-sec"></div>
  <div id="extraction-sec"></div>
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

<!-- ========== FILES TAB ========== -->
<div class="tab-content" id="tab-files">
  <div id="file-list"></div>
</div>

<!-- ========== TICKETS TAB ========== -->
<div class="tab-content" id="tab-tickets">
  <div id="tickets-detail"></div>
</div>

<!-- ========== TIMELINE TAB ========== -->
<div class="tab-content" id="tab-timeline">
  <div class="sec"><h2>Event Timeline</h2><div id="timeline-list"></div></div>
</div>

<!-- ========== LOG TAB ========== -->
<div class="tab-content" id="tab-log">
  <div class="sec">
    <h2>Activity Log</h2>
    <div class="log-filters">
      <button class="log-filter-btn active" data-filter="all">All</button>
      <button class="log-filter-btn" data-filter="error">Error</button>
      <button class="log-filter-btn" data-filter="decision">Decision</button>
      <button class="log-filter-btn" data-filter="learning">Learning</button>
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
  if(['success','pass','validated'].includes(s))return '<span style="color:var(--success)">&#10003;</span>';
  if(s==='converted')return '<span style="color:var(--accent2)">&#8594;</span>';
  if(['failed','fail','escalated'].includes(s))return '<span style="color:var(--fail)">&#10007;</span>';
  if(s.startsWith('retry'))return '<span style="color:var(--warn)">&#8635;</span>';
  if(s==='needs_llm_review')return '<span style="color:var(--orange)">&#9888;</span>';
  return '<span style="color:var(--dim)">&#9679;</span>';
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

  // Summary cards
  let valRate=S.validation_total>0?S.validation_pass+'/'+S.validation_total+' ('+(S.validation_pass*100/S.validation_total|0)+'%)':'N/A';
  let valCls=S.validation_total>0?(S.validation_fail===0?'ok':S.validation_fail<5?'wn':'fl'):'';
  let execRate=S.execution_total>0?S.execution_pass+'/'+S.execution_total+' ('+(S.execution_pass*100/S.execution_total|0)+'%)':'N/A';
  let execCls=S.execution_total>0?(S.execution_fail===0?'ok':'wn'):'';
  let compRate=S.compare_total>0?S.compare_match+'/'+S.compare_total+' ('+(S.compare_match*100/S.compare_total|0)+'%)':'N/A';
  let compCls=S.compare_total>0?(S.compare_fail===0?'ok':S.compare_fail<3?'wn':'fl'):'';
  let patTotal=Object.values(S.oracle_patterns||{}).reduce((a,b)=>a+b,0);

  // Readiness card (full width)
  let rdPct=S.readiness_pct||0;
  let rdCls=rdPct>=90?'ok':rdPct>=70?'wn':'fl';
  let rdDone=S.truly_done||0;
  let rdManual=S.needs_manual||0;
  let rdEsc=S.escalated_queries||0;

  document.getElementById('summary-cards').innerHTML=
    `<div class="card" style="grid-column:1/-1;text-align:center;padding:20px;border-color:${rdPct>=90?'var(--success)':rdPct>=70?'var(--warn)':'var(--fail)'}">
      <div class="lbl">Migration Readiness</div>
      <div class="val ${rdCls}" style="font-size:36px">${rdPct}%</div>
      <div class="det">${rdDone}/${S.tested_queries||'?'} verified OK${S.unverified_queries?' | '+S.unverified_queries+' unverified (no TC)':''}${rdManual?' | '+rdManual+' need attention':''}${rdEsc?' | '+rdEsc+' escalated':''}</div>
    </div>`+
    `<div class="card"><div class="lbl">Input Files</div><div class="val">${S.total_input_files}</div><div class="det">${S.total_input_lines.toLocaleString()} lines, ${S.total_input_queries} queries</div></div>`+
    `<div class="card"><div class="lbl">Output Files</div><div class="val">${S.total_output_files}</div><div class="det">${S.total_output_lines.toLocaleString()} lines</div></div>`+
    `<div class="card"><div class="lbl">EXPLAIN</div><div class="val ${valCls}">${valRate}</div><div class="det">${S.validation_total>0?(S.validation_fail>0?S.validation_fail+' failures':'All passed'):'Not run yet'}</div></div>`+
    `<div class="card"><div class="lbl">Execute</div><div class="val ${execCls}">${execRate}</div><div class="det">${S.execution_total>0?(S.execution_fail>0?S.execution_fail+' failures':'All passed'):'Not run yet'}</div></div>`+
    `<div class="card"><div class="lbl">Compare</div><div class="val ${compCls}">${compRate}</div><div class="det">${S.compare_total>0?(S.compare_fail>0?S.compare_fail+' mismatch':'All matched'):'Not run yet'}</div></div>`+
    `<div class="card"><div class="lbl">Oracle Patterns</div><div class="val">${patTotal.toLocaleString()}</div><div class="det">${Object.keys(S.oracle_patterns||{}).length} types</div></div>`;

  // Phase 3.5 cards (if available)
  if(S.phase7_explain_total>0){
    let p7eRate=S.phase7_explain_pass+'/'+S.phase7_explain_total+' ('+(S.phase7_explain_pass*100/S.phase7_explain_total|0)+'%)';
    let p7eCls=S.phase7_explain_fail===0?'ok':'wn';
    document.getElementById('summary-cards').innerHTML+=
      `<div class="card"><div class="lbl">Phase 3.5 EXPLAIN</div><div class="val ${p7eCls}">${p7eRate}</div><div class="det">MyBatis engine resolved SQL</div></div>`;
  }
  if(S.phase7_compare_total>0){
    let p7cRate=S.phase7_compare_match+'/'+S.phase7_compare_total+' ('+(S.phase7_compare_match*100/S.phase7_compare_total|0)+'%)';
    let p7cCls=S.phase7_compare_fail===0?'ok':S.phase7_compare_fail<3?'wn':'fl';
    document.getElementById('summary-cards').innerHTML+=
      `<div class="card"><div class="lbl">Phase 3.5 Compare</div><div class="val ${p7cCls}">${p7cRate}</div><div class="det">MyBatis resolved Oracle vs PG</div></div>`;
  }

  // Action Items (collapsible, at top)
  renderActionItems();
  // Phase bars
  renderPhaseBars();
  // Pattern bars
  renderBars('pattern-bars',S.oracle_patterns||{},'var(--accent)');
  // Complexity bars
  let compColors={L0:'#22c55e',L1:'#84cc16',L2:'#eab308',L3:'#f97316',L4:'#ef4444'};
  renderBarsOrdered('complexity-bars',S.complexity_dist||{},['L0','L1','L2','L3','L4'],compColors);
  // Validation section
  renderValidationSec();
  // Extraction section
  renderExtractionSec();
}

function renderActionItems(){
  let html='<div class="sec"><div class="file-item"><div class="file-hdr" onclick="toggleItem(this.parentElement)" style="cursor:pointer">';
  html+='<span class="file-arrow">&#9654;</span>';
  html+='<h2 style="display:inline;margin:0">Action Items</h2></div>';
  html+='<div class="file-body">';
  // Build action items from healing tickets + validation
  let actions=[];
  // From healing tickets
  if(DATA.healing&&DATA.healing.tickets){
    let cats={};
    DATA.healing.tickets.forEach(t=>{
      let c=t.category||'other';
      if(!cats[c])cats[c]={count:0,severity:t.severity,sample_error:t.error,sample_file:t.file};
      cats[c].count++;
    });
    let catActions={
      'relation_missing':{who:'DBA',action:'PG 스키마에 누락 테이블 생성 (DDL 이관)'},
      'column_missing':{who:'DBA',action:'누락 컬럼 확인 및 DDL 추가'},
      'syntax_error':{who:'개발자/에이전트',action:'SQL 구문 수정 (Phase 4 셀프힐링 대상)'},
      'type_mismatch':{who:'도구',action:'TC 바인드값 타입 개선 (generate-test-cases.py)'},
      'function_missing':{who:'DBA',action:'PG 호환 함수 생성 (substrb, instr 등)'},
      'operator_mismatch':{who:'개발자',action:'명시적 타입 캐스트 추가 (::TEXT, ::INTEGER)'},
      'xml_invalid':{who:'개발자',action:'XML 파싱 에러 수정 (CDATA, 주석)'},
      'other':{who:'개발자/DBA',action:'수동 분석 필요'},
    };
    for(let [cat,info] of Object.entries(cats).sort((a,b)=>b[1].count-a[1].count)){
      let ca=catActions[cat]||{who:'팀',action:'확인 필요'};
      actions.push({who:ca.who,category:cat,count:info.count,severity:info.severity,action:ca.action});
    }
  }
  // DBA review issues
  if(DATA.dba_review&&DATA.dba_review.check_results){
    for(let [k,v] of Object.entries(DATA.dba_review.check_results)){
      if(v.status==='FAIL'||v.status==='WARN'){
        let ic=v.issues_count||v.invalid_count||(v.issues?v.issues.length:0);
        if(ic>0)actions.push({who:'DBA/개발자',category:k,count:ic,severity:v.status==='FAIL'?'critical':'medium',action:v.description||k});
      }
    }
  }
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
    'phase_3','phase_3.5','phase_4','phase_5','phase_6','phase_7'
  ];
  const phaseLabels={
    'phase_0':'Phase 0: Pre-flight','phase_1':'Phase 1: Parse+Convert',
    'phase_2':'Phase 2: Convert (Rule+LLM)','phase_2.5':'Phase 2.5: Test Cases',
    'phase_3':'Phase 3: Validate','phase_3.5':'Phase 3.5: MyBatis',
    'phase_4':'Phase 4: Self-healing','phase_5':'Phase 5: Learning',
    'phase_6':'Phase 6: DBA Review','phase_7':'Phase 7: Report'
  };
  // Merge aliases into phases (sub-phases count toward parent)
  const aliases={'phase_1.5':'phase_1','phase_2_rule':'phase_2','phase_2_llm':'phase_2',
    'phase_3_compare':'phase_3','phase_3_explain':'phase_3','phase_3_5':'phase_3.5',
    'phase_6_old':'phase_7','phase_7_old':'phase_3.5'};
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
  if(DATA.validation){
    let v=DATA.validation;
    let pass=v.pass||0,fail=v.fail||0,total=v.total||0;
    let badge=fail===0?'<span class="phase-badge badge-done">ALL PASSED</span>':
      '<span class="phase-badge" style="background:rgba(239,68,68,.15);color:var(--fail)">'+fail+' FAILURES</span>';
    html+=`<div class="sec"><h2>EXPLAIN Validation</h2><p>${badge} ${pass}/${total}</p>`;
    if(v.failures&&v.failures.length){
      html+=`<p style="font-size:11px;color:var(--dim)">Showing ${Math.min(v.failures.length,100)} of ${v.failures.length} failures. Full list: validated.json</p>`;
      html+='<table style="margin-top:10px"><tr><th>Test</th><th>Error</th></tr>';
      for(let f of v.failures.slice(0,100)){
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(f.test||'')}</td><td style="color:var(--fail);font-size:11px">${esc(String(f.error||'').substring(0,250))}</td></tr>`;
      }
      html+='</table>';
    }
    html+='</div>';
  }
  if(DATA.execution){
    let e=DATA.execution;
    let pass=e.pass||0,fail=e.fail||0,total=e.total||0;
    let badge=fail===0?'<span class="phase-badge badge-done">ALL PASSED</span>':
      '<span class="phase-badge" style="background:rgba(239,68,68,.15);color:var(--fail)">'+fail+' FAILURES</span>';
    html+=`<div class="sec"><h2>Execution Validation</h2><p>${badge} ${pass}/${total}</p>`;
    if(e.failures&&e.failures.length){
      html+='<table style="margin-top:10px"><tr><th>Test</th><th>Error</th></tr>';
      for(let f of e.failures.slice(0,30)){
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(f.test||'')}</td><td style="color:var(--fail);font-size:11px">${esc(String(f.error||'').substring(0,150))}</td></tr>`;
      }
      html+='</table>';
    }
    html+='</div>';
  }
  if(DATA.comparison){
    let c=DATA.comparison;
    let match=c.pass||c.matched||0,fail=c.fail||c.mismatched||0,warn=c.warn||0,total=c.total||0;
    let badge=fail===0?'<span class="phase-badge badge-done">ALL MATCHED</span>':
      '<span class="phase-badge" style="background:rgba(239,68,68,.15);color:var(--fail)">'+fail+' MISMATCH</span>';
    html+=`<div class="sec"><h2>Oracle vs PostgreSQL Compare</h2><p>${badge} ${match}/${total} matched${warn?' ('+warn+' warnings)':''}</p>`;
    if(c.results&&c.results.length){
      html+='<table style="margin-top:10px"><tr><th>Query</th><th>Case</th><th>Oracle Rows</th><th>PG Rows</th><th>Status</th><th>Detail</th></tr>';
      for(let r of c.results){
        let st=r.match?'<span style="color:var(--success)">MATCH</span>':
          (r.oracle_error||r.pg_error||r.ora_error)?'<span style="color:var(--fail)">ERROR</span>':
          '<span style="color:var(--fail)">DIFF</span>';
        let detail=r.reason||r.oracle_error||r.ora_error||r.pg_error||'';
        html+=`<tr><td style="font-family:var(--mono);font-size:12px">${esc(r.query_id||'')}</td><td>${esc(r.case||'')}</td><td>${r.oracle_rows!=null?r.oracle_rows:(r.ora_rows!=null?r.ora_rows:'?')}</td><td>${r.pg_rows!=null?r.pg_rows:'?'}</td><td>${st}</td><td style="font-size:11px;color:var(--dim)">${esc(String(detail).substring(0,120))}</td></tr>`;
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
    // Show escalated query details from healing tickets
    if(DATA.healing&&DATA.healing.tickets){
      let escTickets=DATA.healing.tickets.filter(t=>t.status==='escalated');
      if(escTickets.length){
        html+='<h3 style="margin-top:12px">Escalated Query Details</h3>';
        html+='<table><tr><th>Ticket</th><th>Query</th><th>File</th><th>Category</th><th>Error</th><th>Retries</th></tr>';
        for(let t of escTickets){
          html+=`<tr><td>${esc(t.ticket_id||'')}</td><td style="font-family:var(--mono)">${esc(t.query_id||'')}</td>`;
          html+=`<td style="font-size:11px">${esc(t.file||'')}</td><td>${esc(t.category||'')}</td>`;
          html+=`<td style="font-size:11px;color:var(--fail)">${esc(String(t.error||'').substring(0,200))}</td>`;
          html+=`<td>${t.retry_count||0}/${t.max_retries||5}</td></tr>`;
        }
        html+='</table>';
      }
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
      let bg=k==='COMPLETE'?'rgba(34,197,94,.15)':k.includes('FAIL')?'rgba(239,68,68,.15)':'rgba(148,163,184,.1)';
      let col=k==='COMPLETE'?'var(--success)':k.includes('FAIL')?'var(--fail)':'var(--dim)';
      html+=`<span class="phase-badge" style="background:${bg};color:${col}">${k}: ${v}</span>`;
    }
    html+=`</div></div>`;
  }
  // Healing Tickets (Phase 4)
  if(DATA.healing&&DATA.healing.tickets&&DATA.healing.tickets.length){
    let h=DATA.healing;
    let resolved=h.tickets.filter(t=>t.status==='resolved').length;
    let escalated=h.tickets.filter(t=>t.status==='escalated').length;
    let open=h.tickets.filter(t=>t.status==='open'||t.status==='in_progress').length;
    html+=`<div class="sec"><h2>Phase 4: Healing Tickets</h2>`;
    html+=`<p>Total: ${h.total_tickets} | Resolved: ${resolved} | Escalated: ${escalated} | Open: ${open}</p>`;
    // By category
    if(h.by_category){
      html+=`<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">`;
      for(let [k,v] of Object.entries(h.by_category).sort((a,b)=>b[1]-a[1])){
        html+=`<span class="phase-badge" style="background:rgba(148,163,184,.1);color:var(--dim)">${k}: ${v}</span>`;
      }
      html+=`</div>`;
    }
    // Escalated tickets detail
    let escTickets=h.tickets.filter(t=>t.status==='escalated'||t.severity==='critical'||t.severity==='high');
    if(escTickets.length){
      html+=`<h3 style="margin-top:12px">Action Required (${escTickets.length}건)</h3>`;
      html+=`<table><tr><th>ID</th><th>Severity</th><th>Category</th><th>File</th><th>Query</th><th>Error</th><th>Retries</th></tr>`;
      for(let t of escTickets.slice(0,50)){
        let sevCls=t.severity==='critical'?'style="color:var(--fail);font-weight:bold"':t.severity==='high'?'style="color:var(--fail)"':'';
        html+=`<tr><td>${esc(t.ticket_id)}</td><td ${sevCls}>${esc(t.severity)}</td><td>${esc(t.category)}</td>`;
        html+=`<td style="font-family:var(--mono);font-size:11px">${esc(t.file||'')}</td>`;
        html+=`<td style="font-family:var(--mono);font-size:11px">${esc(t.query_id||'')}</td>`;
        html+=`<td style="font-size:11px;color:var(--fail)">${esc(String(t.error||'').substring(0,200))}</td>`;
        html+=`<td>${t.retry_count||0}/${t.max_retries||5}</td></tr>`;
      }
      html+=`</table>`;
    }
    html+=`</div>`;
  }
  // EXPLAIN failures by category
  if(DATA.validation&&DATA.validation.failure_categories){
    let cats=DATA.validation.failure_categories;
    if(Object.keys(cats).length>0){
      html+=`<div class="sec"><h2>EXPLAIN Failure Categories</h2>`;
      html+=`<table><tr><th>Category</th><th>Count</th><th>Action</th></tr>`;
      let actions={'SYNTAX_ERROR':'Phase 4 셀프힐링 대상','MISSING_OBJECT':'DBA 스키마 이관 필요','TYPE_MISMATCH':'TC 바인드값 또는 타입 캐스트 수정','PERMISSION':'DB 권한 확인','OTHER':'수동 분석 필요'};
      for(let [k,v] of Object.entries(cats).sort((a,b)=>b[1]-a[1])){
        html+=`<tr><td>${esc(k)}</td><td>${v}</td><td style="font-size:11px;color:var(--dim)">${esc(actions[k]||'')}</td></tr>`;
      }
      html+=`</table></div>`;
    }
  }
  if(DATA.dba_review){
    let dr=DATA.dba_review;
    let issues=dr.issues||dr.findings||[];
    let passCount=issues.filter(i=>i.status==='pass'||i.pass).length;
    let failCount=issues.length-passCount;
    let badge=failCount===0?'<span class="phase-badge badge-done">ALL CLEAR</span>':
      '<span class="phase-badge" style="background:rgba(239,68,68,.15);color:var(--fail)">'+failCount+' ISSUES</span>';
    html+=`<div class="sec"><h2>Phase 6: DBA/Expert Review</h2><p>${badge}</p>`;
    if(issues.length){
      html+='<table style="margin-top:10px"><tr><th>Check</th><th>Status</th><th>Detail</th></tr>';
      for(let issue of issues){
        let st=issue.status==='pass'||issue.pass?'<span style="color:var(--success)">PASS</span>':'<span style="color:var(--fail)">FAIL</span>';
        html+=`<tr><td>${esc(issue.check||issue.name||'')}</td><td>${st}</td><td style="font-size:11px">${esc(String(issue.detail||issue.message||'').substring(0,200))}</td></tr>`;
      }
      html+='</table>';
    }
    html+='</div>';
  }
  document.getElementById('validation-sec').innerHTML=html;
}

function renderExtractionSec(){
  if(!DATA.extracted||DATA.extracted.length===0){document.getElementById('extraction-sec').innerHTML='';return;}
  let html='<div class="sec"><h2>Phase 3.5: MyBatis Extraction</h2>';
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
      let qStatus=q.status||'pending';
      let comp=q.complexity||'-';
      let method=q.conversion_method||q.method||'rule';
      let oraclePatterns=q.oracle_patterns||[];
      let oracleSQL=q.oracle_sql||q.sql_raw||'';
      let pgSQL=q.pg_sql||'';
      let rules=q.rules_applied||[];
      let explain=q.explain||null;
      let execution=q.execution||null;
      let testCases=q.test_cases||[];
      let timing=q.timing||{};
      let history=q.history||[];

      // Status badge color
      let stColor='var(--dim)';
      if(['success','converted','pass'].includes(qStatus))stColor='var(--success)';
      else if(['failed','fail','escalated'].includes(qStatus))stColor='var(--fail)';
      else if(qStatus.startsWith('retry'))stColor='var(--warn)';
      else if(qStatus==='needs_llm_review')stColor='var(--orange)';

      let methodColor=method==='llm'?'var(--purple)':method==='no_change'?'var(--dim)':'var(--success)';
      if(method==='no_change')method='no change';
      if(method==='none')method='no change';

      html+=`<div class="q-item"><div class="q-hdr" onclick="toggleItem(this.parentElement)">`;
      html+=`<span class="q-arrow">&#9654;</span>`;
      html+=`${statusIcon(qStatus)} `;
      html+=`<span class="q-id">${esc(qid)}</span>`;
      html+=`<span class="q-badge" style="background:rgba(148,163,184,.1);color:var(--dim)">${esc(comp)}</span>`;
      html+=`<span class="q-badge" style="background:rgba(168,85,247,.1);color:${methodColor}">${esc(method)}</span>`;
      html+=`<span class="q-badge" style="color:${stColor}">${esc(qStatus)}</span>`;
      html+=`</div>`;

      // Query body (hidden by default)
      html+=`<div class="q-body">`;

      // SQL blocks side-by-side
      if(oracleSQL||pgSQL){
        html+=`<div class="sql-container">`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">Oracle SQL</div><pre>${highlightSQL(oracleSQL)}</pre></div>`;
        html+=`<div class="sql-block"><div class="sql-block-hdr">PostgreSQL SQL</div><pre>${highlightSQL(pgSQL)}</pre></div>`;
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
    let ts=entry.timestamp||entry.ts||'';
    if(ts&&typeof ts==='string'&&ts.includes('T'))ts=ts.split('T')[1].substring(0,8);
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

// ========== Render Log Tab ==========
function renderLog(){
  let log=DATA.activity_log||[];
  if(log.length===0){document.getElementById('log-list').innerHTML='<div style="color:var(--dim)">No activity log found</div>';return;}
  let html='';
  for(let i=0;i<log.length;i++){
    let entry=log[i];
    let ts=entry.timestamp||entry.ts||'';
    if(ts&&typeof ts==='string'&&ts.includes('T'))ts=ts.split('T')[1].substring(0,8);
    let evt=entry.event||entry.action||entry.type||'';
    let msg=entry.message||entry.detail||entry.msg||'';
    if(typeof msg==='object')msg=JSON.stringify(msg).substring(0,200);
    let evtLower=evt.toLowerCase();
    let evtClass='';
    if(evtLower.includes('error')||evtLower.includes('fail'))evtClass='error';
    else if(evtLower.includes('decision'))evtClass='decision';
    else if(evtLower.includes('learn'))evtClass='learning';
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

// ========== Init ==========
renderOverview();
renderTickets();
renderFiles();
renderTimeline();

// ========== Explorer 3-Panel Navigation ==========
var expSelectedFile=null, expSelectedQuery=null;
expRenderFiles();

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
      let st=(q.explain||{}).status||'';
      if(search && !name.toLowerCase().includes(search) && !qid.includes(search)
         && !(q.oracle_sql||'').toLowerCase().includes(search)) return false;
      if(statusF && st!==statusF) return false;
      if(typeF && (q.type||'')!==typeF) return false;
      return true;
    });
    if(filtered.length===0) continue;
    shown+=filtered.length;
    let failC=filtered.filter(q=>(q.explain||{}).status==='fail').length;
    let passC=filtered.filter(q=>(q.explain||{}).status==='pass').length;
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
    let st=(q.explain||{}).status||'';
    let icon=st==='pass'?'<span style="color:var(--success)">&#10003;</span>':st==='fail'?'<span style="color:var(--fail)">&#10007;</span>':'<span style="color:var(--dim)">&#9679;</span>';
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
  // Header
  html+=`<h3 style="margin:0 0 8px">${esc(qid)} <span style="color:var(--dim);font-weight:normal">${esc((q.type||'').toUpperCase())} / ${esc(q.conversion_method||q.method||'')}</span></h3>`;

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

  // Compare results (TC별)
  let compResults=q.compare_results||[];
  if(compResults.length){
    html+=`<div style="margin:8px 0"><strong>TC 비교 결과 (${compResults.length}건):</strong></div>`;
    for(let cr of compResults){
      let icon=cr.match?'<span style="color:var(--success)">&#10003; MATCH</span>':'<span style="color:var(--fail)">&#10007; DIFF</span>';
      let oraR=cr.oracle_rows!=null?cr.oracle_rows:'?';
      let pgR=cr.pg_rows!=null?cr.pg_rows:'?';
      html+=`<div style="padding:4px 8px;margin-bottom:3px;background:rgba(255,255,255,.02);border-radius:4px;font-size:12px;border-left:2px solid ${cr.match?'var(--success)':'var(--fail)'}">`;
      html+=`<strong>${esc(cr.case||cr.test_id||'')}</strong> ${icon} Oracle:${oraR}행 PG:${pgR}행`;
      if(cr.reason)html+=`<div style="color:var(--fail);font-size:11px">사유: ${esc(String(cr.reason))}</div>`;
      html+=`</div>`;
    }
  }

  // Test Cases (바인드 변수 상세)
  let tcs=q.test_cases||[];
  if(tcs.length){
    html+=`<div style="margin:8px 0"><strong>테스트 케이스 (${tcs.length}건):</strong></div>`;
    for(let tc of tcs){
      let binds=tc.binds||tc.params||{};
      html+=`<div style="padding:4px 8px;margin-bottom:2px;background:rgba(255,255,255,.02);border-radius:4px;font-size:11px">`;
      html+=`<strong>${esc(tc.case_id||tc.name||'')}</strong>`;
      html+=`<div style="font-family:var(--mono);color:var(--dim)">`;
      for(let [k,v] of Object.entries(binds)){
        html+=`${esc(k)}=<span style="color:var(--accent)">${esc(String(v))}</span> `;
      }
      html+=`</div></div>`;
    }
  }

  // Healing ticket
  let ticket=null;
  if(DATA.healing&&DATA.healing.tickets){
    ticket=DATA.healing.tickets.find(t=>t.query_id===qid);
  }
  if(ticket){
    let col=ticket.status==='resolved'?'var(--success)':ticket.status==='escalated'?'var(--fail)':'var(--dim)';
    html+=`<div style="margin-top:8px;padding:8px;background:rgba(255,255,255,.03);border-radius:4px;border-left:3px solid ${col}">`;
    html+=`<strong>&#127915; ${esc(ticket.ticket_id||'')}</strong> <span style="color:${col}">[${esc(ticket.status||'')}]</span>`;
    html+=` ${esc(ticket.category||'')}`;
    if(ticket.retry_count)html+=` (${ticket.retry_count}회 시도)`;
    if(ticket.skip_reason)html+=`<div style="color:var(--dim);font-size:11px">사유: ${esc(ticket.skip_reason)}</div>`;
    if(ticket.error)html+=`<div style="color:var(--fail);font-size:11px;margin-top:4px">${esc(String(ticket.error).substring(0,300))}</div>`;
    html+=`</div>`;
  }

  document.getElementById('exp-panel-detail').innerHTML=html;
}
renderLog();

function renderTickets(){
  let html='';
  if(!DATA.healing||!DATA.healing.tickets||DATA.healing.tickets.length===0){
    document.getElementById('tickets-detail').innerHTML='<div class="sec"><p style="color:var(--dim)">No healing tickets generated. Run Phase 4.</p></div>';
    return;
  }
  let h=DATA.healing;
  let tickets=h.tickets;
  let resolved=tickets.filter(t=>t.status==='resolved');
  let escalated=tickets.filter(t=>t.status==='escalated');
  let skipped=tickets.filter(t=>t.status!=='resolved'&&t.status!=='escalated');

  // Summary
  html+=`<div class="sec"><h2>Healing Tickets Summary</h2>`;
  let mybatisResolved=resolved.filter(t=>t.skip_reason==='resolved_by_mybatis_engine').length;
  let healResolved=resolved.length-mybatisResolved;
  html+=`<p>Total: <strong>${tickets.length}</strong> | <span style="color:var(--success)">Resolved: ${resolved.length}</span>`;
  if(mybatisResolved)html+=` (MyBatis: ${mybatisResolved}, Healing: ${healResolved})`;
  html+=` | <span style="color:var(--fail)">Escalated: ${escalated.length}</span> | <span style="color:var(--dim)">Skipped: ${skipped.length}</span></p>`;

  // Category breakdown
  if(h.by_category){
    html+=`<div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">`;
    for(let [k,v] of Object.entries(h.by_category).sort((a,b)=>b[1]-a[1])){
      html+=`<span class="phase-badge" style="background:rgba(148,163,184,.1);color:var(--dim)">${k}: ${v}</span>`;
    }
    html+=`</div>`;
  }
  html+=`</div>`;

  // Resolved tickets
  if(resolved.length){
    html+=`<div class="sec"><h2 style="color:var(--success)">Resolved (${resolved.length})</h2>`;
    html+=`<table><tr><th>ID</th><th>Query</th><th>File</th><th>Category</th><th>Retries</th><th>Error (before fix)</th></tr>`;
    for(let t of resolved.slice(0,100)){
      html+=`<tr><td>${esc(t.ticket_id)}</td><td style="font-family:var(--mono);font-size:11px">${esc(t.query_id||'')}</td>`;
      html+=`<td style="font-size:11px">${esc(t.file||'')}</td><td>${esc(t.category)}</td>`;
      html+=`<td>${t.retry_count||0}</td><td style="font-size:11px;color:var(--dim)">${esc(String(t.error||'').substring(0,150))}</td></tr>`;
    }
    html+=`</table></div>`;
  }

  // Escalated tickets (with full detail)
  if(escalated.length){
    html+=`<div class="sec"><h2 style="color:var(--fail)">Escalated — Manual Action Required (${escalated.length})</h2>`;
    html+=`<table><tr><th>ID</th><th>Query</th><th>File</th><th>Category</th><th>Severity</th><th>Retries</th><th>Error</th></tr>`;
    for(let t of escalated){
      let sevCls=t.severity==='critical'?'style="color:var(--fail);font-weight:bold"':'style="color:var(--fail)"';
      html+=`<tr><td>${esc(t.ticket_id)}</td><td style="font-family:var(--mono)">${esc(t.query_id||'')}</td>`;
      html+=`<td style="font-size:11px">${esc(t.file||'')}</td><td>${esc(t.category)}</td>`;
      html+=`<td ${sevCls}>${esc(t.severity)}</td><td>${t.retry_count||0}/${t.max_retries||5}</td>`;
      html+=`<td style="font-size:11px;color:var(--fail)">${esc(String(t.error||'').substring(0,250))}</td></tr>`;
    }
    html+=`</table></div>`;
  }

  // Skipped tickets (grouped by skip_reason)
  if(skipped.length){
    html+=`<div class="sec"><h2 style="color:var(--dim)">Skipped / Non-Actionable (${skipped.length})</h2>`;
    html+=`<p style="font-size:12px;color:var(--dim)">DBA 스키마 이관, TC 바인드 타입 불일치, 동적 SQL fragment 등 자동 힐링 불가 항목</p>`;
    // Group by skip_reason
    let skipGroups={};
    for(let t of skipped){
      let reason=t.skip_reason||t.category||'unknown';
      if(!skipGroups[reason])skipGroups[reason]={count:0,samples:[]};
      skipGroups[reason].count++;
      if(skipGroups[reason].samples.length<3)skipGroups[reason].samples.push(t);
    }
    html+=`<table><tr><th>사유</th><th>건수</th><th>예시 쿼리</th><th>예시 에러</th></tr>`;
    for(let [reason,info] of Object.entries(skipGroups).sort((a,b)=>b[1].count-a[1].count)){
      let samples=info.samples.map(s=>esc(s.query_id||'')).join(', ');
      let sampleErr=info.samples[0]?esc(String(info.samples[0].error||'').substring(0,100)):'';
      html+=`<tr><td>${esc(reason)}</td><td>${info.count}</td><td style="font-family:var(--mono);font-size:11px">${samples}</td><td style="font-size:11px;color:var(--dim)">${sampleErr}</td></tr>`;
    }
    html+=`</table></div>`;
  }

  document.getElementById('tickets-detail').innerHTML=html;
}

</script>
</body>
</html>'''


def render_html(data):
    """Render the full HTML report by embedding data into the template."""
    embedded = build_embedded_data(data)
    # Serialize to compact JSON
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
        print(f"  Compare: {s['compare_match']}/{s['compare_total']} matched, {s['compare_fail']} mismatch, {s['compare_warn']} warn")
    if s.get('extracted_queries'):
        print(f"  Phase 3.5: {s['extracted_queries']} queries, {s['extracted_variants']} variants")

    fsize = os.path.getsize(args.output)
    print(f"  File size: {fsize:,} bytes")


if __name__ == '__main__':
    main()
