Execute the full OMA (Oracle Migration Accelerator) pipeline from Phase 0 through Phase 7.

## Instructions

1. Read CLAUDE.md at the project root for the complete pipeline specification and phase definitions.
2. Read \`workspace/progress.json\` if it exists to check for any previously completed phases. Resume from the last incomplete phase rather than restarting.
3. Execute each phase sequentially:

   - **Phase 0 - Setup**: Validate workspace structure, ensure input files exist, initialize \`workspace/progress.json\`.
   - **Phase 1 - Extract**: Parse MyBatis/iBatis XML mappers to extract Oracle SQL queries. Run \`bash tools/run-extractor.sh\` or \`python3 tools/parse-xml.py\` as appropriate.
   - **Phase 2 - Analyze**: Run \`python3 tools/query-analyzer.py\` to classify queries by complexity and identify Oracle-specific constructs.
   - **Phase 3 - Convert**: Apply rule-based conversion first (\`python3 tools/oracle-to-pg-converter.py\`), then use LLM-assisted conversion for complex queries that rules cannot handle.
   - **Phase 4 - Validate**: Generate test cases and run EXPLAIN-based validation against PostgreSQL. Use \`python3 tools/validate-queries.py\`.
   - **Phase 5 - Fix**: For any queries that failed validation, analyze errors, apply corrections, and re-validate. Loop until all queries pass or maximum retry count is reached.
   - **Phase 6 - Report**: Generate the final HTML migration report with \`python3 tools/generate-report.py\`.
   - **Phase 7 - Review**: Produce summary statistics and flag any remaining items that need human review.

4. After each phase completes, update \`workspace/progress.json\` with the phase status, timestamp, and any error details.
5. Use the Agent tool to dispatch parallel subagent work where phases allow it (e.g., converting multiple independent SQL files in Phase 3).
6. On failure in any phase, log the error to \`workspace/logs/\`, update progress.json with the failure, and report the issue clearly before stopping.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- \`--from N\` — start from Phase N instead of Phase 0
- \`--to N\` — stop after Phase N instead of running through Phase 7
- \`--dry-run\` — show what would be executed without running anything
