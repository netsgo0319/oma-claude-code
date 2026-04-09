# OMA Kiro - Team Lead Overview Report

**Date:** 2026-04-09
**Branch:** master (44 commits)
**Harness Score:** 8.0/10 (Grade A)

---

## 1. 프로젝트 현황 요약

| 항목 | 수량 | 상세 |
|------|------|------|
| 총 .kiro 파일 | 60개 | 에이전트, 프롬프트, 스킬, 스키마, 스티어링, 설정 포함 |
| 에이전트 (JSON) | 6개 | oracle-pg-leader, converter, validator, reviewer, learner, test-generator |
| 프롬프트 (MD) | 6개 | 에이전트별 1:1 대응 |
| 스킬 (SKILL.md) | 17개 | 파싱, 분석, 변환, 검증, DB접근, 로깅, 리포트, 학습 |
| 스키마 (JSON Schema) | 10개 | parsed, converted, validated, review, test-cases, dependency-graph, complexity-scores, conversion-order, cross-file-graph, transform-plan |
| 스티어링 (MD) | 5개 | product, tech, oracle-pg-rules, edge-cases, db-config |
| 테스트 픽스처 | 3개 | ibatis2-sample.xml, mybatis3-basic.xml, mybatis3-complex.xml |
| 외부 도구 | 1개 | mybatis-sql-extractor (Java/Gradle, 3 파일) |
| 문서 | 3개 | README.md, CONTRIBUTING.md, 설계 스펙 + 구현 플랜 |

### 모델 배정

| 모델 | 에이전트 | 근거 |
|------|---------|------|
| claude-opus-4.6 | leader, reviewer, test-generator | 오케스트레이션/분석/판단 작업 |
| claude-sonnet-4.6 | converter, validator, learner | 변환/검증/학습 (비용 효율) |

### 디렉토리 구조

```
.kiro/          -- Kiro 에이전트 시스템 전체
tools/          -- MyBatis SQL 추출기 (Java)
workspace/
  input/        -- 변환 대상 XML (현재 비어 있음)
  output/       -- 변환 완료 XML
  results/      -- 버전별 중간 결과
  reports/      -- 최종 리포트
  logs/         -- 감사 로그
docs/           -- 설계 스펙, 구현 플랜, 기여 가이드
```

---

## 2. 워크플로우 완성도 (Phase 0~6)

| Phase | 이름 | 구현 상태 | 설명 |
|-------|------|----------|------|
| Phase 0 | 사전 점검 | 완료 | XML 존재, sqlplus/psql 설치, Oracle/PG 접속 테스트. 실패 시 가능 범위 안내. agentSpawn 훅으로 자동 실행. |
| Phase 1 | XML 파싱 | 완료 | parse-xml 스킬 (MyBatis 3.x / iBatis 2.x 자동 판별, 28+35 태그 지원). parsed.json 스키마 정의됨. 3개 테스트 픽스처 보유. |
| Phase 1.5 | 의존성 분석 | 완료 | query-analyzer 스킬 (의존성 그래프 + L0~L4 복잡도 분류 + 위상 정렬). cross-file-analyzer로 다중 파일 의존성도 처리. 스키마 3개(dependency-graph, complexity-scores, conversion-order). |
| Phase 2 | 레이어별 변환 | 완료 | 리프 우선 전략. rule-convert (40+ 룰) + llm-convert (CONNECT BY, MERGE INTO, PL/SQL, ROWNUM 패턴 참조 문서). param-type-convert (JDBC 타입 매핑). complex-query-decomposer (L3~L4 분해). converted.json + transform-plan.json 스키마. |
| Phase 2.5 | 테스트 케이스 생성 | 완료 | generate-test-cases 스킬 (Oracle 딕셔너리 기반). V$SQL_BIND_CAPTURE, 컬럼 통계, FK 활용. test-cases.json 스키마. |
| Phase 3 | 검증 | 완료 | 4단계: EXPLAIN (explain-test) -> 실행 (execute-test, 트랜잭션+ROLLBACK) -> Oracle/PG 비교 (compare-test, Result Integrity Guard 14개 경고코드). validated.json 스키마. DDL 차단 훅 (DROP/TRUNCATE/ALTER/CREATE/GRANT/REVOKE). |
| Phase 4 | 셀프 힐링 | 완료 | reviewer 에이전트가 실패 원인 분석 + 수정안 생성. 최대 3회 재시도 (v1->v2->v3). 실패 시 에스컬레이션 메시지 (시도 이력 포함). review.json 스키마. |
| Phase 5 | 학습 | 완료 | learner 에이전트. 반복 패턴 -> oracle-pg-rules.md 룰 추가, 새 LLM 패턴 -> edge-cases.md 등록, 사용자 해결 건 -> Issue 생성. git branch + PR 자동 생성. stop 훅으로 steering 변경 감지. |
| Phase 6 | 리포트 | 완료 | report 스킬. conversion-report.md (통계/파일별 결과), migration-guide.md (수동 검토 항목). |

### 보조 인프라

| 구성 요소 | 상태 | 설명 |
|----------|------|------|
| progress.json 상태 추적 | 설계 완료 | _pipeline 필드 + 파일별 상태. 상태 전이: pending -> parsing -> converting -> validating -> retry_N -> success/escalated. |
| 실시간 상태 표시 | 구현 완료 | userPromptSubmit 훅으로 매 입력 시 진행 상황 자동 출력. |
| 감사 로그 | 구현 완료 | audit-log 스킬. 10개 로그 타입 (PHASE_START/END, DECISION, ATTEMPT, SUCCESS, ERROR, FIX, ESCALATION, HUMAN_INPUT, LEARNING, WARNING). |
| DB 접근 보안 | 구현 완료 | shell allowedCommands/deniedCommands로 허용 명령 제한. preToolUse 훅으로 DDL 차단. |
| 에스컬레이션 후 재개 | 설계 완료 | "다시 검증해줘" 명령으로 수동 수정 건 재검증 + 학습 루프 재진입. |

---

## 3. 최근 주요 변경사항

최근 커밋 이력 기반 (44 commits total):

| 시기 | 변경 내용 |
|------|----------|
| 최신 | complex-query-decomposer 스킬 추가 (L3~L4 구조적 변환) |
| 최신 | parameter type conversion 단계 추가 (converter 프롬프트) |
| 최신 | cross-file dependency analyzer 추가 (다중 XML 프로젝트 지원) |
| 최신 | ROWNUM 페이지네이션 패턴 추가 + parse-xml/converter 프롬프트 강화 |
| 최근 | README 전면 업데이트 + ASCII 상태 아이콘 |
| 최근 | 실시간 Phase/TODO 상태 표시 기능 추가 |
| 최근 | query dependency graph, complexity scoring, layer-based conversion 추가 |
| 최근 | MyBatis SQL extractor (Java/Gradle) 추가 |
| 최근 | 포괄적 감사 로깅 시스템 추가 (전 에이전트) |
| 초기 | 6개 에이전트 순차 구현 (converter -> learner -> reviewer -> leader -> validator -> test-generator) |
| 초기 | JSON 스키마, learner safety 확장, CONTRIBUTING 가이드 추가 |
| 초기 | MCP 서버 -> CLI 기반 스킬로 전환 (db-oracle, db-postgresql) |

**특이사항:** MCP 서버 의존성을 제거하고 sqlplus/psql CLI 기반으로 전환한 것은 중요한 아키텍처 결정. 검증되지 않은 외부 MCP 패키지 의존성 문제를 해결함.

---

## 4. 강점

### 4.1 멀티 에이전트 아키텍처 설계

- **역할 분리가 명확함:** 6개 에이전트가 각각 단일 책임을 가짐. Leader는 오케스트레이션만, Converter는 변환만, Validator는 검증만.
- **위임 모델:** Leader가 서브에이전트에 작업을 위임하는 구조로, 각 에이전트가 독립적으로 발전 가능.
- **Trust Model:** trusted/untrusted 서브에이전트 구분으로 보안 계층 확보 (converter, test-generator, validator는 trusted; reviewer, learner는 untrusted).

### 4.2 파일 기반 에이전트 간 통신 (IPC)

- **10개 JSON Schema**로 에이전트 간 데이터 계약이 정의됨.
- 버전별 중간 산출물 관리 (v1 -> v2 -> v3)로 이력 추적 가능.
- progress.json으로 전체 파이프라인 상태를 단일 지점에서 추적.

### 4.3 의존성 인식 변환 전략

- **쿼리 간 의존성 그래프 + 위상 정렬**로 리프 쿼리부터 단계적 변환.
- **크로스 파일 분석**으로 다중 XML 프로젝트의 파일 간 의존성까지 처리.
- **복잡도 분류 (L0~L4)**로 변환 전략을 쿼리별로 최적화.

### 4.4 셀프 힐링 루프

- 실패 -> 원인 분석 -> 수정 -> 재검증을 최대 3회 자동 반복.
- 에스컬레이션 시 전체 시도 이력을 사용자에게 제공.
- 사용자 수정 후 재진입 경로 설계됨.

### 4.5 학습 루프와 지식 축적

- Learner 에이전트가 반복 패턴을 steering 파일에 자동 축적.
- git branch + PR 자동 생성으로 팀 공유.
- 시스템 사용이 누적될수록 성공률 향상하는 구조.

### 4.6 비용 효율적 모델 배정

- 복잡한 판단이 필요한 작업(오케스트레이션, 리뷰, 테스트 생성)에 Opus 4.6.
- 반복적 변환/검증 작업에 Sonnet 4.6.
- 에이전트별 resource 선택적 로딩으로 컨텍스트 낭비 최소화.

### 4.7 포괄적 변환 룰셋

- oracle-pg-rules.md에 40+ 함수 변환, 조인 변환, 데이터 타입 변환, 날짜 포맷, MyBatis 특수 변환 등 체계적 정리.
- llm-convert 참조 문서 4개 (CONNECT BY, MERGE INTO, PL/SQL, ROWNUM 패턴).
- JDBC 타입 매핑 참조 문서.

### 4.8 운영 가시성

- 10개 타입의 감사 로그 (JSONL 형식).
- userPromptSubmit 훅으로 매 입력 시 자동 상태 표시.
- agentSpawn 훅으로 시작 시 자동 Pre-flight 체크.
- 에이전트 생명주기 훅 (preToolUse, postToolUse, stop).

---

## 5. 리스크/우려사항

### 5.1 실전 검증 부재 (Critical)

- **workspace/input/이 비어 있음.** 실제 Oracle MyBatis XML로 엔드투엔드 테스트가 한 번도 수행되지 않았을 가능성이 높음.
- 테스트 픽스처 3개(ibatis2-sample, mybatis3-basic, mybatis3-complex)는 스모크 테스트용이며, 실제 프로덕션 규모의 XML과 차이가 클 수 있음.
- 파이프라인 전체 Phase 0~6을 통과하는 통합 테스트가 없음.

### 5.2 자동화 테스트 인프라 없음 (Critical)

- 이전 Harness 평가에서 Testability 3/10으로 최저 점수.
- 테스트 프레임워크, CI/CD 파이프라인, 회귀 테스트가 전혀 없음.
- 에이전트 프롬프트/스킬 변경 시 기존 변환 품질에 미치는 영향을 검증할 수 없음.

### 5.3 SQL 안전 훅의 한계

- DDL 차단 목록에 DELETE, INSERT, UPDATE가 포함되지 않음 (DML은 의도적 허용인지 확인 필요).
- Validator/Reviewer의 preToolUse 훅 매처가 "execute_bash"로 설정되어 있으나, 실제 shell 도구와 매칭 여부 확인 필요.
- $KIRO_TOOL_INPUT이 훅 명령에서 따옴표 처리 시 쉘 인젝션 가능성 (이전 평가에서도 지적됨).

### 5.4 외부 의존성 가용성

- sqlplus, psql CLI가 실행 환경에 설치되어 있어야 함. 컨테이너/클라우드 환경에서 Oracle Instant Client 설치가 번거로울 수 있음.
- gh CLI가 있어야 Learner의 PR/Issue 자동 생성이 동작함.
- Java 11+가 있어야 MyBatis SQL Extractor 사용 가능.

### 5.5 대규모 프로젝트 성능 우려

- 수백 개 XML 파일, 수천 개 쿼리 규모에서의 성능이 미검증.
- LLM 호출 비용과 응답 시간이 L3~L4 복잡 쿼리에서 병목될 수 있음.
- progress.json 단일 파일 기반 상태 관리는 동시성 문제 가능성.

### 5.6 에지케이스 학습 데이터 부재

- edge-cases.md가 빈 상태 (템플릿만 존재). 초기 시딩 데이터가 없으면 첫 변환 시 학습 루프의 가치가 제한적.
- oracle-pg-rules.md 룰셋은 포괄적이나, 실제 프로젝트에서 발견될 예외 케이스(예: 비표준 Oracle 확장, 커스텀 함수)에 대한 대비가 부족.

### 5.7 Kiro CLI 플랫폼 의존성

- Kiro CLI의 서브에이전트 위임(subagent), 훅 시스템, 리소스 로딩 등 핵심 기능이 Kiro 플랫폼에 강하게 결합.
- Kiro CLI의 버전 변경이나 API 변경 시 전체 시스템에 영향.

---

## 6. 다음 단계 권장

### 6.1 즉시 실행 (이번 주)

| 우선순위 | 작업 | 담당 | 효과 |
|---------|------|------|------|
| P0 | **실제 Oracle XML로 파일럿 테스트** | 전원 | 엔드투엔드 동작 검증. 최소 1개 실제 프로젝트의 XML 3~5개로 Phase 0~6 전체 수행. |
| P0 | **DB 환경 구성** | 인프라 | Oracle + PostgreSQL 테스트 DB 세팅, .env 파일 템플릿 배포. |
| P1 | **Phase 1~2 단독 테스트** (DB 불필요) | 개발 | DB 없이 파싱+변환만으로 먼저 변환 품질 확인. 빠른 피드백 루프. |

### 6.2 단기 (1~2주)

| 우선순위 | 작업 | 담당 | 효과 |
|---------|------|------|------|
| P1 | **SQL 안전 훅 점검 및 수정** | 보안 | 훅 매처 정합성 확인, DML 허용 범위 명확화, 쉘 인젝션 취약점 수정. |
| P1 | **에지케이스 초기 시딩** | 개발 | 팀의 기존 마이그레이션 경험에서 알려진 패턴 10~20건을 edge-cases.md에 수동 등록. |
| P2 | **기본 테스트 프레임워크 구축** | 개발 | parse-xml 스킬 단위 테스트 (3개 픽스처 활용), rule-convert 룰 단위 테스트. |

### 6.3 중기 (3~4주)

| 우선순위 | 작업 | 담당 | 효과 |
|---------|------|------|------|
| P2 | **팀 온보딩 세션** | 팀리드 | 전체 워크플로우 데모, 에스컬레이션 대응법, edge-cases 기여 방법 교육. |
| P2 | **대규모 XML 벤치마크** | 개발 | 100+ 쿼리 규모 XML로 성능/비용 측정. LLM 호출 횟수, 총 소요 시간, 토큰 비용 산출. |
| P3 | **CI/CD 파이프라인** | DevOps | 프롬프트/스킬 변경 시 자동 회귀 테스트. Harness eval 자동 실행. |

### 6.4 장기 (1~2개월)

| 우선순위 | 작업 | 담당 | 효과 |
|---------|------|------|------|
| P3 | **다른 프로젝트 팀으로 확대** | 팀리드 | 학습 데이터 축적 가속. 팀별 edge-cases PR 리뷰 프로세스 수립. |
| P3 | **변환 성공률 대시보드** | DevOps | 프로젝트별/복잡도별 성공률 추적. 학습 루프 효과 측정. |
| P4 | **커스텀 함수/패키지 변환 지원** | 개발 | PL/SQL 패키지, 커스텀 함수 등 고급 패턴 지원 확대. |

---

## 부록: Harness 평가 요약

이전 Full Evaluation (7.8/10 -> Grade B) 이후 개선 작업을 거쳐 현재 8.0/10 (Grade A).

**강점 영역 (8~9점):**
- Agent Communication: 9/10
- Context Management: 9/10
- Feedback Loop Maturity: 9/10
- Cost Efficiency: 9/10

**개선 필요 영역:**
- Testability: 3/10 (자동화 테스트 인프라 부재)
- Safety: 7/10 (SQL 안전 훅 정합성)
- Completeness: 7/10 (에러 복구 예시, 스키마 검증)

---

*Report generated by Team Lead review on 2026-04-09.*
