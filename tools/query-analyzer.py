#!/usr/bin/env python3
"""
Phase 1.5: 의존성 분석 + 복잡도 분류 + 변환 순서 결정
parsed.json을 읽어 dependency-graph.json, complexity-scores.json, conversion-order.json을 생성.

Usage:
    python3 tools/query-analyzer.py <parsed.json> [<parsed2.json> ...]

Example:
    python3 tools/query-analyzer.py workspace/results/UserMapper/v1/parsed.json
    python3 tools/query-analyzer.py workspace/results/*/v1/parsed.json
"""

import json
import sys
from collections import defaultdict, deque
from pathlib import Path


# 복잡도 점수 매핑
ORACLE_SCORES = {
    # Rule 패턴 (기계적 변환 가능)
    'NVL': 1, 'NVL2': 1, 'DECODE': 1, 'SYSDATE': 1, 'SYSTIMESTAMP': 1,
    'ROWNUM': 1, 'NEXTVAL': 1, 'CURRVAL': 1, 'OUTER_JOIN_PLUS': 1,
    'FROM_DUAL': 1, 'MINUS': 1, 'TO_NUMBER': 1, 'INSTR': 1,
    'ADD_MONTHS': 1, 'MONTHS_BETWEEN': 1, 'LAST_DAY': 1,
    'GREATEST': 1, 'LEAST': 1, 'BITAND': 1,
    'REGEXP_LIKE': 1, 'REGEXP_REPLACE': 1, 'REGEXP_SUBSTR': 1,
    'REGEXP_INSTR': 1, 'REGEXP_COUNT': 1,
    'WM_CONCAT': 2, 'LISTAGG': 2,
    'DBMS_LOB_SUBSTR': 2, 'DBMS_LOB_GETLENGTH': 2, 'DBMS_LOB_INSTR': 2,
    'DBMS_RANDOM': 2,
    # 변환 불필요 (PG 호환)
    'SUBSTR': 0, 'TO_CHAR': 0, 'TO_DATE': 0, 'TRUNC': 1,
    # LLM 패턴 (구조적 변환 필요)
    'CONNECT_BY': 3, 'START_WITH': 3, 'MERGE_INTO': 3,
    'PIVOT': 2, 'UNPIVOT': 2,
    'ORACLE_HINT': 1,
    'XMLTYPE': 2, 'DBMS_CRYPTO': 2, 'DBMS_OUTPUT': 1,
    'MODEL_CLAUSE': 3, 'KEEP_DENSE_RANK': 2,
    'ROWID': 1, 'TABLE_FUNC': 2,
}

# 동적 SQL 태그별 점수
DYNAMIC_SCORES = {
    'if': 1, 'isNotNull': 1, 'isNotEmpty': 1, 'isNull': 1, 'isEmpty': 1,
    'isEqual': 1, 'isNotEqual': 1, 'isGreaterThan': 1, 'isGreaterEqual': 1,
    'isLessThan': 1, 'isLessEqual': 1,
    'isPropertyAvailable': 1, 'isNotPropertyAvailable': 1,
    'isParameterPresent': 1, 'isNotParameterPresent': 1,
    'choose': 2, 'when': 0, 'otherwise': 0,  # choose만 카운트
    'foreach': 2, 'iterate': 2,
    'where': 0, 'set': 0, 'trim': 0, 'bind': 0, 'dynamic': 1,
}


def classify_level(score):
    """점수 → 레벨 분류."""
    if score == 0:
        return 'L0', 'Static'
    elif score <= 3:
        return 'L1', 'Simple Rule'
    elif score <= 6:
        return 'L2', 'Dynamic Simple'
    elif score <= 12:
        return 'L3', 'Dynamic Complex'
    else:
        return 'L4', 'Oracle Complex'


def analyze(parsed_path):
    """parsed.json을 분석하여 3개 JSON 파일 생성."""
    with open(parsed_path, 'r', encoding='utf-8') as f:
        parsed = json.load(f)

    out_dir = Path(parsed_path).parent
    source = parsed['source_file']
    fragments = {frag['id']: frag for frag in parsed.get('sql_fragments', [])}
    queries = parsed.get('queries', [])

    # === 1. Dependency Graph ===
    nodes = {}
    edges = []

    # SQL fragments as nodes
    for frag in parsed.get('sql_fragments', []):
        nodes[frag['id']] = {
            'query_id': frag['id'],
            'type': 'sql_fragment',
            'depends_on': [],
            'dependents': [],
        }

    # Queries as nodes
    for q in queries:
        qid = q['query_id']
        deps = []
        for inc in q.get('includes', []):
            deps.append(inc)
            edges.append({'from': qid, 'to': inc, 'type': 'SQL_FRAGMENT'})
        nodes[qid] = {
            'query_id': qid,
            'type': q['type'],
            'depends_on': deps,
            'dependents': [],
        }

    # Populate dependents
    for e in edges:
        if e['to'] in nodes:
            nodes[e['to']]['dependents'].append(e['from'])

    # === 2. Complexity Scoring ===
    scores = []
    for q in queries:
        score = 0
        breakdown = {}

        # Oracle 패턴 점수
        for pat in q.get('oracle_patterns', []):
            s = ORACLE_SCORES.get(pat, 1)
            if s > 0:
                key = f'oracle_{pat.lower()}'
                breakdown[key] = breakdown.get(key, 0) + s
                score += s

        # 동적 SQL 점수
        for dyn in q.get('dynamic_elements', []):
            tag = dyn.get('tag', '')
            s = DYNAMIC_SCORES.get(tag, 0)
            if s > 0:
                key = f'dynamic_{tag}'
                breakdown[key] = breakdown.get(key, 0) + s
                score += s

        # Include 참조 점수
        for inc in q.get('includes', []):
            breakdown['include_ref'] = breakdown.get('include_ref', 0) + 1
            score += 1

        # SelectKey 점수
        if q.get('select_key'):
            breakdown['select_key'] = 1
            score += 1

        # Dollar substitution 경고
        if q.get('dollar_substitution'):
            breakdown['dollar_substitution'] = 1
            score += 1

        level, level_name = classify_level(score)
        scores.append({
            'query_id': q['query_id'],
            'score': score,
            'level': level,
            'level_name': level_name,
            'breakdown': breakdown,
        })

    # Summary
    summary = defaultdict(int)
    for s in scores:
        summary[s['level']] += 1
    summary['total'] = len(scores)
    summary['average_score'] = round(
        sum(s['score'] for s in scores) / max(len(scores), 1), 1
    )

    # === 3. Topological Sort (변환 순서) ===
    all_ids = set(nodes.keys())
    in_degree = defaultdict(int)
    adj = defaultdict(list)  # from dependency → to dependent

    for e in edges:
        if e['to'] in all_ids:
            adj[e['to']].append(e['from'])
            in_degree[e['from']] += 1

    for nid in all_ids:
        if nid not in in_degree:
            in_degree[nid] = 0

    # BFS topological sort
    queue = deque(sorted([n for n in all_ids if in_degree[n] == 0]))
    layers = []
    layer_map = {}
    layer_idx = 0

    while queue:
        current = sorted(queue)
        for n in current:
            layer_map[n] = layer_idx
        layers.append({
            'layer': layer_idx,
            'queries': current,
            'description': f'Layer {layer_idx}' + (' (리프 — 의존성 없음)' if layer_idx == 0 else ''),
        })

        next_q = deque()
        for n in current:
            for dep in adj.get(n, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    next_q.append(dep)

        queue = next_q
        layer_idx += 1

    # Remaining (cycles)
    remaining = sorted([n for n in all_ids if n not in layer_map])
    cycles = []
    if remaining:
        layers.append({
            'layer': layer_idx,
            'queries': remaining,
            'description': f'Layer {layer_idx} (순환 의존 — 동시 처리)',
        })
        cycles = remaining

    # === Write outputs ===

    # dependency-graph.json
    dep_graph = {
        'version': 1,
        'source_file': source,
        'nodes': list(nodes.values()),
        'edges': edges,
        'cycles': cycles,
        'total_nodes': len(nodes),
        'total_edges': len(edges),
    }
    with open(out_dir / 'dependency-graph.json', 'w', encoding='utf-8') as f:
        json.dump(dep_graph, f, indent=2, ensure_ascii=False)

    # complexity-scores.json
    comp_scores = {
        'version': 1,
        'source_file': source,
        'queries': scores,
        'summary': dict(summary),
    }
    with open(out_dir / 'complexity-scores.json', 'w', encoding='utf-8') as f:
        json.dump(comp_scores, f, indent=2, ensure_ascii=False)

    # conversion-order.json
    conv_order = {
        'version': 1,
        'source_file': source,
        'layers': layers,
        'total_layers': len(layers),
        'conversion_strategy': 'Layer 0부터 순차적으로 변환 → 검증 → 다음 Layer',
    }
    with open(out_dir / 'conversion-order.json', 'w', encoding='utf-8') as f:
        json.dump(conv_order, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"분석 완료: {source}")
    print(f"  쿼리: {len(queries)}개, 레이어: {len(layers)}개")
    for lvl in ['L0', 'L1', 'L2', 'L3', 'L4']:
        cnt = summary.get(lvl, 0)
        if cnt > 0:
            print(f"  {lvl}: {cnt}개")
    print(f"  평균 복잡도: {summary['average_score']}")
    if cycles:
        print(f"  순환 의존: {len(cycles)}건")

    return comp_scores


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 tools/query-analyzer.py <parsed.json> [<parsed2.json> ...]")
        print("")
        print("Example:")
        print("  python3 tools/query-analyzer.py workspace/results/UserMapper/v1/parsed.json")
        sys.exit(1)

    for path in sys.argv[1:]:
        analyze(path)
        print()
