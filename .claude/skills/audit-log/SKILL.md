---
name: audit-log
description: 활동 로그 기록. 모든 에이전트가 판단 근거, 시도, 에러, 해결 방법을 activity-log.jsonl에 기록할 때 사용합니다.
---

## 로그 파일
- 경로: workspace/logs/activity-log.jsonl
- 형식: JSON Lines (한 줄에 하나의 JSON 객체, append-only)
- 인코딩: UTF-8

## 로그 항목 형식

모든 로그 항목은 다음 필드를 포함한다:

```json
{
  "ts": 1713100860,
  "step": "step-0-preflight | step-1-convert | step-2-tc-generate | step-3-validate-fix | step-4-report",
  "agent": "converter | tc-generator | validate-and-fix | reporter",
  "file": "UserMapper.xml",
  "query_id": "selectUserById",
  "version": 1,
  "type": "아래 타입 중 하나",
  "summary": "한 줄 요약",
  "duration_ms": 1234,
  "detail": { ... }
}
```

### 필드 설명
- **timestamp**: ISO 8601 형식의 기록 시각
- **step**: 현재 Step (step-0-preflight ~ step-4-report)
- **agent**: 기록 주체 에이전트
- **file**: 대상 파일명
- **query_id**: 대상 쿼리 ID
- **version**: 변환 버전
- **type**: 로그 타입 (아래 참조)
- **summary**: 한 줄 요약
- **duration_ms**: (선택) 작업 소요 시간 (밀리초). Step/변환/검증 등의 실행 시간
- **detail**: 타입별 상세 정보 객체

## 로그 타입

### STEP_START — Step 시작
```json
{
  "type": "STEP_START",
  "summary": "Step 1 시작: 50개 파일 변환",
  "detail": {
    "step": "step_1",
    "total_files": 50,
    "batch_size": 5,
    "batch_count": 10
  }
}
```

### STEP_END — Step 완료
```json
{
  "type": "STEP_END",
  "summary": "Step 1 완료: 50파일 변환, 1200룰/300LLM",
  "duration_ms": 45000,
  "detail": {
    "step": "step_1",
    "duration_ms": 45000,
    "success_count": 50,
    "fail_count": 0
  }
}
```

### DECISION — AI의 판단
```json
{
  "type": "DECISION",
  "summary": "getOrgHierarchy: CONNECT BY 감지 → LLM 변환 선택",
  "detail": {
    "decision": "use_llm_convert",
    "reason": "CONNECT BY NOCYCLE + SYS_CONNECT_BY_PATH 복합 패턴, 룰로 처리 불가",
    "alternatives_considered": ["rule_convert: CONNECT BY 단순 패턴만 지원"],
    "confidence": "medium",
    "reference": "edge-cases.md에 유사 패턴 없음"
  }
}
```

### ATTEMPT — 변환/검증 시도
```json
{
  "type": "ATTEMPT",
  "summary": "selectUserById v1 변환 시도: rule-convert",
  "duration_ms": 120,
  "detail": {
    "action": "rule_convert",
    "input_sql": "SELECT ... NVL(status, 'ACTIVE') ...",
    "output_sql": "SELECT ... COALESCE(status, 'ACTIVE') ...",
    "rules_applied": ["NVL→COALESCE", "SYSDATE→CURRENT_TIMESTAMP"],
    "duration_ms": 120
  }
}
```

### SUCCESS — 성공
```json
{
  "type": "SUCCESS",
  "summary": "selectUserById v1 검증 통과 (3단계 + Integrity Guard)",
  "detail": {
    "explain": "pass",
    "execute": "pass (15 rows, 23ms)",
    "compare": "pass (oracle=15, pg=15, match=true)",
    "warnings": [],
    "test_cases_passed": "6/6"
  }
}
```

### ERROR — 에러 (상세 필수)
```json
{
  "type": "ERROR",
  "summary": "getOrgHierarchy v1 검증 실패: RUNTIME_ERROR (infinite recursion)",
  "detail": {
    "step": "execute-test",
    "error_type": "RUNTIME_ERROR",
    "error_subtype": "INFINITE_RECURSION",
    "error_message": "ERROR: statement timeout, query canceled after 30001ms",
    "full_error": "psql: ERROR: canceling statement due to statement timeout\nCONTEXT: ...",
    "sql_attempted": "WITH RECURSIVE org_hierarchy AS (...) SELECT ...",
    "test_case_id": "tc1_bind_capture",
    "bind_values": {"rootId": 1},
    "possible_causes": ["WITH RECURSIVE 순환 탈출 조건 누락", "UNION ALL → UNION 변경 필요"]
  }
}
```

### FIX — 에러 수정 시도
```json
{
  "type": "FIX",
  "summary": "getOrgHierarchy v2: UNION ALL → UNION + 방문 경로 배열 추가",
  "detail": {
    "attempt": 2,
    "fix_description": "UNION ALL을 UNION으로 변경하고, 방문 경로 배열(path)을 추가하여 순환 감지",
    "previous_sql": "WITH RECURSIVE ... UNION ALL ...",
    "fixed_sql": "WITH RECURSIVE ... UNION ... WHERE NOT (id = ANY(path))",
    "fix_source": "validate-and-fix 분석",
    "root_cause": "CONNECT BY NOCYCLE → WITH RECURSIVE 변환 시 순환 탈출 조건 누락"
  }
}
```

### ESCALATION — 사용자 에스컬레이션
```json
{
  "type": "ESCALATION",
  "summary": "getOrgHierarchy 3회 재시도 실패 → 사용자 에스컬레이션",
  "detail": {
    "query_id": "getOrgHierarchy",
    "total_attempts": 3,
    "attempt_history": [
      {"version": 1, "error": "infinite recursion"},
      {"version": 2, "error": "wrong result count (oracle:15, pg:12)"},
      {"version": 3, "error": "NULL sort order difference"}
    ],
    "recommended_action": "수동으로 WITH RECURSIVE 쿼리 검토 필요"
  }
}
```

### HUMAN_INPUT — 사용자 입력/개입
```json
{
  "type": "HUMAN_INPUT",
  "summary": "사용자: 'getOrgHierarchy 수정했어, 다시 검증해줘'",
  "detail": {
    "input_type": "escalation_resolve",
    "user_message": "getOrgHierarchy 수정했어, 다시 검증해줘",
    "affected_file": "OrgMapper.xml",
    "affected_query": "getOrgHierarchy"
  }
}
```

### LEARNING — 패턴 학습
```json
{
  "type": "LEARNING",
  "summary": "에지케이스 등록: CONNECT BY NOCYCLE 순환 방지",
  "detail": {
    "pattern_name": "CONNECT BY NOCYCLE → WITH RECURSIVE 순환 방지",
    "learned_from": "OrgMapper.xml#getOrgHierarchy",
    "trigger": "repeated_failure_resolved",
    "steering_updated": "edge-cases.md",
    "pr_number": 42,
    "resolution": "UNION (not UNION ALL) + 방문 경로 배열로 순환 감지"
  }
}
```

### WARNING — Result Integrity Guard 경고
```json
{
  "type": "WARNING",
  "summary": "WARN_ZERO_BOTH: selectByStatus tc4에서 양쪽 0건",
  "detail": {
    "warning_code": "WARN_ZERO_BOTH",
    "severity": "high",
    "test_case_id": "tc4_null_status",
    "expected_rows_hint": 45,
    "actual_rows": 0,
    "action_taken": "migration-guide.md에 수동 검토 항목 등록"
  }
}
```

## 로깅 규칙

### 반드시 로그를 남겨야 하는 상황:
1. 모든 Step 시작/종료 (STEP_START, STEP_END)
2. 모든 변환 판단 (rule vs llm 선택 — DECISION)
3. 모든 변환 시도 (ATTEMPT)
4. 모든 검증 결과 (SUCCESS 또는 ERROR)
5. 모든 에러 — 에러 메시지 전문, 시도한 SQL, 바인드 값, 가능한 원인 포함 (ERROR)
6. 모든 수정 시도 (FIX)
7. 모든 에스컬레이션 (ESCALATION)
8. 모든 사용자 입력 (HUMAN_INPUT)
9. 모든 학습 (LEARNING)
10. 모든 Result Integrity Guard 경고 (WARNING)

### ERROR 로그 필수 포함 항목:
- error_message: 에러 메시지 원문
- full_error: 가능한 경우 전체 에러 출력 (스택 트레이스 포함)
- sql_attempted: 실행 시도한 SQL 전문
- possible_causes: AI가 판단한 가능한 원인 목록

### 로그 기록 방법:
workspace/logs/ 디렉토리에 activity-log.jsonl 파일로 기록.
각 항목은 한 줄의 JSON으로 append.
```bash
echo '{"timestamp":"...","type":"...","summary":"...","detail":{...}}' >> workspace/logs/activity-log.jsonl
```
또는 write 도구로 파일 끝에 append.

## 참조 문서

- [활동 로그 형식](workspace/logs/activity-log.jsonl)
