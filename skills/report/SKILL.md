---
name: report
description: 변환 완료 후 전체 결과를 취합하여 conversion-report.md와 migration-guide.md를 생성한다. workspace/progress.json과 각 파일의 최종 버전 결과를 데이터 소스로 사용한다.
---

## 입력
- workspace/progress.json
- workspace/results/{filename}/v{최종}/converted.json
- workspace/results/{filename}/v{최종}/validated.json

## 산출물 1: workspace/reports/conversion-report.md

```markdown
# 변환 리포트

## 요약
- 총 파일 수: N
- 총 쿼리 수: N
- 성공: N (N%)
- 실패: N (N%)
- 수동 검토 필요: N
- 평균 재시도 횟수: N.N

## 파일별 결과

| 파일명 | 쿼리 수 | 성공 | 실패 | 재시도 | 최종 상태 |
|--------|---------|------|------|--------|----------|
| UserMapper.xml | 50 | 48 | 2 | 3회 | success |
| OrderMapper.xml | 80 | 80 | 0 | 0 | success |
| ... | | | | | |

## 실패 건 상세

### UserMapper.xml#getOrgHierarchy
- 실패 원인: CONNECT BY NOCYCLE → WITH RECURSIVE 순환 탈출 조건 차이
- 시도 이력:
  - v1: RUNTIME_ERROR (infinite recursion)
  - v2: RUNTIME_ERROR (UNION 변경 후에도 재귀)
  - v3: 사용자 에스컬레이션 → 수동 해결 → success
- 최종 상태: success (v4)

## 변환 방법 통계

| 방법 | 쿼리 수 | 비율 |
|------|---------|------|
| 룰 기반 | N | N% |
| LLM 기반 | N | N% |
| 수동 | N | N% |

## 복잡도 레벨별 통계

| Level | 이름 | 쿼리 수 | 자동 변환 성공률 | 평균 재시도 |
|-------|------|---------|---------------|-----------|
| L0 | Static | N | 100% | 0 |
| L1 | Simple Rule | N | N% | N.N |
| L2 | Dynamic Simple | N | N% | N.N |
| L3 | Dynamic Complex | N | N% | N.N |
| L4 | Oracle Complex | N | N% | N.N |

## 의존성 레이어별 결과

| Layer | 쿼리 수 | 성공 | 실패 | 에스컬레이션 |
|-------|---------|------|------|------------|
| Layer 0 | N | N | N | N |
| Layer 1 | N | N | N | N |
| ...
```

## 산출물 2: workspace/reports/migration-guide.md

```markdown
# 마이그레이션 가이드

## 수동 검토 필요 항목
- [ ] {파일명}#{쿼리ID} — confidence: low, 사유: {notes}
- [ ] {파일명}#{쿼리ID} — compare: warn, 차이: {differences}

## 알려진 제약사항
- Oracle 빈 문자열 = NULL 동작 차이: 관련 쿼리 N건
- Oracle 힌트 제거됨: 관련 쿼리 N건
- PL/SQL 패키지 호출: 별도 함수 마이그레이션 필요 N건

## 이번 변환에서 새로 발견된 에지케이스
- {패턴명}: {설명} (edge-cases.md에 등록됨)

## 권장 후속 작업
1. confidence: low 쿼리 수동 검토
2. compare: warn 쿼리 데이터 검증
3. 인덱스 재검토 (Oracle 힌트 제거에 따른 성능 확인)
4. 부하 테스트
```

## 처리 절차

1. workspace/progress.json 로드 → 전체 현황 파악
2. 각 파일의 최종 버전 결과 수집
3. 통계 집계 (성공/실패/재시도/변환방법)
4. conversion-report.md 생성
5. 수동 검토 대상 식별 (confidence: low, compare: warn, escalated)
6. migration-guide.md 생성
