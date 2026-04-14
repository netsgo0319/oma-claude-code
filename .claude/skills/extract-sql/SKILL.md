---
name: extract-sql
description: MyBatis SqlSessionFactory + BoundSql API를 사용하여 XML 매퍼 파일에서 실제 SQL을 추출한다. 동적 SQL(if/choose/foreach 등)을 MyBatis 엔진이 정확하게 평가하여 실제 생성되는 SQL을 얻는다.
---

## 개요

에이전트가 XML을 직접 해석하는 대신, MyBatis의 실제 엔진(SqlSessionFactory + BoundSql)을 사용하여
동적 SQL을 정확하게 평가한다. 이를 통해:
- `<if>`, `<choose>`, `<foreach>` 등 동적 태그가 OGNL 엔진으로 정확히 평가됨
- `<include>` 참조가 MyBatis가 정확히 resolve
- TypeHandler 기반 정확한 파라미터 바인딩
- 복잡한 중첩 동적 SQL도 100% 정확한 SQL 생성

## 사전 준비

Java 11+ 및 Gradle이 설치되어 있어야 한다.
```bash
java -version   # 11 이상
gradle --version # 또는 ./gradlew 사용
```

최초 1회 빌드:
```bash
cd tools/mybatis-sql-extractor
gradle build
# 또는
gradle shadowJar  # fat jar 생성
```

## 사용법

상세 사용 가이드는 `references/usage-guide.md`를 참조한다.

### 기본 사용 (mybatis-config.xml 없이)
```bash
java -jar tools/mybatis-sql-extractor/build/libs/mybatis-sql-extractor-1.0.0.jar \
  --input workspace/input \
  --output workspace/results/_extracted
```

### mybatis-config.xml 포함
```bash
java -jar tools/mybatis-sql-extractor/build/libs/mybatis-sql-extractor-1.0.0.jar \
  --input workspace/input \
  --output workspace/results/_extracted \
  --config /path/to/mybatis-config.xml
```

### test-cases.json 활용 (다양한 파라미터 조합으로 SQL 추출)
```bash
java -jar tools/mybatis-sql-extractor/build/libs/mybatis-sql-extractor-1.0.0.jar \
  --input workspace/input \
  --output workspace/results/_extracted \
  --params workspace/results/{filename}/v{n}/test-cases.json
```

## 출력 형식

각 XML 파일에 대해 `{filename}-extracted.json` 생성:

```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "framework": "mybatis3",
  "namespace": "com.example.mapper.UserMapper",
  "extraction_method": "SqlSessionFactory_BoundSql",
  "queries": [
    {
      "query_id": "selectUserById",
      "full_id": "com.example.mapper.UserMapper.selectUserById",
      "type": "select",
      "sql_raw": "SELECT id, name, email FROM users WHERE id = ? AND status = NVL(?, 'ACTIVE')",
      "sql_variants": [
        {
          "params": "null",
          "sql": "SELECT id, name FROM users",
          "parameter_mappings": [...]
        },
        {
          "params": "all_non_null",
          "sql": "SELECT id, name FROM users WHERE id = ? AND name LIKE ? AND status = ?",
          "parameter_mappings": [...],
          "param_values": {"id": 1, "name": "test", "status": "ACTIVE"}
        },
        {
          "params": "test_case",
          "sql": "SELECT ...",
          "param_values": {"id": 42, "status": "ACTIVE"}
        }
      ]
    }
  ]
}
```

### sql_variants 설명
- `null` params: 모든 동적 SQL 조건이 false인 경우의 SQL (최소 SQL)
- `empty_map` params: 빈 맵 전달 시 SQL
- `all_non_null` params: 모든 조건이 true인 경우의 SQL (최대 SQL)
- `test_case` params: test-cases.json의 실제 바인드 값으로 생성된 SQL

이 variants를 통해 동적 SQL의 각 분기에서 생성되는 **실제 SQL**을 정확히 파악할 수 있다.

## Step 1에서의 활용

Step 1에서 parse-xml 스킬 대신 (또는 병행하여) 이 도구를 실행:

1. `java -jar ... --input workspace/input --output workspace/results/_extracted`
2. 추출된 JSON에서 sql_raw와 sql_variants를 parsed.json에 병합
3. XML 직접 해석 대신 MyBatis 엔진이 생성한 **실제 SQL**을 변환 대상으로 사용

## 자동 처리되는 문제들

### DTO ClassNotFoundException
parameterType/resultType에 프로젝트 DTO 클래스 (예: `com.example.dto.UserDto`)가 지정되어 있으나
classpath에 없는 경우, **자동으로 `java.util.HashMap`으로 대체**한다.
- 수동 sed 치환 불필요
- 대체된 타입 목록이 JSON 출력의 `dto_replacements` 필드에 기록됨

### Namespace 충돌 (StrictMap Ambiguity)
여러 XML 파일을 하나의 Configuration에 로드하면 같은 이름의 쿼리 ID가 충돌한다.
**각 파일마다 독립된 Configuration을 생성**하여 처리한다.
- 수동 파일별 반복 스크립트 불필요
- 11/11 파일 독립 처리 → 0건 충돌

### Wrapper Script
MyBatis 추출 파이프라인을 한 명령으로 실행:
```bash
bash tools/run-extractor.sh              # 빌드 + 추출
bash tools/run-extractor.sh --validate   # + EXPLAIN 검증
bash tools/run-extractor.sh --execute    # + 실제 쿼리 실행
bash tools/run-extractor.sh --skip-build # 빌드 생략 (재실행)
```

## 제한사항

- Java 11+ 런타임 필요
- MyBatis 3.x만 지원 (iBatis 2.x는 별도 처리 필요)
- 커스텀 TypeHandler가 있는 프로젝트는 mybatis-config.xml 제공 필요
- DTO 클래스는 HashMap으로 자동 대체되므로 타입별 바인딩 정보가 일부 손실될 수 있음
