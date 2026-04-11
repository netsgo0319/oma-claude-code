# OMA Kiro Architecture Guide

> Oracle to PostgreSQL MyBatis/iBatis 마이그레이션 에이전트 시스템의 전체 아키텍처, Phase별 플로우, 의사결정 트리를 설명합니다.

---

## 1. System Overview

```mermaid
flowchart TB
    U["사용자: 변환해줘"]
    U --> L

    subgraph Leader["Leader Agent - Opus 4.6"]
        L[오케스트레이터]
    end

    L --> Tools
    L --> Agents

    subgraph Tools["Pre-built Tools"]
        direction TB
        T1[xml-splitter.py]
        T2[parse-xml.py]
        T3[query-analyzer.py]
        T4[oracle-to-pg-converter.py]
        T5[validate-queries.py]
        T6[generate-report.py]
        T7[run-extractor.sh]
    end

    subgraph Agents["Sub-Agents"]
        direction TB
        A1[Converter - Sonnet 4.6]
        A2[Test Generator - Opus 4.6]
        A3[Validator - Sonnet 4.6]
        A4[Reviewer - Opus 4.6]
        A5[Learner - Sonnet 4.6]
    end

    Agents --> Steering
    A5 -.->|학습 갱신| Steering

    subgraph Steering["Steering - Persistent Context"]
        direction TB
        S1[oracle-pg-rules.md - 40+ 변환 룰]
        S2[edge-cases.md - 학습된 패턴]
        S3[db-config.md - 접속 정보]
    end

    Tools --> Workspace

    subgraph Workspace["Workspace"]
        direction TB
        W1[input - 원본 XML]
        W2[output - 변환된 XML]
        W3[results - 중간 결과]
        W4[reports - HTML 리포트]
    end
```

### 핵심 설계 원칙

| 원칙 | 설명 |
|------|------|
| **도구 우선** | Leader는 스크립트를 작성하지 않는다. `tools/`에 있는 도구만 실행한다 |
| **에이전트 분리** | Leader는 SQL을 직접 변환하지 않는다. 변환은 Converter, 검증은 Validator에 위임한다 |
| **리프 우선** | 의존성 그래프에서 리프 쿼리부터 변환한다. 하위가 실패하면 상위를 시도하지 않는다 |
| **버전 추적** | 모든 변환은 `v1 → v2 → v3`으로 버전 관리된다. 롤백 가능하다 |
| **학습 루프** | 실패 → 수정 → 성공 패턴이 steering에 축적된다. 다음 실행 시 자동 적용된다 |

---

## 2. Phase Pipeline

```mermaid
flowchart LR
    P0[Phase 0\n사전 점검]
    P1[Phase 1\n파싱]
    P15[Phase 1.5\n의존성 분석]
    P2[Phase 2\n변환]
    P25[Phase 2.5\nTC 생성]
    P3[Phase 3\n검증]
    P4[Phase 4\n셀프 힐링]
    P5[Phase 5\n학습]
    P35[Phase 3.5\nMyBatis 검증]
    P6[Phase 6\nDBA 검증]
    P7[Phase 7\n리포트]

    P0 --> P1 --> P15 --> P2 --> P25 --> P3
    P3 -->|실패 있음| P4
    P3 -->|전부 성공| P35
    P3 -.->|옵셔널| P35
    P35 --> P4
    P4 --> P5 --> P6 --> P7
```

### Phase 요약

| Phase | 이름 | 실행 주체 | 도구/에이전트 | 산출물 |
|-------|------|----------|-------------|--------|
| **0** | 사전 점검 | Leader 직접 | shell | Pre-flight 결과 요약 |
| **1** | 파싱 | Leader 직접 | `xml-splitter.py` → `parse-xml.py` | `parsed.json`, `_metadata.json` |
| **1.5** | 의존성 분석 | Leader 직접 | `query-analyzer.py` | `dependency-graph.json`, `complexity-scores.json`, `conversion-order.json` |
| **2** | 변환 | Leader + **Converter** | `oracle-to-pg-converter.py` + Converter agent | `output/*.xml`, `conversion-report.json` |
| **2.5** | TC 생성 | **Test Generator** | Oracle Dictionary 조회 | `test-cases.json` |
| **3** | 검증 | Leader + **Validator** | `validate-queries.py` | `validated.json`, `execute_validated.json` |
| **3.5** | MyBatis 검증 | Leader 직접 | `run-extractor.sh` | `*-extracted.json` |
| **4** | 셀프 힐링 | **Reviewer** → **Converter** → **Validator** | 최대 3회 루프 | `review.json`, `v2/`, `v3/` |
| **5** | 학습 | **Learner** | steering 파일 갱신 + git | `edge-cases.md` 갱신, PR 생성 |
| **6** | DBA/Expert 검증 | Leader 직접 | DBA review checklist | `review-result.json` |
| **7** | 리포트 | Leader 직접 | `generate-report.py` | `migration-report.html` |

---

## 3. Phase 0: Pre-flight Check

```mermaid
flowchart TD
    Start([Phase 0 시작]) --> X{XML 파일 존재?}
    X -->|NO| Stop1[XML 배치 요청 - 중단]
    X -->|YES| SqlPlus{sqlplus 설치?}

    SqlPlus -->|YES| OraConn{Oracle 접속 성공?}
    SqlPlus -->|NO| Psql{psql 설치?}

    OraConn -->|YES| Psql
    OraConn -->|NO| OraFail[Oracle 접속 실패\n환경변수 확인 안내]
    OraFail --> Psql

    Psql -->|YES| PgConn{PostgreSQL 접속 성공?}
    Psql -->|NO| Decision

    PgConn -->|YES| Decision
    PgConn -->|NO| PgFail[PG 접속 실패\n환경변수 확인 안내]
    PgFail --> Decision

    Decision{어디까지 가능?}
    Decision -->|전부 OK| Full[Phase 1~7 전체 수행]
    Decision -->|DB 미연결| Partial[Phase 1~2만 가능]
    Decision -->|XML 없음| Stop1

    Full --> P1([Phase 1 진입])
    Partial -->|사용자 동의| P1
```

### Pre-flight 체크리스트

| 항목 | 체크 명령 | 필수 | 영향 |
|------|----------|------|------|
| XML 파일 | `ls workspace/input/*.xml` | **필수** | 없으면 전체 중단 |
| sqlplus | `which sqlplus` | 선택 | 없으면 Phase 2.5 스킵 |
| psql | `which psql` | 선택 | 없으면 Phase 3 스킵 |
| Oracle 접속 | `sqlplus ... "SELECT 1 FROM DUAL"` | 선택 | 실패 시 TC 생성 불가 |
| PostgreSQL 접속 | `psql -c "SELECT 1"` | 선택 | 실패 시 검증 불가 |

---

## 4. Phase 1 → 1.5: 파싱 & 분석

```mermaid
flowchart TD
    Start([Phase 1 시작]) --> Scan[workspace/input 스캔\nXML 파일 목록 수집]
    Scan --> Size[wc -l로 파일 크기 확인]
    Size --> Check{1000줄 이상?}
    Check -->|YES| Split[xml-splitter.py\n쿼리 단위로 분할]
    Check -->|NO| Direct[분할 불필요]
    Split --> Parse[parse-xml.py\nOracle 패턴 감지 + 동적 SQL 식별]
    Direct --> Parse
    Parse --> Parsed[parsed.json 생성\n쿼리별 oracle_tags, params, dynamic]

    Parsed --> P15([Phase 1.5 시작])
    P15 --> QA[query-analyzer.py]

    subgraph Analysis["의존성 분석 & 복잡도 분류"]
        QA --> Dep[의존성 그래프 구축\ninclude, association, collection]
        Dep --> Comp[복잡도 점수 산정\nL0~L4]
        Comp --> Topo[위상 정렬\n변환 레이어 결정]
    end

    Topo --> Order[conversion-order.json\nLayer 0, 1, 2, ...]
    Topo --> Cross[cross-file-analyzer\n파일 간 의존성]
    Cross --> FileOrder[cross-file-graph.json\n파일 변환 순서]

    Order --> P2([Phase 2 진입])
    FileOrder --> P2
```

### 복잡도 분류 기준 - L0~L4

```mermaid
flowchart LR
    L0[L0: Static\nOracle 구문 없음\n변환 불필요]
    L1[L1: Simple Rule\nNVL, SYSDATE\n1:1 치환]
    L2[L2: Multi-Pattern\n동적 SQL + Oracle\n여러 패턴 조합]
    L3[L3: Structural\nCONNECT BY, MERGE\n구조 변경 필요]
    L4[L4: Oracle Complex\nL3 + 동적 SQL +\n수동 검토 권장]

    L0 --> L1 --> L2 --> L3 --> L4
```

| Level | 점수 범위 | Oracle 패턴 예시 | 동적 SQL | 변환 전략 |
|-------|----------|-----------------|----------|----------|
| **L0** | 0 | 없음 | 없음 | 변환 불필요 |
| **L1** | 1~5 | NVL, SYSDATE, TO_DATE, ROWNUM, FROM DUAL | 단순 if | **룰 기반** 자동 치환 |
| **L2** | 6~15 | L1 + DECODE 중첩 + LISTAGG + 서브쿼리 | choose, foreach | **룰 우선**, 일부 LLM |
| **L3** | 16~30 | CONNECT BY, MERGE INTO, PIVOT | 복잡 동적 SQL | **LLM 위주** + transform-plan |
| **L4** | 31+ | L3 + 크로스 파일 + PL/SQL | 모든 조합 | **LLM + 수동 검토** 권장 |

### 점수 산정 요소

| 요소 | 점수 |
|------|------|
| NVL, DECODE, TO_DATE 등 단순 함수 | +1 each |
| ROWNUM pagination | +3 |
| CONNECT BY / START WITH | +5 |
| MERGE INTO | +5 |
| PIVOT / UNPIVOT | +4 |
| 동적 SQL if | +1 each |
| 동적 SQL foreach | +2 |
| 동적 SQL choose 중첩 | +3 |
| include 참조 | +1 each |
| selectKey | +2 |
| 크로스 파일 의존 | +3 |

---

## 5. Phase 2: 레이어별 변환

```mermaid
flowchart TD
    Start([Phase 2 시작]) --> Load[conversion-order.json 로드]
    Load --> Layer0

    subgraph Layer0["Layer 0 - 리프 쿼리"]
        L0_Rule[oracle-to-pg-converter.py\n기계적 변환 40+ 룰]
        L0_Check{unconverted\n패턴 남음?}
        L0_LLM[Converter Agent\nLLM 변환]
        L0_Rule --> L0_Check
        L0_Check -->|YES| L0_LLM
        L0_Check -->|NO| L0_Done[Layer 0 변환 완료]
        L0_LLM --> L0_Done
    end

    L0_Done --> L0_Val{Layer 0 전부 성공?}
    L0_Val -->|NO| Heal[Phase 4 셀프 힐링]
    Heal --> L0_Val
    L0_Val -->|YES| Layer1

    subgraph Layer1["Layer 1 - Layer 0 의존"]
        L1_Convert[Layer 0 결과 참조하며 변환]
    end

    Layer1 --> L1_Val{Layer 1 전부 성공?}
    L1_Val -->|YES| LayerN[...Layer N 반복...]
    L1_Val -->|NO| Heal2[Phase 4]
    Heal2 --> L1_Val

    LayerN --> Done([Phase 2 완료])
```

### 변환 전략 의사결정

```mermaid
flowchart TD
    Q[쿼리 1건] --> Level{복잡도 Level?}

    Level -->|L0| Pass[변환 불필요\n그대로 통과]
    Level -->|L1 ~ L2| Rule[oracle-to-pg-converter.py\n기계적 변환]
    Level -->|L3 ~ L4| Decompose[complex-query-decomposer\n쿼리 분해]

    Rule --> RuleCheck{unconverted\n잔여 패턴?}
    RuleCheck -->|NO| Done[변환 완료]
    RuleCheck -->|YES| LLM

    Decompose --> Plan[transform-plan.json\n변환 DAG]
    Plan --> LLM[Converter Agent\nLLM 변환]
    LLM --> Done
```

### 기계적 변환 룰 - 주요 40+

| 카테고리 | Oracle | PostgreSQL | 비고 |
|---------|--------|-----------|------|
| **함수** | `NVL(a, b)` | `COALESCE(a, b)` | 중첩 5단계 처리 |
| | `NVL2(a, b, c)` | `CASE WHEN a IS NOT NULL THEN b ELSE c END` | |
| | `DECODE(a,b,c,...)` | `CASE a WHEN b THEN c ... END` | 마지막 홀수=ELSE |
| **날짜** | `SYSDATE` | `CURRENT_TIMESTAMP` | |
| | `SYSDATE - 30` | `CURRENT_TIMESTAMP - INTERVAL '30 days'` | timestamp arithmetic |
| | `TRUNC(date)` | `DATE_TRUNC('day', date)::DATE` | 복잡 표현식 대응 |
| | `ADD_MONTHS(d, n)` | `d + n * INTERVAL '1 month'` | |
| **집계** | `LISTAGG(col, sep) WITHIN GROUP (...)` | `STRING_AGG(col, sep ORDER BY ...)` | |
| | `WM_CONCAT(col)` | `STRING_AGG(col::text, ',')` | |
| **시퀀스** | `seq.NEXTVAL` | `nextval('seq')` | |
| **페이지네이션** | `ROWNUM <= N` | `LIMIT N` | 3-level 패턴 대응 |
| | `FETCH FIRST N ROWS ONLY` | `LIMIT N` | 12c+ |
| **기타** | `FROM DUAL` | _(제거)_ | |
| | `MINUS` | `EXCEPT` | |
| | `/*+ HINT */` | `-- hint: ...` | 주석 변환 |

---

## 6. Phase 2.5 → 3: 테스트 & 검증

```mermaid
flowchart TD
    subgraph Phase25["Phase 2.5: 테스트 케이스 생성"]
        TC1[V$SQL_BIND_CAPTURE\n운영 바인드 값]
        TC2[ALL_TAB_COL_STATISTICS\n컬럼 경계값]
        TC3[동적 SQL 분기별\n파라미터 조합]
        TC1 & TC2 & TC3 --> TCS[test-cases.json\n쿼리당 3~10 TC]
    end

    TCS --> Phase3

    subgraph Phase3["Phase 3: 검증"]
        direction TB
        Step1[Step 1: EXPLAIN\n문법 검증]
        Step2[Step 2: 실행\n실제 쿼리 수행]
        Step3[Step 3: 비교\nOracle vs PG 결과 대조]
        Step4[Step 4: Integrity Guard\n14개 경고 코드 점검]
        Step1 --> Step2 --> Step3 --> Step4
    end

    Step4 --> Result{결과}
    Result -->|전부 PASS| P5([Phase 5])
    Result -->|FAIL 있음| P4([Phase 4])
```

### 검증 4단계 상세

| 단계 | 도구 | 목적 | 판정 기준 |
|------|------|------|----------|
| **EXPLAIN** | `validate-queries.py --local` | PG SQL 문법 검증 | QUERY PLAN 반환 = PASS |
| **비교** | `validate-queries.py --compare` | **Oracle vs PG 양쪽 실행 + 결과 비교** | SELECT: row/값 일치, DML: affected rows 일치 |
| **실행** | `validate-queries.py --execute` | PG만 실행 (Oracle 불가 시 폴백) | 에러 없이 row count 반환 = PASS |
| **Integrity Guard** | `--compare` 내장 | 결과 신뢰성 검증 | 14개 경고 코드 |

### Result Integrity Guard 경고 코드

| 코드 | 심각도 | 의미 |
|------|--------|------|
| `WARN_ZERO_ALL_CASES` | **Critical** | 모든 TC에서 양쪽 0행 반환 |
| `WARN_MOSTLY_ZERO` | High | 80%+ TC에서 0행 반환 |
| `WARN_ZERO_BOTH` | High | SELECT에서 양쪽 0행 (테스트 데이터 부재 의심) |
| `WARN_ZERO_BOTH_DML` | Low | DML에서 양쪽 0건 (정상 — 데이터 없음) |
| `WARN_SAME_COUNT_DIFF_ROWS` | High | 행 수 동일하나 내용 다름 |
| `WARN_NULL_NON_NULLABLE` | Medium | NOT NULL 컬럼에 NULL 반환 |
| `WARN_WHITESPACE_DIFF` | Low | 공백 차이만 존재 |

---

## 7. Phase 4: 셀프 힐링

```mermaid
flowchart TD
    Start([실패 건 수집]) --> R1

    subgraph Try1["시도 1"]
        R1[Reviewer Agent\n원인 분석]
        R1 --> C1[Converter Agent\nreview.json 기반 재변환 v2]
        C1 --> V1[Validator Agent\nv2 재검증]
    end

    V1 --> Check1{성공?}
    Check1 -->|YES| Done1[완료 - status: success]
    Check1 -->|NO| R2

    subgraph Try2["시도 2"]
        R2[Reviewer + Converter v3 + Validator]
    end

    R2 --> Check2{성공?}
    Check2 -->|YES| Done2[완료]
    Check2 -->|NO| R3

    subgraph Try3["시도 3 - 최종"]
        R3[Reviewer + Converter v4 + Validator]
    end

    R3 --> Check3{성공?}
    Check3 -->|YES| Done3[완료]
    Check3 -->|NO| Esc[에스컬레이션\n사용자에게 알림]
```

### 상태 전이

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> parsing: Phase 1
    parsing --> analyzing: Phase 1.5
    analyzing --> converting: Phase 2
    converting --> testing: Phase 2.5
    testing --> validating: Phase 3

    validating --> success: PASS
    validating --> retry_1: FAIL

    retry_1 --> success: PASS
    retry_1 --> retry_2: FAIL

    retry_2 --> success: PASS
    retry_2 --> retry_3: FAIL

    retry_3 --> success: PASS
    retry_3 --> escalated: 3회 실패

    escalated --> success: 사용자 수정 후 재검증

    success --> [*]
```

---

## 8. Phase 5 → 7: 학습 & DBA 검증 & 리포트

```mermaid
flowchart LR
    subgraph Phase5["Phase 5: 학습"]
        Scan[Learner가 스캔]
        Pat1[반복 성공 패턴\n같은 fix 3회+]
        Pat2[LLM 변환 새 패턴]
        Pat3[사용자 해결 건]

        Scan --> Pat1 & Pat2 & Pat3
        Pat1 -->|룰 추가| Rules[oracle-pg-rules.md]
        Pat2 -->|등록| Edge[edge-cases.md]
        Pat3 -->|등록 + Issue| Edge
    end

    subgraph Git["Git 자동화"]
        Branch[git branch\nlearn/date-pattern]
        Commit[git commit]
        PR[gh pr create]
        Branch --> Commit --> PR
    end

    Edge --> Branch
    Rules --> Branch

    subgraph Phase6["Phase 6: DBA/Expert 검증"]
        DBA[DBA review checklist]
        DBAResult[review-result.json]
        DBA --> DBAResult
    end

    PR --> Phase6

    subgraph Phase7New["Phase 7: 리포트"]
        Gen[generate-report.py]
        HTML[migration-report.html\n통합 HTML]
        Gen --> HTML
    end

    Phase6 --> Phase7New
```

---

## 9. Phase 3.5: MyBatis 엔진 검증 - 옵셔널

```mermaid
flowchart TD
    Start{Java 11+ 설치?}
    Start -->|NO| Skip[Phase 3.5 스킵\n통합 테스트로 검증 안내]
    Start -->|YES| Build

    subgraph Phase35["Phase 3.5"]
        Build[gradle build\nmybatis-sql-extractor]
        Extract[SqlExtractor.java\n파일별 독립 처리]
        DTO[DTO 자동 대체\nClassNotFound to HashMap]
        Variants[SQL Variants 생성\nnull, empty, all_non_null, test_case]

        Build --> Extract
        Extract --> DTO
        DTO --> Variants
    end

    Variants --> Validate[validate-queries.py --extracted\nEXPLAIN + 실행 검증]
    Validate --> Report[결과를 리포트에 반영]
```

### Phase 3.5가 해결하는 문제

| 문제 | Phase 3만으로는 | Phase 3.5에서는 |
|------|----------------|-------------|
| `<if test="name != null">` | 정적 파싱으로 SQL 추정 | MyBatis OGNL 엔진이 정확히 평가 |
| `<foreach collection="list">` | 전개 불가, 더미 값 사용 | 실제 컬렉션으로 SQL 생성 |
| `<choose>/<when>/<otherwise>` | 모든 분기를 알 수 없음 | 파라미터 조합별 variant 추출 |
| `<include refid="...">` | 텍스트 치환으로 추정 | MyBatis가 정확히 resolve |

---

## 10. 에이전트 간 통신

```mermaid
sequenceDiagram
    participant U as 사용자
    participant L as Leader
    participant C as Converter
    participant TG as Test Generator
    participant V as Validator
    participant R as Reviewer
    participant LN as Learner

    U->>L: 변환해줘
    Note over L: Phase 0: Pre-flight

    L->>L: Phase 1: xml-splitter + parse-xml
    L->>L: Phase 1.5: query-analyzer

    L->>L: Phase 2 Rule: oracle-to-pg-converter
    L->>C: unconverted 쿼리 위임
    C-->>L: converted.json

    L->>TG: Phase 2.5: 테스트 케이스 생성
    TG-->>L: test-cases.json

    L->>L: Phase 3: validate-queries.py
    L->>V: 검증 결과 분석 위임
    V-->>L: validated.json

    alt 실패 건 있음
        L->>R: Phase 4: 실패 원인 분석
        R-->>L: review.json
        L->>C: review 기반 재변환 v2
        C-->>L: converted_v2.json
        L->>V: v2 재검증
        V-->>L: validated_v2.json
    end

    L->>LN: Phase 5: 학습 요청
    LN-->>L: edge-cases 갱신, PR 생성

    L->>L: Phase 6: DBA/Expert review
    L->>L: Phase 7: generate-report.py
    L-->>U: migration-report.html
```

### 파일 기반 통신 규약

| 생성 | 소비 | 파일 | 위치 |
|------|------|------|------|
| Leader | Converter, Analyzer | `parsed.json` | `results/file/v1/` |
| Leader | Converter | `conversion-order.json` | `results/file/v1/` |
| Leader, Converter, Validator | All | `query-tracking.json` | `results/file/v1/` |
| Converter | Validator, Reviewer | `converted.json` | `results/file/v1/` |
| Test Generator | Validator | `test-cases.json` | `results/file/v1/` |
| Validator | Reviewer, Leader | `validated.json` | `results/_validation/` |
| Reviewer | Converter | `review.json` | `results/file/v1/` |

---

## 11. 전체 의사결정 트리

```mermaid
flowchart TD
    A[XML 파일 수신] --> B{DB 접속 가능?}

    B -->|전부 가능| Full[Phase 0~7 전체]
    B -->|DB 없음| Partial[Phase 0~2만]
    B -->|PG만 가능| NoPG[Phase 0~3]

    Full --> C{파일 크기?}
    Partial --> C
    NoPG --> C

    C -->|1000줄+| Split[xml-splitter로 분할]
    C -->|1000줄 미만| Direct[직접 처리]

    Split --> Parse[parse-xml.py]
    Direct --> Parse

    Parse --> D{Oracle 패턴 감지?}
    D -->|없음 - L0| PassThru[변환 불필요\n그대로 통과]
    D -->|L1 ~ L2| RuleBased[Rule 기반 기계적 변환]
    D -->|L3 ~ L4| Complex[쿼리 분해\ntransform-plan]

    RuleBased --> E{잔여 패턴?}
    E -->|없음| Validate
    E -->|있음| LLM[Converter Agent\nLLM 변환]

    Complex --> LLM
    LLM --> Validate

    Validate[Phase 3 검증] --> F{결과?}
    F -->|PASS| Learn[Phase 5: 학습]
    F -->|FAIL| Heal[Phase 4: 셀프 힐링 x3]
    F -->|3회 실패| Escalate[에스컬레이션]

    Heal --> Validate
    Learn --> DBAReview[Phase 6: DBA/Expert 검증]
    Escalate --> Learn

    DBAReview --> Report[Phase 7: HTML 리포트]
    Report --> End([완료])
```

---

## 12. 디렉토리 구조 & 데이터 플로우

```
workspace/
├── input/                          # [불변] 원본 Oracle XML
│   ├── UserMapper.xml
│   └── OrderMapper.xml
│
├── output/                         # [Phase 2] 변환된 PostgreSQL XML
│   ├── UserMapper.xml
│   └── OrderMapper.xml
│
├── results/
│   ├── UserMapper/
│   │   ├── v1/
│   │   │   ├── chunks/             # Phase 1: 분할 결과
│   │   │   │   ├── _metadata.json
│   │   │   │   └── q_001_selectUser.xml
│   │   │   ├── parsed.json         # Phase 1: 파싱 결과
│   │   │   ├── query-tracking.json # Phase 1~7: 쿼리별 추적 (before/after, EXPLAIN, TC, timing)
│   │   │   ├── dependency-graph.json    # Phase 1.5
│   │   │   ├── complexity-scores.json   # Phase 1.5
│   │   │   ├── conversion-order.json    # Phase 1.5
│   │   │   ├── conversion-report.json   # Phase 2
│   │   │   └── test-cases.json          # Phase 2.5
│   │   └── v2/                     # Phase 4: 재시도 시 생성
│   │       └── ...
│   │
│   ├── _global/
│   │   └── cross-file-graph.json   # Phase 1.5: 크로스 파일 의존성
│   │
│   ├── _validation/                # Phase 3
│   │   ├── explain_test.sql
│   │   ├── execute_test.sql
│   │   ├── test_manifest.json
│   │   ├── validated.json          # EXPLAIN 결과
│   │   ├── execute_validated.json  # 실행 결과
│   │   └── batches/                # SSM 원격 실행용
│   │
│   └── _extracted/                 # Phase 3.5
│       ├── UserMapper-extracted.json
│       └── OrderMapper-extracted.json
│
├── reports/
│   └── migration-report.html       # Phase 7: 통합 HTML 리포트
│
├── logs/
│   └── activity-log.jsonl          # 전체 감사 로그
│
└── progress.json                   # 실시간 진행 상태
```

---

## 13. 에이전트 구성 상세

```mermaid
flowchart TB
    Leader[Leader - Opus 4.6\n도구: shell, read, write, glob, grep, subagent\nPhase 0~2, 3도구, 3.5, 6, 7 직접 실행]

    Leader -->|LLM 변환 위임| Converter
    Leader -->|TC 생성 위임| TestGen
    Leader -->|검증 위임| Validator
    Leader -->|실패 분석 위임| Reviewer
    Leader -->|학습 위임| Learner
    Reviewer -->|수정안 전달| Converter

    Converter[Converter - Sonnet 4.6\n도구: shell python3/java, read, write\n스킬: rule-convert, llm-convert, param-type-convert\nsteering: oracle-pg-rules, edge-cases]

    TestGen[Test Generator - Opus 4.6\n도구: shell sqlplus, read, write\n스킬: generate-test-cases, db-oracle]

    Validator[Validator - Sonnet 4.6\n도구: shell psql/sqlplus, read, write\n스킬: explain-test, execute-test, compare-test\n훅: 파괴적 SQL 차단]

    Reviewer[Reviewer - Opus 4.6\n도구: shell psql/sqlplus, read, write\n스킬: audit-log\n훅: 파괴적 SQL 차단]

    Learner[Learner - Sonnet 4.6\n도구: shell git/gh, read, write\n스킬: learn-edge-case, audit-log]
```

---

## 14. SSM 원격 실행 패턴

VPC 내부 Aurora/RDS에 직접 접속이 불가한 경우, AWS SSM을 경유하여 검증합니다.

```mermaid
sequenceDiagram
    participant Local as 로컬 환경
    participant S3 as S3 Bucket
    participant SSM as SSM omabox EC2
    participant Aurora as Aurora PostgreSQL

    Local->>Local: validate-queries.py --generate
    Note over Local: explain_test.sql 생성

    Local->>S3: SQL 스크립트 업로드
    Local->>SSM: aws ssm send-command
    SSM->>S3: SQL 스크립트 다운로드
    SSM->>Aurora: psql -f explain_test.sql
    Aurora-->>SSM: EXPLAIN 결과
    SSM-->>Local: 실행 결과 반환

    Local->>Local: validate-queries.py --parse-results
    Note over Local: validated.json 생성
```

---

## 15. 실행 예시

### 전체 자동 실행

```
사용자: 변환해줘

Leader:
======================================
>>> Phase 0: 사전 점검
======================================
XML 파일: 11개 감지
sqlplus: NOT FOUND
psql: OK
PostgreSQL 접속: OK
-> Phase 1~3, 6 진행 가능 (TC 생성은 스킵)

>>> Phase 1: 파싱 완료 (11파일, 172쿼리)
>>> Phase 1.5: 의존성 분석 완료 (L0:45, L1:67, L2:38, L3:15, L4:7)
>>> Phase 2: 변환 완료 (Rule:158, LLM:14)
>>> Phase 3: EXPLAIN 검증 81/87 PASS, 6 FAIL
>>> Phase 4: 셀프 힐링 6건 -> 5건 성공, 1건 에스컬레이션
>>> Phase 5: edge-cases.md에 3건 추가, PR #2 생성
>>> Phase 6: DBA/Expert 검증 완료
>>> Phase 7: migration-report.html 생성

workspace/reports/migration-report.html 에서 결과를 확인하세요.
```

### 특정 파일만

```
사용자: UserMapper.xml만 변환해줘
Leader: UserMapper.xml 1건만 Phase 0~7 실행
```

### 에스컬레이션 후 재개

```
사용자: selectComplexReport 쿼리 수정했어. 다시 검증해줘
Leader: v3 생성 -> Validator 검증 -> 성공 -> Learner 학습
```
