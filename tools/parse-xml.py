#!/usr/bin/env python3
"""
MyBatis/iBatis XML Chunk Parser
xml-splitter.py로 분할된 chunk들을 파싱하여 parsed.json을 생성한다.
Oracle 패턴 감지, 동적 SQL 식별, 파라미터 추출을 수행.

Usage:
    python3 tools/parse-xml.py <chunks_dir> <output_json>

Example:
    python3 tools/parse-xml.py workspace/results/UserMapper/v1/chunks/ workspace/results/UserMapper/v1/parsed.json
"""

import xml.etree.ElementTree as ET
import json
import re
import sys
import os
from pathlib import Path

# Oracle patterns → rule (기계적 변환 가능)
RULE_PATTERNS = {
    'NVL2': r'\bNVL2\s*\(',
    'NVL': r'\bNVL\s*\(',
    'DECODE': r'\bDECODE\s*\(',
    'SYSDATE': r'\bSYSDATE\b',
    'SYSTIMESTAMP': r'\bSYSTIMESTAMP\b',
    'ROWNUM': r'\bROWNUM\b',
    'NEXTVAL': r'\.\s*NEXTVAL\b',
    'CURRVAL': r'\.\s*CURRVAL\b',
    'OUTER_JOIN_PLUS': r'\(\+\)',
    'FROM_DUAL': r'\bFROM\s+DUAL\b',
    'LISTAGG': r'\bLISTAGG\s*\(',
    'MINUS': r'\bMINUS\b',
    'TO_DATE': r'\bTO_DATE\s*\(',
    'TO_CHAR': r'\bTO_CHAR\s*\(',
    'TO_NUMBER': r'\bTO_NUMBER\s*\(',
    'TRUNC': r'\bTRUNC\s*\(',
    'ADD_MONTHS': r'\bADD_MONTHS\s*\(',
    'MONTHS_BETWEEN': r'\bMONTHS_BETWEEN\s*\(',
    'LAST_DAY': r'\bLAST_DAY\s*\(',
    'INSTR': r'\bINSTR\s*\(',
    'SUBSTR': r'\bSUBSTR\s*\(',
    'WM_CONCAT': r'\bWM_CONCAT\s*\(',
    'GREATEST': r'\bGREATEST\s*\(',
    'LEAST': r'\bLEAST\s*\(',
    'REGEXP_LIKE': r'\bREGEXP_LIKE\s*\(',
    'REGEXP_SUBSTR': r'\bREGEXP_SUBSTR\s*\(',
    'REGEXP_REPLACE': r'\bREGEXP_REPLACE\s*\(',
    'REGEXP_INSTR': r'\bREGEXP_INSTR\s*\(',
    'REGEXP_COUNT': r'\bREGEXP_COUNT\s*\(',
    'DBMS_LOB_SUBSTR': r'\bDBMS_LOB\s*\.\s*SUBSTR\b',
    'DBMS_LOB_GETLENGTH': r'\bDBMS_LOB\s*\.\s*GETLENGTH\b',
    'DBMS_LOB_INSTR': r'\bDBMS_LOB\s*\.\s*INSTR\b',
    'DBMS_RANDOM': r'\bDBMS_RANDOM\s*\.',
    'BITAND': r'\bBITAND\s*\(',
    'SYSDATE_ARITH': r'\bSYSDATE\s*[+-]\s*\d+',
}

# Post-conversion residual patterns (detect Oracle remnants in converted output)
POST_CONVERSION_PATTERNS = {
    'TIMESTAMP_MINUS_INT': r'\bCURRENT_TIMESTAMP\s*-\s*\d+\b(?!\s*days)',
    'BARE_TRUNC': r'(?<!DATE_)\bTRUNC\s*\(',
}

# Oracle patterns → llm (구조적 변환 필요)
LLM_PATTERNS = {
    'CONNECT_BY': r'\bCONNECT\s+BY\b',
    'START_WITH': r'\bSTART\s+WITH\b',
    'MERGE_INTO': r'\bMERGE\s+INTO\b',
    'PIVOT': r'\bPIVOT\s*\(',
    'UNPIVOT': r'\bUNPIVOT\s*\(',
    'ORACLE_HINT': r'/\*\+.*?\*/',
    'XMLTYPE': r'\bXMLTYPE\b',
    'DBMS_CRYPTO': r'\bDBMS_CRYPTO\s*\.',
    'DBMS_OUTPUT': r'\bDBMS_OUTPUT\s*\.',
    'MODEL_CLAUSE': r'\bMODEL\s+',
    'KEEP_DENSE_RANK': r'\bKEEP\s*\(\s*DENSE_RANK\b',
    'ROWID': r'\bROWID\b',
    'TABLE_FUNC': r'\bTABLE\s*\(\s*\w+',
    'CUSTOM_PACKAGE': r'\b(?!DBMS_|UTL_|SYS_)[A-Z][A-Z0-9_]+\s*\.\s*[A-Z]\w*\s*\(',
}

DYNAMIC_TAGS_MYBATIS3 = {'if', 'choose', 'when', 'otherwise', 'where', 'set', 'trim', 'foreach', 'bind'}
DYNAMIC_TAGS_IBATIS2 = {'dynamic', 'isNull', 'isNotNull', 'isEmpty', 'isNotEmpty',
                         'isEqual', 'isNotEqual', 'isGreaterThan', 'isGreaterEqual',
                         'isLessThan', 'isLessEqual', 'isPropertyAvailable',
                         'isNotPropertyAvailable', 'isParameterPresent',
                         'isNotParameterPresent', 'iterate'}


def get_all_text(elem):
    """재귀적으로 요소의 모든 텍스트를 추출."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return ' '.join(parts)


def extract_params(sql_text):
    """MyBatis/iBatis 파라미터 추출."""
    params = []
    seen = set()

    # MyBatis 3.x: #{param} #{param,jdbcType=VARCHAR}
    for m in re.finditer(r'#\{(\w+)(?:,\s*jdbcType\s*=\s*(\w+))?\}', sql_text):
        name, jdbc = m.group(1), m.group(2)
        if name not in seen:
            seen.add(name)
            params.append({"name": name, "jdbc_type": jdbc, "notation": "#{}"})

    # iBatis 2.x: #param#
    for m in re.finditer(r'#(\w+)#', sql_text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            params.append({"name": name, "jdbc_type": None, "notation": "#prop#"})

    # Dollar substitution: ${param}
    for m in re.finditer(r'\$\{(\w+)\}', sql_text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            params.append({"name": name, "jdbc_type": None, "notation": "${}"})

    return params


def extract_dynamic_elements(elem, framework='mybatis3'):
    """동적 SQL 요소 추출."""
    dynamic_tags = DYNAMIC_TAGS_MYBATIS3 if framework == 'mybatis3' else DYNAMIC_TAGS_IBATIS2
    elements = []
    for child in elem:
        tag = child.tag
        if tag in dynamic_tags:
            el = {"tag": tag}
            if tag in ('if', 'when'):
                el["test"] = child.get('test', '')
            elif tag in ('isNull', 'isNotNull', 'isEmpty', 'isNotEmpty',
                          'isEqual', 'isNotEqual', 'isGreaterThan', 'isGreaterEqual',
                          'isLessThan', 'isLessEqual'):
                el["property"] = child.get('property', '')
                if child.get('compareValue'):
                    el["compareValue"] = child.get('compareValue')
            elif tag == 'foreach':
                el["collection"] = child.get('collection', '')
                el["item"] = child.get('item', '')
            elif tag == 'iterate':
                el["property"] = child.get('property', '')
                el["conjunction"] = child.get('conjunction', '')
            el["content"] = get_all_text(child).strip()[:200]
            elements.append(el)
        elements.extend(extract_dynamic_elements(child, framework))
    return elements


def detect_oracle_patterns(sql_text):
    """Oracle 패턴 감지 및 rule/llm 분류."""
    rule_found = []
    llm_found = []

    for name, pattern in RULE_PATTERNS.items():
        if re.search(pattern, sql_text, re.IGNORECASE | re.DOTALL):
            rule_found.append(name)

    for name, pattern in LLM_PATTERNS.items():
        if re.search(pattern, sql_text, re.IGNORECASE | re.DOTALL):
            llm_found.append(name)

    tags = []
    if llm_found:
        tags.append("llm")
    if rule_found:
        tags.append("rule")
    if not tags:
        tags.append("rule")  # Oracle 패턴 없으면 변환 불필요 (rule로 통과)

    return tags, rule_found + llm_found


def extract_includes(elem):
    """include refid 추출."""
    includes = []
    for inc in elem.iter('include'):
        refid = inc.get('refid', '')
        if refid:
            includes.append(refid)
    return includes


def extract_select_key(elem):
    """selectKey 추출."""
    sk = elem.find('selectKey')
    if sk is None:
        return None
    return {
        "key_property": sk.get('keyProperty', sk.get('keyProperty', '')),
        "result_type": sk.get('resultType', sk.get('resultClass', '')),
        "order": sk.get('order', sk.get('type', 'BEFORE')),
        "sql": get_all_text(sk).strip()
    }


def parse_chunks(chunks_dir):
    """chunk 디렉토리의 모든 파일을 파싱하여 parsed.json 구조를 생성."""
    meta_path = Path(chunks_dir) / '_metadata.json'
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    source_file = meta['source_file']
    framework = meta['framework']
    namespace = meta['namespace']

    sql_fragments = []
    queries = []
    warnings = []

    query_types = {'select', 'insert', 'update', 'delete', 'statement', 'procedure'}

    for chunk in meta['chunks']:
        chunk_path = Path(chunks_dir) / chunk['file']
        if not chunk_path.exists():
            warnings.append(f"{chunk['id']}: chunk 파일 없음 ({chunk['file']})")
            continue

        try:
            tree = ET.parse(chunk_path)
            root = tree.getroot()
        except ET.ParseError as e:
            warnings.append(f"{chunk['id']}: XML 파싱 에러 ({e})")
            continue

        elem = root[0] if len(root) > 0 else None
        if elem is None:
            continue

        cid = chunk['id']
        ctype = chunk['type']

        if ctype == 'sql':
            sql_text = get_all_text(elem).strip()
            sql_fragments.append({"id": cid, "sql": sql_text})

        elif ctype in query_types:
            sql_raw = get_all_text(elem).strip()
            params = extract_params(sql_raw)
            dynamic = extract_dynamic_elements(elem, framework)
            oracle_tags, oracle_patterns = detect_oracle_patterns(sql_raw)
            includes = extract_includes(elem)
            select_key = extract_select_key(elem)

            query = {
                "query_id": cid,
                "type": ctype,
                "parameter_type": elem.get('parameterType', elem.get('parameterClass')),
                "result_type": elem.get('resultType', elem.get('resultClass')),
                "result_map": elem.get('resultMap'),
                "statement_type": elem.get('statementType', 'PREPARED'),
                "sql_raw": sql_raw,
                "sql_branches": [{"condition": "always", "sql": sql_raw}],
                "dynamic_elements": dynamic,
                "parameters": params,
                "oracle_tags": oracle_tags,
                "oracle_patterns": oracle_patterns,
                "includes": includes,
                "select_key": select_key,
            }

            # ${} 문자열 치환 감지
            if re.search(r'\$\{\w+\}', sql_raw):
                query["dollar_substitution"] = True
                warnings.append(
                    f"{cid}: ${{...}} 사용 감지 — 런타임 문자열 치환으로 Oracle 구문이 숨어있을 수 있음"
                )

            queries.append(query)
        # resultMap, parameterMap, cacheModel 등은 구조 참조용으로 스킵

    # 통계
    rule_count = sum(1 for q in queries if 'rule' in q['oracle_tags'])
    llm_count = sum(1 for q in queries if 'llm' in q['oracle_tags'])
    has_dyn = any(len(q['dynamic_elements']) > 0 for q in queries)
    has_inc = any(len(q['includes']) > 0 for q in queries)
    has_sk = any(q['select_key'] is not None for q in queries)
    ibatis = framework == 'ibatis2'

    parsed = {
        "version": 1,
        "source_file": source_file,
        "framework": framework,
        "namespace": namespace,
        "sql_fragments": sql_fragments,
        "queries": queries,
        "metadata": {
            "total_queries": len(queries),
            "rule_tagged": rule_count,
            "llm_tagged": llm_count,
            "has_dynamic_sql": has_dyn,
            "has_includes": has_inc,
            "has_select_key": has_sk,
            "ibatis_specific": ibatis,
        },
        "warnings": warnings,
    }

    return parsed


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 tools/parse-xml.py <chunks_dir> <output_json>")
        print("")
        print("Example:")
        print("  python3 tools/parse-xml.py workspace/results/UserMapper/v1/chunks/ workspace/results/UserMapper/v1/parsed.json")
        sys.exit(1)

    chunks_dir = sys.argv[1]
    output_path = sys.argv[2]

    if not Path(chunks_dir).exists():
        print(f"Error: chunks directory not found: {chunks_dir}")
        sys.exit(1)

    meta_path = Path(chunks_dir) / '_metadata.json'
    if not meta_path.exists():
        print(f"Error: _metadata.json not found in {chunks_dir}")
        print("Run xml-splitter.py first.")
        sys.exit(1)

    import time as _time
    _start = _time.time()

    parsed = parse_chunks(chunks_dir)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    _elapsed = int((_time.time() - _start) * 1000)

    m = parsed['metadata']
    print(f"Parsed: {parsed['source_file']}")
    print(f"  Queries: {m['total_queries']} (rule: {m['rule_tagged']}, llm: {m['llm_tagged']})")
    print(f"  Dynamic SQL: {m['has_dynamic_sql']}, Includes: {m['has_includes']}, SelectKey: {m['has_select_key']}")
    if parsed['warnings']:
        print(f"  Warnings: {len(parsed['warnings'])}")
        for w in parsed['warnings'][:5]:
            print(f"    - {w}")
        if len(parsed['warnings']) > 5:
            print(f"    ... and {len(parsed['warnings']) - 5} more")

    # Initialize query tracking
    try:
        from tracking_utils import TrackingManager
        tm = TrackingManager(os.path.dirname(output_path))
        count = tm.init_tracking(parsed['source_file'], parsed['queries'])
        print(f"  Query tracking initialized: {count} queries")
    except Exception as e:
        print(f"  Warning: Could not initialize query tracking: {e}")

    # Update progress.json
    try:
        from tracking_utils import TrackingManager
        progress_path = os.path.join(os.path.dirname(os.path.dirname(output_path)), '..', 'progress.json')
        # Normalize: workspace/results/{file}/v1/parsed.json → workspace/progress.json
        progress_path = str(Path(output_path).parent.parent.parent / 'progress.json')
        TrackingManager.update_progress(
            progress_path, parsed['source_file'],
            status='parsed',
            queries_total=m['total_queries'],
            queries_pass=0, queries_fail=0, queries_escalated=0,
            phase=1,
        )
        TrackingManager.update_pipeline_phase(progress_path, 'phase_1', '파싱', 'done',
                                               files=1, queries=m['total_queries'])
    except Exception as e:
        print(f"  Warning: Could not update progress.json: {e}")

    # Activity log
    try:
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='parse-xml', phase='phase_1',
                     file=parsed['source_file'],
                     detail=f"Parsed {m['total_queries']} queries (rule:{m['rule_tagged']}, llm:{m['llm_tagged']})",
                     duration_ms=_elapsed)
    except Exception:
        pass

    # Update results/_index.json for dashboard
    update_results_index(output_path)


def update_results_index(output_path):
    """Update workspace/results/_index.json with known result directories."""
    results_dir = Path(output_path).parent.parent  # workspace/results/
    index_path = results_dir / '_index.json'

    dirs = []
    if results_dir.exists():
        for d in sorted(results_dir.iterdir()):
            if d.is_dir() and not d.name.startswith('_'):
                dirs.append(d.name)

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump({"directories": dirs, "updated": str(Path(output_path).name)}, f, ensure_ascii=False)


if __name__ == '__main__':
    main()
