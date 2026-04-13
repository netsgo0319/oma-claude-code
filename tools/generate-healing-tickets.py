#!/usr/bin/env python3
"""
Phase 4: Healing Ticket Generator
EXPLAIN/Compare 실패 결과에서 에러를 분류하여 healing ticket을 생성한다.

Usage:
    python3 tools/generate-healing-tickets.py
    python3 tools/generate-healing-tickets.py --validation-dir workspace/results/_validation/ --output workspace/results/_healing/

Output:
    workspace/results/_healing/tickets.json
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime


def classify_error(error_msg):
    """에러 메시지를 카테고리로 분류."""
    err = str(error_msg).lower()

    if 'not well-formed' in err or 'xml' in err:
        return 'xml_invalid', 'critical'
    if 'syntax error' in err:
        return 'syntax_error', 'high'
    if 'function' in err and 'does not exist' in err:
        return 'function_missing', 'high'
    if 'value too long' in err:
        return 'type_mismatch', 'medium'
    if 'invalid input syntax' in err:
        return 'type_mismatch', 'medium'
    if 'operator does not exist' in err:
        return 'operator_mismatch', 'medium'
    if 'relation' in err and 'does not exist' in err:
        return 'relation_missing', 'low'
    if 'column' in err and 'does not exist' in err:
        return 'column_missing', 'low'
    if 'ambiguous' in err:
        return 'ambiguous_ref', 'medium'
    if 'unterminated' in err:
        return 'syntax_error', 'high'
    if 'division by zero' in err:
        return 'runtime_error', 'medium'

    return 'other', 'medium'


def main():
    parser = argparse.ArgumentParser(description='Phase 4: Healing Ticket Generator')
    parser.add_argument('--validation-dir', default='workspace/results/_validation/')
    parser.add_argument('--validation-phase7-dir', default='workspace/results/_validation_phase35/')
    parser.add_argument('--output', default='workspace/results/_healing/')
    parser.add_argument('--max-retries', type=int, default=5)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    tickets = []
    ticket_id = 0
    seen_queries = set()  # Deduplicate by query_id

    # Load validation results
    for val_dir in [args.validation_dir, args.validation_phase7_dir]:
        val_path = Path(val_dir) / 'validated.json'
        if not val_path.exists():
            continue

        with open(val_path) as f:
            vdata = json.load(f)

        for failure in vdata.get('failures', []):
            test_id = failure.get('test', failure.get('test_id', ''))
            error = failure.get('error', '')

            # Extract query_id from test_id (format: file.queryId.variant)
            parts = test_id.rsplit('.', 1)
            query_parts = parts[0].rsplit('.', 1) if len(parts) > 0 else ['', '']

            # Deduplicate: one ticket per unique query_id + category
            category, severity = classify_error(error)
            file_name = ''
            query_id = ''

            if '.' in parts[0]:
                segments = parts[0].split('.')
                query_id = segments[-1] if len(segments) >= 2 else parts[0]
                file_name = '.'.join(segments[:-1]) + '.xml' if len(segments) >= 2 else ''

            dedup_key = f"{query_id}:{category}"
            if dedup_key in seen_queries:
                continue
            seen_queries.add(dedup_key)

            ticket_id += 1
            tickets.append({
                'ticket_id': f'HT-{ticket_id:04d}',
                'status': 'open',
                'category': category,
                'severity': severity,
                'query_id': query_id,
                'file': file_name,
                'error': str(error)[:500],
                'test_id': test_id,
                'retry_count': 0,
                'max_retries': args.max_retries,
                'created_at': datetime.now().isoformat(),
                'history': [],
            })

    # Sort by severity (critical > high > medium > low)
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    tickets.sort(key=lambda t: (severity_order.get(t['severity'], 9), t['ticket_id']))

    # Write tickets
    with open(output_dir / 'tickets.json', 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'max_retries': args.max_retries,
            'total_tickets': len(tickets),
            'by_category': {},
            'by_severity': {},
            'tickets': tickets,
        }, f, indent=2, ensure_ascii=False)

    # Summary
    from collections import Counter
    cat_counts = Counter(t['category'] for t in tickets)
    sev_counts = Counter(t['severity'] for t in tickets)

    # Update summary in JSON
    with open(output_dir / 'tickets.json') as f:
        data = json.load(f)
    data['by_category'] = dict(cat_counts)
    data['by_severity'] = dict(sev_counts)
    with open(output_dir / 'tickets.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Actionable tickets (exclude DBA-only: relation_missing, column_missing)
    actionable = [t for t in tickets if t['category'] not in ('relation_missing', 'column_missing')]
    dba_only = [t for t in tickets if t['category'] in ('relation_missing', 'column_missing')]

    print(f"=== Phase 4: Healing Tickets ===")
    print(f"Total tickets: {len(tickets)}")
    print(f"  Actionable (자동 힐링 대상): {len(actionable)}")
    print(f"  DBA-only (스키마 이관 필요): {len(dba_only)}")
    print(f"\nBy category:")
    for cat, cnt in cat_counts.most_common():
        print(f"  {cat}: {cnt}")
    print(f"\nBy severity:")
    for sev, cnt in sev_counts.most_common():
        print(f"  {sev}: {cnt}")
    print(f"\nSaved: {output_dir / 'tickets.json'}")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_START', agent='healing-ticket-generator', phase='phase_4',
                     detail=f"Tickets: {len(tickets)} total, {len(actionable)} actionable, "
                            f"{len(dba_only)} DBA-only")
    except Exception:
        pass


if __name__ == '__main__':
    main()
