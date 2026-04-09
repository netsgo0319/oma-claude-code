
# 학습된 에지케이스

> Learner 에이전트가 자동으로 항목을 추가합니다.
> 수동 편집 가능. PR로 팀 공유.

## 형식

각 항목은 다음 구조를 따릅니다:

### [패턴 이름]
- **Oracle**: 원본 SQL 패턴/예시
- **PostgreSQL**: 변환 결과/예시
- **주의**: 변환 시 주의사항
- **발견일**: YYYY-MM-DD
- **출처**: {파일명}#{쿼리ID}
- **해결 방법**: rule | llm | manual


### TO_CHAR 단일 인자 (포맷 없음)
- **Oracle**: `TO_CHAR(expr)` — 숫자/CLOB 등을 문자열로 변환
- **PostgreSQL**: `expr::TEXT` 또는 `CAST(expr AS TEXT)`
- **주의**: PG의 TO_CHAR는 포맷 인자가 필수. 단일 인자 호출 시 syntax error 발생
- **발견일**: 2026-04-10
- **출처**: Phase4 셀프힐링
- **해결 방법**: rule


### CURRENT_TIMESTAMP - integer (날짜 산술)
- **Oracle**: `SYSDATE - 30`, `SYSDATE + 7` — 날짜에 숫자를 더하면 일(day) 단위
- **PostgreSQL**: `CURRENT_TIMESTAMP - INTERVAL '30 days'`, `CURRENT_TIMESTAMP + INTERVAL '7 days'`
- **주의**: 기계적 변환으로 SYSDATE→CURRENT_TIMESTAMP 변환 후 `-30` 부분이 남으면 `operator does not exist: timestamp with time zone - integer` 에러. 반드시 INTERVAL 변환 함께 수행
- **발견일**: 2026-04-09
- **출처**: Phase7 Aurora EXPLAIN 검증 (AnalyticsMapper, CustomerServiceMapper, PromotionMapper)
- **해결 방법**: rule (oracle-to-pg-converter.py에 추가됨)


### DATE + numeric (DATE 리터럴 + 숫자)
- **Oracle**: `DATE '2025-01-01' + (expr)` — DATE + number는 일수 덧셈
- **PostgreSQL**: `DATE '2025-01-01' + (expr)::INTEGER` — DATE + integer는 가능하지만 DATE + numeric은 불가
- **주의**: 나누기 결과가 numeric 타입이면 ::INTEGER 캐스트 필요
- **발견일**: 2026-04-09
- **출처**: Phase7 Aurora EXPLAIN 검증 (InventoryMapper)
- **해결 방법**: manual (컨텍스트 판단 필요)

