---
name: param-type-convert
description: MyBatis 파라미터 타입 변환. converter 에이전트가 jdbcType=BLOB→BINARY, CLOB→VARCHAR, CURSOR→OTHER 등 XML 속성을 변환할 때 사용합니다.
---

## 개요

SQL 본문 변환(rule-convert, llm-convert)과 별개로, MyBatis XML의 파라미터/결과 매핑 속성도 변환이 필요하다.

상세 타입 매핑 테이블과 예시는 `references/jdbc-type-mapping.md`를 참조한다.

## 변환 대상

### 1. #{param, jdbcType=XXX} 바인드 변수의 jdbcType

| Oracle jdbcType | PostgreSQL jdbcType | 비고 |
|-----------------|--------------------|----|
| BLOB | BINARY | Oracle BLOB → PG BYTEA |
| CLOB | VARCHAR | Oracle CLOB → PG TEXT |
| NCLOB | VARCHAR | Oracle NCLOB → PG TEXT |
| CURSOR | OTHER | Oracle REF CURSOR → PG refcursor |
| SQLXML | SQLXML | 유지 (PG도 지원) |
| NUMBER | NUMERIC | |
| FLOAT | DOUBLE | |
| DATE | TIMESTAMP | Oracle DATE = 날짜+시간 |
| TIMESTAMP | TIMESTAMP | 유지 |
| VARCHAR | VARCHAR | 유지 |
| CHAR | CHAR | 유지 |
| INTEGER | INTEGER | 유지 |
| BIGINT | BIGINT | 유지 |
| DECIMAL | DECIMAL | 유지 |
| BOOLEAN | BOOLEAN | 유지 |
| ARRAY | ARRAY | 유지 |
| STRUCT | OTHER | Oracle STRUCT → PG composite type |
| RAW | BINARY | Oracle RAW → PG BYTEA |

### 2. resultType / parameterType 클래스명
일반적으로 변환 불필요 (Java 클래스는 동일). 예외:
- Oracle 전용 타입 핸들러 참조 시 경고

### 3. typeHandler 속성
Oracle 전용 TypeHandler를 감지하여 경고:
```xml
<!-- Oracle 전용 TypeHandler 감지 시 WARNING -->
#{data, typeHandler=com.example.OracleXmlTypeHandler}
```
→ WARNING: "OracleXmlTypeHandler는 PostgreSQL에서 동작하지 않을 수 있음. PostgreSQL 용 TypeHandler로 교체 필요."

### 4. mode 속성 (IN/OUT/INOUT)
```xml
<!-- Oracle -->
#{result, mode=OUT, jdbcType=CURSOR}
<!-- PostgreSQL -->
#{result, mode=OUT, jdbcType=OTHER}
```

### 5. <selectKey> 속성
```xml
<!-- iBatis 2.x -->
<selectKey keyProperty="id" resultClass="long" type="pre">
<!-- MyBatis 3.x (변환 불필요, 하지만 내부 SQL은 변환) -->
<selectKey keyProperty="id" resultType="long" order="BEFORE">
```

### 6. statementType 속성
```xml
<!-- Oracle 프로시저 호출 -->
<select statementType="CALLABLE">
  {call PKG.PROC(#{p1}, #{p2, mode=OUT, jdbcType=CURSOR})}
</select>
<!-- PostgreSQL -->
<select statementType="CALLABLE">
  {call proc(#{p1}, #{p2, mode=OUT, jdbcType=OTHER})}
</select>
```

## 처리 절차

1. parsed.json에서 각 쿼리의 parameters 배열 분석
2. #{param, jdbcType=XXX} 패턴에서 jdbcType 추출
3. 매핑 테이블에 따라 변환
4. typeHandler 속성이 있으면 Oracle 전용 여부 판단 → WARNING
5. mode=OUT + jdbcType=CURSOR → jdbcType=OTHER로 변환
6. 변환 결과를 converted.json의 각 쿼리에 param_type_changes 배열로 기록:

```json
{
  "query_id": "callProc",
  "param_type_changes": [
    {
      "parameter": "result",
      "attribute": "jdbcType",
      "from": "CURSOR",
      "to": "OTHER",
      "reason": "Oracle REF CURSOR → PostgreSQL refcursor"
    }
  ]
}
```

## 주의사항
- SQL 본문의 변환(NVL→COALESCE 등)은 이 스킬의 범위가 아님 (rule-convert/llm-convert 담당)
- 이 스킬은 XML 속성 레벨의 변환만 담당
- 변환이 필요 없는 jdbcType (VARCHAR, INTEGER 등)은 건너뛰기
- typeHandler 관련 WARNING은 migration-guide.md에 등록

## 참조 문서

- [jdbc-type-mapping](references/jdbc-type-mapping.md)
- [변환 룰셋](../../rules/oracle-pg-rules.md)
