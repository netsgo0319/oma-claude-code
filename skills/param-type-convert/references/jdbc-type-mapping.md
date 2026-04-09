# Oracle → PostgreSQL JDBC Type Mapping Reference

## 변환 필요 타입

### BLOB → BINARY
```xml
<!-- Oracle -->
#{content, jdbcType=BLOB}
<!-- PostgreSQL -->
#{content, jdbcType=BINARY}
```
Oracle BLOB는 PostgreSQL에서 BYTEA로 매핑. MyBatis jdbcType은 BINARY 사용.

### CLOB / NCLOB → VARCHAR
```xml
<!-- Oracle -->
#{description, jdbcType=CLOB}
#{description, jdbcType=NCLOB}
<!-- PostgreSQL -->
#{description, jdbcType=VARCHAR}
```
Oracle CLOB/NCLOB는 PostgreSQL에서 TEXT로 매핑. MyBatis jdbcType은 VARCHAR 사용.

### CURSOR → OTHER
```xml
<!-- Oracle (OUT 파라미터로 커서 반환) -->
#{result, mode=OUT, jdbcType=CURSOR}
<!-- PostgreSQL (refcursor) -->
#{result, mode=OUT, jdbcType=OTHER}
```
Oracle의 REF CURSOR는 PostgreSQL에서 refcursor 타입. MyBatis에서는 jdbcType=OTHER로 매핑.

### NUMBER → NUMERIC
```xml
<!-- Oracle -->
#{amount, jdbcType=NUMBER}
<!-- PostgreSQL -->
#{amount, jdbcType=NUMERIC}
```

### RAW → BINARY
```xml
<!-- Oracle -->
#{hash, jdbcType=RAW}
<!-- PostgreSQL -->
#{hash, jdbcType=BINARY}
```

### STRUCT → OTHER
```xml
<!-- Oracle (사용자 정의 객체 타입) -->
#{address, jdbcType=STRUCT}
<!-- PostgreSQL -->
#{address, jdbcType=OTHER}
```

### DATE → TIMESTAMP
```xml
<!-- Oracle (DATE = 날짜+시간) -->
#{createdAt, jdbcType=DATE}
<!-- PostgreSQL (DATE = 날짜만, TIMESTAMP = 날짜+시간) -->
#{createdAt, jdbcType=TIMESTAMP}
```
주의: Oracle DATE는 시간 정보를 포함하므로 PostgreSQL TIMESTAMP에 매핑.
순수 날짜만 사용하는 경우는 DATE 유지 가능 — 컨텍스트에 따라 판단.

## 변환 불필요 타입

VARCHAR, CHAR, INTEGER, BIGINT, DECIMAL, BOOLEAN, ARRAY, TIMESTAMP, SQLXML, DOUBLE, FLOAT, REAL, BIT, TINYINT, SMALLINT

## Oracle 전용 TypeHandler 경고 패턴

다음 패턴이 typeHandler 속성에 나타나면 WARNING:
- `OracleXmlTypeHandler`
- `OracleBlobTypeHandler`
- `OracleArrayTypeHandler`
- `OracleStructTypeHandler`
- 패키지명에 `oracle` 포함하는 모든 TypeHandler
