---
disable-model-invocation: true
---

Reset the OMA workspace to a clean state, preserving input files.

## Instructions

1. Confirm the reset action by displaying what will be cleared:
   - `workspace/output/` -- converted SQL files
   - `workspace/results/` -- validation results
   - `workspace/reports/` -- generated reports
   - `workspace/logs/` -- execution logs
   - `workspace/progress.json` -- pipeline progress tracker

2. Run the reset script:
   ```
   bash tools/reset-workspace.sh --force
   ```

3. Verify the reset was successful:
   - Check that `workspace/output/`, `workspace/results/`, `workspace/reports/`, and `workspace/logs/` are empty or contain only placeholder files
   - Check that `workspace/progress.json` has been removed or reset
   - Confirm that `workspace/input/` still contains the original source files

4. Report the result: what was cleared and what was preserved.

## Arguments

$ARGUMENTS

If `--keep-logs` is passed as an argument, preserve the `workspace/logs/` directory during reset.
