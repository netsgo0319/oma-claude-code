Execute the full OMA (Oracle Migration Accelerator) pipeline from Phase 0 through Phase 7.

## Instructions

1. Read CLAUDE.md at the project root for the complete pipeline specification and phase definitions.
2. Read `workspace/progress.json` if it exists to check for any previously completed phases. Resume from the last incomplete phase rather than restarting.
3. Execute each phase sequentially (CLAUDE.md 참조):

   - **Phase 0 - Pre-flight**: 환경 체크 (XML, Python, psql, sqlplus, Java). Oracle 오브젝트 스캔. PG pgcrypto 확인.
   - **Phase 1 - Parse + Rule Convert**: `bash tools/batch-process.sh --all --parallel 8`. XML 파싱 + 40+ 룰 기계적 변환.
   - **Phase 2 - LLM Convert**: unconverted 패턴을 Converter 서브에이전트에 위임 (CONNECT BY, MERGE, (+) 등).
   - **Phase 2.5 - Test Cases**: `python3 tools/generate-test-cases.py`. Oracle 딕셔너리 4소스에서 TC 생성.
   - **Phase 3 - Validation**: EXPLAIN → Execute → Compare (3단계). MyBatis 추출 SQL 우선 사용 (`--extracted`).
   - **Phase 4 - Self-healing**: `python3 tools/generate-healing-tickets.py`. 티켓 기반 최대 5회 힐링 루프.
   - **Phase 5 - Learning**: Learner 서브에이전트가 edge-cases/rules 갱신 + Git PR.
   - **Phase 6 - DBA Review**: Reviewer 서브에이전트가 XML 무결성 + 잔여 패턴 최종 검증.
   - **Phase 7 - Report**: `python3 tools/generate-query-matrix.py --json` + `python3 tools/generate-report.py`.

4. After each phase completes, update `workspace/progress.json` with the phase status, timestamp, and any error details.
5. Use the Agent tool to dispatch parallel subagent work where phases allow it.
6. On failure in any phase, log the error to `workspace/logs/`, update progress.json with the failure, and report the issue clearly before stopping.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- `--from N` — start from Phase N instead of Phase 0
- `--to N` — stop after Phase N instead of running through Phase 7
- `--dry-run` — show what would be executed without running anything
