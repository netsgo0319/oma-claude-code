#!/usr/bin/env python3
"""
Diagnose Failures — FAIL/NOT_TESTED 근본 원인 분석 + 개선 액션 생성.

Usage:
    python3 tools/diagnose-failures.py --matrix pipeline/step-4-report/output/query-matrix.json
    python3 tools/diagnose-failures.py --results-dir ... --validation-dir ...
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Oracle 내장 패턴 (변환 누락 판별용)
ORACLE_PATTERNS = re.compile(
    r'\b(NVL|NVL2|DECODE|SYSDATE|SYSTIMESTAMP|ROWNUM|TO_NUMBER|TO_CHAR|TO_DATE|'
    r'TRUNC|ADD_MONTHS|MONTHS_BETWEEN|CONNECT\s+BY|START\s+WITH|'
    r'MERGE\s+INTO|FROM\s+DUAL|LISTAGG|WM_CONCAT|ROWID)\b', re.IGNORECASE
)


def classify_fail(q):
    """FAIL 쿼리를 5분류."""
    state = q.get('final_state', '')
    mybatis = q.get('mybatis_extracted', 'no')
    explain_err = q.get('explain_error', '') or ''
    sql_after = q.get('sql_after', '') or q.get('xml_after', '') or ''
    compare_detail = q.get('compare_detail', [])

    # DBA
    if state in ('FAIL_SCHEMA_MISSING', 'FAIL_COLUMN_MISSING', 'FAIL_FUNCTION_MISSING'):
        return 'DBA_SCHEMA', q.get('missing_object', {})

    # TC 타입
    if state in ('FAIL_TC_TYPE_MISMATCH', 'FAIL_TC_OPERATOR'):
        return 'TC_QUALITY', explain_err[:200]

    # 변환 버그 vs 추출 한계
    if state == 'FAIL_SYNTAX':
        if mybatis == 'no':
            return 'EXTRACTION_LIMIT', explain_err[:200]
        # mybatis 렌더링 됐는데 SYNTAX → Oracle 패턴 잔존 확인
        if ORACLE_PATTERNS.search(sql_after):
            return 'CONVERSION_BUG', explain_err[:200]
        return 'CONVERSION_BUG', explain_err[:200]

    # Compare 불일치
    if state == 'FAIL_COMPARE_DIFF':
        # Oracle에서도 실패했는지 확인
        oracle_errors = [d for d in compare_detail
                        if d.get('fail_type') == 'oracle_error' or d.get('oracle_rows') is None]
        if oracle_errors:
            return 'TC_QUALITY', 'Oracle에서도 실행 실패 — TC 바인드값 문제'
        return 'COMPARE_DIFF', str(compare_detail[:2])

    # ESCALATED
    if state == 'FAIL_ESCALATED':
        attempts = q.get('attempts', [])
        last_err = attempts[-1].get('error_detail', '') if attempts else ''
        return 'CONVERSION_BUG', f'3회 수정 실패: {last_err[:100]}'

    return 'OTHER', state


def classify_not_tested(q):
    """NOT_TESTED 쿼리를 3분류."""
    state = q.get('final_state', '')
    if state == 'NOT_TESTED_DML_SKIP':
        return 'DML_SKIP'
    elif state == 'NOT_TESTED_NO_RENDER':
        return 'RENDER_FAIL'
    elif state == 'NOT_TESTED_NO_DB':
        return 'NO_DB'
    elif state == 'NOT_TESTED_PENDING':
        return 'PENDING'
    return 'OTHER'


def extract_error_patterns(queries):
    """에러 메시지에서 반복 패턴 추출."""
    patterns = Counter()
    for q in queries:
        err = q.get('explain_error', '') or ''
        if not err:
            for att in q.get('attempts', []):
                err = att.get('error_detail', '') or ''
                if err:
                    break
        if not err:
            continue

        # 패턴 정규화 (테이블명/컬럼명 등 구체값 제거)
        normalized = re.sub(r'"[^"]*"', '"X"', err)
        normalized = re.sub(r"'[^']*'", "'X'", normalized)
        normalized = re.sub(r'\d+', 'N', normalized)
        normalized = normalized[:120]
        patterns[normalized] += 1

    return patterns


def generate_actions(fail_counts, nt_counts, error_patterns, total):
    """우선순위별 개선 액션 생성."""
    actions = []

    # FAIL 기반 액션
    if fail_counts.get('CONVERSION_BUG', 0) > 0:
        n = fail_counts['CONVERSION_BUG']
        actions.append({
            'priority': 1, 'category': 'CONVERSION_BUG',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'converter 재수정 또는 oracle-pg-rules.md에 룰 추가',
            'detail': '변환된 XML에 Oracle 패턴 잔존 — fix-loop에서 수정하거나 converter 룰 보강',
        })

    if fail_counts.get('TC_QUALITY', 0) > 0:
        n = fail_counts['TC_QUALITY']
        actions.append({
            'priority': 2, 'category': 'TC_QUALITY',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'TC 재생성 (LLM) 또는 커스텀 바인드 보강',
            'detail': 'Oracle에서도 실패하는 TC — 바인드값 타입 불일치 또는 ${} 동적 변수',
        })

    if fail_counts.get('EXTRACTION_LIMIT', 0) > 0:
        n = fail_counts['EXTRACTION_LIMIT']
        actions.append({
            'priority': 3, 'category': 'EXTRACTION_LIMIT',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'pre-resolve-includes.py 실행 + MyBatis extractor 재추출',
            'detail': 'MyBatis 렌더링 없이 정적 추출된 쿼리 — cross-file include 미해결 가능',
        })

    if fail_counts.get('DBA_SCHEMA', 0) > 0:
        n = fail_counts['DBA_SCHEMA']
        actions.append({
            'priority': 4, 'category': 'DBA_SCHEMA',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'DBA에게 누락 DDL 전달',
            'detail': 'PG에 테이블/컬럼/함수 없음 — DDL 이관 필요',
        })

    if fail_counts.get('COMPARE_DIFF', 0) > 0:
        n = fail_counts['COMPARE_DIFF']
        actions.append({
            'priority': 5, 'category': 'COMPARE_DIFF',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'SQL 로직 수동 검토',
            'detail': 'Oracle/PG 양쪽 실행 성공하지만 결과 불일치 — 비즈니스 로직 변환 오류',
        })

    # NOT_TESTED 기반 액션
    if nt_counts.get('RENDER_FAIL', 0) > 0:
        n = nt_counts['RENDER_FAIL']
        actions.append({
            'priority': 2, 'category': 'RENDER_FAIL',
            'count': n, 'pct': round(n / total * 100, 1),
            'action': 'TC 보강 + OGNL stub 확인 + pre-resolve-includes 실행',
            'detail': 'MyBatis 렌더링 실패 — TC 파라미터 부족, OGNL 클래스 누락, 또는 cross-file include',
        })

    # 에러 패턴 기반 액션
    top_patterns = error_patterns.most_common(5)
    for pattern, count in top_patterns:
        if count >= 5:
            if 'operator does not exist' in pattern:
                actions.append({
                    'priority': 2, 'category': 'REPEATED_PATTERN',
                    'count': count, 'pct': round(count / total * 100, 1),
                    'action': f'타입 캐스트 룰 추가 (반복 {count}회)',
                    'detail': pattern,
                })
            elif 'does not exist' in pattern and 'relation' in pattern:
                pass  # DBA에서 이미 카운트
            elif 'syntax error' in pattern:
                actions.append({
                    'priority': 3, 'category': 'REPEATED_PATTERN',
                    'count': count, 'pct': round(count / total * 100, 1),
                    'action': f'변환 룰 추가 (반복 {count}회)',
                    'detail': pattern,
                })

    return sorted(actions, key=lambda x: x['priority'])


def main():
    ap = argparse.ArgumentParser(description='Diagnose migration failures')
    ap.add_argument('--matrix', default=None, help='query-matrix.json path')
    ap.add_argument('--results-dir', default=None)
    ap.add_argument('--validation-dir', default=None)
    ap.add_argument('--output', default='pipeline/diagnose/')
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # Load data
    if args.matrix:
        data = json.loads(Path(args.matrix).read_text(encoding='utf-8'))
        queries = data.get('queries', [])
    else:
        # TODO: tracking + validation에서 직접 로드
        print("ERROR: --matrix 필요")
        return

    total = len(queries)
    print(f"=== Diagnose Failures ({total} queries) ===\n")

    # 1) FAIL 분류
    fail_queries = [q for q in queries if q.get('final_state', '').startswith('FAIL_')]
    fail_counts = Counter()
    fail_details = defaultdict(list)
    for q in fail_queries:
        category, detail = classify_fail(q)
        fail_counts[category] += 1
        fail_details[category].append({
            'query_id': q.get('query_id', ''),
            'file': q.get('original_file', ''),
            'state': q.get('final_state', ''),
            'detail': str(detail)[:200],
        })

    print("FAIL 5분류:")
    for cat, count in fail_counts.most_common():
        pct = round(count / total * 100, 1)
        print(f"  {cat}: {count}건 ({pct}%)")

    # 2) NOT_TESTED 분류
    nt_queries = [q for q in queries if q.get('final_state', '').startswith('NOT_TESTED')]
    nt_counts = Counter()
    for q in nt_queries:
        nt_counts[classify_not_tested(q)] += 1

    print(f"\nNOT_TESTED 3분류:")
    for cat, count in nt_counts.most_common():
        print(f"  {cat}: {count}건")

    # 3) PASS
    pass_count = sum(1 for q in queries if q.get('final_state', '').startswith('PASS_'))
    print(f"\nPASS: {pass_count}건 ({round(pass_count/total*100,1)}%)")

    # 4) 에러 패턴
    error_patterns = extract_error_patterns(fail_queries)
    print(f"\nTop 에러 패턴:")
    for pattern, count in error_patterns.most_common(10):
        print(f"  {count:4d}x  {pattern[:80]}")

    # 5) 개선 액션
    actions = generate_actions(fail_counts, nt_counts, error_patterns, total)
    print(f"\n개선 액션 ({len(actions)}건):")
    for a in actions:
        print(f"  P{a['priority']} [{a['category']}] {a['count']}건({a['pct']}%) — {a['action']}")

    # 6) 산출물 저장
    today = datetime.now().strftime('%Y%m%d')
    diagnosis = {
        'date': today, 'total': total,
        'pass_count': pass_count,
        'fail_counts': dict(fail_counts),
        'not_tested_counts': dict(nt_counts),
        'fail_details': {k: v[:20] for k, v in fail_details.items()},
        'top_error_patterns': error_patterns.most_common(20),
        'actions': actions,
    }
    (out / f'diagnosis-{today}.json').write_text(
        json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding='utf-8')

    # improvement-actions.md
    md_lines = [f"# 개선 액션 — {today}", "",
                f"전체: {total}쿼리, PASS: {pass_count}({round(pass_count/total*100,1)}%), "
                f"FAIL: {len(fail_queries)}, NOT_TESTED: {len(nt_queries)}", ""]
    for a in actions:
        md_lines.append(f"## P{a['priority']}: {a['category']} ({a['count']}건, {a['pct']}%)")
        md_lines.append(f"**액션:** {a['action']}")
        md_lines.append(f"**상세:** {a['detail']}")
        md_lines.append("")
    (out / 'improvement-actions.md').write_text('\n'.join(md_lines), encoding='utf-8')

    # top-errors.md
    err_lines = [f"# Top 에러 패턴 — {today}", ""]
    for pattern, count in error_patterns.most_common(20):
        err_lines.append(f"- **{count}건**: `{pattern[:100]}`")
    (out / 'top-errors.md').write_text('\n'.join(err_lines), encoding='utf-8')

    print(f"\n산출물: {out}/")
    print(f"  diagnosis-{today}.json")
    print(f"  improvement-actions.md")
    print(f"  top-errors.md")


if __name__ == '__main__':
    main()
