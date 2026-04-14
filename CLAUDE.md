# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증 에이전트.

## 트리거

"변환해줘", "convert", "마이그레이션", "시작" → **전체 파이프라인 자동 실행**.
특정 단계만 요청 시 해당 단계만 실행.

## 핵심 원칙

1. **EXPLAIN만으로 끝내지 마라.** Oracle↔PG 양쪽 실행 결과가 동일해야 한다. EXPLAIN 통과 ≠ 변환 성공.
2. **단계를 건너뛰지 마라.** 환경점검 → 변환 → TC → 검증+수정 루프 → 보고서. 순서 필수.
3. **기존 도구만 사용하라.** workspace/ 아래에 임시 스크립트를 만들지 마라.
4. **#{param}은 MyBatis 바인드 파라미터다.** Oracle 구문이 아니므로 변환하지 마라.

## 파이프라인

```
환경점검 → 파싱+변환 → TC생성 → 검증+수정 루프 → 보고서
```

### Step 0: 환경점검

| 항목 | 확인 | 필수 |
|------|------|------|
| XML 파일 | `workspace/input/*.xml` 존재 | **필수** |
| Python 3 | `python3 --version` | **필수** |
| oracledb | `python3 -c "import oracledb"` | 권장 |
| psycopg2 | `python3 -c "import psycopg2"` | 권장 |
| Java 11+ | `java -version` | 권장 (MyBatis 엔진) |
| Oracle/PG 접속 | 환경변수 확인 | 선택 |

미설치 시 설치 명령을 **안내**하라 (자동 설치 금지).
Oracle 접속 시 `python3 tools/generate-sample-data.py`로 테이블 샘플 수집.
`JAVA_SRC_DIR` 미설정 시 사용자에게 경로를 **반드시 물어보라**.

### Step 1: 파싱 + 룰 변환

```bash
bash tools/batch-process.sh --all --parallel 8
```

unconverted 패턴이 남으면 **Converter 서브에이전트**에 위임 (3파일/30쿼리 단위 병렬).

### Step 2: TC 생성

```bash
python3 tools/generate-test-cases.py --samples-dir workspace/results/_samples/
```

TC 우선순위: **고객 제공 바인드값** > 샘플 데이터 > Java VO > Oracle 딕셔너리 > 추론.
고객 바인드값이 있으면 최우선 반영. 나머지는 기본값으로 채워서 **무조건 테스트**.

### Step 3: 검증 + 수정 루프 (핵심)

```bash
# MyBatis 렌더링
bash tools/run-extractor.sh --validate

# 검증 (--full: EXPLAIN → Execute → Compare 원자적)
python3 tools/validate-queries.py --full \
  --extracted workspace/results/_extracted_pg/ \
  --output workspace/results/_validation/ \
  --tracking-dir workspace/results/
```

**검증 결과에 FAIL이 있으면:**
- **validate-and-fix** 서브에이전트에 위임
- 에이전트가 내부에서: 에러 분류 → SQL 수정 → `--full` 재검증 (최대 5회)
- **스키마 에러(relation_missing, column_missing)는 즉시 스킵** — DBA 영역
- 모든 시도를 query-tracking.json에 기록 (TC, 시도 내용, 결과)

```
Agent({
  subagent_type: "validate-and-fix",
  prompt: "FAIL 쿼리 수정: files=[...], max_retries=5"
})
```

100+ 쿼리: 여러 validate-and-fix 에이전트에 파일 단위 병렬 분배.

**0건==0건도 유효한 PASS.** Compare 스킵 금지.
**DML: PG는 BEGIN/ROLLBACK, Oracle은 SELECT COUNT(*) WHERE.**

### Step 4: 보고서

```bash
python3 tools/generate-query-matrix.py --output workspace/reports/query-matrix.csv --json
python3 tools/generate-report.py
```

산출물:
- `query-matrix.csv` — 전체 쿼리별 변환/검증/비교 현황 (14개 상태)
- `migration-report.html` — Overview(통계) + Explorer(쿼리별 라이프사이클)

## 14개 쿼리 최종 상태

| 상태 | 설명 |
|------|------|
| PASS_COMPLETE | 변환+비교 통과 |
| PASS_HEALED | 수정 후 비교 통과 |
| PASS_NO_CHANGE | 변환 불필요 + 비교 통과 |
| FAIL_SCHEMA_MISSING | PG 테이블 없음 (DBA) |
| FAIL_COLUMN_MISSING | PG 컬럼 없음 (DBA) |
| FAIL_FUNCTION_MISSING | PG 함수 없음 (DBA) |
| FAIL_ESCALATED | 5회 수정 후 미해결 |
| FAIL_SYNTAX | SQL 문법 에러 |
| FAIL_COMPARE_DIFF | Oracle↔PG 결과 불일치 |
| FAIL_TC_TYPE_MISMATCH | 바인드값 타입 불일치 |
| FAIL_TC_OPERATOR | 연산자 타입 불일치 |
| NOT_TESTED_NO_RENDER | MyBatis 렌더링 실패 |
| NOT_TESTED_NO_DB | DB 미접속 |
| NOT_TESTED_PENDING | 변환 미완료 |

## 도구

| 도구 | 용도 |
|------|------|
| `tools/batch-process.sh` | Step 1: 파싱+룰변환 병렬 |
| `tools/generate-sample-data.py` | Step 0: Oracle 테이블 샘플 수집 |
| `tools/generate-test-cases.py` | Step 2: TC 생성 |
| `tools/validate-queries.py` | Step 3: 검증 (--full) |
| `tools/run-extractor.sh` | Step 3: MyBatis 렌더링 |
| `tools/generate-query-matrix.py` | Step 4: 쿼리 매트릭스 CSV |
| `tools/generate-report.py` | Step 4: HTML 리포트 |
| `tools/oracle-to-pg-converter.py` | 룰 기반 변환 엔진 |
| `tools/sync-tracking-to-xml.py` | tracking→XML 동기화 |
| `tools/reset-workspace.sh` | 초기화 |

## 서브에이전트 (2개)

| 에이전트 | 모델 | 역할 |
|---------|------|------|
| converter | sonnet | Oracle→PG 변환 (룰+LLM) |
| validate-and-fix | sonnet | 검증+에러분류+수정+재검증 루프 |

배치: 1개당 최대 30쿼리 / 3파일. 동시 여러 에이전트 위임 가능.

## 상태 표시

```
● Step 0: 환경점검 ✓
● Step 1: 파싱+변환 (426파일, 4953쿼리)
◐ Step 3: 검증+수정 (80/150)
○ Step 4: 보고서
─────────────────────
Progress: 53% | PASS:80 FAIL:0 WAIT:70
```

## 변환 룰

작업 전 반드시 Read:
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
