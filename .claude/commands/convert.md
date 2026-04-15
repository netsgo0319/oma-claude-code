---
disable-model-invocation: true
---

Execute the full OMA (Oracle Migration Accelerator) pipeline from Step 0 through Step 4.

## Instructions

1. Read CLAUDE.md at the project root for the complete pipeline specification and step definitions.
2. Read `workspace/progress.json` if it exists to check for any previously completed steps. Resume from the last incomplete step rather than restarting.
3. Execute each step sequentially (CLAUDE.md 참조):

   - **Step 0 - Preflight**: 환경 체크 (XML, Python, psql, sqlplus, Java). Oracle 오브젝트 스캔. PG pgcrypto 확인.
   - **Step 1 - Parse + Convert**: XML 파싱 + 40+ 룰 기계적 변환 + LLM 복합 변환 (Converter 서브에이전트).
   - **Step 2 - TC Generate**: 테스트 케이스 생성. `python3 tools/generate-test-cases.py --samples-dir workspace/results/_samples/`.
   - **Step 3 - Validate + Fix Loop**: MyBatis 렌더링 → EXPLAIN → Execute → Compare (3단계 검증). 실패 쿼리는 validate-and-fix 서브에이전트로 수정+재검증 루프 (최대 3회).
   - **Step 4 - Report**: `python3 tools/generate-query-matrix.py --json` + `python3 tools/generate-report.py`.

4. After each step completes, update `workspace/progress.json` with the step status, timestamp, and any error details.
5. Use the Agent tool to dispatch parallel subagent work where steps allow it.
6. On failure in any step, log the error to `workspace/logs/`, update progress.json with the failure, and report the issue clearly before stopping.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- `--from N` — start from Step N instead of Step 0
- `--to N` — stop after Step N instead of running through Step 4
- `--dry-run` — show what would be executed without running anything
