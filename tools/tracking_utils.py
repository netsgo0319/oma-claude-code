#!/usr/bin/env python3
"""
Query Tracking Utilities
모든 도구가 import하여 query-tracking.json과 progress.json을 일관되게 갱신한다.

Usage:
    from tracking_utils import TrackingManager
    tm = TrackingManager('workspace/results/UserMapper/v1')
    tm.init_tracking('UserMapper.xml', queries_from_parsed)
    tm.update_query('selectUser', convert_started=now, oracle_sql='...', pg_sql='...')
    tm.update_progress('workspace/progress.json', 'UserMapper.xml', phase=2)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Default log path
_LOG_PATH = 'workspace/logs/activity-log.jsonl'


def log_activity(action, agent='tool', phase=None, step=None, file=None, query_id=None,
                 detail=None, duration_ms=None, log_path=None):
    """Append a single activity log entry to activity-log.jsonl.
    Called automatically by tools — no Leader intervention needed."""
    log_path = Path(log_path or _LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        'ts': now_iso(),
        'type': action,
        'agent': agent,
        'action': action,
    }
    if phase:
        entry['phase'] = phase
    if step:
        entry['step'] = step
    if file:
        entry['file'] = file
    if query_id:
        entry['query_id'] = query_id
    if detail:
        entry['detail'] = detail
    if duration_ms is not None:
        entry['duration_ms'] = duration_ms

    try:
        import fcntl
        with open(log_path, 'a', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass


def now_iso():
    """UTC Unix timestamp (seconds). 보고서에서 로컬 시간으로 파싱."""
    return int(datetime.now(timezone.utc).timestamp())


class TrackingManager:
    """query-tracking.json과 progress.json을 관리하는 공용 클래스."""

    def __init__(self, results_dir):
        """results_dir: workspace/results/{file}/v{n}/"""
        self.results_dir = Path(results_dir)
        self.tracking_path = self.results_dir / 'query-tracking.json'
        self._data = None

    def _load(self):
        if self._data is None:
            if self.tracking_path.exists():
                with open(self.tracking_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            else:
                self._data = {
                    'version': 1,
                    'file': '',
                    'file_version': 1,
                    'created_at': now_iso(),
                    'updated_at': now_iso(),
                    'queries': []
                }
        return self._data

    def _save(self):
        if self._data:
            import fcntl
            self._data['updated_at'] = now_iso()
            self.results_dir.mkdir(parents=True, exist_ok=True)
            with open(self.tracking_path, 'w', encoding='utf-8') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(self._data, f, indent=2, ensure_ascii=False)
                fcntl.flock(f, fcntl.LOCK_UN)

    def _find_query(self, query_id):
        data = self._load()
        for q in data['queries']:
            if q['query_id'] == query_id:
                return q
        return None

    # ===== Phase 1: 초기 뼈대 생성 =====

    def init_tracking(self, filename, parsed_queries, file_version=1):
        """parsed.json의 쿼리 목록으로 tracking 초기화.
        parsed_queries: list of dicts with query_id, type, sql_raw, oracle_tags, oracle_patterns, etc.
        """
        data = self._load()
        data['file'] = filename
        data['file_version'] = file_version
        data['created_at'] = now_iso()

        existing_ids = {q['query_id'] for q in data['queries']}

        for pq in parsed_queries:
            qid = pq.get('query_id', '')
            if qid in existing_ids:
                continue
            data['queries'].append({
                'query_id': qid,
                'type': pq.get('type', 'select'),
                'status': 'parsed',
                'complexity': None,
                'layer': None,
                'oracle_sql': pq.get('sql_raw', ''),
                'pg_sql': None,
                'oracle_patterns': pq.get('oracle_patterns', []),
                'conversion_method': None,
                'rules_applied': [],
                'confidence': None,
                'dynamic_elements': pq.get('dynamic_elements', []),
                'parameters': pq.get('parameters', []),
                'explain': None,
                'execution': None,
                'test_cases': [],
                'timing': {},
                'history': []
            })

        self._save()
        return len(data['queries'])

    # ===== Phase 1.5: 복잡도/레이어 갱신 =====

    def update_complexity(self, query_id, complexity, layer):
        q = self._find_query(query_id)
        if q:
            q['complexity'] = complexity
            q['layer'] = layer
            q['status'] = 'analyzed'
            self._save()

    # ===== Phase 2: 변환 결과 기록 =====

    def update_conversion(self, query_id, pg_sql, method, rules_applied=None,
                          confidence='high', duration_ms=None):
        q = self._find_query(query_id)
        if q:
            q['pg_sql'] = pg_sql
            q['conversion_method'] = method
            q['rules_applied'] = rules_applied or []
            q['confidence'] = confidence
            q['status'] = 'converted'
            if duration_ms is not None:
                q['timing']['convert_ms'] = duration_ms
                q['timing']['convert_started'] = now_iso()
            q['history'].append({
                'version': self._load()['file_version'],
                'status': 'converted',
                'error': None,
                'fix': None,
                'agent': method,
                'timestamp': now_iso()
            })
            self._save()

    # ===== Phase 3: 검증 결과 기록 =====

    def update_explain(self, query_id, status, plan_summary=None, error=None, duration_ms=None, phase='3', source='static'):
        """Update EXPLAIN result. phase='3' or '3.5', source='static' or 'mybatis'."""
        q = self._find_query(query_id)
        if q:
            result = {
                'status': status,
                'validation_source': source,
                'plan_summary': plan_summary,
                'error': error,
                'executed_at': now_iso(),
                'duration_ms': duration_ms
            }
            if phase == '3.5':
                # Phase 3.5 결과는 별도 필드에 저장 (Phase 3 결과 보존)
                q['explain_phase35'] = result
                # Phase 3에서 fail이었는데 3.5에서 pass이면 status 복구
                if status == 'pass' and q.get('explain', {}).get('status') == 'fail':
                    q['status'] = 'validating'
            else:
                q['explain'] = result
                if status == 'pass' and (q['status'] in ('converted', 'validating')):
                    q['status'] = 'validating'
                elif status == 'fail':
                    q['status'] = 'failed'
            if duration_ms is not None:
                q['timing'][f'explain{"_phase35" if phase == "3.5" else ""}_ms'] = duration_ms
            self._save()

    def update_execution(self, query_id, status, row_count=None, columns=None,
                         error=None, duration_ms=None):
        q = self._find_query(query_id)
        if q:
            q['execution'] = {
                'status': status,
                'row_count': row_count,
                'columns': columns,
                'duration_ms': duration_ms,
                'error': error,
                'executed_at': now_iso()
            }
            if duration_ms is not None:
                q['timing']['execute_ms'] = duration_ms
            self._save()

    def update_test_case(self, query_id, case_id, binds, oracle_result=None,
                         pg_result=None, match=None, warnings=None):
        q = self._find_query(query_id)
        if q:
            # Find existing or create new
            existing = None
            for tc in q['test_cases']:
                if tc.get('case_id') == case_id:
                    existing = tc
                    break
            if existing is None:
                existing = {'case_id': case_id, 'binds': binds}
                q['test_cases'].append(existing)

            if oracle_result is not None:
                existing['oracle_result'] = oracle_result
            if pg_result is not None:
                existing['pg_result'] = pg_result
            if match is not None:
                existing['match'] = match
            if warnings is not None:
                existing['warnings'] = warnings
            self._save()

    # ===== Step 3: 수정 시도 기록 (attempts) =====

    def add_attempt(self, query_id, error_category=None, error_detail=None,
                    fix_applied='', result='fail'):
        """수정 시도를 attempts 배열에 추가. validate-and-fix 에이전트가 호출.
        Usage:
            tm = TrackingManager('pipeline/step-1-convert/output/results/UserMapper.xml/v1')
            tm.add_attempt('selectUser', error_category='SYNTAX_ERROR',
                           error_detail='syntax error near NVL',
                           fix_applied='NVL→COALESCE 변환 누락', result='pass')
        """
        q = self._find_query(query_id)
        if q:
            if 'attempts' not in q:
                q['attempts'] = []
            attempt_num = len(q['attempts']) + 1
            q['attempts'].append({
                'attempt': attempt_num,
                'ts': now_iso(),
                'error_category': error_category,
                'error_detail': error_detail,
                'fix_applied': fix_applied,
                'result': result,
            })
            if result == 'pass':
                q['status'] = 'success'
            elif attempt_num >= 3:
                q['status'] = 'escalated'
            self._save()
            return attempt_num
        return 0

    def mark_success(self, query_id):
        q = self._find_query(query_id)
        if q:
            q['status'] = 'success'
            # Compute total timing
            timing = q.get('timing', {})
            total = sum(v for k, v in timing.items() if k.endswith('_ms') and isinstance(v, int))
            timing['total_ms'] = total
            self._save()

    def mark_failed(self, query_id, error, retry_num=None):
        q = self._find_query(query_id)
        if q:
            if retry_num:
                q['status'] = f'retry_{retry_num}'
            else:
                q['status'] = 'failed'
            q['history'].append({
                'version': self._load()['file_version'],
                'status': q['status'],
                'error': error,
                'fix': None,
                'agent': None,
                'timestamp': now_iso()
            })
            self._save()

    def mark_escalated(self, query_id):
        q = self._find_query(query_id)
        if q:
            q['status'] = 'escalated'
            self._save()

    # ===== Progress.json 갱신 =====

    @staticmethod
    def update_progress(progress_path, filename, **kwargs):
        """progress.json의 특정 파일 항목을 갱신한다.
        병렬 실행 시 파일 잠금으로 race condition 방지.
        kwargs: phase, status, queries_pass, queries_fail, 등
        """
        import fcntl
        progress_path = Path(progress_path)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(progress_path) + '.lock'

        with open(lock_path, 'w') as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                if progress_path.exists():
                    with open(progress_path, 'r', encoding='utf-8') as f:
                        progress = json.load(f)
                else:
                    progress = {'_pipeline': {}, 'files': {}}

                if filename not in progress.get('files', {}):
                    progress.setdefault('files', {})[filename] = {}

                fdata = progress['files'][filename]
                fdata['last_updated'] = now_iso()
                for k, v in kwargs.items():
                    fdata[k] = v

                # Recompute summary
                pipeline = progress.setdefault('_pipeline', {})
                files = progress.get('files', {})
                total_q = sum(f.get('queries_total', 0) for f in files.values())
                pass_q = sum(f.get('queries_pass', 0) for f in files.values())
                fail_q = sum(f.get('queries_fail', 0) for f in files.values())
                esc_q = sum(f.get('queries_escalated', 0) for f in files.values())
                pipeline['summary'] = {
                    'total_files': len(files),
                    'total_queries': total_q,
                    'success': pass_q,
                    'fail': fail_q,
                    'pending': total_q - pass_q - fail_q - esc_q,
                    'escalated': esc_q
                }
                pipeline['last_updated'] = now_iso()

                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, indent=2, ensure_ascii=False)
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    @staticmethod
    def update_pipeline_phase(progress_path, phase_id, phase_name, status,
                              started_at=None, ended_at=None, duration_ms=None, **extra):
        """progress.json의 _pipeline.phases 갱신. 파일 잠금 포함."""
        import fcntl
        progress_path = Path(progress_path)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(progress_path) + '.lock'

        with open(lock_path, 'w') as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                if progress_path.exists():
                    with open(progress_path, 'r', encoding='utf-8') as f:
                        progress = json.load(f)
                else:
                    progress = {'_pipeline': {}, 'files': {}}

                pipeline = progress.setdefault('_pipeline', {})
                phases = pipeline.setdefault('phases', {})

                phase_data = phases.setdefault(phase_id, {})
                phase_data['status'] = status
                if started_at:
                    phase_data['started'] = started_at
                if ended_at:
                    phase_data['ended'] = ended_at
                if duration_ms is not None:
                    phase_data['duration_ms'] = duration_ms
                for k, v in extra.items():
                    phase_data[k] = v

                if status == 'running':
                    pipeline['current_phase'] = phase_id
                    pipeline['current_phase_name'] = phase_name

                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, indent=2, ensure_ascii=False)
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    # ===== 요약 =====

    def get_summary(self):
        data = self._load()
        queries = data.get('queries', [])
        status_counts = {}
        for q in queries:
            s = q.get('status', 'pending')
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            'file': data.get('file', ''),
            'total': len(queries),
            'status_counts': status_counts,
        }

    def get_resume_point(self):
        """중단 후 재개 시 어디서부터 시작해야 하는지 반환."""
        data = self._load()
        incomplete = []
        for q in data.get('queries', []):
            if q.get('status') not in ('success', 'escalated'):
                incomplete.append({
                    'query_id': q['query_id'],
                    'status': q.get('status'),
                    'last_phase': 'phase_2' if q.get('pg_sql') else 'phase_1'
                })
        return incomplete
