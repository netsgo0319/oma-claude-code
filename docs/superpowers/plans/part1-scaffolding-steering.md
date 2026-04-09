# Part 1: Scaffolding + Steering

## Task 1: 프로젝트 스캐폴딩

**Files:**
- Create: `.gitignore`
- Create: 디렉토리 구조 전체

- [ ] **Step 1: 디렉토리 구조 생성**

```bash
mkdir -p .kiro/agents
mkdir -p .kiro/prompts
mkdir -p .kiro/skills/parse-xml/references
mkdir -p .kiro/skills/parse-xml/assets
mkdir -p .kiro/skills/rule-convert/references
mkdir -p .kiro/skills/llm-convert/references
mkdir -p .kiro/skills/explain-test
mkdir -p .kiro/skills/execute-test
mkdir -p .kiro/skills/compare-test
mkdir -p .kiro/skills/report
mkdir -p .kiro/skills/learn-edge-case
mkdir -p .kiro/steering
mkdir -p workspace/input
mkdir -p workspace/output
mkdir -p workspace/results
mkdir -p workspace/reports
```

- [ ] **Step 2: .gitignore 생성**

Create: `.gitignore`

```
# Runtime artifacts
workspace/results/
workspace/progress.json

# Secrets
.env
.env.*

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 3: 검증**

```bash
find .kiro -type d | sort
cat .gitignore
```

Expected: 모든 디렉토리 존재, .gitignore 내용 확인

- [ ] **Step 4: 커밋**

```bash
git add .gitignore
git commit -m "chore: add project scaffolding and .gitignore"
```

> Note: 빈 디렉토리는 Git이 추적하지 않으므로, 이후 태스크에서 파일이 추가되면서 자연스럽게 추적됨.

---

## Task 2: Steering 파일

**Files:**
- Create: `.kiro/steering/product.md`
- Create: `.kiro/steering/tech.md`
- Create: `.kiro/steering/oracle-pg-rules.md`
- Create: `.kiro/steering/edge-cases.md`
- Create: `.kiro/steering/db-config.md`

- [ ] **Step 1: product.md 생성**

Create: `.kiro/steering/product.md`

```markdown
---
inclusion: always
---

# Oracle → PostgreSQL Migration Accelerator

## 목적
MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환하고
검증하는 Kiro 에이전트 시스템.

## 워크플로우
1. XML 파싱 → 쿼리 추출 & Oracle 구문 태깅
2. 룰 기반 변환 (단순 패턴) + LLM 변환 (복잡 패턴)
3. 3단계 검증: EXPLAIN → 실행 → Oracle/PostgreSQL 비교
4. 실패 시 원인 분석 → 자동 재시도 (최대 3회) → 에스컬레이션
5. 학습된 에지케이스 축적 → 자동 PR/Issue

## 산출물
- 변환된 XML 파일 (workspace/output/)
- 버전별 중간 결과 (workspace/results/{file}/v{n}/)
- 변환 리포트 (workspace/reports/conversion-report.md)
- 마이그레이션 가이드 (workspace/reports/migration-guide.md)

## 사용법
1. workspace/input/ 에 변환 대상 XML 배치
2. .env 파일에 Oracle/PostgreSQL 접속 정보 설정
3. oracle-pg-leader 에이전트 실행: `kiro-cli --agent oracle-pg-leader`
```

- [ ] **Step 2: tech.md 생성**

Create: `.kiro/steering/tech.md`

```markdown
---
inclusion: always
---

# 기술 스택 & 의존성

## 에이전트 런타임
- Kiro CLI + Custom Agent (JSON)
- 모델:
  - 오케스트레이터/분석: claude-opus-4.6 (1M context)
  - 변환/검증/학습: claude-sonnet-4.6 (1M context)

## DB 연결
- Oracle: sqlplus CLI (db-oracle 스킬 참조)
- PostgreSQL: psql CLI (db-postgresql 스킬 참조)
- 접속 정보: 환경변수로 관리 (.env)

## 외부 도구
- gh CLI: PR/Issue 자동 생성 (learner 에이전트)
- git: 형상관리

## 파일 형식
- 입력: MyBatis 3.x / iBatis 2.x XML
- 중간 산출물: JSON (버전별)
- 최종 산출물: XML + Markdown 리포트

## 디렉토리 규약
- workspace/input/     — 원본 (불변)
- workspace/output/    — 최종 변환 결과
- workspace/results/   — 버전별 중간 산출물 ({filename}/v{n}/)
- workspace/reports/   — 리포트
- workspace/progress.json — 진행 상황 추적

## 에이전트 구성
- oracle-pg-leader: 오케스트레이터 (메인)
- converter: 변환 서브에이전트
- validator: 검증 서브에이전트
- reviewer: 실패 분석 서브에이전트
- learner: 학습 서브에이전트
```

- [ ] **Step 3: oracle-pg-rules.md 생성**

Create: `.kiro/steering/oracle-pg-rules.md`

```markdown
---
inclusion: always
---

# Oracle → PostgreSQL 변환 룰셋

> Converter 에이전트가 rule-convert 스킬 실행 시 참조.
> Learner 에이전트가 반복 패턴 발견 시 여기에 룰 추가.

## 함수 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| NVL(a, b) | COALESCE(a, b) | |
| NVL2(a, b, c) | CASE WHEN a IS NOT NULL THEN b ELSE c END | |
| DECODE(a,b,c,...) | CASE a WHEN b THEN c ... END | 마지막 홀수 인자 = ELSE |
| SYSDATE | CURRENT_TIMESTAMP | DATE 컨텍스트면 CURRENT_DATE |
| SYSTIMESTAMP | CURRENT_TIMESTAMP | |
| LISTAGG(col, sep) WITHIN GROUP (ORDER BY ...) | STRING_AGG(col, sep ORDER BY ...) | WITHIN GROUP 제거 |
| ROWNUM | ROW_NUMBER() OVER() | 서브쿼리 래핑 필요할 수 있음 |
| sequence.NEXTVAL | nextval('sequence') | 따옴표 필수 |
| sequence.CURRVAL | currval('sequence') | |
| SUBSTR(s, pos, len) | SUBSTRING(s FROM pos FOR len) | 또는 SUBSTR 그대로 (PG 지원) |
| INSTR(s, sub) | POSITION(sub IN s) | 3번째 인자 있으면 별도 처리 |
| TO_DATE(s, fmt) | TO_DATE(s, fmt) | 포맷 문자열 변환 필요 |
| TO_CHAR(d, fmt) | TO_CHAR(d, fmt) | 포맷 문자열 변환 필요 |
| TO_NUMBER(s) | CAST(s AS NUMERIC) | 또는 s::NUMERIC |
| TRUNC(date) | DATE_TRUNC('day', date) | |
| ADD_MONTHS(d, n) | d + INTERVAL 'n months' | |
| MONTHS_BETWEEN(d1, d2) | EXTRACT(YEAR FROM AGE(d1,d2))*12 + EXTRACT(MONTH FROM AGE(d1,d2)) | |
| LAST_DAY(d) | (DATE_TRUNC('month', d) + INTERVAL '1 month - 1 day')::DATE | |

## 조인 변환

| Oracle | PostgreSQL |
|--------|-----------|
| WHERE a.col = b.col(+) | a LEFT JOIN b ON a.col = b.col |
| WHERE a.col(+) = b.col | a RIGHT JOIN b ON a.col = b.col |
| 복수 (+) 조건 | 복수 ON 조건으로 변환 |

## 데이터 타입 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| VARCHAR2(n) | VARCHAR(n) | |
| NVARCHAR2(n) | VARCHAR(n) | |
| CHAR(n) | CHAR(n) | |
| NUMBER | NUMERIC | |
| NUMBER(p) | NUMERIC(p) | |
| NUMBER(p,s) | NUMERIC(p,s) | |
| INTEGER | INTEGER | |
| FLOAT | DOUBLE PRECISION | |
| DATE | TIMESTAMP | Oracle DATE = 날짜+시간 |
| TIMESTAMP | TIMESTAMP | |
| CLOB | TEXT | |
| NCLOB | TEXT | |
| BLOB | BYTEA | |
| RAW(n) | BYTEA | |
| LONG | TEXT | |
| XMLTYPE | XML | |

## 날짜 포맷 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| RR | YY | 2자리 연도 |
| YYYY | YYYY | |
| MM | MM | |
| DD | DD | |
| HH24 | HH24 | |
| HH / HH12 | HH12 | |
| MI | MI | |
| SS | SS | |
| FF / FF3 / FF6 | MS / US | 밀리초/마이크로초 |
| AM / PM | AM / PM | |
| DAY | DAY | |
| DY | DY | |
| MON | MON | |
| MONTH | MONTH | |
| Q | Q | 분기 |
| WW | WW | 주차 |
| D | D | 요일 번호 (주의: 시작점 다름) |

## 기타 구문 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| SELECT ... FROM DUAL | SELECT ... | FROM 절 제거 |
| '' (빈 문자열) = NULL | '' ≠ NULL | COALESCE/NULLIF로 래핑 검토 |
| /*+ HINT */ | -- hint: HINT (주석 보존) | 또는 제거 (설정 가능) |
| ROWID | ctid | 직접 대응 비권장, 로직 재설계 검토 |
| MINUS | EXCEPT | |
| table PARTITION(name) | 파티션 문법 다름 | 케이스별 검토 |
| CONNECT BY 단순 레벨 (LEVEL ≤ N) | generate_series(1, N) | 재귀 불필요 케이스 |

## MyBatis/iBatis 특수 변환

| 대상 | Oracle 패턴 | PostgreSQL 패턴 |
|------|------------|----------------|
| selectKey | SELECT SEQ.NEXTVAL FROM DUAL | SELECT nextval('seq') |
| selectKey order | type="pre" (iBatis) | order="BEFORE" |
| 파라미터 표기 | #prop# (iBatis) | #{prop} (MyBatis) |
| 파라미터 표기 | $prop$ (iBatis) | ${prop} (MyBatis) |
| procedure 호출 | {call PKG.PROC()} | SELECT * FROM proc() |
```

- [ ] **Step 4: edge-cases.md 생성**

Create: `.kiro/steering/edge-cases.md`

```markdown
---
inclusion: always
---

# 학습된 에지케이스

> Learner 에이전트가 자동으로 항목을 추가합니다.
> 수동 편집 가능. PR로 팀 공유.

## 형식

각 항목은 다음 구조를 따릅니다:

### [패턴 이름]
- **Oracle**: 원본 SQL 패턴/예시
- **PostgreSQL**: 변환 결과/예시
- **주의**: 변환 시 주의사항
- **발견일**: YYYY-MM-DD
- **출처**: {파일명}#{쿼리ID}
- **해결 방법**: rule | llm | manual

---

(아래로 Learner가 항목 추가)
```

- [ ] **Step 5: db-config.md 생성**

Create: `.kiro/steering/db-config.md`

```markdown
---
inclusion: manual
---

# DB 접속 설정

> 사용법: 채팅에서 #db-config 으로 호출

## Oracle (소스)

- Host: ${ORACLE_HOST}
- Port: ${ORACLE_PORT}
- SID/Service: ${ORACLE_SID}
- User: ${ORACLE_USER}
- Password: (환경변수 ORACLE_PASSWORD 참조)

## PostgreSQL (타겟)

- Host: ${PG_HOST}
- Port: ${PG_PORT}
- Database: ${PG_DATABASE}
- Schema: ${PG_SCHEMA}
- User: ${PG_USER}
- Password: (환경변수 PG_PASSWORD 참조)

## 테스트 설정

- statement_timeout: 30s
- 트랜잭션 모드: 읽기 전용 (SELECT), 롤백 (DML)
- 결과 비교 허용 오차: 소수점 1e-10, 날짜 포맷 차이 허용

## 환경변수 설정 예시

```bash
export ORACLE_HOST=oracle.example.com
export ORACLE_PORT=1521
export ORACLE_SID=ORCL
export ORACLE_USER=migration_user
export ORACLE_PASSWORD=****
export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_SCHEMA=public
export PG_USER=migration_user
export PG_PASSWORD=****
```
```

- [ ] **Step 6: 검증**

```bash
ls -la .kiro/steering/
head -3 .kiro/steering/product.md
head -3 .kiro/steering/tech.md
head -3 .kiro/steering/oracle-pg-rules.md
head -3 .kiro/steering/edge-cases.md
head -3 .kiro/steering/db-config.md
```

Expected: 5개 파일 존재, 각각 frontmatter 확인 (`---` / `inclusion:`)

- [ ] **Step 7: 커밋**

```bash
git add .kiro/steering/
git commit -m "feat: add steering files (product, tech, rules, edge-cases, db-config)"
```
