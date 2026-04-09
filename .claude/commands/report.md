Generate the OMA HTML migration report.

## Instructions

1. Verify that pipeline results exist by checking:
   - `workspace/results/` contains validation results
   - `workspace/output/` contains converted SQL files
   - If neither exists, report that the pipeline must be run first.

2. Generate the HTML report:
   ```
   python3 tools/generate-report.py
   ```

3. After report generation, verify the output:
   - Check that the report file was created in `workspace/reports/`
   - Read the generated report to confirm it contains the expected sections (summary, per-file details, error listings)

4. Display a summary of what the report contains:
   - Total files processed
   - Conversion success rate
   - Validation pass rate
   - Key issues requiring human review
   - Path to the generated HTML file

5. If `workspace/dashboard.html` exists, note that it can also be opened for an interactive view of the migration status.

## Arguments

$ARGUMENTS

If arguments are provided, interpret them as:
- `--open` -- after generating, display the report file path for opening in a browser
- `--format FORMAT` -- generate in an alternative format (html, json, csv) if supported by the tool
