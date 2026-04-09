#!/usr/bin/env python3
"""
Phase 6/7: Self-contained HTML Report Generator
모든 변환 결과를 종합하여 하나의 HTML 파일로 생성한다.

Usage:
    python3 tools/generate-report.py
    python3 tools/generate-report.py --output workspace/reports/migration-report.html

Data sources (자동 탐색):
    workspace/progress.json              전체 진행 상태
    workspace/results/*/v*/parsed.json   파싱 결과
    workspace/results/*/v*/conversion-report.json  변환 리포트
    workspace/results/*/v*/complexity-scores.json  복잡도
    workspace/results/*/v*/dependency-graph.json   의존성
    workspace/results/*/v*/test-cases.json         테스트 케이스
    workspace/results/_validation/validated.json   EXPLAIN 검증
    workspace/results/_validation/execute_validated.json  실행 검증
    workspace/results/_extracted/*-extracted.json   MyBatis 추출 결과
    workspace/logs/activity-log.jsonl              활동 로그
    workspace/input/*.xml / workspace/output/*.xml 원본/변환 파일 비교
"""

import json
import os
import re
import sys
import glob
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
                    entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def count_xml_queries(xml_path):
    """Count query elements in an XML file."""
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


def collect_data(base_dir):
    """Collect all available data from the workspace."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'progress': None,
        'files': {},
        'validation': None,
        'execution': None,
        'extracted': [],
        'activity_log': [],
        'input_files': [],
        'output_files': [],
        'summary': {},
    }

    ws = Path(base_dir) / 'workspace'

    # 1. Progress
    data['progress'] = load_json(ws / 'progress.json')

    # 2. Input/Output XML files
    for xml_file in sorted((ws / 'input').glob('*.xml')) if (ws / 'input').exists() else []:
        finfo = {
            'name': xml_file.name,
            'size_bytes': xml_file.stat().st_size,
            'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
            'queries': count_xml_queries(xml_file),
        }
        data['input_files'].append(finfo)

    for xml_file in sorted((ws / 'output').glob('*.xml')) if (ws / 'output').exists() else []:
        finfo = {
            'name': xml_file.name,
            'size_bytes': xml_file.stat().st_size,
            'lines': sum(1 for _ in open(xml_file, encoding='utf-8', errors='ignore')),
            'queries': count_xml_queries(xml_file),
        }
        data['output_files'].append(finfo)

    # 3. Per-file results
    results_dir = ws / 'results'
    if results_dir.exists():
        for d in sorted(results_dir.iterdir()):
            if d.is_dir() and not d.name.startswith('_'):
                fname = d.name
                file_data = {'name': fname, 'versions': {}}

                for vdir in sorted(d.glob('v*')):
                    vname = vdir.name
                    vdata = {}
                    for json_name in ['parsed.json', 'conversion-report.json', 'complexity-scores.json',
                                      'dependency-graph.json', 'conversion-order.json', 'test-cases.json']:
                        jp = vdir / json_name
                        if jp.exists():
                            vdata[json_name.replace('.json', '')] = load_json(jp)
                    file_data['versions'][vname] = vdata

                data['files'][fname] = file_data

    # 4. Validation
    val_dir = ws / 'results' / '_validation'
    if val_dir.exists():
        data['validation'] = load_json(val_dir / 'validated.json')
        data['execution'] = load_json(val_dir / 'execute_validated.json')

    # 5. Extracted (Phase 7)
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
    log_path = ws / 'logs' / 'activity-log.jsonl'
    data['activity_log'] = load_jsonl(log_path)

    # 7. Compute summary
    data['summary'] = compute_summary(data)

    return data


def compute_summary(data):
    """Compute aggregate statistics."""
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
        'validation_pass': 0,
        'validation_fail': 0,
        'validation_total': 0,
    }

    # Oracle patterns from progress
    if data['progress'] and 'files' in data['progress']:
        for fname, fdata in data['progress']['files'].items():
            patterns = fdata.get('oraclePatterns', {})
            for p, count in patterns.items():
                s['oracle_patterns'][p] = s['oracle_patterns'].get(p, 0) + count
            comp = fdata.get('complexity', {})
            for level, count in comp.items():
                s['complexity_dist'][level] = s['complexity_dist'].get(level, 0) + count

    # Oracle patterns from parsed.json
    for fname, fdata in data['files'].items():
        for vname, vdata in fdata.get('versions', {}).items():
            parsed = vdata.get('parsed')
            if parsed:
                for q in parsed.get('queries', []):
                    for p in q.get('oracle_patterns', []):
                        s['oracle_patterns'][p] = s['oracle_patterns'].get(p, 0) + 1

            # Conversion report stats
            report = vdata.get('conversion-report')
            if report:
                rules = report.get('rules_applied', report.get('conversion_stats', {}))
                if isinstance(rules, dict):
                    for rule, count in rules.items():
                        s['conversion_methods']['rule'] += (count if isinstance(count, int) else 1)
                unconverted = report.get('unconverted', [])
                s['conversion_methods']['llm'] += len(unconverted) if isinstance(unconverted, list) else 0

    # Validation
    if data['validation']:
        s['validation_pass'] = data['validation'].get('pass', 0)
        s['validation_fail'] = data['validation'].get('fail', 0)
        s['validation_total'] = data['validation'].get('total', 0)

    if data['execution']:
        s['execution_pass'] = data['execution'].get('pass', 0)
        s['execution_fail'] = data['execution'].get('fail', 0)
        s['execution_total'] = data['execution'].get('total', 0)

    # Extracted (Phase 7)
    s['extracted_files'] = len(data['extracted'])
    s['extracted_queries'] = sum(e['total_queries'] for e in data['extracted'])
    s['extracted_variants'] = sum(e['total_variants'] for e in data['extracted'])
    s['extracted_multi_branch'] = sum(e['multi_branch'] for e in data['extracted'])

    return s


def render_html(data):
    """Render the full HTML report."""
    s = data['summary']
    progress = data['progress'] or {}
    pipeline = progress.get('_pipeline', {})

    # Determine overall status
    phase_name = pipeline.get('current_phase_name', progress.get('currentPhase', 'N/A'))
    phases_done = pipeline.get('phases_completed', [])

    # Validation rate
    val_rate = ''
    if s.get('validation_total', 0) > 0:
        val_rate = f"{s['validation_pass']}/{s['validation_total']} ({s['validation_pass']*100//s['validation_total']}%)"

    exec_rate = ''
    if s.get('execution_total', 0) > 0:
        exec_rate = f"{s['execution_pass']}/{s['execution_total']} ({s['execution_pass']*100//s['execution_total']}%)"

    # Sort oracle patterns by count desc
    sorted_patterns = sorted(s['oracle_patterns'].items(), key=lambda x: -x[1])

    # File comparison table
    file_rows = ''
    input_map = {f['name']: f for f in data['input_files']}
    output_map = {f['name']: f for f in data['output_files']}
    all_names = sorted(set(list(input_map.keys()) + list(output_map.keys())))
    for name in all_names:
        inp = input_map.get(name, {})
        out = output_map.get(name, {})
        prog_data = progress.get('files', {}).get(name, {})
        status = prog_data.get('status', '-')
        status_cls = 'success' if status in ('converted', 'success', 'validated') else 'warn' if status in ('converting', 'validating') else 'fail' if status in ('failed', 'escalated') else ''
        total_q = prog_data.get('totalQueries', inp.get('queries', '-'))
        patterns_str = ', '.join(f'{k}:{v}' for k, v in sorted(prog_data.get('oraclePatterns', {}).items(), key=lambda x: -x[1])[:5])
        file_rows += f'''<tr>
            <td class="mono">{escape(name)}</td>
            <td>{inp.get('lines', '-'):,}</td>
            <td>{out.get('lines', '-'):,}</td>
            <td>{total_q}</td>
            <td class="{status_cls}">{status}</td>
            <td class="small">{escape(patterns_str)}</td>
        </tr>\n'''

    # Validation failures
    val_failures_html = ''
    if data['validation'] and data['validation'].get('failures'):
        for f in data['validation']['failures'][:30]:
            val_failures_html += f'<tr><td class="mono">{escape(str(f.get("test","")))}</td><td class="error-text">{escape(str(f.get("error",""))[:150])}</td></tr>\n'

    # Validation warnings
    val_warnings_html = ''
    if data['validation'] and data['validation'].get('warnings'):
        for w in data['validation']['warnings']:
            sev_cls = 'fail' if w.get('severity') == 'critical' else 'warn'
            val_warnings_html += f'<tr><td class="{sev_cls}">{escape(w.get("code",""))}</td><td>{escape(w.get("query_id",""))}</td><td>{escape(w.get("message",""))}</td></tr>\n'

    # Execution failures
    exec_failures_html = ''
    if data['execution'] and data['execution'].get('failures'):
        for f in data['execution']['failures'][:30]:
            exec_failures_html += f'<tr><td class="mono">{escape(str(f.get("test","")))}</td><td class="error-text">{escape(str(f.get("error",""))[:150])}</td></tr>\n'

    # Extracted (Phase 7) table
    extracted_rows = ''
    for e in data['extracted']:
        dto_str = ', '.join(e.get('dto_replacements', [])[:3])
        if len(e.get('dto_replacements', [])) > 3:
            dto_str += f' +{len(e["dto_replacements"])-3} more'
        extracted_rows += f'''<tr>
            <td class="mono">{escape(e.get('source', e['file']))}</td>
            <td>{e['total_queries']}</td>
            <td>{e['total_variants']}</td>
            <td>{e['multi_branch']}</td>
            <td class="small">{escape(dto_str)}</td>
        </tr>\n'''

    # Activity log (last 30 entries)
    log_rows = ''
    for entry in data['activity_log'][-30:]:
        ts = entry.get('timestamp', entry.get('ts', ''))
        if ts:
            ts = ts.split('T')[-1][:8] if 'T' in str(ts) else str(ts)
        evt = entry.get('event', entry.get('type', ''))
        msg = entry.get('message', entry.get('detail', entry.get('msg', '')))
        if isinstance(msg, dict):
            msg = json.dumps(msg, ensure_ascii=False)[:120]
        log_rows += f'<tr><td class="mono">{escape(str(ts))}</td><td>{escape(str(evt))}</td><td class="small">{escape(str(msg)[:120])}</td></tr>\n'

    # Oracle pattern chart data (for the bar)
    pattern_bars = ''
    if sorted_patterns:
        max_count = sorted_patterns[0][1] if sorted_patterns else 1
        for pname, pcount in sorted_patterns[:15]:
            pct = min(100, int(pcount / max_count * 100))
            pattern_bars += f'''<div class="bar-row">
                <span class="bar-label">{escape(pname)}</span>
                <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
                <span class="bar-value">{pcount:,}</span>
            </div>\n'''

    # Complexity distribution
    complexity_bars = ''
    comp = s.get('complexity_dist', {})
    if comp:
        max_c = max(comp.values()) if comp else 1
        for level in ['L0', 'L1', 'L2', 'L3', 'L4']:
            cnt = comp.get(level, 0)
            pct = min(100, int(cnt / max_c * 100)) if max_c > 0 else 0
            color = {'L0': '#22c55e', 'L1': '#84cc16', 'L2': '#eab308', 'L3': '#f97316', 'L4': '#ef4444'}.get(level, '#888')
            complexity_bars += f'''<div class="bar-row">
                <span class="bar-label">{level}</span>
                <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
                <span class="bar-value">{cnt}</span>
            </div>\n'''

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OMA Migration Report</title>
<style>
:root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0; --dim: #94a3b8;
         --accent: #3b82f6; --success: #22c55e; --warn: #eab308; --fail: #ef4444; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
        background: var(--bg); color: var(--text); line-height: 1.6; padding: 20px; }}
.container {{ max-width: 1200px; margin: 0 auto; }}

/* Header */
.header {{ text-align: center; padding: 30px 0 20px; border-bottom: 1px solid var(--border); margin-bottom: 30px; }}
.header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; }}
.header .subtitle {{ color: var(--dim); font-size: 14px; }}

/* Stat cards */
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
.stat .label {{ font-size: 12px; color: var(--dim); text-transform: uppercase; letter-spacing: 0.05em; }}
.stat .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
.stat .detail {{ font-size: 12px; color: var(--dim); margin-top: 4px; }}
.stat .value.success {{ color: var(--success); }}
.stat .value.warn {{ color: var(--warn); }}
.stat .value.fail {{ color: var(--fail); }}

/* Sections */
.section {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 20px; }}
.section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
.section h3 {{ font-size: 15px; font-weight: 600; margin: 16px 0 10px; color: var(--dim); }}

/* Tables */
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; padding: 8px 12px; background: rgba(255,255,255,0.05); border-bottom: 1px solid var(--border);
      font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--dim); }}
td {{ padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }}
tr:hover {{ background: rgba(255,255,255,0.03); }}
.mono {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; }}
.small {{ font-size: 11px; color: var(--dim); }}
.success {{ color: var(--success); font-weight: 600; }}
.warn {{ color: var(--warn); font-weight: 600; }}
.fail {{ color: var(--fail); font-weight: 600; }}
.error-text {{ color: var(--fail); font-size: 11px; font-family: monospace; }}

/* Bars */
.bar-row {{ display: flex; align-items: center; margin-bottom: 6px; }}
.bar-label {{ width: 160px; font-size: 12px; font-family: monospace; flex-shrink: 0; }}
.bar-track {{ flex: 1; height: 20px; background: rgba(255,255,255,0.05); border-radius: 4px; margin: 0 12px; overflow: hidden; }}
.bar-fill {{ height: 100%; background: var(--accent); border-radius: 4px; transition: width 0.3s; }}
.bar-value {{ width: 60px; text-align: right; font-size: 12px; font-family: monospace; color: var(--dim); }}

/* Two column */
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 768px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

/* Badge */
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
.badge-success {{ background: rgba(34,197,94,0.15); color: var(--success); }}
.badge-warn {{ background: rgba(234,179,8,0.15); color: var(--warn); }}
.badge-fail {{ background: rgba(239,68,68,0.15); color: var(--fail); }}

/* Footer */
.footer {{ text-align: center; padding: 20px; color: var(--dim); font-size: 12px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>Oracle &rarr; PostgreSQL Migration Report</h1>
    <div class="subtitle">Generated: {data['generated_at'][:19].replace('T', ' ')} | OMA Kiro Migration Accelerator</div>
</div>

<!-- Summary Stats -->
<div class="stats">
    <div class="stat">
        <div class="label">Input Files</div>
        <div class="value">{s['total_input_files']}</div>
        <div class="detail">{s['total_input_lines']:,} lines, {s['total_input_queries']} queries</div>
    </div>
    <div class="stat">
        <div class="label">Output Files</div>
        <div class="value">{s['total_output_files']}</div>
        <div class="detail">{s['total_output_lines']:,} lines, {s['total_output_queries']} queries</div>
    </div>
    <div class="stat">
        <div class="label">EXPLAIN Validation</div>
        <div class="value {('success' if s.get('validation_fail',1)==0 else 'warn' if s.get('validation_fail',0)<5 else 'fail')}">{val_rate or 'N/A'}</div>
        <div class="detail">{('All passed' if s.get('validation_fail',1)==0 else str(s.get('validation_fail',0))+' failures') if val_rate else 'Not run yet'}</div>
    </div>
    <div class="stat">
        <div class="label">Execution Validation</div>
        <div class="value {('success' if s.get('execution_fail',1)==0 else 'warn')}">{exec_rate or 'N/A'}</div>
        <div class="detail">{('All passed' if s.get('execution_fail',1)==0 else str(s.get('execution_fail',0))+' failures') if exec_rate else 'Not run yet'}</div>
    </div>
    <div class="stat">
        <div class="label">Phase 7 Extraction</div>
        <div class="value">{s['extracted_queries'] or 'N/A'}</div>
        <div class="detail">{s['extracted_variants']} variants, {s['extracted_multi_branch']} multi-branch</div>
    </div>
    <div class="stat">
        <div class="label">Oracle Patterns</div>
        <div class="value">{sum(s['oracle_patterns'].values()):,}</div>
        <div class="detail">{len(s['oracle_patterns'])} types detected</div>
    </div>
</div>

<!-- File-by-File Results -->
<div class="section">
    <h2>File-by-File Results</h2>
    <table>
        <tr><th>File</th><th>Input Lines</th><th>Output Lines</th><th>Queries</th><th>Status</th><th>Top Patterns</th></tr>
        {file_rows}
    </table>
</div>

<!-- Oracle Patterns + Complexity -->
<div class="two-col">
    <div class="section">
        <h2>Oracle Pattern Distribution</h2>
        {pattern_bars if pattern_bars else '<p style="color:var(--dim)">No patterns detected yet</p>'}
    </div>
    <div class="section">
        <h2>Complexity Distribution</h2>
        {complexity_bars if complexity_bars else '<p style="color:var(--dim)">No complexity data yet</p>'}
        <div class="small" style="margin-top:12px">
            L0: Standard SQL (no conversion) &middot; L1: Simple function swap &middot; L2: Multi-pattern<br>
            L3: Structural change (CONNECT BY, MERGE) &middot; L4: Complex + dynamic SQL
        </div>
    </div>
</div>

<!-- EXPLAIN Validation -->
{'<div class="section"><h2>EXPLAIN Validation Results</h2>' + (
    '<p><span class="badge badge-success">ALL PASSED</span> ' + val_rate + '</p>' if s.get('validation_fail', 1) == 0 else
    '<p><span class="badge badge-warn">' + str(s.get('validation_fail', 0)) + ' FAILURES</span> ' + val_rate + '</p>' +
    '<h3>Failures</h3><table><tr><th>Test</th><th>Error</th></tr>' + val_failures_html + '</table>'
) + (
    '<h3>Integrity Warnings</h3><table><tr><th>Code</th><th>Query</th><th>Message</th></tr>' + val_warnings_html + '</table>' if val_warnings_html else ''
) + '</div>' if data['validation'] else ''}

<!-- Execution Validation -->
{'<div class="section"><h2>Execution Validation Results</h2>' + (
    '<p><span class="badge badge-success">ALL PASSED</span> ' + exec_rate + '</p>' if s.get('execution_fail', 1) == 0 else
    '<p><span class="badge badge-warn">' + str(s.get('execution_fail', 0)) + ' FAILURES</span> ' + exec_rate + '</p>' +
    '<h3>Failures</h3><table><tr><th>Test</th><th>Error</th></tr>' + exec_failures_html + '</table>'
) + '</div>' if data['execution'] else ''}

<!-- Phase 7: MyBatis Extraction -->
{'<div class="section"><h2>Phase 7: MyBatis Engine Extraction</h2>' +
    '<table><tr><th>File</th><th>Queries</th><th>Variants</th><th>Multi-Branch</th><th>DTO Replacements</th></tr>' +
    extracted_rows + '</table>' +
    '<div class="small" style="margin-top:8px">Extracted using MyBatis SqlSessionFactory + BoundSql API with H2 dummy datasource</div>' +
'</div>' if data['extracted'] else ''}

<!-- Activity Log -->
{'<div class="section"><h2>Activity Log (Recent)</h2>' +
    '<table><tr><th>Time</th><th>Event</th><th>Detail</th></tr>' +
    log_rows + '</table></div>' if log_rows else ''}

<div class="footer">
    OMA Kiro &mdash; Oracle Migration Accelerator &mdash; Powered by Claude
</div>

</div>
</body>
</html>'''

    return html


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
    if s.get('extracted_queries'):
        print(f"  Phase 7: {s['extracted_queries']} queries, {s['extracted_variants']} variants")

    fsize = os.path.getsize(args.output)
    print(f"  File size: {fsize:,} bytes")


if __name__ == '__main__':
    main()
