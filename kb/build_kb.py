from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import struct
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2
BUILDER_VERSION = "2.0.0"

TITLE_RE = re.compile(r"^#\s+([A-Z]+-\d+)\s+[—-]\s+(.+?)\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H3_RE = re.compile(r"^###\s+(.+?)\s*$")
VERSION_RE = re.compile(
    r"Phiên bản\s+([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"(Ban hành|Cập nhật):\s*(\d{2}/\d{4})",
    re.IGNORECASE,
)
APPROVER_RE = re.compile(r"Người duyệt:\s*([^·]+)", re.IGNORECASE)
VERSION_VALUE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
ISO_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

DOC_TYPE_MAP = {
    "FAQ": "FAQ",
    "GUIDE": "GUIDE",
    "POL": "POLICY",
    "RUN": "RUNBOOK",
    "SOP": "SOP",
}
VALID_STATUSES = {"active", "inactive", "draft"}


def month_to_iso(value: str | None) -> str | None:
    """Convert MM/YYYY to YYYY-MM without inventing a day."""
    if not value:
        return None
    month, year = value.split("/")
    result = f"{year}-{month}"
    validate_iso_month(result, "published_date")
    return result


def validate_iso_month(value: str, field_name: str) -> None:
    match = ISO_MONTH_RE.fullmatch(value)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"{field_name} must use YYYY-MM with a valid month: {value!r}")


def version_key(version: str | None) -> tuple[int, ...]:
    """Convert a dotted numeric version into a naturally sortable tuple."""
    if not version:
        return ()
    if not VERSION_VALUE_RE.fullmatch(version):
        raise ValueError(f"Unsupported version format: {version!r}")
    return tuple(int(part) for part in version.split("."))


def load_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Return YAML front matter and the Markdown body.

    Front matter is optional to preserve compatibility with legacy documents.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"Unclosed YAML front matter in {path.name}") from exc

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on the runtime
        raise RuntimeError(
            "PyYAML is required for documents that use YAML front matter. "
            "Install dependencies from requirements.txt."
        ) from exc

    try:
        metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML front matter in {path.name}: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError(f"YAML front matter must be a mapping in {path.name}")
    return metadata, "\n".join(lines[end + 1 :]).lstrip("\n")


def _first_nonempty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _optional_string(value: Any, field: str, path: Path) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        result = str(value).strip()
        return result or None
    raise ValueError(f"{field} must be a scalar in {path.name}")


def _keyword_list(value: Any, path: Path) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        keyword = _optional_string(item, "keywords", path)
        if keyword and keyword not in result:
            result.append(keyword)
    return result


def parse_document(path: Path) -> dict[str, Any]:
    """Read one Markdown document and extract validated document metadata."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Empty document: {path}")

    front_matter, body = load_front_matter(text, path)
    title_line = _first_nonempty_line(body)
    title_match = TITLE_RE.match(title_line)
    if not title_match:
        raise ValueError(f"Unexpected title format in {path.name}: {title_line!r}")

    heading_doc_id, heading_title = title_match.groups()
    body_lines = body.splitlines()
    title_index = next(i for i, line in enumerate(body_lines) if line.strip())
    metadata_line = next(
        (
            line.strip()
            for line in body_lines[title_index + 1 : title_index + 6]
            if line.strip().startswith("**")
        ),
        "",
    )

    version_match = VERSION_RE.search(metadata_line)
    date_match = DATE_RE.search(metadata_line)
    approver_match = APPROVER_RE.search(metadata_line)

    doc_id = _optional_string(front_matter.get("doc_id"), "doc_id", path) or heading_doc_id
    title = _optional_string(front_matter.get("title"), "title", path) or heading_title
    if doc_id != heading_doc_id:
        raise ValueError(
            f"Front-matter doc_id {doc_id!r} disagrees with heading {heading_doc_id!r} "
            f"in {path.name}"
        )
    if title != heading_title:
        raise ValueError(
            f"Front-matter title disagrees with heading in {path.name}: "
            f"{title!r} != {heading_title!r}"
        )

    prefix = doc_id.split("-", 1)[0]
    doc_type = (
        _optional_string(front_matter.get("doc_type"), "doc_type", path)
        or DOC_TYPE_MAP.get(prefix, prefix)
    ).upper()
    version = _optional_string(front_matter.get("version"), "version", path)
    if version is None and version_match:
        version = version_match.group(1)
    if version:
        version_key(version)

    published_date = _optional_string(
        front_matter.get("published_date"), "published_date", path
    )
    if published_date is None and date_match:
        published_date = month_to_iso(date_match.group(2))
    if published_date:
        validate_iso_month(published_date, "published_date")

    date_type = _optional_string(front_matter.get("date_type"), "date_type", path)
    if date_type is None and date_match:
        date_type = date_match.group(1)

    owner = _optional_string(front_matter.get("owner"), "owner", path)
    if owner is None and "Phòng CNTT" in metadata_line:
        owner = "Phòng CNTT"
    approver = _optional_string(front_matter.get("approver"), "approver", path)
    if approver is None and approver_match:
        approver = approver_match.group(1).strip()

    status = _optional_string(front_matter.get("status"), "status", path)
    if status:
        status = status.lower()
        if status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUSES)} in {path.name}"
            )

    replaces = _optional_string(front_matter.get("replaces"), "replaces", path)
    legacy_replacement = "Thay thế phiên bản trước" in metadata_line
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "doc_id": doc_id,
        "title": title,
        "source_file": path.name,
        "source_path": str(path),
        "source_sha256": source_sha256,
        "doc_type": doc_type,
        "version": version,
        "date_type": date_type,
        "published_date": published_date,
        "owner": owner,
        "approver": approver,
        "replaces": replaces,
        "replaced_previous": bool(replaces) or legacy_replacement,
        "declared_status": status,
        "keywords": _keyword_list(front_matter.get("keywords"), path),
        "metadata_raw": metadata_line,
        "metadata_source": "front_matter" if front_matter else "legacy",
        "text": body,
        "is_active": False,
        "active_reason": "not resolved",
    }


def _select_latest_revision(doc_id: str, revisions: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [doc for doc in revisions if doc["declared_status"] not in {"inactive", "draft"}]
    if not eligible:
        raise ValueError(f"No eligible active revision for {doc_id}")
    if len(eligible) == 1:
        return eligible[0]

    versions_present = [bool(doc["version"]) for doc in eligible]
    if any(versions_present) and not all(versions_present):
        raise ValueError(
            f"Ambiguous revisions for {doc_id}: do not mix versioned and unversioned "
            "documents without declaring one status: active"
        )

    if all(versions_present):
        best_key = max(version_key(doc["version"]) for doc in eligible)
        winners = [doc for doc in eligible if version_key(doc["version"]) == best_key]
    else:
        if any(not doc["published_date"] for doc in eligible):
            raise ValueError(
                f"Ambiguous unversioned revisions for {doc_id}: published_date is required"
            )
        best_date = max(doc["published_date"] for doc in eligible)
        winners = [doc for doc in eligible if doc["published_date"] == best_date]

    if len(winners) != 1:
        names = ", ".join(doc["source_file"] for doc in winners)
        raise ValueError(f"Ambiguous latest revision for {doc_id}: {names}")
    return winners[0]


def mark_active_revisions(documents: list[dict[str, Any]]) -> None:
    """Resolve revisions and guarantee exactly one active revision per doc_id."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in documents:
        groups[doc["doc_id"]].append(doc)

    for doc_id, revisions in groups.items():
        seen_revision_keys: set[tuple[str, str]] = set()
        for doc in revisions:
            identity = (
                "version" if doc["version"] else "date",
                doc["version"] or doc["published_date"] or "undated",
            )
            if identity in seen_revision_keys:
                raise ValueError(f"Duplicate revision {identity[1]!r} for {doc_id}")
            seen_revision_keys.add(identity)

        declared_active = [doc for doc in revisions if doc["declared_status"] == "active"]
        if len(declared_active) > 1:
            raise ValueError(f"Multiple revisions declare status: active for {doc_id}")
        active = declared_active[0] if declared_active else _select_latest_revision(doc_id, revisions)

        revision_values = {doc["version"] for doc in revisions if doc["version"]}
        if active["replaces"] and active["replaces"] not in revision_values:
            raise ValueError(
                f"{active['source_file']} replaces unknown version {active['replaces']!r}"
            )

        for doc in revisions:
            if doc is not active and doc["replaces"]:
                raise ValueError(
                    f"Inactive revision {doc['source_file']} must not declare replaces"
                )
            doc["is_active"] = doc is active
            if doc is active:
                if doc["declared_status"] == "active":
                    doc["active_reason"] = "explicitly declared active"
                elif len(revisions) == 1:
                    doc["active_reason"] = "only revision found"
                else:
                    doc["active_reason"] = "latest unambiguous revision selected"
            else:
                doc["active_reason"] = f"superseded by {active['source_file']}"

        if sum(int(doc["is_active"]) for doc in revisions) != 1:
            raise AssertionError(f"Revision resolver failed for {doc_id}")


def split_markdown_units(text: str) -> list[dict[str, Any]]:
    """Split at H2/H3 boundaries while retaining their hierarchy."""
    units: list[dict[str, Any]] = []
    section: str | None = None
    subsection: str | None = None
    section_order = 0
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if section and content:
            units.append(
                {
                    "section": section,
                    "subsection": subsection,
                    "section_order": section_order,
                    "content": content,
                }
            )
        buffer = []

    for line in text.splitlines():
        h2 = H2_RE.match(line.strip())
        h3 = H3_RE.match(line.strip())
        if h2:
            flush()
            section = h2.group(1).strip()
            subsection = None
            section_order += 1
        elif h3 and section:
            flush()
            subsection = h3.group(1).strip()
        elif section:
            buffer.append(line)
    flush()
    return units


def split_h2_sections(text: str) -> list[dict[str, Any]]:
    """Backward-compatible alias for callers of the original helper."""
    return split_markdown_units(text)


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _paragraph_blocks(content: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]


def _split_oversized_prose(block: str, max_words: int, overlap_words: int) -> list[str]:
    """Split long prose; preserve Markdown tables and procedural lists intact."""
    lines = block.splitlines()
    is_table = len(lines) >= 2 and any("|" in line for line in lines[:2])
    is_procedure = sum(bool(re.match(r"^\s*\d+[.)]\s+", line)) for line in lines) >= 2
    if is_table or is_procedure or _word_count(block) <= max_words:
        return [block]

    words = block.split()
    step = max(1, max_words - overlap_words)
    return [" ".join(words[start : start + max_words]) for start in range(0, len(words), step)]


def split_long_content(content: str, max_words: int, overlap_words: int) -> list[str]:
    if max_words <= 0:
        raise ValueError("max_words must be greater than 0")
    if overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("overlap_words must be >= 0 and smaller than max_words")
    if _word_count(content) <= max_words:
        return [content]

    blocks: list[str] = []
    for block in _paragraph_blocks(content):
        blocks.extend(_split_oversized_prose(block, max_words, overlap_words))

    chunks: list[str] = []
    current: list[str] = []
    for block in blocks:
        if current and _word_count("\n\n".join(current + [block])) > max_words:
            chunks.append("\n\n".join(current))
            current = []
        current.append(block)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def revision_label(doc: dict[str, Any]) -> str:
    if doc["version"]:
        return "v" + doc["version"].replace(".", "_")
    if doc["published_date"]:
        return "d" + doc["published_date"].replace("-", "")
    return "current"


def make_chunks(
    documents: list[dict[str, Any]],
    max_words: int = 450,
    overlap_words: int = 60,
) -> list[dict[str, Any]]:
    """Create hierarchical, revision-aware chunks from parsed documents."""
    chunks: list[dict[str, Any]] = []
    for doc in documents:
        units = split_markdown_units(doc["text"])
        if not units:
            raise ValueError(f"No non-empty ## sections found in {doc['source_file']}")

        chunk_order = 0
        for unit in units:
            pieces = split_long_content(unit["content"], max_words, overlap_words)
            parent_section_id = (
                f"{doc['doc_id']}_{revision_label(doc)}_section_"
                f"{unit['section_order']:03d}"
            )
            for piece_order, content in enumerate(pieces, start=1):
                chunk_order += 1
                chunk_id = (
                    f"{doc['doc_id']}_{revision_label(doc)}_chunk_{chunk_order:03d}"
                )
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "parent_section_id": parent_section_id,
                        "doc_id": doc["doc_id"],
                        "title": doc["title"],
                        "section": unit["section"],
                        "subsection": unit["subsection"],
                        "section_order": unit["section_order"],
                        "piece_order": piece_order,
                        "chunk_order": chunk_order,
                        "source_file": doc["source_file"],
                        "source_sha256": doc["source_sha256"],
                        "doc_type": doc["doc_type"],
                        "version": doc["version"],
                        "published_date": doc["published_date"],
                        "owner": doc["owner"],
                        "approver": doc["approver"],
                        "keywords": " ".join(doc["keywords"]),
                        "is_active": doc["is_active"],
                        "content": content,
                        "content_sha256": hashlib.sha256(
                            content.encode("utf-8")
                        ).hexdigest(),
                    }
                )
    return chunks


def write_jsonl(chunks: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fout:
        for chunk in chunks:
            fout.write(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n")


def _embedding_rows(
    chunks: list[dict[str, Any]], embedding_model: str | None
) -> Iterable[tuple[int, str, int, bytes]]:
    if not embedding_model:
        return []
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "--embedding-model requires sentence-transformers. Install it and make "
            "sure the requested model is available locally."
        ) from exc

    model = SentenceTransformer(embedding_model)
    texts = [
        "\n".join(
            filter(
                None,
                [chunk["doc_id"], chunk["title"], chunk["section"], chunk["subsection"], chunk["content"]],
            )
        )
        for chunk in chunks
    ]
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [
        (index, embedding_model, len(vector), struct.pack(f"<{len(vector)}f", *vector))
        for index, vector in enumerate(vectors)
    ]


def build_sqlite(
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    db_path: Path,
    embedding_model: str | None = None,
    built_at: str | None = None,
) -> None:
    """Create normalized storage, active/archive FTS indexes, and optional embeddings."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing database directly: {db_path}. "
            "Use build_artifacts() for validated atomic replacement."
        )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(
            """
            CREATE TABLE build_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                doc_id TEXT NOT NULL,
                title TEXT NOT NULL,
                source_file TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                version TEXT,
                published_date TEXT,
                date_type TEXT,
                owner TEXT,
                approver TEXT,
                replaces_version TEXT,
                replaced_previous INTEGER NOT NULL CHECK(replaced_previous IN (0, 1)),
                declared_status TEXT,
                is_active INTEGER NOT NULL CHECK(is_active IN (0, 1)),
                active_reason TEXT NOT NULL,
                metadata_source TEXT NOT NULL,
                metadata_raw TEXT
            );

            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                parent_section_id TEXT NOT NULL,
                document_id INTEGER NOT NULL,
                doc_id TEXT NOT NULL,
                title TEXT NOT NULL,
                section TEXT NOT NULL,
                subsection TEXT,
                section_order INTEGER NOT NULL,
                piece_order INTEGER NOT NULL,
                chunk_order INTEGER NOT NULL,
                source_file TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                version TEXT,
                published_date TEXT,
                owner TEXT,
                approver TEXT,
                keywords TEXT NOT NULL,
                is_active INTEGER NOT NULL CHECK(is_active IN (0, 1)),
                content TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE TABLE chunk_embeddings (
                chunk_id INTEGER PRIMARY KEY,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                vector BLOB NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES chunks(id)
            );

            CREATE INDEX idx_chunks_active ON chunks(is_active);
            CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
            CREATE INDEX idx_chunks_document_id ON chunks(document_id);
            CREATE INDEX idx_documents_doc_id ON documents(doc_id);
            CREATE UNIQUE INDEX idx_one_active_revision
                ON documents(doc_id) WHERE is_active = 1;
            """
        )

        info = {
            "schema_version": str(SCHEMA_VERSION),
            "builder_version": BUILDER_VERSION,
            "built_at_utc": built_at or datetime.now(timezone.utc).isoformat(),
            "document_count": str(len(documents)),
            "chunk_count": str(len(chunks)),
            "embedding_model": embedding_model or "",
        }
        conn.executemany("INSERT INTO build_info(key, value) VALUES (?, ?)", info.items())

        doc_pk_by_source: dict[str, int] = {}
        for doc in documents:
            cur = conn.execute(
                """
                INSERT INTO documents (
                    doc_id, title, source_file, source_path, source_sha256, doc_type,
                    version, published_date, date_type, owner, approver, replaces_version,
                    replaced_previous, declared_status, is_active, active_reason,
                    metadata_source, metadata_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["doc_id"], doc["title"], doc["source_file"], doc["source_path"],
                    doc["source_sha256"], doc["doc_type"], doc["version"],
                    doc["published_date"], doc["date_type"], doc["owner"], doc["approver"],
                    doc["replaces"], int(doc["replaced_previous"]), doc["declared_status"],
                    int(doc["is_active"]), doc["active_reason"], doc["metadata_source"],
                    doc["metadata_raw"],
                ),
            )
            doc_pk_by_source[doc["source_file"]] = int(cur.lastrowid)

        chunk_pk_by_index: dict[int, int] = {}
        for index, chunk in enumerate(chunks):
            cur = conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, parent_section_id, document_id, doc_id, title, section,
                    subsection, section_order, piece_order, chunk_order, source_file,
                    source_sha256, content_sha256, doc_type, version, published_date,
                    owner, approver, keywords, is_active, content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"], chunk["parent_section_id"],
                    doc_pk_by_source[chunk["source_file"]], chunk["doc_id"], chunk["title"],
                    chunk["section"], chunk["subsection"], chunk["section_order"],
                    chunk["piece_order"], chunk["chunk_order"], chunk["source_file"],
                    chunk["source_sha256"], chunk["content_sha256"], chunk["doc_type"],
                    chunk["version"], chunk["published_date"], chunk["owner"],
                    chunk["approver"], chunk["keywords"], int(chunk["is_active"]),
                    chunk["content"],
                ),
            )
            chunk_pk_by_index[index] = int(cur.lastrowid)

        try:
            for table_name in ("active_chunks_fts", "all_chunks_fts"):
                conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE {table_name} USING fts5(
                        doc_id, title, doc_type, section, subsection, keywords, content,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "SQLite FTS5 is unavailable. Use a recent standard Python/SQLite build."
            ) from exc

        fts_values = [
            (
                chunk_pk_by_index[index], chunk["doc_id"], chunk["title"], chunk["doc_type"],
                chunk["section"], chunk["subsection"] or "", chunk["keywords"], chunk["content"],
            )
            for index, chunk in enumerate(chunks)
        ]
        insert_fts = """
            INSERT INTO {table}(rowid, doc_id, title, doc_type, section, subsection, keywords, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn.executemany(insert_fts.format(table="all_chunks_fts"), fts_values)
        conn.executemany(
            insert_fts.format(table="active_chunks_fts"),
            [row for row, chunk in zip(fts_values, chunks) if chunk["is_active"]],
        )

        embedding_rows = _embedding_rows(chunks, embedding_model)
        conn.executemany(
            "INSERT INTO chunk_embeddings(chunk_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
            [
                (chunk_pk_by_index[index], model, dimensions, vector)
                for index, model, dimensions, vector in embedding_rows
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_build(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]], db_path: Path
) -> None:
    """Fail closed if storage, revision, or index invariants are violated."""
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate chunk_id generated")
    source_files = [doc["source_file"] for doc in documents]
    if len(source_files) != len(set(source_files)):
        raise ValueError("Duplicate source filename; source_file is a unique provenance key")

    active_by_doc: dict[str, int] = defaultdict(int)
    for doc in documents:
        active_by_doc[doc["doc_id"]] += int(doc["is_active"])
    invalid = {doc_id: count for doc_id, count in active_by_doc.items() if count != 1}
    if invalid:
        raise ValueError(f"Expected exactly one active revision per doc_id: {invalid}")

    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        counts = {
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "all_fts": conn.execute("SELECT COUNT(*) FROM all_chunks_fts").fetchone()[0],
            "active_fts": conn.execute("SELECT COUNT(*) FROM active_chunks_fts").fetchone()[0],
        }
        expected_active = sum(int(chunk["is_active"]) for chunk in chunks)
        expected = {
            "documents": len(documents),
            "chunks": len(chunks),
            "all_fts": len(chunks),
            "active_fts": expected_active,
        }
        if counts != expected:
            raise RuntimeError(f"Build count mismatch: actual={counts}, expected={expected}")
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"Foreign-key validation failed: {foreign_key_errors}")
    finally:
        conn.close()


def build_artifacts(
    docs_dir: Path,
    out_dir: Path,
    max_words: int = 450,
    overlap_words: int = 60,
    embedding_model: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path, Path]:
    """Build and validate temporary artifacts before atomically publishing them."""
    paths = sorted(docs_dir.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No Markdown files found under {docs_dir}")

    documents = [parse_document(path) for path in paths]
    mark_active_revisions(documents)
    chunks = make_chunks(documents, max_words=max_words, overlap_words=overlap_words)
    out_dir.mkdir(parents=True, exist_ok=True)
    built_at = datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix=".kb-build-", dir=out_dir) as temp_name:
        temp_dir = Path(temp_name)
        temp_jsonl = temp_dir / "chunks.jsonl"
        temp_db = temp_dir / "knowledge_base.db"
        temp_manifest = temp_dir / "build_manifest.json"
        write_jsonl(chunks, temp_jsonl)
        build_sqlite(
            documents,
            chunks,
            temp_db,
            embedding_model=embedding_model,
            built_at=built_at,
        )
        validate_build(documents, chunks, temp_db)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "built_at_utc": built_at,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "active_chunk_count": sum(int(chunk["is_active"]) for chunk in chunks),
            "embedding_model": embedding_model,
            "sources": [
                {
                    "source_file": doc["source_file"],
                    "sha256": doc["source_sha256"],
                    "is_active": doc["is_active"],
                }
                for doc in documents
            ],
        }
        temp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        jsonl_path = out_dir / "chunks.jsonl"
        db_path = out_dir / "knowledge_base.db"
        manifest_path = out_dir / "build_manifest.json"
        os.replace(temp_jsonl, jsonl_path)
        os.replace(temp_db, db_path)
        os.replace(temp_manifest, manifest_path)

    return documents, chunks, jsonl_path, db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local Markdown knowledge base.")
    parser.add_argument("--docs-dir", type=Path, default=Path("data/docs"))
    parser.add_argument("--out-dir", type=Path, default=Path("kb/artifacts"))
    parser.add_argument("--max-words", type=int, default=450)
    parser.add_argument("--overlap-words", type=int, default=60)
    parser.add_argument(
        "--embedding-model",
        help=(
            "Optional local sentence-transformers model. If omitted, the build remains "
            "lexical-only and fully offline."
        ),
    )
    args = parser.parse_args()

    documents, chunks, jsonl_path, db_path = build_artifacts(
        args.docs_dir,
        args.out_dir,
        max_words=args.max_words,
        overlap_words=args.overlap_words,
        embedding_model=args.embedding_model,
    )
    print(f"Documents: {len(documents)}")
    print(f"Chunks:    {len(chunks)}")
    print(f"JSONL:     {jsonl_path}")
    print(f"SQLite:    {db_path}")
    print(f"Manifest:  {args.out_dir / 'build_manifest.json'}")
    print("\nDocument status:")
    for doc in documents:
        status = "ACTIVE" if doc["is_active"] else "INACTIVE"
        print(
            f"- {doc['doc_id']} version={doc['version'] or 'n/a'}: {status} | "
            f"{doc['source_file']} ({doc['active_reason']})"
        )


if __name__ == "__main__":
    main()
