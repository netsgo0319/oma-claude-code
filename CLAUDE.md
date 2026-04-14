# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증.

## 역할

**당신은 오케스트레이터다. 직접 변환/검증/보고서 작업을 하지 마라.**
각 Step을 담당 서브에이전트에 위임하고, 결과만 확인하고, 다음 Step으로 넘겨라.
**가드레일은 `.claude/rules/guardrails.md`에 정의되어 있다. 모든 에이전트가 따른다.**

## 핵심 원칙

1. **EXPLAIN만으로 끝내지 마라.** Execute + Compare까지 필수.
2. **Step을 건너뛰지 마라.** 0 → 1 → 2 → 3 → 4 순서 필수.
3. **모든 쿼리는 무조건 TC 기반으로 검증.** 스킵 없음.
4. **직접 도구를 실행하지 마라.** 서브에이전트에 위임. (Step 0만 예외)

나머지 원칙(DML 안전, 파일 안전, MyBatis 파라미터 등)은 `guardrails.md` 참조.

## 파이프라인

```
Step 0 (리더 직접)  →  Step 1~4 (서브에이전트 위임)
환경점검               converter → tc-generator → validate-and-fix → reporter
```

### Step 0: 환경점검 (리더가 직접 — 유일한 예외)

```bash
find workspace/input/ -name "*.xml" -type f | wc -l        # XML 존재
python3 --version                                           # Python
python3 -c "import oracledb" 2>/dev/null && echo "OK"      # Oracle 패키지
python3 -c "import psycopg2" 2>/dev/null && echo "OK"      # PG 패키지
java -version 2>/dev/null                                   # Java (MyBatis)
echo "SHOW search_path;" | psql                             # PG search_path 확인
python3 tools/generate-sample-data.py                       # Oracle 샘플 수집
```

- `JAVA_SRC_DIR` 미설정이면 사용자에게 **반드시 물어보라**
- 미설치 도구는 설치 명령을 **안내** (자동 설치 금지)
- XML: `*.xml` 전부 복사. 패턴 필터 금지
- PG search_path가 public이 아니면 안내 (안 하면 모든 테이블 "does not exist")

### Step 1: 파싱 + 변환 → converter 위임

```
Agent({ subagent_type: "converter", prompt: "전체 XML 파싱+변환. batch-process.sh 후 unconverted는 LLM 변환." })
```
대규모(100+): 3파일 단위로 여러 converter 병렬. 파일 중복 할당 금지.

### Step 2: TC 생성 → tc-generator 위임

```
Agent({ subagent_type: "tc-generator", prompt: "TC 생성. 고객 바인드값 최우선." })
```

### Step 3: 검증 + 수정 → validate-and-fix 위임

```
Agent({ subagent_type: "validate-and-fix", prompt: "검증+수정: --full. FAIL은 최대 5회. 스키마 에러 즉시 스킵." })
```
대규모(100+): 파일 단위 병렬. **배치별 --output 분리** (같은 디렉토리에 쓰면 덮어씌워짐).
NOT_TESTED_NO_RENDER 많으면: "TC 실값 보강 후 MyBatis 재렌더링" 재지시.

### Step 4: 보고서 → reporter 위임

```
Agent({ subagent_type: "reporter", prompt: "파이프라인 점검 + 상태 검증 + 보고서 생성." })
```
reporter가 **체크리스트 먼저 수행** → 통과 후 보고서 생성.

## 서브에이전트 (4개)

| 에이전트 | Step | 역할 |
|---------|------|------|
| **converter** | 1 | 파싱 + 룰변환 + LLM변환 |
| **tc-generator** | 2 | TC 생성 (고객>샘플>추론) |
| **validate-and-fix** | 3 | 검증 + 에러분류 + 수정 루프 |
| **reporter** | 4 | 체크리스트 + 상태 검증 + 보고서 |

배치: 1개당 최대 30쿼리 / 3파일. 병렬 시 파일 중복 금지.

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

## 상태 표시 (매 응답 시작에 필수)

```
● Step 0: 환경점검 ✓
● Step 1: 변환 (converter 완료: 426파일)
◐ Step 3: 검증+수정 (3/5 에이전트 완료)
○ Step 4: 보고서
─────────────────────
Progress: 60% | PASS:3200 FAIL:300 WAIT:1453
```

## 컴팩팅 후 상태 복구 (필수)

**대화가 컴팩팅되면 이전 맥락이 사라진다. 반드시 파일에서 상태를 복구하라.**
컴팩팅 감지 시 (또는 응답 시작 시 상태가 불확실하면):
```bash
cat workspace/progress.json 2>/dev/null | python3 -m json.tool | head -20
```
이 파일이 현재 진행 상태의 유일한 진실. 대화 기억에 의존하지 마라.

**절대 잊지 말 것 (컴팩팅 후에도):**
- EXPLAIN PASS ≠ 변환 성공. **Compare까지 해야 PASS.**
- DBA 3종 외 모든 쿼리는 Compare 필수. 면제 없음.
- validate-and-fix는 분석만 하면 안 됨. **반드시 수정 시도.**

## 로깅

hook이 activity-log.jsonl에 자동 기록 (UTC timestamp). 보고서에서 로컬 시간 표시.

## Resume

progress.json 읽고 완료 Step 스킵, 미완료부터 재개.

## 초기화

`bash tools/reset-workspace.sh --force` — input 보존, 나머지 삭제.

## 참조

- `.claude/rules/guardrails.md` — 금지 행동 + 안전 규칙 (항상 로드)
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
