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
