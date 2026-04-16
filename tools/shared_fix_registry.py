#!/usr/bin/env python3
"""
Shared Fix Registry — 배치 간 수정 패턴 공유.

fix-loop에서 성공한 수정 패턴을 shared-fixes.jsonl에 기록.
다른 배치가 같은 패턴을 발견하면 즉시 적용 (시도 소비 없음).

Scout → Broadcast 모드:
  1) scout 배치가 패턴 발견 → shared-fixes.jsonl에 기록
  2) pre-apply가 shared-fixes를 읽어 나머지 파일에 일괄 적용
  3) 나머지 배치는 이미 적용된 상태로 시작

파일 경합 안전: fcntl.flock으로 append-only 쓰기.
"""

import fcntl
import json
import os
import re
import time
from pathlib import Path

DEFAULT_REGISTRY_PATH = 'pipeline/step-3-validate-fix/shared-fixes.jsonl'


def _lock_append(path, data):
    """flock으로 안전하게 JSONL append."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def record_fix(pattern_id, regex_pattern, replacement, source_query='',
               agent='', confidence='high', registry_path=None):
    """성공한 수정 패턴을 레지스트리에 기록.

    Args:
        pattern_id: 패턴 식별자 (e.g., "TIMESTAMP_MINUS_INT")
        regex_pattern: 매칭 정규식 (e.g., r"CURRENT_TIMESTAMP\s*-\s*(\d+)")
        replacement: 치환 문자열 (e.g., r"CURRENT_TIMESTAMP - INTERVAL '\1 days'")
        source_query: 발견한 쿼리 (e.g., "DayAvgMapper::selectList")
        agent: 에이전트 이름 (e.g., "batch3")
        confidence: high/medium/low
    """
    entry = {
        'pattern_id': pattern_id,
        'regex': regex_pattern,
        'replacement': replacement,
        'confidence': confidence,
        'source_query': source_query,
        'agent': agent,
        'ts': int(time.time()),
    }
    path = registry_path or DEFAULT_REGISTRY_PATH
    _lock_append(path, entry)
    return entry


def load_fixes(registry_path=None, min_confidence='low'):
    """레지스트리에서 수정 패턴 로드. 중복 제거 (pattern_id 기준 최신만).

    Returns: [{pattern_id, regex, replacement, confidence, ...}]
    """
    path = Path(registry_path or DEFAULT_REGISTRY_PATH)
    if not path.exists():
        return []

    confidence_rank = {'high': 3, 'medium': 2, 'low': 1}
    min_rank = confidence_rank.get(min_confidence, 0)

    fixes = {}  # pattern_id → latest entry
    with open(path, 'r', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = entry.get('pattern_id', '')
                conf = entry.get('confidence', 'low')
                if confidence_rank.get(conf, 0) >= min_rank:
                    fixes[pid] = entry
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    return list(fixes.values())


def apply_fixes_to_sql(sql, fixes):
    """SQL 문자열에 알려진 수정 패턴 적용.

    Returns: (modified_sql, applied_patterns)
    """
    result = sql
    applied = []
    for fix in fixes:
        regex = fix.get('regex', '')
        replacement = fix.get('replacement', '')
        if not regex or not replacement:
            continue
        try:
            new_result = re.sub(regex, replacement, result, flags=re.IGNORECASE)
            if new_result != result:
                applied.append(fix['pattern_id'])
                result = new_result
        except re.error:
            continue
    return result, applied


def apply_fixes_to_xml(xml_path, fixes, dry_run=False):
    """XML 파일에 알려진 수정 패턴 일괄 적용.

    Returns: (applied_count, applied_patterns)
    """
    xml_path = Path(xml_path)
    if not xml_path.exists():
        return 0, []

    content = xml_path.read_text(encoding='utf-8')
    new_content = content
    all_applied = []

    for fix in fixes:
        regex = fix.get('regex', '')
        replacement = fix.get('replacement', '')
        if not regex or not replacement:
            continue
        try:
            modified = re.sub(regex, replacement, new_content, flags=re.IGNORECASE)
            if modified != new_content:
                all_applied.append(fix['pattern_id'])
                new_content = modified
        except re.error:
            continue

    if all_applied and not dry_run:
        xml_path.write_text(new_content, encoding='utf-8')

    return len(all_applied), all_applied


def pre_apply_all(xml_dir, registry_path=None, dry_run=False):
    """디렉토리 내 모든 XML에 shared-fixes 일괄 적용 (Step 3b).

    Returns: {filename: [applied_patterns]}
    """
    fixes = load_fixes(registry_path)
    if not fixes:
        print("  No shared fixes to apply")
        return {}

    print(f"  Loaded {len(fixes)} shared fix patterns")
    xml_dir = Path(xml_dir)
    results = {}
    total_applied = 0

    for xml_file in sorted(xml_dir.glob('**/*.xml')):
        count, patterns = apply_fixes_to_xml(xml_file, fixes, dry_run=dry_run)
        if count:
            results[xml_file.name] = patterns
            total_applied += count

    mode = "(dry-run)" if dry_run else ""
    print(f"  Pre-applied: {total_applied} fixes across {len(results)} files {mode}")
    return results


def match_error_to_fix(error_message, fixes):
    """에러 메시지와 매칭되는 알려진 수정 패턴 찾기.

    fix-loop에서 시도 전에 호출: 이미 알려진 패턴이면 바로 적용.
    Returns: matching fix entry or None
    """
    if not error_message:
        return None

    err_lower = error_message.lower()

    # 에러 메시지 키워드 → 패턴 매칭
    keyword_map = {
        'timestamp': ['TIMESTAMP_MINUS_INT', 'TIMESTAMP_PLUS_INT', 'INTERVAL'],
        'interval': ['TIMESTAMP_MINUS_INT', 'TIMESTAMP_PLUS_INT'],
        'date_trunc': ['TRUNC_NUMERIC', 'TRUNC_DATE'],
        'trunc': ['TRUNC_NUMERIC', 'TRUNC_DATE'],
        'operator does not exist': ['TYPE_CAST', 'OPERATOR_MISMATCH'],
        'nvl': ['RESIDUAL_NVL'],
        'decode': ['RESIDUAL_DECODE'],
        'sysdate': ['RESIDUAL_SYSDATE'],
        'dual': ['RESIDUAL_DUAL'],
        'regexp_instr': ['REGEXP_INSTR'],
        'lpad': ['LPAD_NUMERIC'],
        'to_char': ['TO_CHAR_SINGLE'],
    }

    fix_by_id = {f['pattern_id']: f for f in fixes}

    for keyword, pattern_ids in keyword_map.items():
        if keyword in err_lower:
            for pid in pattern_ids:
                if pid in fix_by_id:
                    return fix_by_id[pid]

    return None


# ── CLI ──

if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='Shared Fix Registry')
    sub = ap.add_subparsers(dest='cmd')

    # list
    sub.add_parser('list', help='List all recorded fixes')

    # pre-apply
    pa = sub.add_parser('pre-apply', help='Apply shared fixes to XML directory')
    pa.add_argument('--xml-dir', required=True)
    pa.add_argument('--dry-run', action='store_true')
    pa.add_argument('--registry', default=None)

    # record
    rec = sub.add_parser('record', help='Record a fix pattern')
    rec.add_argument('--pattern-id', required=True)
    rec.add_argument('--regex', required=True)
    rec.add_argument('--replacement', required=True)
    rec.add_argument('--source', default='')
    rec.add_argument('--agent', default='manual')

    args = ap.parse_args()

    if args.cmd == 'list':
        fixes = load_fixes()
        print(f"=== Shared Fix Registry ({len(fixes)} patterns) ===")
        for f in fixes:
            print(f"  {f['pattern_id']:30s} [{f.get('confidence','?'):6s}] {f.get('source_query','')}")
            print(f"    regex: {f.get('regex','')[:60]}")
            print(f"    repl:  {f.get('replacement','')[:60]}")

    elif args.cmd == 'pre-apply':
        results = pre_apply_all(args.xml_dir, registry_path=args.registry, dry_run=args.dry_run)

    elif args.cmd == 'record':
        entry = record_fix(args.pattern_id, args.regex, args.replacement,
                          source_query=args.source, agent=args.agent)
        print(f"Recorded: {json.dumps(entry, ensure_ascii=False)}")

    else:
        ap.print_help()
