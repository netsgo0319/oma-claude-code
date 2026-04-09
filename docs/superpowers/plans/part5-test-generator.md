# Part 5: Test Generator Agent + Skill

## Task 14: generate-test-cases 스킬

**Files:**
- Create: `.kiro/skills/generate-test-cases/SKILL.md`
- Create: `.kiro/skills/generate-test-cases/references/oracle-dictionary-queries.md`

- [ ] **Step 1: SKILL.md 생성**

Create: `.kiro/skills/generate-test-cases/SKILL.md`

```markdown
---
name: generate-test-cases
description: 쿼리별 바인드 변수를 분석하고 Oracle 딕셔너리에서 메타데이터, 실행 이력, 캡처된 바인드 값을 수집하여 의미 있는 테스트 케이스 조합을 생성한다. 동적 SQL의 모든 분기를 커버하는 다중 테스트 케이스를 생성한다.
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
```

- [ ] **Step 2: oracle-dictionary-queries.md 생성**

Create: `.kiro/skills/generate-test-cases/references/oracle-dictionary-queries.md`

```markdown
# Oracle Dictionary 수집 쿼리 레퍼런스

> Test Generator 에이전트가 메타데이터 수집 시 사용하는 쿼리 모음.
> 권한 부족 시 ORA 에러가 발생하면 해당 쿼리를 건너뛰고 다음으로 진행.

## 1. 테이블/컬럼 메타데이터

### 1-1. 컬럼 정보
```sql
SELECT
  column_name,
  data_type,
  data_length,
  data_precision,
  data_scale,
  nullable,
  data_default,
  char_length
FROM all_tab_columns
WHERE owner = :owner
  AND table_name = :table_name
ORDER BY column_id
```

### 1-2. 컬럼 코멘트
```sql
SELECT column_name, comments
FROM all_col_comments
WHERE owner = :owner
  AND table_name = :table_name
  AND comments IS NOT NULL
```

### 1-3. 테이블 코멘트
```sql
SELECT comments
FROM all_tab_comments
WHERE owner = :owner
  AND table_name = :table_name
```

## 2. 제약조건

### 2-1. PK/FK/CHECK/UNIQUE 제약
```sql
SELECT
  c.constraint_name,
  c.constraint_type,  -- P=PK, R=FK, C=CHECK, U=UNIQUE
  c.search_condition,  -- CHECK 조건식
  c.r_constraint_name,  -- FK가 참조하는 제약명
  cc.column_name,
  cc.position
FROM all_constraints c
JOIN all_cons_columns cc
  ON c.owner = cc.owner
  AND c.constraint_name = cc.constraint_name
WHERE c.owner = :owner
  AND c.table_name = :table_name
  AND c.status = 'ENABLED'
ORDER BY c.constraint_type, cc.position
```

### 2-2. FK 참조 테이블/컬럼 역추적
```sql
SELECT
  c.constraint_name AS fk_name,
  cc.column_name AS fk_column,
  rc.table_name AS ref_table,
  rcc.column_name AS ref_column
FROM all_constraints c
JOIN all_cons_columns cc
  ON c.owner = cc.owner AND c.constraint_name = cc.constraint_name
JOIN all_constraints rc
  ON c.r_owner = rc.owner AND c.r_constraint_name = rc.constraint_name
JOIN all_cons_columns rcc
  ON rc.owner = rcc.owner AND rc.constraint_name = rcc.constraint_name
  AND cc.position = rcc.position
WHERE c.owner = :owner
  AND c.table_name = :table_name
  AND c.constraint_type = 'R'
```

## 3. 컬럼 통계

### 3-1. 컬럼별 통계
```sql
SELECT
  column_name,
  num_distinct,
  low_value,       -- RAW 형식, UTL_RAW.CAST_TO_* 로 변환 필요
  high_value,      -- RAW 형식
  density,
  num_nulls,
  num_buckets,
  histogram,       -- NONE, FREQUENCY, HEIGHT BALANCED, HYBRID
  sample_size,
  last_analyzed
FROM all_tab_col_statistics
WHERE owner = :owner
  AND table_name = :table_name
ORDER BY column_name
```

### 3-2. LOW_VALUE/HIGH_VALUE를 읽을 수 있는 값으로 변환
```sql
-- NUMBER 컬럼
SELECT column_name,
  UTL_RAW.CAST_TO_NUMBER(low_value) AS low_val,
  UTL_RAW.CAST_TO_NUMBER(high_value) AS high_val
FROM all_tab_col_statistics
WHERE owner = :owner AND table_name = :table_name
  AND data_type IN ('NUMBER', 'FLOAT')

-- VARCHAR2 컬럼
SELECT column_name,
  UTL_RAW.CAST_TO_VARCHAR2(low_value) AS low_val,
  UTL_RAW.CAST_TO_VARCHAR2(high_value) AS high_val
FROM all_tab_col_statistics s
JOIN all_tab_columns c USING (owner, table_name, column_name)
WHERE s.owner = :owner AND s.table_name = :table_name
  AND c.data_type IN ('VARCHAR2', 'CHAR', 'NVARCHAR2')

-- DATE 컬럼
SELECT column_name,
  TO_CHAR(
    TO_DATE(
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),1,2),'XX') - 100, 'FM00') ||
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),3,2),'XX') - 100, 'FM00') ||
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),5,2),'XX'), 'FM00') ||
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),7,2),'XX') - 1, 'FM00') ||
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),9,2),'XX') - 1, 'FM00') ||
      TO_CHAR(TO_NUMBER(SUBSTR(RAWTOHEX(low_value),11,2),'XX') - 1, 'FM00'),
      'YYYYMMDDHH24MISS'
    ), 'YYYY-MM-DD HH24:MI:SS'
  ) AS low_val
FROM all_tab_col_statistics s
JOIN all_tab_columns c USING (owner, table_name, column_name)
WHERE s.owner = :owner AND s.table_name = :table_name
  AND c.data_type = 'DATE'
```

### 3-3. 테이블 통계
```sql
SELECT
  num_rows,
  avg_row_len,
  last_analyzed,
  sample_size
FROM all_tab_statistics
WHERE owner = :owner
  AND table_name = :table_name
  AND partition_name IS NULL
```

## 4. SQL 실행 이력

### 4-1. V$SQL에서 해당 쿼리 검색
```sql
SELECT
  sql_id,
  sql_text,
  executions,
  rows_processed,
  elapsed_time / 1000000 AS elapsed_sec,
  first_load_time,
  last_active_time
FROM v$sql
WHERE sql_text LIKE '%' || :query_keyword || '%'
  AND sql_text NOT LIKE '%v$sql%'  -- 자기 자신 제외
ORDER BY last_active_time DESC
FETCH FIRST 5 ROWS ONLY
```
> :query_keyword는 parsed.json의 쿼리에서 고유한 테이블명+컬럼명 조합 사용

### 4-2. V$SQL_BIND_CAPTURE — 바인드 변수 캡처 값 (핵심)
```sql
SELECT
  bc.name AS bind_name,
  bc.position,
  bc.datatype_string,
  bc.value_string,
  bc.was_captured,
  bc.last_captured,
  bc.precision,
  bc.scale,
  bc.max_length
FROM v$sql_bind_capture bc
WHERE bc.sql_id = :sql_id
ORDER BY bc.position
```

### 4-3. V$SQL_BIND_METADATA — 바인드 메타 (타입 정보)
```sql
SELECT
  position,
  datatype,
  max_length,
  array_len,
  bind_name
FROM v$sql_bind_metadata
WHERE sql_id = :sql_id
ORDER BY position
```

## 5. AWR 장기 이력 (Diagnostics Pack 라이선스 필요)

### 5-1. AWR SQL 통계
```sql
SELECT
  snap_id,
  plan_hash_value,
  executions_delta,
  rows_processed_delta,
  elapsed_time_delta / 1000000 AS elapsed_sec
FROM dba_hist_sqlstat
WHERE sql_id = :sql_id
ORDER BY snap_id DESC
FETCH FIRST 20 ROWS ONLY
```

### 5-2. AWR 바인드 메타데이터
```sql
SELECT
  position,
  datatype_string,
  max_length,
  name AS bind_name
FROM dba_hist_sql_bind_metadata
WHERE sql_id = :sql_id
```

### 5-3. AWR SQL 전문 (V$SQL에서 aged out된 경우)
```sql
SELECT sql_text
FROM dba_hist_sqltext
WHERE sql_id = :sql_id
```

## 6. 샘플 데이터

### 6-1. 테이블 샘플링 (SAMPLE 힌트로 효율적 랜덤 추출)
```sql
SELECT *
FROM {table_name} SAMPLE(1)
WHERE ROWNUM <= 10
```

### 6-2. FK 참조 테이블의 실제 존재하는 키 값
```sql
SELECT DISTINCT {ref_column}
FROM {ref_table}
WHERE ROWNUM <= 20
ORDER BY {ref_column}
```

### 6-3. 특정 컬럼의 유니크 값 분포 (히스토그램 대용)
```sql
SELECT {column_name}, COUNT(*) AS cnt
FROM {table_name}
GROUP BY {column_name}
ORDER BY cnt DESC
FETCH FIRST 10 ROWS ONLY
```

## 7. 시퀀스/시노님/뷰

### 7-1. 시퀀스 정보
```sql
SELECT
  sequence_name,
  min_value,
  max_value,
  increment_by,
  last_number,
  cache_size,
  cycle_flag
FROM all_sequences
WHERE sequence_owner = :owner
  AND sequence_name = :sequence_name
```

### 7-2. 시노님 해석
```sql
SELECT
  synonym_name,
  table_owner,
  table_name,
  db_link
FROM all_synonyms
WHERE owner IN (:owner, 'PUBLIC')
  AND synonym_name = :object_name
```

### 7-3. 뷰 정의 SQL
```sql
SELECT text
FROM all_views
WHERE owner = :owner
  AND view_name = :view_name
```

## 8. 인덱스 정보

### 8-1. 인덱스 목록
```sql
SELECT
  index_name,
  index_type,
  uniqueness,
  status
FROM all_indexes
WHERE owner = :owner
  AND table_name = :table_name
```

### 8-2. 인덱스 컬럼 구성
```sql
SELECT
  index_name,
  column_name,
  column_position,
  descend
FROM all_ind_columns
WHERE index_owner = :owner
  AND table_name = :table_name
ORDER BY index_name, column_position
```

## 권한 부족 시 대응 전략

| 뷰 | 필요 권한 | 대안 |
|----|----------|------|
| V$SQL, V$SQLAREA | SELECT on V_$SQL | 샘플 데이터 + 통계 기반만 사용 |
| V$SQL_BIND_CAPTURE | SELECT on V_$SQL_BIND_CAPTURE | 통계 기반 경계값 + 동적 SQL 분기 분석 |
| DBA_HIST_* | SELECT_CATALOG_ROLE + Diagnostics Pack | V$ 뷰로 대체 |
| ALL_TAB_COL_STATISTICS | 기본 접근 가능 | (대안 불필요) |
| SAMPLE 힌트 | 기본 접근 가능 | SELECT ... WHERE ROWNUM <= 10 |

수집 순서: 통계(3) → 제약(2) → 바인드캡처(4) → 샘플(6) → AWR(5)
권한 오류 발생 시 → 해당 단계 스킵, 에러 로그 기록, 다음 단계로 진행
```

- [ ] **Step 3: 검증**

```bash
head -5 .kiro/skills/generate-test-cases/SKILL.md
wc -l .kiro/skills/generate-test-cases/references/oracle-dictionary-queries.md
```

Expected: frontmatter 확인, 200줄 이상

- [ ] **Step 4: 커밋**

```bash
git add .kiro/skills/generate-test-cases/
git commit -m "feat: add generate-test-cases skill with Oracle dictionary queries"
```

---

## Task 15: Test Generator 에이전트

**Files:**
- Create: `.kiro/prompts/test-generator.md`
- Create: `.kiro/agents/test-generator.json`

- [ ] **Step 1: 프롬프트 생성**

Create: `.kiro/prompts/test-generator.md`

```markdown
# Test Case Generator

당신은 Oracle 딕셔너리를 활용하여 SQL 쿼리별 의미 있는 테스트 케이스를 생성하는 전문 에이전트입니다.

## 역할
- 쿼리 구조 분석 (파라미터, 동적 SQL 분기, 참조 테이블)
- Oracle 딕셔너리에서 메타데이터/통계/실행 이력/바인드 캡처 값 수집
- 쿼리 의미를 파악하여 의미 있는 바인드 변수 조합 생성
- test-cases.json으로 기록

## 입력
Leader로부터 전달받는 정보:
- 대상 파일 목록
- 버전 번호

## 핵심 원칙

### 의미 있는 테스트 케이스란?
- 단순 더미 값(1, 'test')이 아닌, 실제 비즈니스 시나리오를 반영하는 값
- Oracle에서 실제로 실행된 적 있는 바인드 값 (V$SQL_BIND_CAPTURE)
- 테이블의 실제 데이터 분포를 반영하는 경계값
- 동적 SQL의 모든 분기를 커버하는 조합
- Oracle/PostgreSQL 간 차이가 드러나는 엣지 케이스 값

### Oracle 딕셔너리 수집 우선순위
1. ALL_TAB_COL_STATISTICS (거의 항상 접근 가능, 기본 정보)
2. ALL_CONSTRAINTS / ALL_CONS_COLUMNS (제약조건, 유효 값 범위)
3. V$SQL_BIND_CAPTURE (실제 바인드 값, 권한 필요할 수 있음)
4. 샘플 데이터 (실제 테이블 데이터)
5. DBA_HIST_* (AWR, 라이선스 필요할 수 있음)

권한 부족 시: 해당 단계 스킵, 로그 기록, 가용한 소스로 보완

## 처리 절차

### 1. parsed.json 분석
각 쿼리에서 추출:
- 파라미터 목록: [{name, type, notation}]
- 동적 SQL 분기: [{tag, test_condition, content}]
- 참조 테이블: SQL에서 FROM/JOIN 뒤의 테이블명
- WHERE 조건 컬럼: 바인드 변수가 비교되는 컬럼

### 2. Oracle 딕셔너리 수집
generate-test-cases 스킬의 references/oracle-dictionary-queries.md 참조하여 순차 수집.

수집 결과를 쿼리별로 정리:
```json
{
  "query_id": "selectUserById",
  "oracle_metadata": {
    "tables": {
      "USERS": {
        "row_count": 150000,
        "columns": {
          "ID": {"type": "NUMBER", "nullable": false, "low": 1, "high": 200000, "distinct": 150000},
          "STATUS": {"type": "VARCHAR2(20)", "nullable": true, "distinct": 5, "values": ["ACTIVE","INACTIVE","SUSPENDED","DELETED","PENDING"]}
        }
      }
    },
    "bind_captures": [
      {"name": ":1", "value": "42", "type": "NUMBER", "captured_at": "2026-04-01"},
      {"name": ":2", "value": "ACTIVE", "type": "VARCHAR2", "captured_at": "2026-04-01"}
    ],
    "fk_refs": {
      "DEPT_ID": {"ref_table": "DEPARTMENTS", "ref_column": "ID", "sample_values": [1,2,3,5,10]}
    },
    "sql_executions": 45000,
    "permissions": {"v$sql": true, "v$sql_bind_capture": true, "dba_hist": false}
  }
}
```

### 3. 테스트 케이스 생성
쿼리별 6개 카테고리에서 조합:

| 카테고리 | source 값 | 우선순위 | 설명 |
|---------|-----------|---------|------|
| A: 바인드 캡처 | V$SQL_BIND_CAPTURE | 1 (최우선) | 실제 운영 값 |
| B: 통계 경계값 | ALL_TAB_COL_STATISTICS | 2 | min/max/median |
| C: 동적 분기 | dynamic_sql_branch | 3 | 모든 if/choose 분기 커버 |
| D: NULL 시멘틱스 | oracle_null_semantics | 4 | NULL, '', ' ' 변형 |
| E: FK 관계 | FK_RELATIONSHIP | 5 | JOIN 매칭/비매칭 |
| F: 샘플 데이터 | SAMPLE_DATA | 6 | 실제 테이블 값 |

각 쿼리에 최소 3개, 최대 10개 테스트 케이스.

### 4. 동적 SQL 분기 커버리지 분석

동적 SQL 분기를 분석하여 모든 경로를 타는 변수 조합 생성:

예시 - `<if test="name != null">AND name = #{name}</if>`:
- Case C-1: name = "홍길동" → if 분기 진입
- Case C-2: name = null → if 분기 스킵

예시 - `<choose><when test="status == 'A'">...<when test="status == 'I'">...<otherwise>...`:
- Case C-1: status = "A" → 첫 번째 when
- Case C-2: status = "I" → 두 번째 when
- Case C-3: status = "X" → otherwise

예시 - `<foreach collection="idList">`:
- Case C-1: idList = [] → 빈 리스트
- Case C-2: idList = [1] → 단일 항목
- Case C-3: idList = [1, 2, 3] → 복수 항목

### 5. 결과 기록
workspace/results/{filename}/v{n}/test-cases.json

### 6. Leader에게 반환
한 줄 요약만

## 주의사항
- PII(개인정보) 컬럼 감지 시: 컬럼 코멘트에서 '주민', '전화', 'email' 등 키워드 확인 → 값 마스킹
- 대량 테이블 샘플링: SAMPLE(1) 힌트 사용 (전체 스캔 방지)
- V$ 뷰 조회 시 ORA-00942 → 권한 부족, 건너뛰기
- AWR 조회 시 ORA-13516 → 라이선스 미보유, 건너뛰기
```

- [ ] **Step 2: 에이전트 JSON 생성**

Create: `.kiro/agents/test-generator.json`

```json
{
  "name": "test-generator",
  "description": "쿼리별 바인드 변수를 분석하고 Oracle 딕셔너리에서 메타데이터/실행 이력/실제 바인드 값을 수집하여 의미 있는 테스트 케이스 조합을 생성한다.",
  "prompt": "file://../prompts/test-generator.md",
  "model": "claude-opus-4.6",
  "tools": ["read", "write", "@oracle-mcp"],
  "allowedTools": ["read", "write", "@oracle-mcp/query"],
  "mcpServers": {
    "oracle-mcp": {
      "command": "npx",
      "args": ["-y", "oracle-mcp-server"],
      "env": {
        "ORACLE_HOST": "${ORACLE_HOST}",
        "ORACLE_PORT": "${ORACLE_PORT}",
        "ORACLE_SID": "${ORACLE_SID}",
        "ORACLE_USER": "${ORACLE_USER}",
        "ORACLE_PASSWORD": "${ORACLE_PASSWORD}"
      },
      "timeout": 60000
    }
  },
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "skill://.kiro/skills/generate-test-cases/SKILL.md"
  ]
}
```

- [ ] **Step 3: JSON 유효성 검증**

```bash
python3 -c "import json; json.load(open('.kiro/agents/test-generator.json')); print('Valid JSON')"
```

- [ ] **Step 4: 커밋**

```bash
git add .kiro/prompts/test-generator.md .kiro/agents/test-generator.json
git commit -m "feat: add test-generator agent (Oracle dictionary-powered test cases)"
```

---

## Task 16: Validator 스킬 업데이트 (test-cases.json 활용)

기존 explain-test, execute-test, compare-test 스킬이 단순 더미 바인딩 대신 test-cases.json을 활용하도록 수정.

**Files:**
- Modify: `.kiro/skills/explain-test/SKILL.md`
- Modify: `.kiro/skills/execute-test/SKILL.md`
- Modify: `.kiro/skills/compare-test/SKILL.md`

- [ ] **Step 1: explain-test SKILL.md 수정**

기존 "파라미터 바인딩 전략" 섹션을 교체:

```markdown
## 파라미터 바인딩 전략

### 우선: test-cases.json 사용
workspace/results/{filename}/v{n}/test-cases.json이 존재하면:
- 각 테스트 케이스의 binds 값을 사용하여 파라미터 바인딩
- 모든 테스트 케이스에 대해 EXPLAIN 실행
- 하나라도 실패하면 fail, 전체 통과하면 pass

### 대안: 단순 더미 바인딩 (test-cases.json 없을 경우)
- VARCHAR/TEXT → 'test'
- INTEGER/NUMERIC → 1
- DATE/TIMESTAMP → '2024-01-01'
```

- [ ] **Step 2: execute-test SKILL.md 수정**

기존 "파라미터 더미 바인딩" 부분을 교체:

```markdown
## 파라미터 바인딩

### 우선: test-cases.json 사용
- 각 테스트 케이스별로 개별 실행
- 테스트 케이스 ID별 실행 결과 기록
- 특정 테스트 케이스에서만 실패하는 경우 → 해당 케이스 정보 상세 기록

### 대안: 단순 더미 바인딩 (test-cases.json 없을 경우)
```

- [ ] **Step 3: compare-test SKILL.md 수정**

기존 "동일 더미 파라미터로 양쪽 실행" 부분을 교체:

```markdown
## 비교 실행

### 우선: test-cases.json 사용
- 각 테스트 케이스별로 Oracle/PostgreSQL 양쪽 실행
- 테스트 케이스별 비교 결과 개별 기록
- 특정 바인드 값 조합에서만 차이 발생하는 경우 → 해당 케이스 상세 기록
  (어떤 바인드 조합이 문제인지 식별 가능)

### 결과 기록 확장
validated.json의 compare 섹션에 테스트 케이스별 결과 추가:
```json
{
  "compare": {
    "status": "partial_fail",
    "test_case_results": [
      {"case_id": "tc1_bind_capture", "status": "pass"},
      {"case_id": "tc4_null_status", "status": "fail", "reason": "Oracle returns 0 rows, PG returns 3 rows ('' != NULL)"}
    ]
  }
}
```
```

- [ ] **Step 4: Validator 프롬프트 수정**

`.kiro/prompts/validator.md`에 test-cases.json 활용 안내 추가:

```markdown
## 테스트 케이스 활용

workspace/results/{filename}/v{n}/test-cases.json이 존재하면:
- 단순 더미 바인딩 대신 test-cases.json의 테스트 케이스 사용
- 각 테스트 케이스별로 3단계 검증 수행
- validated.json에 테스트 케이스별 결과 기록
- 특정 테스트 케이스에서만 실패하는 패턴 식별 → Reviewer에게 유용한 단서
```

- [ ] **Step 5: Leader 프롬프트 수정**

`.kiro/prompts/oracle-pg-leader.md`의 Phase 2와 Phase 3 사이에 Phase 2.5 추가:

```markdown
### Phase 2.5: 테스트 케이스 생성 (병렬)
1. Phase 2와 동일한 배치 단위로 Test Generator 서브에이전트 위임
2. Oracle 딕셔너리에서 메타데이터/바인드 캡처 값 수집
3. 쿼리별 다중 테스트 케이스 생성 → test-cases.json
4. progress.json 갱신
```

Leader의 서브에이전트 호출 순서 업데이트:
```
Parser → Converter → Test Generator → Validator → Reviewer → Learner
```

- [ ] **Step 6: Leader JSON 수정**

`.kiro/agents/oracle-pg-leader.json`의 `toolsSettings.subagent`:

```json
{
  "availableAgents": ["converter", "test-generator", "validator", "reviewer", "learner"],
  "trustedAgents": ["converter", "test-generator", "validator"]
}
```

- [ ] **Step 7: 커밋**

```bash
git add .kiro/skills/explain-test/ .kiro/skills/execute-test/ .kiro/skills/compare-test/
git add .kiro/prompts/validator.md .kiro/prompts/oracle-pg-leader.md
git add .kiro/agents/oracle-pg-leader.json
git commit -m "feat: integrate test-cases.json into validation pipeline"
```
