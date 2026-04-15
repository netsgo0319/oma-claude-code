---
name: generate-test-cases
description: 테스트 케이스 생성. tc-generator 에이전트가 쿼리별 바인드 변수를 분석하고 Oracle 딕셔너리에서 샘플 데이터, V$SQL_BIND_CAPTURE, 컬럼 통계를 수집하여 TC를 만들 때 사용합니다.
---

## 입력
- workspace/results/{filename}/v{n}/parsed.json

## 처리 절차

### 1단계: 쿼리 구조 분석

parsed.json에서 각 쿼리의 정보 추출:
- 파라미터 목록 (name, type, notation)
- 동적 SQL 분기 조건 (if test="...", choose/when, isEmpty 등)
- SQL 내 참조 테이블명
- JOIN 관계
- WHERE 조건 컬럼

### 2단계: Oracle 딕셔너리 메타데이터 수집

references/oracle-dictionary-queries.md의 쿼리를 사용하여 다음을 순차 수집:

#### 2-1. 테이블/컬럼 메타데이터
- ALL_TAB_COLUMNS: 컬럼명, 데이터 타입, 길이, nullable, 기본값
- ALL_COL_COMMENTS: 컬럼 설명 (비즈니스 의미 파악용)
- ALL_TAB_COMMENTS: 테이블 설명

#### 2-2. 제약조건
- ALL_CONSTRAINTS + ALL_CONS_COLUMNS:
  - PRIMARY KEY: PK 컬럼 식별 → 유효한 키 값 생성
  - FOREIGN KEY: FK 관계 → 참조 무결성 맞는 값 생성
  - CHECK: 허용 값 범위 → 제약 내 값 생성
  - NOT NULL: 필수 파라미터 식별

#### 2-3. 컬럼 통계 (가장 중요)
- ALL_TAB_COL_STATISTICS:
  - NUM_DISTINCT: 유니크 값 개수 → 카디널리티 파악
  - LOW_VALUE / HIGH_VALUE: 최솟값/최댓값 → 경계값 테스트 케이스
  - NUM_NULLS: NULL 비율 → NULL 테스트 케이스 비중 판단
  - HISTOGRAM: 분포 유형 → 빈번한 값 vs 희소 값
- ALL_TAB_STATISTICS:
  - NUM_ROWS: 테이블 행 수 → LIMIT 테스트 기준
  - AVG_ROW_LEN: 평균 행 크기

#### 2-4. SQL 실행 이력 (V$ 동적 성능 뷰)
- V$SQL / V$SQLAREA:
  - SQL 텍스트에서 해당 쿼리 매칭 (파싱된 SQL의 핵심 키워드로 LIKE 검색)
  - EXECUTIONS: 실행 횟수
  - ROWS_PROCESSED: 처리된 행 수
  - SQL_ID: 바인드 캡처 조회 키

- V$SQL_BIND_CAPTURE (핵심):
  - SQL_ID로 조인
  - NAME: 바인드 변수명
  - VALUE_STRING: 실제 운영에서 캡처된 바인드 값
  - DATATYPE_STRING: 데이터 타입
  - LAST_CAPTURED: 캡처 시점
  - WAS_CAPTURED: 캡처 여부
  → 실제 운영 트래픽에서 사용된 바인드 값을 테스트 케이스로 활용

- V$SQL_BIND_METADATA:
  - 바인드 변수의 메타 정보 (타입, 정밀도, 스케일)

#### 2-5. AWR 장기 이력 (권한 있을 경우)
- DBA_HIST_SQLSTAT:
  - 장기간 실행 통계 (일별/시간별)
  - 성능 변화 추이
- DBA_HIST_SQL_BIND_METADATA:
  - AWR 스냅샷에 저장된 바인드 메타데이터
- DBA_HIST_SQLTEXT:
  - SQL 전문 (V$SQL에서 aged out된 경우 AWR에서 복구)

> AWR 조회 시 ORA-13516 등 라이선스 오류 발생 시 → 건너뛰고 V$ 뷰만 사용

#### 2-6. 샘플 데이터
- 각 관련 테이블에서 실제 데이터 샘플링:
  ```sql
  SELECT * FROM {table} SAMPLE(1) WHERE ROWNUM <= 10
  ```
- FK 참조 테이블의 실제 존재하는 키 값 수집:
  ```sql
  SELECT DISTINCT {fk_column} FROM {fk_table} WHERE ROWNUM <= 20
  ```

#### 2-7. 시퀀스/시노님/뷰
- ALL_SEQUENCES: 현재 값(LAST_NUMBER), 증분(INCREMENT_BY), 범위
- ALL_SYNONYMS: 시노님 → 실제 객체 해석
- ALL_VIEWS: 뷰 → 기반 테이블 SQL 파악

#### 2-8. 인덱스 정보
- ALL_INDEXES: 인덱스 유형, 유니크 여부
- ALL_IND_COLUMNS: 인덱스 컬럼 구성
  → 인덱스 컬럼 기반 테스트 케이스에서 인덱스 사용 여부 검증 가능

### 3단계: 테스트 케이스 조합 생성

쿼리 ID별로 다음 카테고리의 테스트 케이스를 생성:

#### Category A: Oracle 바인드 캡처 기반 (최우선)
- V$SQL_BIND_CAPTURE에서 수집한 실제 운영 값
- 캡처 시점이 다른 값이 여러 개면 모두 테스트 케이스로 사용
- source: "V$SQL_BIND_CAPTURE"

#### Category B: 통계 기반 경계값
- LOW_VALUE → 최솟값 테스트
- HIGH_VALUE → 최댓값 테스트
- 중간값 (샘플 데이터에서 추출)
- source: "ALL_TAB_COL_STATISTICS"

#### Category C: 동적 SQL 분기 커버리지
- parsed.json의 dynamic_elements 분석
- 각 `<if test="...">` 조건을 TRUE/FALSE로 만드는 값 조합
- `<choose>/<when>` 각 분기를 타는 값
- `<foreach>` → 빈 리스트, 단일 항목, 복수 항목
- source: "dynamic_sql_branch"

#### Category D: NULL/빈 문자열 시멘틱스
- Oracle '' = NULL 차이 검출용
- 각 nullable 파라미터에 대해:
  - NULL 값
  - 빈 문자열 ''
  - 공백 문자열 ' '
- source: "oracle_null_semantics"

#### Category E: FK 관계 기반
- FK 참조 테이블에 실제 존재하는 값 → JOIN이 매칭되는 테스트
- FK 참조 테이블에 없는 값 → JOIN이 매칭 안 되는 테스트
- source: "FK_RELATIONSHIP"

#### Category F: 샘플 데이터 기반
- 실제 테이블에서 샘플링한 행의 값
- 여러 행에서 다양한 값 추출
- source: "SAMPLE_DATA"

### 4단계: 결과 기록

workspace/results/{filename}/v{n}/test-cases.json에 기록

### 4.5단계: 기대값 힌트 생성

Validator의 Zero-Result Guard가 활용할 `expected_rows_hint`를 쿼리별로 계산:

```
expected_rows_hint = V$SQL.ROWS_PROCESSED / V$SQL.EXECUTIONS
```

V$SQL 접근 불가 시 대안:
- ALL_TAB_STATISTICS.NUM_ROWS와 WHERE 조건의 선택도(selectivity) 추정
- 추정 불가 시 null (Guard에서 WARN_BELOW_EXPECTED 스킵)

test-cases.json에 기록:
```json
{
  "query_id": "selectUserById",
  "expected_rows_hint": 45,
  "expected_rows_source": "V$SQL (avg of 12000 executions)",
  "test_cases": [...]
}
```

또한 각 테스트 케이스에 not_null_columns 정보 포함 (Zero-Result Guard의 WARN_NULL_NON_NULLABLE용):
```json
{
  "case_id": "tc1_bind_capture",
  "binds": { "id": 42, "status": "ACTIVE" },
  "not_null_columns": ["ID", "NAME", "CREATED_AT"]
}
```

### 5단계: Leader에게 반환

한 줄 요약: "{filename}: {N}개 쿼리, 총 {M}개 테스트 케이스 생성 (바인드캡처:{a}, 통계:{b}, 분기:{c}, NULL:{d}, FK:{e}, 샘플:{f})"

## 주의사항
- V$ 뷰 접근 권한이 없을 수 있음 → 권한 오류 시 해당 카테고리 스킵하고 다른 소스로 보완
- AWR (DBA_HIST_*) 조회는 Diagnostics Pack 라이선스 필요 → 오류 시 건너뛰기
- 대량 테이블의 샘플링은 SAMPLE 힌트 사용 (전체 스캔 방지)
- 민감 데이터 주의: PII 컬럼은 마스킹하여 기록 (이름, 이메일 등)
- 하나의 쿼리에 최소 3개, 최대 10개 테스트 케이스 생성

## 참조 문서

- [oracle-dictionary-queries](references/oracle-dictionary-queries.md)
