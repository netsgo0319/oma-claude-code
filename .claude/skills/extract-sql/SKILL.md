---
name: extract-sql
description: MyBatis BoundSql 엔진으로 동적 SQL 추출. validate-and-fix 에이전트가 검증 전에 <if>, <choose>, <foreach> 등 동적 태그를 평가하여 실행 가능한 SQL을 얻을 때 사용합니다. 반드시 run-extractor.sh를 통해 실행합니다.
---

## 개요

MyBatis의 실제 엔진(SqlSessionFactory + BoundSql)으로 동적 SQL을 정확하게 평가.
- `<if>`, `<choose>`, `<foreach>` 등 동적 태그가 OGNL 엔진으로 정확히 평가됨
- `<include>` 참조가 MyBatis가 정확히 resolve
- TypeHandler 기반 정확한 파라미터 바인딩

## ★ 실행 방법 (run-extractor.sh만 사용)

```bash
bash tools/run-extractor.sh              # 빌드 + 추출
bash tools/run-extractor.sh --validate   # + EXPLAIN 검증
bash tools/run-extractor.sh --execute    # + 실제 쿼리 실행
bash tools/run-extractor.sh --skip-build # 빌드 생략 (재실행)
```

**이것이 유일한 실행 방법이다.** 아래는 전부 금지:
- ❌ `gradle build` 직접 실행
- ❌ `java -jar mybatis-sql-extractor-*.jar ...` 직접 실행
- ❌ TypeHandler/OGNL stub 클래스 직접 생성
- ❌ build.gradle 수정

### ClassNotFoundException 자동 처리

`run-extractor.sh`가 자동으로 처리한다 (최대 5회 재시도):
1. 추출 실행 → ClassNotFoundException 감지
2. 해당 클래스의 stub Java 파일 자동 생성
3. 재빌드 + 재실행
4. **에이전트가 개입할 필요 없음**

TypeHandler stub 클래스들은 이미 repo에 존재한다:
- `tools/mybatis-sql-extractor/src/main/java/com/oma/typehandler/` (5개)
- `tools/mybatis-sql-extractor/src/main/java/com/kns/framework/util/StringUtil.java`
- `tools/mybatis-sql-extractor/src/main/java/Cannot/Cannot.java`
- `tools/mybatis-sql-extractor/src/main/java/CodeDescTypeHandler.java`

**"typehandler가 없다", "패키지가 없다" 에러를 보더라도 직접 대응하지 마라. `run-extractor.sh`에 맡겨라.**

## 사전 준비

Java 11+ 및 Gradle이 설치되어 있어야 한다.
```bash
java -version   # 11 이상
gradle --version # 또는 ./gradlew 사용
```

## 출력 형식

각 XML 파일에 대해 `{filename}-extracted.json` 생성:

```json
{
  "source_file": "UserMapper.xml",
  "framework": "mybatis3",
  "queries": [
    {
      "query_id": "selectUserById",
      "type": "select",
      "sql_variants": [
        {
          "params": "null",
          "sql": "SELECT id, name FROM users"
        },
        {
          "params": "all_non_null",
          "sql": "SELECT id, name FROM users WHERE id = ? AND status = ?",
          "parameter_mappings": [...]
        }
      ]
    }
  ]
}
```

### sql_variants 설명
- `null`: 모든 동적 SQL 조건이 false (최소 SQL)
- `all_non_null`: 모든 조건이 true (최대 SQL)
- `test_case`: test-cases.json의 실제 바인드 값으로 생성된 SQL

## 자동 처리되는 문제들

| 문제 | 자동 처리 |
|------|----------|
| DTO ClassNotFoundException | HashMap으로 자동 대체 |
| Namespace 충돌 | 파일마다 독립 Configuration |
| TypeHandler 누락 | stub 클래스 자동 생성 + 재빌드 |
| OGNL util 클래스 누락 | stub 클래스 자동 생성 + 재빌드 |

## 제한사항

- Java 11+ 런타임 필요
- MyBatis 3.x만 지원 (iBatis 2.x는 별도 처리 필요)
- DTO 클래스는 HashMap으로 자동 대체되므로 타입별 바인딩 정보가 일부 손실될 수 있음

## 참조 문서

- [run-extractor.sh](../../tools/run-extractor.sh) — 빌드+추출 통합 스크립트
- [validate-pipeline](../validate-pipeline/SKILL.md) — 검증 파이프라인 (1단계에서 이 도구 사용)
