### Step 1: Understanding the dataset
- Log of 5 systems
- JSONL format - where each line is a seperate, valid JSON object separated by a newline character
- Time range: 7 days from 27/07 to 02/08

### Step 2: Profile the dataset before making any cleaning decisions
I inspected app_logs_7days.jsonl, and there are 2,923 physical lines.
- 2,905 parse successfully as JSON
- 18 malformed JSON lines