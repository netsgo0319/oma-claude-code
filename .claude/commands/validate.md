Run Phase 3 validation only -- generate test scripts and execute EXPLAIN/execution validation against PostgreSQL.

## Instructions

1. Check that converted SQL files exist in `workspace/output/`. If no converted files are found, report that conversion (Phase 3) must be run first via `/convert --from 3 --to 3` or the full pipeline.

2. Generate test cases for all converted queries:
   - Read the converted SQL files from `workspace/output/`
   - For each query, generate an EXPLAIN-based test that verifies PostgreSQL can parse and plan the query
   - For queries with parameter placeholders, generate reasonable test parameter values based on the query context

3. Execute validation:
   ```
   python3 tools/validate-queries.py
   ```

4. Collect and summarize results:
   - **Pass count**: Queries that passed EXPLAIN validation
   - **Fail count**: Queries that failed with errors
   - **Error breakdown**: Group failures by error type (syntax error, missing function, type mismatch, etc.)
   - **Details**: For each failure, show the query ID, the original Oracle SQL, the converted PostgreSQL SQL, and the error message

5. Write validation results to `workspace/results/` and update `workspace/progress.json` if it exists.

6. If there are failures, suggest running the fix-and-retry cycle (Phase 5) or provide specific guidance on what needs manual correction.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- `--file FILENAME` -- validate only queries from a specific source file
- `--explain-only` -- run EXPLAIN without executing queries
- `--verbose` -- show full EXPLAIN output for all queries, not just failures
