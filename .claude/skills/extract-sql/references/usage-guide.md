# MyBatis SQL Extractor 사용 가이드

## 왜 필요한가?

MyBatis XML의 동적 SQL은 런타임에 OGNL 표현식으로 평가된다:

```xml
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="name != null">AND name = #{name}</if>
    <if test="status != null">AND status = #{status}</if>
    <foreach collection="ids" open="AND id IN (" separator="," close=")">
      #{item}
    </foreach>
  </where>
</select>
```

이 쿼리가 실제로 생성하는 SQL은 파라미터에 따라 다르다:
- name=null, status=null, ids=[] → `SELECT * FROM users`
- name="test", status=null, ids=[] → `SELECT * FROM users WHERE name = ?`
- name="test", status="A", ids=[1,2] → `SELECT * FROM users WHERE name = ? AND status = ? AND id IN (?, ?)`

에이전트(LLM)가 이걸 직접 해석하면 복잡한 경우 실수할 수 있다.
MyBatis 엔진이 직접 평가하면 100% 정확하다.

## 빌드

```bash
cd tools/mybatis-sql-extractor
gradle build
```

빌드 결과: `build/libs/mybatis-sql-extractor-1.0.0.jar`

## 실행 예시

### 단독 실행
```bash
java -jar build/libs/mybatis-sql-extractor-1.0.0.jar \
  --input ../../workspace/input \
  --output ../../workspace/results/_extracted
```

### 에이전트 내에서 실행
메인 에이전트에서:
```bash
java -jar tools/mybatis-sql-extractor/build/libs/mybatis-sql-extractor-1.0.0.jar \
  --input workspace/input \
  --output workspace/results/_extracted
```

## 출력 활용

추출된 `*-extracted.json`의 sql_variants를 parsed.json에 병합하여 사용:
- sql_variants의 각 variant가 동적 SQL의 각 분기를 나타냄
- 변환 시 모든 variant의 Oracle 구문을 변환해야 함
- variant별로 다른 Oracle 패턴이 나타날 수 있음 (예: name != null일 때만 NVL 사용)

## 트러블슈팅

### ClassNotFoundException
원인: mybatis-config.xml에 참조된 TypeHandler/TypeAlias 클래스 없음
해결: --config 없이 기본 설정으로 실행, 또는 프로젝트의 classpath에 해당 클래스 포함

### mapper XML 파싱 에러
원인: DTD 참조 실패, 네임스페이스 충돌
해결: 에러 로그 확인, 해당 파일은 extract-sql 없이 parse-xml 스킬로 폴백

### iBatis 2.x 파일
extract-sql은 MyBatis 3.x만 지원. iBatis 2.x 파일(<sqlMap>)은 기존 parse-xml 스킬로 처리.
