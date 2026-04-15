#!/usr/bin/env python3
"""
Learn from Results — 마이그레이션 결과 분석 + 패턴 추출 + 룰 승격 제안.

Usage:
    python3 tools/learn-from-results.py \
      --matrix pipeline/step-4-report/output/query-matrix.json \
      --output pipeline/learning/

파이프라인 완료 후 수동 실행. 반복 패턴을 찾아 edge-case → rule 승격을 제안.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ── Pattern extraction ──

# 에러 메시지에서 패턴 추출 정규식
_ERROR_PATTERNS = [
    (r'function\s+(\w+)\(.*?\)\s+does not exist', 'FUNCTION_MISSING'),
    (r'relation\s+"?(\w+)"?\s+does not exist', 'RELATION_MISSING'),
    (r'column\s+"?(\w+)"?\s+.*?does not exist', 'COLUMN_MISSING'),
    (r'operator does not exist:\s+(\w+)\s+', 'OPERATOR_MISMATCH'),
    (r'invalid input syntax for (?:type\s+)?(\w+)', 'TYPE_MISMATCH'),
    (r'syntax error at or near\s+"(\w+)"', 'SYNTAX_ERROR'),
    (r'(SYSDATE|ROWNUM|NVL|DECODE|TO_DATE|TO_CHAR|TO_NUMBER)', 'RESIDUAL_ORACLE'),
]

# fix_applied에서 변환 패턴 추출
_FIX_PATTERNS = [
    (r'NVL\s*→\s*COALESCE', 'NVL_TO_COALESCE'),
    (r'SYSDATE\s*→\s*(?:NOW|CURRENT_TIMESTAMP)', 'SYSDATE_TO_NOW'),
    (r'DECODE\s*→\s*CASE', 'DECODE_TO_CASE'),
    (r'ROWNUM\s*→\s*(?:LIMIT|ROW_NUMBER)', 'ROWNUM_TO_LIMIT'),
    (r'TO_DATE\s*→', 'TO_DATE_CONVERT'),
    (r'TO_CHAR\s*→', 'TO_CHAR_CONVERT'),
    (r'TO_NUMBER\s*→', 'TO_NUMBER_CONVERT'),
    (r'CONNECT\s*BY\s*→\s*(?:RECURSIVE|WITH)', 'CONNECT_BY_TO_CTE'),
    (r'MERGE\s*→', 'MERGE_TO_UPSERT'),
    (r'SUBSTR\s*→\s*SUBSTRING', 'SUBSTR_TO_SUBSTRING'),
    (r'(?:NVL2|NULLIF)\s*→', 'NULL_FUNC_CONVERT'),
    (r'(?:subquery|alias)\s*→\s*AS', 'SUBQUERY_ALIAS'),
    (r'(?:UPDATE|SET)\s+.*alias', 'UPDATE_ALIAS_FIX'),
    (r'(?:varchar|int).*(?:cast|::)', 'TYPE_CAST_FIX'),
    (r'\$\{.*\}\s*→', 'DOLLAR_SUBST_FIX'),
]


def _extract_error_pattern(error_detail):
    """에러 메시지에서 분류 가능한 패턴 추출."""
    if not error_detail:
        return None, None
    for regex, category in _ERROR_PATTERNS:
        m = re.search(regex, error_detail, re.I)
        if m:
            return category, m.group(1) if m.lastindex else ''
    return 'OTHER', error_detail[:80]


def _extract_fix_pattern(fix_applied):
    """수정 내용에서 변환 패턴 추출."""
    if not fix_applied:
        return None
    for regex, category in _FIX_PATTERNS:
        if re.search(regex, fix_applied, re.I):
            return category
    return 'CUSTOM_FIX'


def _load_existing_rules(rules_path):
    """기존 oracle-pg-rules.md에서 룰명 추출."""
    rules = set()
    if not Path(rules_path).exists():
        return rules
    text = Path(rules_path).read_text(encoding='utf-8')
    for m in re.finditer(r'##\s+(.+)', text):
        rules.add(m.group(1).strip().upper())
    # 패턴 키워드도 추출
    for m in re.finditer(r'`(\w+)`\s*→\s*`(\w+)`', text):
        rules.add(f"{m.group(1).upper()}_TO_{m.group(2).upper()}")
    return rules


def _load_existing_edges(edge_path):
    """기존 edge-cases.md에서 케이스명 추출."""
    edges = set()
    if not Path(edge_path).exists():
        return edges
    text = Path(edge_path).read_text(encoding='utf-8')
    for m in re.finditer(r'##\s+(.+)', text):
        edges.add(m.group(1).strip())
    return edges


# ── Analysis ──

def analyze_matrix(matrix_path):
    """query-matrix.json 분석."""
    data = json.loads(Path(matrix_path).read_text(encoding='utf-8'))
    queries = data.get('queries', [])

    results = {
        'total_queries': len(queries),
        'healed_patterns': [],      # PASS_HEALED에서 추출한 성공 패턴
        'escalated_patterns': [],    # FAIL_ESCALATED 미해결 패턴
        'error_distribution': Counter(),
        'fix_distribution': Counter(),
        'rule_effectiveness': Counter(),  # conversion_history에서 룰 적용 횟수
        'state_counts': Counter(),
    }

    for q in queries:
        state = q.get('final_state', q.get('status', 'UNKNOWN'))
        results['state_counts'][state] += 1

        # conversion_history → 룰 적용 횟수
        for ch in q.get('conversion_history', []):
            pattern = ch.get('pattern', '')
            if pattern:
                results['rule_effectiveness'][pattern] += 1

        # attempts → 에러/수정 패턴
        for att in q.get('attempts', []):
            err_cat, err_detail = _extract_error_pattern(att.get('error_detail', ''))
            fix_pat = _extract_fix_pattern(att.get('fix_applied', ''))
            att_result = att.get('result', '')

            if err_cat:
                results['error_distribution'][err_cat] += 1

            if fix_pat:
                results['fix_distribution'][fix_pat] += 1

            entry = {
                'query_id': q.get('query_id', ''),
                'file': q.get('original_file', ''),
                'error_category': err_cat,
                'error_detail': err_detail,
                'fix_pattern': fix_pat,
                'fix_applied': att.get('fix_applied', ''),
                'result': att_result,
            }

            if state == 'PASS_HEALED' and att_result == 'pass':
                results['healed_patterns'].append(entry)
            elif state == 'FAIL_ESCALATED':
                results['escalated_patterns'].append(entry)

    return results


def build_cumulative(new_run, cumulative_path):
    """누적 패턴 카운트 갱신."""
    if Path(cumulative_path).exists():
        cumulative = json.loads(Path(cumulative_path).read_text(encoding='utf-8'))
    else:
        cumulative = {'patterns': {}, 'runs': []}

    today = datetime.now().strftime('%Y%m%d')
    cumulative['runs'].append(today)

    # 성공 패턴 누적
    for entry in new_run['healed_patterns']:
        pat = entry.get('fix_pattern', 'UNKNOWN')
        if pat not in cumulative['patterns']:
            cumulative['patterns'][pat] = {
                'count': 0,
                'first_seen': today,
                'last_seen': today,
                'status': 'edge_case',
                'examples': [],
            }
        p = cumulative['patterns'][pat]
        p['count'] += 1
        p['last_seen'] = today
        # 예시 최대 3개 유지
        if len(p['examples']) < 3:
            p['examples'].append({
                'query_id': entry['query_id'],
                'file': entry['file'],
                'fix': entry.get('fix_applied', '')[:100],
            })

    # 실패 패턴 누적
    for entry in new_run['escalated_patterns']:
        pat = entry.get('error_category', 'UNKNOWN')
        key = f"UNRESOLVED_{pat}"
        if key not in cumulative['patterns']:
            cumulative['patterns'][key] = {
                'count': 0,
                'first_seen': today,
                'last_seen': today,
                'status': 'unresolved',
                'examples': [],
            }
        p = cumulative['patterns'][key]
        p['count'] += 1
        p['last_seen'] = today
        if len(p['examples']) < 3:
            p['examples'].append({
                'query_id': entry['query_id'],
                'file': entry['file'],
                'error': entry.get('error_detail', '')[:100],
            })

    return cumulative


def evaluate_promotions(cumulative, existing_rules, existing_edges, threshold=3):
    """승격 후보 평가."""
    promotions = []

    # 기계적 치환 가능한 패턴 (converter 룰 추가 가능)
    mechanical_patterns = {
        'NVL_TO_COALESCE', 'SYSDATE_TO_NOW', 'DECODE_TO_CASE',
        'ROWNUM_TO_LIMIT', 'SUBSTR_TO_SUBSTRING', 'SUBQUERY_ALIAS',
        'UPDATE_ALIAS_FIX', 'TO_DATE_CONVERT', 'TO_CHAR_CONVERT',
        'TO_NUMBER_CONVERT',
    }

    for pat, info in cumulative['patterns'].items():
        count = info['count']
        status = info['status']

        # 이미 승격된 것은 스킵
        if status == 'rule':
            continue

        # 기존 룰에 이미 있는지 확인
        if any(pat.upper() in r for r in existing_rules):
            info['status'] = 'rule'
            continue

        if count >= threshold:
            is_mechanical = pat in mechanical_patterns
            promotions.append({
                'pattern': pat,
                'count': count,
                'first_seen': info['first_seen'],
                'last_seen': info['last_seen'],
                'target': 'oracle-to-pg-converter.py' if is_mechanical else 'oracle-pg-rules.md',
                'type': 'mechanical' if is_mechanical else 'guide',
                'examples': info['examples'],
            })
            info['status'] = 'promotion_candidate'
        elif count >= 1 and status == 'edge_case':
            # 기존 edge-cases에 없으면 추가 제안
            if not any(pat.lower() in e.lower() for e in existing_edges):
                promotions.append({
                    'pattern': pat,
                    'count': count,
                    'target': 'edge-cases.md',
                    'type': 'edge_case',
                    'examples': info['examples'],
                })

    return promotions


def generate_promotion_md(promotions, run_result):
    """승격 후보 마크다운 생성."""
    lines = [
        f"# Learning Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        "",
        f"- Total queries: {run_result['total_queries']}",
        f"- States: {dict(run_result['state_counts'])}",
        f"- Healed patterns: {len(run_result['healed_patterns'])}",
        f"- Escalated patterns: {len(run_result['escalated_patterns'])}",
        "",
    ]

    # 룰 적용 현황
    if run_result['rule_effectiveness']:
        lines.append("## Rule Effectiveness (이번 실행)")
        lines.append("")
        lines.append("| Pattern | Applied Count |")
        lines.append("|---------|--------------|")
        for pat, cnt in run_result['rule_effectiveness'].most_common(20):
            lines.append(f"| {pat} | {cnt} |")
        lines.append("")

    # 승격 후보
    converter_candidates = [p for p in promotions if p['target'] == 'oracle-to-pg-converter.py']
    rule_candidates = [p for p in promotions if p['target'] == 'oracle-pg-rules.md']
    edge_candidates = [p for p in promotions if p['target'] == 'edge-cases.md']

    if converter_candidates:
        lines.append("## Converter Rule 추가 후보 (기계적 치환)")
        lines.append("")
        for p in sorted(converter_candidates, key=lambda x: -x['count']):
            lines.append(f"### {p['pattern']} ({p['count']}회)")
            lines.append("")
            for ex in p['examples']:
                lines.append(f"- `{ex['query_id']}` ({ex['file']}): {ex.get('fix', '')}")
            lines.append("")

    if rule_candidates:
        lines.append("## oracle-pg-rules.md 추가 후보 (가이드)")
        lines.append("")
        for p in sorted(rule_candidates, key=lambda x: -x['count']):
            lines.append(f"### {p['pattern']} ({p['count']}회)")
            lines.append("")
            for ex in p['examples']:
                lines.append(f"- `{ex['query_id']}` ({ex['file']}): {ex.get('fix', '')}")
            lines.append("")

    if edge_candidates:
        lines.append("## edge-cases.md 추가 후보")
        lines.append("")
        for p in sorted(edge_candidates, key=lambda x: -x['count']):
            lines.append(f"- **{p['pattern']}** ({p['count']}회): {p['examples'][0].get('fix', '') or p['examples'][0].get('error', '')}")
        lines.append("")

    # 미해결 패턴
    unresolved = [p for p in promotions if p['pattern'].startswith('UNRESOLVED_')]
    if unresolved:
        lines.append("## Unresolved (DBA/수동 검토 필요)")
        lines.append("")
        for p in sorted(unresolved, key=lambda x: -x['count']):
            lines.append(f"- **{p['pattern']}** ({p['count']}회)")
            for ex in p['examples']:
                lines.append(f"  - `{ex['query_id']}` ({ex['file']}): {ex.get('error', '')}")
        lines.append("")

    if not promotions:
        lines.append("## No promotion candidates found")
        lines.append("")
        lines.append("All patterns are either already in rules or below threshold.")
        lines.append("")

    return '\n'.join(lines)


# ── Main ──

def main():
    ap = argparse.ArgumentParser(description='Learn from migration results')
    ap.add_argument('--matrix', required=True, help='query-matrix.json path')
    ap.add_argument('--rules', default='.claude/rules/oracle-pg-rules.md')
    ap.add_argument('--edge-cases', default='.claude/rules/edge-cases.md')
    ap.add_argument('--output', default='pipeline/learning/')
    ap.add_argument('--threshold', type=int, default=3, help='Promotion threshold (default: 3)')
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("=== Learn from Results ===\n")

    # 1. Analyze
    print(f"  Analyzing: {args.matrix}")
    run_result = analyze_matrix(args.matrix)
    print(f"  Queries: {run_result['total_queries']}")
    print(f"  States: {dict(run_result['state_counts'])}")
    print(f"  Healed: {len(run_result['healed_patterns'])} fix patterns")
    print(f"  Escalated: {len(run_result['escalated_patterns'])} unresolved")
    print(f"  Error types: {dict(run_result['error_distribution'])}")
    print(f"  Fix types: {dict(run_result['fix_distribution'])}")
    print(f"  Rule hits: {sum(run_result['rule_effectiveness'].values())} total")

    # 2. Cumulative update
    cumulative_path = out / 'cumulative.json'
    cumulative = build_cumulative(run_result, cumulative_path)
    cumulative_path.write_text(json.dumps(cumulative, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n  Cumulative: {len(cumulative['patterns'])} patterns across {len(cumulative['runs'])} runs")

    # 3. Evaluate promotions
    existing_rules = _load_existing_rules(args.rules)
    existing_edges = _load_existing_edges(args.edge_cases)
    promotions = evaluate_promotions(cumulative, existing_rules, existing_edges, args.threshold)
    print(f"  Promotion candidates: {len(promotions)}")

    # 4. Save run result
    today = datetime.now().strftime('%Y%m%d')
    run_path = out / f'run-{today}.json'
    run_result['state_counts'] = dict(run_result['state_counts'])
    run_result['error_distribution'] = dict(run_result['error_distribution'])
    run_result['fix_distribution'] = dict(run_result['fix_distribution'])
    run_result['rule_effectiveness'] = dict(run_result['rule_effectiveness'])
    run_path.write_text(json.dumps(run_result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"  Run saved: {run_path}")

    # 5. Generate promotion markdown
    md = generate_promotion_md(promotions, run_result)
    md_path = out / 'promotion-candidates.md'
    md_path.write_text(md, encoding='utf-8')
    print(f"  Promotions: {md_path}")

    # Summary
    converter_count = sum(1 for p in promotions if p.get('target') == 'oracle-to-pg-converter.py')
    rule_count = sum(1 for p in promotions if p.get('target') == 'oracle-pg-rules.md')
    edge_count = sum(1 for p in promotions if p.get('target') == 'edge-cases.md')
    print(f"\n=== Done ===")
    print(f"  Converter rule candidates: {converter_count}")
    print(f"  oracle-pg-rules candidates: {rule_count}")
    print(f"  edge-cases candidates: {edge_count}")
    if promotions:
        print(f"\n  Review: cat {md_path}")


if __name__ == '__main__':
    main()
