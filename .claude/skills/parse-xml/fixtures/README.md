# Test Fixtures

MyBatis/iBatis XML 샘플 파일 — parse-xml 스킬의 스모크 테스트 및 변환 파이프라인 검증용.

## 파일 목록

| 파일 | 프레임워크 | 커버하는 패턴 |
|------|-----------|-------------|
| mybatis3-basic.xml | MyBatis 3.x | CRUD, 동적 SQL (if/where/choose/foreach/set), sql+include, selectKey, NVL, SYSDATE, ROWNUM, DECODE, (+) outer join |
| mybatis3-complex.xml | MyBatis 3.x | CONNECT BY NOCYCLE, SYS_CONNECT_BY_PATH, ORDER SIBLINGS BY, MERGE INTO, LISTAGG, ROWNUM 페이징, Oracle 힌트, NVL2, TO_CHAR, ADD_MONTHS, MONTHS_BETWEEN, TO_DATE |
| mybatis3-nightmare.xml | MyBatis 3.x | **L4 복합**: ROWNUM 3중 페이징 + CONNECT BY NOCYCLE(조건부) + (+)조인 + 스칼라 서브쿼리 + LISTAGG + DECODE + NVL + REGEXP_LIKE + DBMS_LOB + 다중 CONNECT BY(3개) + CONNECT_BY_ISLEAF + CONNECT_BY_ROOT + SYS_CONNECT_BY_PATH + GREATEST/LEAST + MERGE INTO + DELETE절 + FETCH FIRST + 분석함수 + foreach + choose |
| ibatis2-sample.xml | iBatis 2.x | dynamic, isNotNull, isNotEmpty, isEqual, isGreaterThan, iterate, selectKey type=pre, #prop# 표기, procedure, cacheModel, resultMap, typeAlias |

## 사용법

```bash
# parse-xml 스모크 테스트
cp .claude/skills/parse-xml/fixtures/*.xml workspace/input/
kiro-cli --agent oracle-pg-leader
# workspace/results/ 에서 parsed.json 확인
```

## 검증 체크리스트

- [ ] mybatis3-basic.xml: 10개 쿼리 파싱, Oracle 구문 태깅 (rule: NVL/SYSDATE/ROWNUM/DECODE/(+), llm: 없음)
- [ ] mybatis3-complex.xml: 6개 쿼리 파싱, Oracle 구문 태깅 (rule: NVL2/TO_CHAR/ADD_MONTHS/LISTAGG/ROWNUM/힌트, llm: CONNECT BY/MERGE INTO)
- [ ] mybatis3-nightmare.xml: 4개 쿼리 파싱, Oracle 구문 태깅 (rule: NVL/DECODE/SYSDATE/ADD_MONTHS/GREATEST/REGEXP/DBMS_LOB/LISTAGG/(+)/DUAL, llm: CONNECT BY×3/MERGE INTO/ROWNUM페이징/FETCH FIRST)
- [ ] ibatis2-sample.xml: 4개 쿼리 파싱, iBatis 2.x 태그 인식, #prop# 표기 감지, procedure 태깅
