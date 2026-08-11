# Application Log Data Pipeline

## Overview
`/pipeline` contains a local **batch pipeline** processing seven days of application logs through Raw, Bronze, and Silver layers. 

```text
data/raw/app_logs_7days.jsonl
              │
              ▼
       JSON line validation
        ┌─────┴─────┐
        ▼           ▼
 Bronze valid   Bronze quarantine
    JSONL       malformed JSONL
        │
        ▼
Deduplicate → Normalize → Derive fields → Pandera validation
        │
        ▼
Silver Parquet partitioned by event_date_utc0
        │
        ▼
DuckDB reporting queries
```
![alt text](../images/duckdb.png)
https://vutr.substack.com/p/duckdb-at-a-high-level

## Prerequisites
- Python 3.10 or newer
- Dependencies from the project-level `requirements.txt`

From the project root:
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Files
| File | Responsibility |
|---|---|
| `main.py` | Run ingestion and transformation |
| `ingest.py` | Read raw data and separates parseable JSON lines from malformed lines |
| `transform.py` | Deduplicates, normalizes, enriches, validates, and writes Silver data |
| `data_quality.py` | Defines the Pandera Silver data contract and cross-column checks. |
| `logger.py` | Creates reusable file loggers under `pipeline/logs` |
| `report.py` | Runs three analytical queries against the partitioned Parquet dataset |
| `outputs/report_results.md` | Report documentation; `report.py` currently prints to stdout |

## Input contract

The pipeline expects one JSON object per physical line in:

```text
data/raw/app_logs_7days.jsonl
```

Expected source fields:

| Field | Expected value |
|---|---|
| `timestamp` | Timestamp parseable by pandas, or the known corrupted value `not-a-date` |
| `service` | One of `notification-worker`, `auth-service`, `payment-api`, `batch-report`, `web-portal` |
| `level` | `INFO`, `WARN`, or `ERROR`; a missing level |
| `message` | Non-null log message |
| `request_id` | Format `req-########` |
| `trace_id` | Optional; when present, format `trace-##########` |

The configured event-date range is 2026-07-27 through 2026-08-02, inclusive.

## Run the pipeline

Run from the repository root so all relative paths resolve consistently:

```bash
python3 -m pipeline.main
```

Equivalent direct execution is supported:

```bash
python3 pipeline/main.py
```

The orchestrator exits with status `1` and logs the traceback if either stage fails.

## Processing stages

### 1. Raw to Bronze
`run_ingestion()` **reads the source one line at a time**:
- valid JSON objects are written to `data/bronze/bronze_valid_records.jsonl`
- malformed JSON lines are written to
  `data/bronze/quarantine/malformed_records.jsonl`

For the supplied dataset, one run produces:
```text
Physical input lines: 2,923
Valid JSON records:   2,905
Malformed records:       18
```

### 2. Bronze to Silver
`run_transformation()` performs these operations in order:
1. Load Bronze JSONL with `pandas` (6 source columns are strictly required)
2. Remove complete duplicates across the source columns, keeping the first record
3. Parse timestamps as UTC with invalid values coerced to `null`
4. **Mark** unparseable timestamps `is_event_corrupted` and **forward-fill** their event timestamp
5. Derive `event_date_utc0` from `event_timestamp_0`
6. Impute a missing level as `INFO` only when the message is `Heartbeat ok` and mark this record with `is_level_imputed`
7. Extract `event_error_type` from messages beginning with `ERR`
8. Implement **data quality control using Pandera**
9. Write Parquet partitioned by `event_date_utc0`

For one clean execution of the supplied dataset:
```text
Bronze records:        2,905
Duplicates removed:      28
Silver records:        2,877
Date partitions:           7
```

## Silver schema

The output retains the six source columns and adds:

| Derived field | Description |
|---|---|
| `event_timestamp_utc0` | UTC timestamp; known corrupted timestamps are forward-filled |
| `event_date_utc0` | Date used as the Parquet partition key |
| `is_event_corrupted` | Indicates a timestamp that could not be parsed |
| `is_level_imputed` | Indicates that a missing heartbeat level was set to `INFO` |
| `event_error_type` | First error token, or `HTTP <status>`, extracted from `ERR ...` messages |

## Reporting

After a successful pipeline run:

```bash
python3 pipeline/report.py
```

`report.py` creates an in-memory DuckDB view over all Parquet files and prints:

1. The service or tied services with the most `ERROR` events
2. Daily `ERROR` counts
3. The three highest-frequency `(event_error_type, service)` combinations

