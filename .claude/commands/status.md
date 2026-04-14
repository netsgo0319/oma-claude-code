Show the current OMA pipeline progress and workspace status.

## Instructions

1. Read `workspace/progress.json` from the project root. If it does not exist, report that the pipeline has not been started yet and suggest running `/convert` to begin.

2. Display a formatted summary including:
   - **Overall progress**: How many steps are complete out of total steps
   - **Current step**: Which step is currently in progress (if any)
   - **Step-by-step breakdown**: For each step (0-4), show:
     - Status (pending / in-progress / complete / failed)
     - Start and end timestamps (if available)
     - Duration (if complete)
     - Error summary (if failed)
   - **Statistics**: Total queries extracted, converted, validated, and failed (if available in progress.json)
   - **Errors**: List any logged errors with file paths to detailed logs

3. Also check for recent files in `workspace/logs/` and report the last few log entries if they exist.

4. Check `workspace/output/`, `workspace/results/`, and `workspace/reports/` to report how many output artifacts have been generated.

5. Present all information in a clean, readable table or structured format.
