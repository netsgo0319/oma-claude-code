Run Step 3 validation using `--full` atomic mode (EXPLAIN + Execute + Compare in one pass).

## Instructions

1. Check that converted SQL files exist in `workspace/output/`. If not found, report that conversion must be run first via `/convert`.

2. Run MyBatis rendering first (if Java available):
   ```bash
   bash tools/run-extractor.sh --validate
   ```

3. Execute full validation (--full does EXPLAIN + Execute + Compare + parse atomically):
   ```bash
   python3 tools/validate-queries.py --full \
     --extracted workspace/results/_extracted_pg/ \
     --output workspace/results/_validation/ \
     --tracking-dir workspace/results/
   ```
   **개별 단계(--generate, --local, --execute, --compare, --parse-results)를 따로 실행하지 마라.**

4. Collect and summarize results:
   - **Pass count**: Queries that passed all 3 stages (EXPLAIN + Execute + Compare)
   - **Fail count**: Queries that failed with errors
   - **Error breakdown**: Group failures by error type and stage
   - **Details**: For each failure, show query ID, Oracle SQL, PG SQL, and error message

5. Update `workspace/progress.json` with Step 3 status.

6. If failures exist, note that the validate-and-fix subagent will handle self-healing in Step 3.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- `--files FILE1,FILE2` -- validate only specific files (passed to --files)
- `--verbose` -- show full output for all queries, not just failures
