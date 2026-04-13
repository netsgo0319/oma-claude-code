---
name: llm-convert
description: 룰셋으로 처리할 수 없는 복잡한 Oracle SQL을 LLM을 활용하여 PostgreSQL로 변환한다. CONNECT BY 계층쿼리, MERGE INTO, PIVOT/UNPIVOT, PL/SQL 호출, 복합 분석함수 등을 처리한다.
---

## 입력
- parsed.json에서 "llm" 태그된 쿼리
- 또는 rule-convert에서 에스컬레이션된 쿼리 (잔존 Oracle 구문)

## 처리 절차

1. 쿼리 분류:
   - HIERARCHY: CONNECT BY / START WITH / LEVEL / SYS_CONNECT_BY_PATH
   - MERGE: MERGE INTO ... WHEN MATCHED / NOT MATCHED
   - PIVOT: PIVOT / UNPIVOT
   - PLSQL: 프로시저/패키지 호출, PL/SQL 블록
   - ANALYTIC: 복합 분석함수 (Oracle 전용 윈도우 함수)
   - OTHER: 위 분류에 해당하지 않는 복잡 패턴

2. steering/edge-cases.md에서 동일 패턴 선례 확인:
   - 선례 있으면 → 선례 기반 변환 (confidence: high)
   - 선례 없으면 → references/ 패턴 가이드 참조하여 변환

3. 분류별 변환 실행:
   - HIERARCHY → references/connect-by-patterns.md 참조
   - MERGE → references/merge-into-patterns.md 참조
   - PLSQL → references/plsql-patterns.md 참조
   - ROWNUM_PAGINATION → references/rownum-pagination-patterns.md 참조 (3중 페이징, 12c FETCH FIRST 등)
   - PIVOT → 아래 인라인 가이드 참조
   - OTHER → LLM 자유 변환 (confidence: low)

4. PIVOT / UNPIVOT 변환 (인라인):
   ```sql
   -- Oracle PIVOT
   SELECT * FROM sales
   PIVOT (SUM(amount) FOR quarter IN ('Q1' AS q1, 'Q2' AS q2, 'Q3' AS q3, 'Q4' AS q4))
   -- PostgreSQL (CASE 집계)
   SELECT
     SUM(CASE WHEN quarter = 'Q1' THEN amount END) AS q1,
     SUM(CASE WHEN quarter = 'Q2' THEN amount END) AS q2,
     SUM(CASE WHEN quarter = 'Q3' THEN amount END) AS q3,
     SUM(CASE WHEN quarter = 'Q4' THEN amount END) AS q4
   FROM sales
   GROUP BY ...
   ```

   ```sql
   -- Oracle UNPIVOT
   SELECT * FROM quarterly_sales
   UNPIVOT (amount FOR quarter IN (q1 AS 'Q1', q2 AS 'Q2', q3 AS 'Q3', q4 AS 'Q4'))
   -- PostgreSQL (LATERAL + VALUES)
   SELECT qs.*, v.quarter, v.amount
   FROM quarterly_sales qs
   CROSS JOIN LATERAL (
     VALUES ('Q1', qs.q1), ('Q2', qs.q2), ('Q3', qs.q3), ('Q4', qs.q4)
   ) AS v(quarter, amount)
   ```

5. confidence 평가:
   - high: edge-cases.md에 선례 있거나 단순 패턴
   - medium: references 가이드로 변환 가능하지만 검증 필요
   - low: 자유 변환, 반드시 수동 검토 권장

6. 변환 결과를 converted.json에 기록:
   - method: "llm", pattern, confidence, notes

7. 원본 SQL을 주석으로 보존:
   ```sql
   /* Original Oracle: SELECT ... CONNECT BY PRIOR ... */
   WITH RECURSIVE ...
   ```

## 주의사항
- confidence: low인 경우 notes에 불확실 사유 상세 기록
- 동적 SQL 내 복잡 쿼리도 분기별 개별 변환
- 하나의 쿼리에 rule + llm 혼합 가능 (예: NVL + CONNECT BY)
  - rule 부분 먼저 치환 후, 나머지 복잡 부분을 llm으로 처리
