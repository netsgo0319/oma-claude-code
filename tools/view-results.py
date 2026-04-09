#!/usr/bin/env python3
"""
OMA Kiro Result Viewer
JSON 결과물을 HTML로 변환하여 브라우저에서 확인.

Usage:
    python3 tools/view-results.py                    # workspace/results 전체 → HTML 생성 후 브라우저 오픈
    python3 tools/view-results.py --no-open          # HTML 생성만 (브라우저 안 열기)
    python3 tools/view-results.py --port 8080        # 로컬 서버로 실행
"""

import json
import sys
import os
import webbrowser
import http.server
import threading
from pathlib import Path
from datetime import datetime

WORKSPACE = "workspace"
OUTPUT_HTML = "workspace/reports/dashboard.html"


def load_json(path):
    """JSON 파일 로드 (없으면 None)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_jsonl(path):
    """JSONL 파일 로드."""
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
    except FileNotFoundError:
        pass
    return entries


def collect_results():
    """workspace에서 모든 결과물 수집."""
    results = {
        'generated_at': datetime.now().isoformat(),
        'progress': load_json(f'{WORKSPACE}/progress.json'),
        'files': {},
        'activity_log': load_jsonl(f'{WORKSPACE}/logs/activity-log.jsonl'),
    }

    results_dir = Path(f'{WORKSPACE}/results')
    if results_dir.exists():
        for file_dir in sorted(results_dir.iterdir()):
            if file_dir.is_dir() and file_dir.name != '_global' and file_dir.name != '_extracted':
                file_name = file_dir.name
                v1_dir = file_dir / 'v1'
                if v1_dir.exists():
                    results['files'][file_name] = {
                        'parsed': load_json(v1_dir / 'parsed.json'),
                        'conversion_report': load_json(v1_dir / 'conversion-report.json'),
                        'complexity_scores': load_json(v1_dir / 'complexity-scores.json'),
                        'dependency_graph': load_json(v1_dir / 'dependency-graph.json'),
                        'conversion_order': load_json(v1_dir / 'conversion-order.json'),
                    }

    # Global cross-file graph
    results['cross_file_graph'] = load_json(f'{WORKSPACE}/results/_global/cross-file-graph.json')

    return results


def generate_html(results):
    """결과를 HTML로 렌더링."""
    progress = results.get('progress') or {}
    files = results.get('files', {})
    activity_log = results.get('activity_log', [])

    # Count totals
    total_queries = 0
    total_rule = 0
    total_llm = 0
    total_conversions = 0
    for fname, fdata in files.items():
        if fdata.get('parsed'):
            m = fdata['parsed'].get('metadata', {})
            total_queries += m.get('total_queries', 0)
            total_rule += m.get('rule_tagged', 0)
            total_llm += m.get('llm_tagged', 0)
        if fdata.get('conversion_report'):
            total_conversions += fdata['conversion_report'].get('total_replacements', 0)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OMA Kiro - Migration Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }}
  h1 {{ color: #58a6ff; margin-bottom: 8px; }}
  h2 {{ color: #58a6ff; margin: 24px 0 12px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  h3 {{ color: #8b949e; margin: 16px 0 8px; }}
  .header {{ display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }}
  .header pre {{ color: #58a6ff; font-size: 10px; line-height: 1.1; }}
  .timestamp {{ color: #8b949e; font-size: 13px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card .label {{ color: #8b949e; font-size: 12px; text-transform: uppercase; }}
  .card .value {{ color: #f0f6fc; font-size: 28px; font-weight: bold; margin-top: 4px; }}
  .card .sub {{ color: #8b949e; font-size: 12px; margin-top: 4px; }}
  .card.green .value {{ color: #3fb950; }}
  .card.blue .value {{ color: #58a6ff; }}
  .card.yellow .value {{ color: #d29922; }}
  .card.red .value {{ color: #f85149; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #21262d; }}
  th {{ background: #161b22; color: #8b949e; font-size: 12px; text-transform: uppercase; }}
  tr:hover {{ background: #161b22; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
  .badge-green {{ background: #238636; color: #fff; }}
  .badge-blue {{ background: #1f6feb; color: #fff; }}
  .badge-yellow {{ background: #9e6a03; color: #fff; }}
  .badge-red {{ background: #da3633; color: #fff; }}
  .badge-gray {{ background: #30363d; color: #8b949e; }}
  .bar {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 4px 0; background: #21262d; }}
  .bar-fill {{ height: 100%; }}
  .bar-green {{ background: #3fb950; }}
  .bar-blue {{ background: #58a6ff; }}
  .bar-yellow {{ background: #d29922; }}
  .bar-red {{ background: #f85149; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .log-entry {{ padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 13px; }}
  .log-type {{ font-weight: 600; }}
  .log-type-ERROR {{ color: #f85149; }}
  .log-type-SUCCESS {{ color: #3fb950; }}
  .log-type-DECISION {{ color: #58a6ff; }}
  .log-type-WARNING {{ color: #d29922; }}
  .log-type-PHASE {{ color: #bc8cff; }}
  .log-time {{ color: #484f58; }}
  .tab-container {{ margin: 16px 0; }}
  .tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #30363d; }}
  .tab {{ padding: 8px 16px; cursor: pointer; color: #8b949e; border-bottom: 2px solid transparent; }}
  .tab.active {{ color: #58a6ff; border-bottom-color: #58a6ff; }}
  .tab-content {{ display: none; padding: 16px 0; }}
  .tab-content.active {{ display: block; }}
  .pattern-bar {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
  .pattern-name {{ width: 120px; font-size: 12px; color: #8b949e; text-align: right; }}
  .pattern-count {{ font-size: 12px; color: #c9d1d9; width: 40px; }}
  .pattern-fill {{ height: 16px; border-radius: 3px; min-width: 2px; }}
  pre.json {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; max-height: 400px; overflow-y: auto; }}
  .empty {{ color: #484f58; font-style: italic; padding: 20px; text-align: center; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>OMA Kiro Dashboard</h1>
    <div class="timestamp">Generated: {results['generated_at']}</div>
  </div>
</div>

<div class="cards">
  <div class="card blue">
    <div class="label">총 쿼리</div>
    <div class="value">{total_queries}</div>
    <div class="sub">파일 {len(files)}개</div>
  </div>
  <div class="card green">
    <div class="label">Rule 변환</div>
    <div class="value">{total_conversions}</div>
    <div class="sub">기계적 치환</div>
  </div>
  <div class="card yellow">
    <div class="label">LLM 필요</div>
    <div class="value">{total_llm}</div>
    <div class="sub">구조적 변환</div>
  </div>
  <div class="card">
    <div class="label">Phase</div>
    <div class="value">{progress.get('phase', progress.get('_pipeline', {}).get('current_phase_name', 'N/A'))}</div>
  </div>
</div>
"""

    # File summary table
    if files:
        html += "<h2>파일별 결과</h2>\n<table>\n"
        html += "<tr><th>파일</th><th>쿼리</th><th>Rule</th><th>LLM</th><th>변환</th><th>미변환</th><th>복잡도</th></tr>\n"
        for fname, fdata in files.items():
            parsed = fdata.get('parsed', {})
            meta = parsed.get('metadata', {}) if parsed else {}
            report = fdata.get('conversion_report', {}) or {}
            scores = fdata.get('complexity_scores', {}) or {}
            summary = scores.get('summary', {})

            queries = meta.get('total_queries', 0)
            rule = meta.get('rule_tagged', 0)
            llm = meta.get('llm_tagged', 0)
            conversions = report.get('total_replacements', 0)
            unconverted = report.get('unconverted_count', 0)
            avg_score = summary.get('average_score', '-')

            lvl_counts = ' '.join([f'L{i}:{summary.get(f"L{i}",0)}' for i in range(5) if summary.get(f'L{i}', 0) > 0])

            html += f"<tr><td>{fname}</td><td>{queries}</td><td>{rule}</td><td>{llm}</td>"
            html += f"<td><span class='badge badge-green'>{conversions}</span></td>"
            html += f"<td><span class='badge badge-{'red' if unconverted > 0 else 'gray'}'>{unconverted}</span></td>"
            html += f"<td>{lvl_counts} (avg:{avg_score})</td></tr>\n"
        html += "</table>\n"

    # Per-file details
    for fname, fdata in files.items():
        html += f"<h2>{fname}</h2>\n"

        # Oracle patterns
        parsed = fdata.get('parsed')
        if parsed:
            from collections import Counter
            patterns = Counter()
            for q in parsed.get('queries', []):
                for p in q.get('oracle_patterns', []):
                    patterns[p] += 1

            if patterns:
                max_count = max(patterns.values())
                html += "<h3>Oracle 패턴 분포</h3>\n<div class='section'>\n"
                for pat, cnt in patterns.most_common(15):
                    pct = cnt / max_count * 100
                    html += f"<div class='pattern-bar'>"
                    html += f"<div class='pattern-name'>{pat}</div>"
                    html += f"<div style='flex:1'><div class='pattern-fill bar-blue' style='width:{pct}%'></div></div>"
                    html += f"<div class='pattern-count'>{cnt}</div></div>\n"
                html += "</div>\n"

        # Complexity distribution
        scores = fdata.get('complexity_scores')
        if scores:
            summary = scores.get('summary', {})
            total = summary.get('total', 1)
            html += "<h3>복잡도 분포</h3>\n<div class='section'>\n<div class='bar'>\n"
            colors = {'L0': '#3fb950', 'L1': '#58a6ff', 'L2': '#d29922', 'L3': '#f0883e', 'L4': '#f85149'}
            for lvl in ['L0', 'L1', 'L2', 'L3', 'L4']:
                cnt = summary.get(lvl, 0)
                if cnt > 0:
                    pct = cnt / total * 100
                    html += f"<div class='bar-fill' style='width:{pct}%;background:{colors[lvl]}'></div>\n"
            html += "</div>\n"
            html += "<div style='display:flex;gap:16px;margin-top:8px;font-size:12px'>\n"
            for lvl in ['L0', 'L1', 'L2', 'L3', 'L4']:
                cnt = summary.get(lvl, 0)
                if cnt > 0:
                    html += f"<span style='color:{colors[lvl]}'>{lvl}: {cnt}</span>\n"
            html += "</div></div>\n"

        # Conversion report
        report = fdata.get('conversion_report')
        if report and report.get('rules_applied'):
            html += "<h3>변환 룰 적용 현황</h3>\n<table>\n"
            html += "<tr><th>룰</th><th>적용 횟수</th></tr>\n"
            for rule, cnt in sorted(report['rules_applied'].items(), key=lambda x: -x[1]):
                html += f"<tr><td>{rule}</td><td>{cnt}</td></tr>\n"
            html += "</table>\n"

        # Unconverted patterns
        if report and report.get('unconverted'):
            html += "<h3>미변환 패턴 (LLM 필요)</h3>\n<table>\n"
            html += "<tr><th>패턴</th><th>심각도</th></tr>\n"
            for u in report['unconverted']:
                sev = u.get('severity', 'unknown')
                badge = 'red' if sev == 'needs_llm' else 'yellow'
                html += f"<tr><td>{u.get('pattern','')}</td>"
                html += f"<td><span class='badge badge-{badge}'>{sev}</span></td></tr>\n"
            html += "</table>\n"

        # Residual patterns
        if report and report.get('residual_oracle_patterns'):
            html += "<h3>잔존 Oracle 패턴 (변환 후)</h3>\n<table>\n"
            html += "<tr><th>라인</th><th>패턴</th><th>쿼리</th><th>컨텍스트</th></tr>\n"
            for r in report['residual_oracle_patterns'][:30]:
                html += f"<tr><td>{r.get('line','')}</td><td>{r.get('pattern','')}</td>"
                html += f"<td>{r.get('query_id','')}</td>"
                ctx = r.get('context', '')[:80]
                html += f"<td style='font-size:11px;color:#8b949e'>{ctx}</td></tr>\n"
            if len(report['residual_oracle_patterns']) > 30:
                html += f"<tr><td colspan=4 class='empty'>... +{len(report['residual_oracle_patterns'])-30}건 더</td></tr>\n"
            html += "</table>\n"

    # Activity log
    if activity_log:
        html += "<h2>감사 로그 (최근 50건)</h2>\n<div class='section'>\n"
        for entry in activity_log[-50:]:
            log_type = entry.get('type', 'UNKNOWN')
            summary_text = entry.get('summary', '')
            ts = entry.get('timestamp', '')[:19]
            html += f"<div class='log-entry'>"
            html += f"<span class='log-time'>{ts}</span> "
            html += f"<span class='log-type log-type-{log_type}'>[{log_type}]</span> "
            html += f"{summary_text}</div>\n"
        html += "</div>\n"

    # Raw JSON viewer
    html += """
<h2>Raw JSON</h2>
<div class='section'>
<select id='json-select' onchange='showJson()' style='background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:8px;border-radius:4px;width:100%'>
<option value=''>-- 파일 선택 --</option>
"""
    json_data = {}
    for fname, fdata in files.items():
        for key, val in fdata.items():
            if val:
                json_id = f"{fname}/{key}"
                json_data[json_id] = val
                html += f"<option value='{json_id}'>{fname} / {key}.json</option>\n"
    if progress:
        json_data['progress.json'] = progress
        html += "<option value='progress.json'>progress.json</option>\n"

    html += f"""</select>
<pre class='json' id='json-view'></pre>
</div>

<script>
const jsonData = {json.dumps(json_data, ensure_ascii=False)};
function showJson() {{
  const sel = document.getElementById('json-select').value;
  const view = document.getElementById('json-view');
  if (sel && jsonData[sel]) {{
    view.textContent = JSON.stringify(jsonData[sel], null, 2);
  }} else {{
    view.textContent = '';
  }}
}}
</script>

</body>
</html>"""

    return html


def main():
    args = sys.argv[1:]
    no_open = '--no-open' in args
    serve_mode = '--port' in args

    results = collect_results()
    html = generate_html(results)

    os.makedirs(os.path.dirname(OUTPUT_HTML) or '.', exist_ok=True)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard generated: {OUTPUT_HTML}")
    print(f"  Files: {len(results['files'])}")
    print(f"  Log entries: {len(results['activity_log'])}")

    if serve_mode:
        port_idx = args.index('--port')
        port = int(args[port_idx + 1]) if port_idx + 1 < len(args) else 8080
        os.chdir(WORKSPACE)
        handler = http.server.SimpleHTTPRequestHandler
        server = http.server.HTTPServer(('', port), handler)
        print(f"\nServing at http://localhost:{port}/reports/dashboard.html")
        print("Press Ctrl+C to stop")
        webbrowser.open(f'http://localhost:{port}/reports/dashboard.html')
        server.serve_forever()
    elif not no_open:
        abs_path = os.path.abspath(OUTPUT_HTML)
        webbrowser.open(f'file://{abs_path}')


if __name__ == '__main__':
    main()
