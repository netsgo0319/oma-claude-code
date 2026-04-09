# PL/SQL → PL/pgSQL 변환 패턴

## 프로시저 호출 (MyBatis callable)

```xml
<!-- Oracle -->
<select id="callProc" statementType="CALLABLE">
  {call PKG_USER.GET_USER_INFO(#{userId, mode=IN}, #{result, mode=OUT, jdbcType=CURSOR})}
</select>

<!-- PostgreSQL -->
<select id="callProc" statementType="CALLABLE">
  {call get_user_info(#{userId, mode=IN}, #{result, mode=OUT, jdbcType=OTHER})}
</select>
```
> Oracle PACKAGE.PROCEDURE → PostgreSQL에서는 패키지 없이 함수명만
> OUT 파라미터의 jdbcType: CURSOR → OTHER (PostgreSQL refcursor)

## 함수 호출 (SELECT 내)

```sql
-- Oracle
SELECT PKG_UTIL.FORMAT_NAME(first_name, last_name) FROM employees
-- PostgreSQL
SELECT format_name(first_name, last_name) FROM employees
```
> 패키지명 제거, 함수명만 사용

## PACKAGE 전체 변환 가이드

Oracle PACKAGE는 PostgreSQL에 직접 대응이 없음. 변환 전략:

1. **스키마로 대체**: `PKG_USER.PROC()` → `pkg_user.proc()` (스키마.함수)
2. **함수만 마이그레이션**: 패키지 내 각 프로시저/함수를 독립 PL/pgSQL 함수로 생성
3. **패키지 변수**: 세션 변수 또는 임시 테이블로 대체

> 이 변환은 SQL 레벨에서 자동화하기 어려움. migration-guide.md에 수동 검토 항목으로 등록.

## CURSOR 변환

```sql
-- Oracle PL/SQL
OPEN cur FOR SELECT * FROM users WHERE dept_id = p_dept_id;
-- PL/pgSQL
RETURN QUERY SELECT * FROM users WHERE dept_id = p_dept_id;
```

## 예외 처리

```sql
-- Oracle
EXCEPTION
  WHEN NO_DATA_FOUND THEN ...
  WHEN TOO_MANY_ROWS THEN ...
-- PL/pgSQL
EXCEPTION
  WHEN NO_DATA_FOUND THEN ...
  WHEN TOO_MANY_ROWS THEN ...
```
> 기본 예외명은 동일. Oracle 전용 예외는 개별 매핑 필요.

## 주의사항
- MyBatis XML에서 PL/SQL 호출은 `statementType="CALLABLE"` 확인
- OUT/INOUT 파라미터의 jdbcType 변환 필요
- 패키지 레벨 변환은 XML 변환 범위를 넘어서므로 가이드 문서에 기록
