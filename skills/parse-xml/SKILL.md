---
name: parse-xml
description: MyBatis 또는 iBatis XML 파일을 파싱하여 SQL 쿼리를 추출한다. mapper namespace, 쿼리 ID, SQL 타입(select/insert/update/delete), 동적 SQL 요소(if/choose/foreach 등), 파라미터 매핑을 식별한다.
---

## 참조 자료
- `references/mybatis-ibatis-tag-reference.md` — MyBatis 3.x (28태그) + iBatis 2.x (35태그) 전수 레퍼런스
- `assets/parsed-template.json` — parsed.json 출력 형식 템플릿
- `fixtures/` — 스모크 테스트용 XML 샘플:
  - `mybatis3-basic.xml` — 기본 CRUD + 동적 SQL + Oracle 함수
  - `mybatis3-complex.xml` — CONNECT BY, MERGE INTO, LISTAGG, ROWNUM 페이징
  - `mybatis3-nightmare.xml` — L4 복합 (ROWNUM+CONNECT BY×3+REGEXP+DBMS_LOB+MERGE)
  - `ibatis2-sample.xml` — iBatis 2.x 동적 태그, iterate, procedure
  - `README.md` — fixture 사용법 및 검증 체크리스트

## 입력
- XML 파일 경로 (단일 또는 glob 패턴)

## 처리 절차

1. XML 루트 태그로 프레임워크 판별:
   - `<mapper namespace="...">` → MyBatis 3.x (28개 태그 대상)
   - `<sqlMap namespace="...">` → iBatis 2.x (35개+ 태그 대상)
   - references/mybatis-ibatis-tag-reference.md §7 체크리스트 기준으로 전수 파싱

2. 각 쿼리 노드 추출:
   - MyBatis: `<select>`, `<insert>`, `<update>`, `<delete>`
   - iBatis: 위 + `<statement>`, `<procedure>`

3. 동적 SQL 요소 식별 및 구조화:
   - MyBatis: `<if>`, `<choose>/<when>/<otherwise>`, `<where>`, `<set>`, `<trim>`, `<foreach>`, `<bind>`
   - iBatis: `<dynamic>`, `<isNull>`, `<isNotNull>`, `<isEmpty>`, `<isNotEmpty>`, `<isEqual>`, `<isNotEqual>`, `<isGreaterThan>`, `<isGreaterEqual>`, `<isLessThan>`, `<isLessEqual>`, `<isPropertyAvailable>`, `<isNotPropertyAvailable>`, `<isParameterPresent>`, `<isNotParameterPresent>`, `<iterate>`

4. `<include refid="...">` 처리:
   - 같은 XML 내 `<sql id="...">` 를 찾아 인라인 전개
   - 여러 XML 간 cross-reference가 있으면 참조 관계만 기록 (전개하지 않음)
   - MyBatis 3.x의 `<include>` 내부 `<property>` 오버라이드 처리

5. 파라미터 매핑 추출:
   - MyBatis: `#{param}`, `#{param,jdbcType=VARCHAR}`, `${param}`
   - iBatis: `#param#`, `#param:VARCHAR#`, `$param$`
   - 자동 판별하여 통일된 형식으로 기록

6. Oracle 특유 구문 태깅:
   - 단순 패턴 → "rule" 태그:
     - NVL, NVL2, DECODE, SYSDATE, SYSTIMESTAMP
     - ROWNUM, sequence.NEXTVAL/CURRVAL
     - (+) 아우터 조인, FROM DUAL
     - TO_DATE/TO_CHAR 포맷 차이, LISTAGG, MINUS
   - 복잡 패턴 → "llm" 태그:
     - CONNECT BY / START WITH (계층 쿼리)
     - MERGE INTO
     - PIVOT / UNPIVOT
     - PL/SQL 프로시저/패키지 호출
     - Oracle 힌트 (/*+ ... */)
     - XMLTYPE 조작

7. `<selectKey>` 내부 Oracle 시퀀스 패턴 감지:
   - `SELECT SEQ.NEXTVAL FROM DUAL` → "rule" 태그

8. 결과를 `workspace/results/{filename}/v1/parsed.json` 으로 기록
   - assets/parsed-template.json 형식 참조

## ${...} 문자열 치환 감지

`${param}`은 MyBatis가 런타임에 문자열로 직접 치환하는 패턴이다.
실제 값이 XML에 없으므로 Oracle 구문이 숨어있을 수 있다.

감지 시:
1. `${...}` 사용 위치와 용도를 parsed.json에 기록
2. 해당 쿼리에 `dollar_substitution` 플래그 추가
3. WARNING 로그 기록:
   "${tableName} 사용 감지: 런타임 문자열 치환으로 Oracle 구문이 숨어있을 수 있음. 수동 검토 필요."
4. migration-guide.md의 수동 검토 항목에 등록

## 주의사항
- 동적 SQL은 가능한 모든 분기의 SQL을 추출
- iBatis `<iterate>` 내부의 `#list[]#` 표기도 파라미터로 추출
- resultMap, parameterMap 정의는 파싱하되 SQL 변환 대상은 아님 (구조 참조용)
- `<cache>`, `<cache-ref>` 등 비SQL 태그는 메타데이터로 기록
