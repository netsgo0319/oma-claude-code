---
name: rule-convert
description: Oracle SQL을 PostgreSQL로 룰 기반 변환. converter 에이전트가 NVL→COALESCE, DECODE→CASE, SYSDATE→CURRENT_TIMESTAMP 등 40+ 패턴을 기계적으로 치환할 때 사용합니다. oracle-pg-rules.md 룰셋을 참조합니다.
---

## 입력
- workspace/results/{filename}/v{n}/parsed.json

각 룰의 상세 변환 예시와 엣지 케이스는 `references/rule-catalog.md`를 참조한다.

## 처리 절차

1. parsed.json 로드 후 `oracle_tags`에 "rule"이 포함된 쿼리 필터링

2. .claude/rules/oracle-pg-rules.md 룰셋 로드

3. 각 쿼리에 대해 순서대로 룰 적용:
   a. 함수 변환 (NVL → COALESCE, DECODE → CASE 등)
   b. 조인 변환 ((+) → ANSI JOIN)
   c. 데이터 타입 변환 (DDL 문이 포함된 경우)
   d. 날짜 포맷 변환 (TO_DATE/TO_CHAR 내 포맷 문자열)
   e. 기타 구문 변환 (DUAL 제거, MINUS → EXCEPT 등)
   f. MyBatis/iBatis 특수 변환 (selectKey, 파라미터 표기)

4. 동적 SQL 분기별로 각각 룰 적용:
   - `<if>` 내부 SQL도 변환
   - `<choose>/<when>/<otherwise>` 각 분기 변환
   - `<foreach>` 내부 SQL 변환

5. 변환 후 Oracle 구문 잔존 검사:
   - 정규식으로 NVL\(, DECODE\(, SYSDATE, ROWNUM, \(\+\), FROM DUAL 등 스캔
   - 잔존하면 해당 쿼리를 "llm" 태그로 에스컬레이션

6. 변환된 XML 파일 생성:
   - workspace/output/{filename}.xml
   - 원본 XML 구조 유지, SQL 본문만 교체

7. 메타데이터 기록:
   - workspace/results/{filename}/v{n}/converted.json
   - 각 쿼리별 method: "rule", rules_applied 목록, confidence: "high"

8. Leader에게 한 줄 요약 반환

## 주의사항
- 하나의 쿼리에 여러 룰이 중복 적용될 수 있음 (NVL + SYSDATE + DUAL 등)
- 동적 SQL 태그의 속성(test 조건 등)은 변환하지 않음 — SQL 본문만 변환
- 룰 적용 순서: 함수 → 조인 → 타입 → 포맷 → 기타 → MyBatis 특수
- .claude/rules/edge-cases.md도 참조하여 학습된 패턴이 있으면 우선 적용
