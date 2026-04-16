---
inclusion: always
---

# 학습된 에지케이스

> 파이프라인 실행 중 발견된 항목이 자동으로 추가됩니다.
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

---

(아래로 항목 추가)

### MEDIAN → PERCENTILE_CONT
- **Oracle**: `MEDIAN(salary)`
- **PostgreSQL**: `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary)`
- **주의**: ordered-set aggregate이므로 GROUP BY와 함께 사용 가능. WITHIN GROUP 절 필수
- **발견일**: 2026-04-10
- **출처**: Phase4 셀프힐링
- **해결 방법**: rule

---

### TO_CHAR 단일 인자 (포맷 없음)
- **Oracle**: `TO_CHAR(expr)` — 숫자/CLOB 등을 문자열로 변환
- **PostgreSQL**: `expr::TEXT` 또는 `CAST(expr AS TEXT)`
- **주의**: PG의 TO_CHAR는 포맷 인자가 필수. 단일 인자 호출 시 syntax error 발생
- **발견일**: 2026-04-10
- **출처**: Phase4 셀프힐링
- **해결 방법**: rule

---

### GROUPING() 함수 ORDER BY 직접 참조
- **Oracle**: `ORDER BY GROUPING(col)`
- **PostgreSQL**: SELECT에서 `GROUPING(col) AS grp_col` alias 부여 후 `ORDER BY grp_col`
- **주의**: PG에서 ORDER BY에 GROUPING() 직접 사용 시 구문 오류 발생 가능. SELECT alias 경유 필수
- **발견일**: 2026-04-10
- **출처**: Phase4 셀프힐링
- **해결 방법**: manual

---

### CURRENT_TIMESTAMP - integer (날짜 산술)
- **Oracle**: `SYSDATE - 30`, `SYSDATE + 7` — 날짜에 숫자를 더하면 일(day) 단위
- **PostgreSQL**: `CURRENT_TIMESTAMP - INTERVAL '30 days'`, `CURRENT_TIMESTAMP + INTERVAL '7 days'`
- **주의**: 기계적 변환으로 SYSDATE→CURRENT_TIMESTAMP 변환 후 `-30` 부분이 남으면 `operator does not exist: timestamp with time zone - integer` 에러. 반드시 INTERVAL 변환 함께 수행
- **발견일**: 2026-04-09
- **출처**: Phase6 Aurora EXPLAIN 검증 (AnalyticsMapper, CustomerServiceMapper, PromotionMapper)
- **해결 방법**: rule (oracle-to-pg-converter.py에 추가됨)

---

### TRUNC(timestamp) — 복잡 표현식 누락
- **Oracle**: `TRUNC(o.ORDERED_AT)`, `TRUNC(MAX(o.DATE))` — 날짜를 자정으로 잘라냄
- **PostgreSQL**: `DATE_TRUNC('day', o.ORDERED_AT)::DATE`, `DATE_TRUNC('day', MAX(o.DATE))::DATE`
- **주의**: 이전 변환기가 `TRUNC(\w+)` 단순 패턴만 매칭하여 `TRUNC(o.COL)`, `TRUNC(MAX(...))` 등 복잡 표현식 누락. 괄호 매칭 방식으로 수정됨. 숫자 TRUNC(n, precision)과 구별: 인자 1개=날짜, 2개=숫자
- **발견일**: 2026-04-09
- **출처**: Phase6 Aurora EXPLAIN 검증 (InventoryMapper)
- **해결 방법**: rule (oracle-to-pg-converter.py 수정됨)

---

### DATE + numeric (DATE 리터럴 + 숫자)
- **Oracle**: `DATE '2025-01-01' + (expr)` — DATE + number는 일수 덧셈
- **PostgreSQL**: `DATE '2025-01-01' + (expr)::INTEGER` — DATE + integer는 가능하지만 DATE + numeric은 불가
- **주의**: 나누기 결과가 numeric 타입이면 ::INTEGER 캐스트 필요
- **발견일**: 2026-04-09
- **출처**: Phase6 Aurora EXPLAIN 검증 (InventoryMapper)
- **해결 방법**: manual (컨텍스트 판단 필요)

---

### SELECT alias를 ORDER BY CASE 내부에서 참조
- **Oracle**: `SELECT CASE ... END AS RESTOCK_PRIORITY ... ORDER BY CASE RESTOCK_PRIORITY WHEN ...`
- **PostgreSQL**: ORDER BY에서 CASE 내부에 SELECT alias 참조 불가. CASE 전체를 반복하거나 서브쿼리로 래핑
- **주의**: ORDER BY에서 단순 alias 참조(`ORDER BY RESTOCK_PRIORITY`)는 되지만, `CASE alias WHEN ...` 형태는 alias를 컬럼으로 인식하지 못함
- **발견일**: 2026-04-09
- **출처**: Phase6 Aurora EXPLAIN 검증 (InventoryMapper::selectReorderRecommendations)
- **해결 방법**: manual (CASE 전체 반복 또는 서브쿼리 래핑)

---

### Custom Oracle Packages - PKG_CRYPTO
- **Oracle**: `PKG_CRYPTO.ENCRYPT(col)`, `PKG_CRYPTO.DECRYPT(result)`
- **PostgreSQL**: pgcrypto 확장의 encrypt()/decrypt() 또는 커스텀 PL/pgSQL 함수
- **주의**: 커스텀 패키지는 자동 변환 불가. 패키지 소스(PL/SQL) 분석 후 수동 마이그레이션 필요. 암호화 키 관리 정책도 확인 필수
- **발견일**: 2026-04-11
- **출처**: 검증 세션 (decryptMal, encryptOms 실패)
- **해결 방법**: manual

---

### LPAD(numeric) → LPAD(expr::TEXT)
- **Oracle**: `LPAD(SEQ_NO, 5, '0')` — 숫자를 자동으로 문자열 변환
- **PostgreSQL**: `LPAD(SEQ_NO::TEXT, 5, '0')` — PG의 LPAD는 TEXT 인자만 허용
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (13건)
- **해결 방법**: rule — **converter.py 자동 변환 구현됨**

---

### TO_CLOB(expr) → expr::TEXT
- **Oracle**: `TO_CLOB('long text')` — CLOB 타입 변환
- **PostgreSQL**: `'long text'::TEXT` — PG에 TO_CLOB 함수 없음
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (2건)
- **해결 방법**: rule — **converter.py 자동 변환 구현됨**

---

### TO_DATE 단일 인자 → TO_DATE(expr, 'YYYYMMDD')
- **Oracle**: `TO_DATE(COL)` — 포맷 없이 호출 가능 (NLS_DATE_FORMAT 사용)
- **PostgreSQL**: `TO_DATE(COL, 'YYYYMMDD')` — PG는 포맷 인자 필수
- **주의**: 기본 포맷 'YYYYMMDD' 추정. 실제 데이터 포맷 확인 필요
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (2건)
- **해결 방법**: rule — **converter.py 자동 변환 구현됨**

---

### date_column - numeric → date_column - numeric::INTEGER
- **Oracle**: `EXPDATE - 30` — DATE - NUMBER는 일수 뺄셈
- **PostgreSQL**: `EXPDATE - 30::INTEGER` — DATE - INTEGER는 가능하지만 DATE - NUMERIC은 불가
- **주의**: CURRENT_TIMESTAMP 산술은 별도 INTERVAL 룰로 처리. 일반 date 컬럼용
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (5건)
- **해결 방법**: rule — **converter.py 자동 변환 구현됨**

---

### RATIO_TO_REPORT() → expr / NULLIF(SUM(expr) OVER(), 0)
- **Oracle**: `RATIO_TO_REPORT(COUNT(*)) OVER()` — 비율 계산 분석함수
- **PostgreSQL**: `COUNT(*)::NUMERIC / NULLIF(SUM(COUNT(*)) OVER(), 0)` — 직접 대응 없음
- **주의**: 윈도우 함수 재구성 필요. 0 나누기 방지 NULLIF 필수
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (4건)
- **해결 방법**: llm

---

### REGEXP_INSTR → PG 대체
- **Oracle**: `REGEXP_INSTR(COL, '[0-9]')` — 정규식 위치 반환
- **PostgreSQL**: 직접 대응 없음. 존재 확인이면 `col ~ pattern`으로 대체
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (6건)
- **해결 방법**: llm

---

### varchar = boolean (MyBatis 바인딩)
- **Oracle**: `DELYN = #{delyn}` — MyBatis가 boolean을 문자열로 바인딩
- **PostgreSQL**: varchar = boolean 타입 불일치
- **주의**: MyBatis XML에서 javaType="java.lang.String" 명시 필요
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (5건)
- **해결 방법**: manual (MyBatis parameterType 수정)

---

### multiple assignments to same column (MyBatis 동적 SQL)
- **Oracle**: 여러 `<if>` 블록에서 같은 컬럼 SET → Oracle은 마지막 값 적용
- **PostgreSQL**: 같은 컬럼 중복 SET 시 syntax error
- **주의**: MyBatis `<choose><when>` 으로 분기 재구성 필요
- **발견일**: 2026-04-12
- **출처**: Phase4 셀프힐링 (13건)
- **해결 방법**: manual (MyBatis XML 구조 변경)

---

### TO_CHAR 단일 인자 (2차 발견 — 대량)
- **Oracle**: `TO_CHAR(expr)` — 숫자/날짜를 문자열로 변환 (NLS_FORMAT 사용)
- **PostgreSQL**: `(expr)::TEXT` — PG의 TO_CHAR는 포맷 인자 필수
- **주의**: daiso 프로젝트에서 대량 발견. **converter.py 자동 변환 구현됨 (v2)**
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 회고 — FAIL_SYNTAX 175건 중 상당수
- **해결 방법**: rule — **converter.py에 `_convert_to_char_single` 추가됨**

---

### 서브쿼리 alias 누락 (FROM 절)
- **Oracle**: `SELECT * FROM (SELECT ... ) WHERE ...` — alias 없이 동작
- **PostgreSQL**: `SELECT * FROM (SELECT ... ) AS sub_1 WHERE ...` — alias 필수
- **주의**: 인라인 뷰, ROWNUM 페이징 래핑 등에서 빈번. **converter.py 자동 변환 구현됨 (v2)**
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 회고 — syntax error at or near "WHERE" 다수
- **해결 방법**: rule — **converter.py에 `_convert_subquery_alias` 추가됨**

---

### varchar = integer 암묵적 캐스팅
- **Oracle**: `WHERE CHAR_COL = 1` — 암묵적으로 숫자→문자열 변환
- **PostgreSQL**: `operator does not exist: character varying = integer` 에러
- **주의**: TC 바인드값 타입과 PG 컬럼 타입 불일치가 주 원인. validate-queries.py에서 타입 인식 파라미터 바인딩 개선됨
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 회고 — FAIL_TC_OPERATOR 132건, FAIL_TC_TYPE_MISMATCH 229건
- **해결 방법**: tool 개선 — **validate-queries.py `bind_params()` 타입 추론 강화**

---

### MyBatis ${} 동적 테이블명/컬럼명
- **Oracle/PG 공통**: `${tableName}`, `${colName}` — 런타임에 테이블/컬럼명 주입
- **문제**: 검증 시 `placeholder_tbl`로 치환되어 syntax error 발생 (25건)
- **주의**: validate-queries.py에서 ${} 변수를 유효한 SQL 식별자로 치환하도록 개선됨
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 회고 — syntax error at or near "placeholder_tbl"
- **해결 방법**: tool 개선 — **validate-queries.py `_dollar_replace()` 컨텍스트 인식 치환**

---

### UPDATE SET alias.col (PG alias 불가)
- **Oracle**: `UPDATE TABLE_A A SET A.COL1 = ...` — alias 사용 가능
- **PostgreSQL**: `UPDATE TABLE_A A SET COL1 = ...` — SET 절에 alias 불가
- **주의**: 단순 alias 제거로 해결. 서브쿼리에서 alias 참조는 유지
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 (153건 FAIL_SYNTAX 중 다수)
- **해결 방법**: rule — **converter.py 자동 변환 구현됨**

---

### UPDATE SET (cols) = (SELECT ...) → UPDATE ... FROM
- **Oracle**: `UPDATE T SET (C1, C2) = (SELECT B.C1, B.C2 FROM B WHERE B.KEY = T.KEY)`
- **PostgreSQL**: `UPDATE T SET C1 = B.C1, C2 = B.C2 FROM B WHERE B.KEY = T.KEY`
- **주의**: 서브쿼리가 복잡한 경우 FROM 절로 풀어야 함. 동적 MyBatis 태그가 SET 안에 있으면 수동 변환
- **발견일**: 2026-04-15
- **출처**: Step 3 검증 (21파일 77건)
- **해결 방법**: llm (구조 변경 필요)

---

### TRUNC(숫자) vs TRUNC(날짜) — 타입 기반 구별
- **Oracle**: `TRUNC(3.14, 2)` → 숫자 절삭, `TRUNC(SYSDATE)` → 날짜 자정
- **PostgreSQL**: 숫자 `TRUNC(3.14, 2)` → 그대로 유지, 날짜 `DATE_TRUNC('day', expr)::DATE`
- **주의**: 현재 converter가 모든 TRUNC를 DATE_TRUNC로 변환하여 숫자 TRUNC 20건+ 오변환. **인자 수 기반 구별**: 1인자=날짜 추정, 2인자=숫자 확정
- **발견일**: 2026-04-15
- **출처**: PR #8 보고서 — 수정 루프에서 20건+ 수동 수정
- **해결 방법**: rule 승격 대상 — **converter.py TRUNC 룰에 인자 수 분기 추가 필요**

---

### REGEXP_INSTR(col, pattern) > 0 → col ~ pattern
- **Oracle**: `REGEXP_INSTR(COL, '[0-9]') > 0` — 정규식 매칭 존재 여부
- **PostgreSQL**: `COL ~ '[0-9]'` — POSIX 정규식 매칭
- **주의**: `REGEXP_INSTR(...) = 0` → `COL !~ pattern`. 위치 반환이 필요한 경우는 PL/pgSQL 함수 필요
- **발견일**: 2026-04-15 (3회 반복, 승격 대상)
- **출처**: PR #8 보고서 — 수정 루프에서 반복 수정
- **해결 방법**: rule 승격 대상 — **converter.py에 REGEXP_INSTR > 0 → ~ 패턴 추가 필요**

---

### COUNT 쿼리 내 무의미한 ORDER BY
- **Oracle**: `SELECT COUNT(*) FROM T ORDER BY COL` — Oracle은 허용하지만 무의미
- **PostgreSQL**: 동일하게 허용하지만 성능 저하. PG 옵티마이저가 제거하기도 함
- **주의**: EXPLAIN 자체는 통과하지만 Compare에서 영향 가능. converter에서 COUNT 쿼리의 ORDER BY 자동 제거하면 깔끔
- **발견일**: 2026-04-15 (5건 반복)
- **출처**: PR #8 보고서 — adm-board, adm-item-itemunit, wms-ctmaster-location, wms-wif-das
- **해결 방법**: rule 승격 대상
