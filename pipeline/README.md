# Application Log Data Pipeline

## Overview

This directory contains a local batch pipeline that processes seven days of application logs
through Raw, Bronze, and Silver layers. It isolates malformed JSON without losing the raw input,
normalizes valid records, enforces a Pandera data contract, writes date-partitioned Parquet, and
provides DuckDB queries for operational reporting.

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
deduplicate → normalize → derive fields → Pandera validation
        │
        ▼
Silver Parquet partitioned by event_date_utc0
        │
        ▼
DuckDB reporting queries
```

## Files

| File | Responsibility |
|---|---|
| `main.py` | Resolves project paths and orchestrates ingestion and transformation. |
| `ingest.py` | Separates parseable JSON lines from malformed lines. |
| `transform.py` | Deduplicates, normalizes, enriches, validates, and writes Silver data. |
| `data_quality.py` | Defines the Pandera Silver data contract and cross-column checks. |
| `logger.py` | Creates reusable file loggers under `pipeline/logs`. |
| `report.py` | Runs three analytical queries against the partitioned Parquet dataset. |
| `outputs/report_results.md` | Reserved location for report documentation; `report.py` currently prints to stdout. |

## Prerequisites

- Python 3.10 or newer
- Dependencies from the project-level `requirements.txt`

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Input contract

The pipeline expects one JSON object per physical line in:

```text
data/raw/app_logs_7days.jsonl
```

Expected source fields:

| Field | Expected value |
|---|---|
| `timestamp` | Timestamp parseable by pandas, or the known corrupted value `not-a-date`. |
| `service` | One of `notification-worker`, `auth-service`, `payment-api`, `batch-report`, `web-portal`. |
| `level` | `INFO`, `WARN`, or `ERROR`; a missing level is repaired only for `Heartbeat ok`. |
| `message` | Non-null log message. |
| `request_id` | Format `req-########`. |
| `trace_id` | Optional; when present, format `trace-##########`. |

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

`run_ingestion()` reads the source one line at a time:

- valid JSON objects are written to `data/bronze/bronze_valid_records.jsonl`;
- malformed JSON lines are written to
  `data/bronze/quarantine/malformed_records.jsonl` with source file, physical line number, raw
  text, and parser error;
- empty lines are logged and skipped;
- both Bronze outputs use write mode, so a rerun replaces the previous Bronze result.

For the supplied dataset, one run produces:

```text
Physical input lines: 2,923
Valid JSON records:   2,905
Malformed records:       18
```

### 2. Bronze to Silver

`run_transformation()` performs these operations in order:

1. Load Bronze JSONL with pandas.
2. Require all six source columns.
3. Remove complete duplicates across the source columns, keeping the first record.
4. Parse timestamps as UTC with invalid values coerced to null.
5. Mark corrupted timestamps and forward-fill their event timestamp.
6. Derive `event_date_utc0`.
7. Impute a missing level as `INFO` only when the message is `Heartbeat ok`.
8. Extract `event_error_type` from messages beginning with `ERR`.
9. Validate the complete DataFrame with Pandera in lazy mode.
10. Write Parquet partitioned by `event_date_utc0`.

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
| `event_timestamp_utc0` | UTC timestamp; known corrupted timestamps are forward-filled. |
| `event_date_utc0` | Date used as the Parquet partition key. |
| `is_event_corrupted` | Indicates a timestamp that could not be parsed. |
| `is_level_imputed` | Indicates that a missing heartbeat level was set to `INFO`. |
| `event_error_type` | First error token, or `HTTP <status>`, extracted from `ERR ...` messages. |

Pandera checks allowed services and levels, date range, nullability, ID formats, repaired
timestamps, and valid heartbeat-level imputation. Validation collects all failures and prevents
invalid Silver data from being written.

## Reporting

After a successful pipeline run:

```bash
python3 pipeline/report.py
```

`report.py` creates an in-memory DuckDB view over all Parquet files and prints:

1. the service or tied services with the most `ERROR` events, using two equivalent queries;
2. daily `ERROR` counts;
3. the three highest-frequency `(event_error_type, service)` combinations.

## Outputs and logging

| Path | Contents |
|---|---|
| `data/bronze/bronze_valid_records.jsonl` | Parseable source records. |
| `data/bronze/quarantine/malformed_records.jsonl` | Malformed records with diagnostics. |
| `data/silver/silver_valid_records.parquet/` | Hive-style date-partitioned Parquet dataset. |
| `pipeline/logs/pipeline.log` | Stage counts, quality results, errors, and tracebacks. |

## Operational cautions

- Run commands from the project root; `report.py` uses a project-relative Parquet path.
- Raw and Bronze files are ignored by Git and must be supplied or regenerated locally.
- The Silver writer does not currently clear or atomically replace an existing Parquet dataset.
  Repeated runs can add more files to existing date partitions and cause DuckDB to count the
  same logical records more than once. Before a full rerun, deliberately archive or remove the
  previous `data/silver/silver_valid_records.parquet` directory, or update the writer to use an
  idempotent overwrite strategy.
- Forward-fill assumes a valid timestamp exists before a corrupted row. A corrupted first row
  fails the non-null Silver contract.
- The date range and allowed service list are dataset-specific constants in `data_quality.py`.
- There is currently no automated pipeline test suite; successful Pandera validation and log
  counts are the primary execution checks.

## Troubleshooting

| Symptom | Check |
|---|---|
| `FileNotFoundError` | Confirm the raw JSONL exists and run from the project root. |
| Missing-column error | Inspect the Bronze source schema and required fields in `transform.py`. |
| Pandera failure | Review failure cases and traceback in `pipeline/logs/pipeline.log`. |
| Duplicate report counts | Check for multiple Parquet files created by repeated pipeline runs. |
| `ModuleNotFoundError` | Activate the virtual environment and reinstall `requirements.txt`. |

