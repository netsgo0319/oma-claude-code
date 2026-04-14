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
