# Local Knowledge Base

## Overview

This directory contains a revision-aware retrieval system for the Markdown documents in
`data/docs`. It parses document metadata without modifying the sources, resolves current and
superseded revisions, creates hierarchical chunks, builds SQLite FTS5 indexes, and returns
citable context for an AI assistant.

The default system is lexical, local, and offline. Optional local embeddings provide hybrid
semantic retrieval when explicitly configured.

```text
Original Markdown documents
            ↓
metadata parsing and revision validation
            ↓
H2/H3 hierarchical chunking
            ↓
temporary JSONL + SQLite + manifest
            ↓
integrity and freshness validation
            ↓
atomic artifact publication

User question
      ↓
normalize → strict FTS → relaxed FTS → optional semantic candidates
      ↓
rerank → relevance filter → deduplicate → diversify
      ↓
citable source chunks / LLM context
```

## Files

| File | Responsibility |
|---|---|
| `build_kb.py` | Parses sources, resolves versions, chunks documents, validates, and builds artifacts. |
| `search_kb.py` | Plans queries, retrieves candidates, reranks results, and formats LLM context. |
| `eval_questions.json` | Retrieval regression cases and expected sources/answers. |
| `evaluate_kb.py` | Runs evaluations and reports pass rate and mean reciprocal rank. |
| `test_kb.py` | Unit and integration tests, including failure paths and semantic fusion. |
| `smoke_test.py` | Fast artifact, freshness, integrity, and retrieval acceptance check. |
| `artifacts/` | Generated JSONL, SQLite database, and build manifest. |

The operational update procedure is in
[`../sop/KB_UPDATE_SOP.md`](../sop/KB_UPDATE_SOP.md).

## Prerequisites

- Python 3.10 or newer
- SQLite compiled with FTS5, included in normal modern Python distributions
- Project dependencies

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Source-document contract

The checked-in files under `data/docs` retain their original Markdown format:

```markdown
# POL-01 — Chính sách sao lưu dữ liệu

**Công ty ... — Phòng CNTT** · Phiên bản 2.0 · Ban hành: 05/2026

## Quy định

Document content...
```

The parser extracts the document ID and title from the H1, and reads version, publication/update
month, owner, approver, and replacement text from the bold metadata line. It also supports
optional YAML front matter for future external sources, but the existing documents do not require
migration.

Supported logical document types are derived from the ID prefix:

```text
FAQ → FAQ       GUIDE → GUIDE       POL → POLICY
RUN → RUNBOOK   SOP → SOP
```

Dates preserve source precision as `YYYY-MM`; no day is invented. Versions must be dotted
integers such as `1.0` or `2.1.3`.

## Build the KB

Run from the project root:

```bash
python3 kb/build_kb.py
```

Options:

```text
--docs-dir PATH       Markdown source directory; default data/docs
--out-dir PATH        Artifact output directory; default kb/artifacts
--max-words N         Soft maximum prose chunk size; default 450
--overlap-words N     Overlap for oversized prose; default 60
--embedding-model ID  Optional local sentence-transformers model
```

The build fails closed on malformed metadata, duplicate revisions, ambiguous current versions,
duplicate chunk IDs, invalid dates/versions, missing non-empty H2 sections, or database integrity
errors.

### Revision resolution

Documents are grouped by logical `doc_id`. The resolver guarantees exactly one active revision:

1. one explicitly active revision wins, when structured metadata provides it;
2. otherwise the highest dotted numeric version wins;
3. unversioned revisions fall back to publication month;
4. ambiguous ties or mixed versioned/unversioned revisions are rejected.

For the current source set:

```text
POL-01 v1.0 → inactive and retained for audit
POL-01 v2.0 → active and available to normal search
```

SQLite additionally enforces one active row per `doc_id` with a partial unique index.

### Chunking

- H2 headings define parent sections.
- H3 headings define subsections.
- Short sections remain whole.
- Oversized prose is split by paragraph and overlapping word windows.
- Markdown tables and numbered procedures remain intact.
- Every chunk carries hierarchy, source/version metadata, active status, and source/content
  SHA-256 hashes.

The current eight source documents produce 22 chunks, of which 20 belong to active revisions.

### Atomic publication

The builder creates temporary artifacts, then validates SQLite integrity, foreign keys, row
counts, FTS counts, chunk uniqueness, and active-revision invariants. Only a valid build replaces
the published artifacts; a failed build leaves the previous database untouched.

## Artifacts and database structure

| Artifact | Purpose |
|---|---|
| `artifacts/chunks.jsonl` | Inspectable chunk records with metadata and provenance. |
| `artifacts/knowledge_base.db` | Documents, chunks, FTS5 indexes, and optional embeddings. |
| `artifacts/build_manifest.json` | Schema/build versions, timestamp, counts, model, and source hashes. |

Important SQLite objects:

| Object | Purpose |
|---|---|
| `documents` | One row per source revision. |
| `chunks` | Retrieval chunks linked to document revisions. |
| `active_chunks_fts` | Normal search index containing current revisions only. |
| `all_chunks_fts` | Audit index containing current and superseded revisions. |
| `chunk_embeddings` | Optional normalized embedding vectors. |
| `build_info` | Schema, builder, count, date, and model metadata. |

Separating active and archive indexes prevents old revisions from affecting active-index BM25
statistics.

## Search

```bash
# Normal active-only search
python3 kb/search_kb.py "Backup được lưu giữ bao nhiêu ngày?" --top-k 3

# Audit active and historical revisions
python3 kb/search_kb.py "POL-01 backup" --include-inactive

# Require at least 70% query-term coverage
python3 kb/search_kb.py "restart payment-api queue" --min-relevance 0.7
```

Useful options:

```text
--db PATH                       Alternative SQLite database
--top-k N                       Maximum returned chunks; default 5
--include-inactive              Search the audit index
--max-per-document N            Diversity limit; default 2
--min-relevance FLOAT           Coverage/semantic gate; default 0.6
--semantic / --no-semantic      Enable/disable available embeddings
--semantic-min-similarity FLOAT Semantic acceptance threshold; default 0.35
```

### Retrieval behavior

The query planner lowercases and accent-normalizes input, removes duplicate and common
Vietnamese/English stop words, safely quotes FTS terms, and expands controlled domain synonyms
such as `backup ↔ sao lưu` and `restart ↔ khởi động lại`.

Search then:

1. tries a strict `AND` query;
2. obtains relaxed `OR` candidates when more recall is needed;
3. optionally adds embedding candidates;
4. boosts exact document IDs, error codes, and service names;
5. reranks by coverage and reciprocal ranks;
6. rejects candidates below the relevance threshold;
7. removes duplicate content and limits results per document.

FTS5 field weights are:

| Field | Weight |
|---|---:|
| `doc_id` | 5.0 |
| `title` | 3.0 |
| `section` | 2.5 |
| `subsection` | 2.0 |
| `doc_type` | 1.5 |
| `keywords` | 1.5 |
| `content` | 1.0 |

Lower raw BM25 scores are better. The combined displayed retrieval score is higher-is-better.

### Python API

```python
from kb.search_kb import KnowledgeBase

kb = KnowledgeBase("kb/artifacts/knowledge_base.db")
results = kb.search(
    "ERR NullPointer ReportBuilder",
    top_k=3,
)
context = kb.format_context(results)
```

`format_context()` labels source content as untrusted reference data, preserves citations, escapes
source-boundary markers, and instructs a later generation layer to decline unsupported answers.
This project provides retrieval and context preparation; it does not itself call an LLM.

## Optional semantic retrieval

Install the optional package and provide a local model:

```bash
python3 -m pip install "sentence-transformers>=5,<6"
python3 kb/build_kb.py --embedding-model /path/to/local/model
python3 kb/search_kb.py "Who authorizes data recovery?" --semantic
```

Vectors are normalized and stored in SQLite. Search computes cosine similarity and fuses semantic
and lexical ranks. The default artifact has no embeddings and does not download a model.

## Evaluation and tests

```bash
python3 kb/evaluate_kb.py
python3 kb/smoke_test.py
python3 -m unittest discover -s kb -p 'test_*.py' -v
```

The 12 evaluation cases cover current-version selection, stale-version exclusion, accentless
Vietnamese, English/Vietnamese synonyms, error and service identifiers, document-ID lookup,
expected answer terms, ranking, and no-answer behavior.

Current verified baseline:

```text
Documents:             8
Chunks:                22
Active-index chunks:   20
Retrieval evaluations: 12/12 passed
Mean reciprocal rank:  1.000
Unit tests:            12/12 passed
Smoke test:            passed
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Database not found | Run `python3 kb/build_kb.py` from the project root. |
| Outdated schema | Rebuild the artifacts with the current builder. |
| FTS5 unavailable | Use a standard modern Python/SQLite distribution with FTS5. |
| No search results | Inspect stop-word removal, synonyms, relevance threshold, and source wording. |
| Old version appears | Confirm normal search is not using `--include-inactive`; rerun smoke tests. |
| Semantic search error | Rebuild with `--embedding-model` and install `sentence-transformers`. |
| Build rejected | Correct the reported metadata, version, section, or integrity problem; do not edit SQLite directly. |

## Known limitations

- Domain synonyms are maintained manually.
- Default search is lexical and does not provide general semantic understanding.
- Thresholds are calibrated on a small 12-case evaluation set.
- Optional vector search scans stored vectors directly and is intended for small datasets.
- Legacy metadata parsing depends on the documented source-line convention.
- Answer generation and production LLM integration are outside this directory's scope.
