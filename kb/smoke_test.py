from __future__ import annotations

import sqlite3
from pathlib import Path

from evaluate_kb import run_evaluation
from search_kb import KnowledgeBase


DB_PATH = Path("kb/artifacts/knowledge_base.db")
EVAL_PATH = Path("kb/eval_questions.json")


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError("Run build_kb.py first.")

    conn = sqlite3.connect(DB_PATH)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        active_fts_count = conn.execute(
            "SELECT COUNT(*) FROM active_chunks_fts"
        ).fetchone()[0]
        all_fts_count = conn.execute("SELECT COUNT(*) FROM all_chunks_fts").fetchone()[0]
        pol01 = conn.execute(
            """
            SELECT version, is_active
            FROM documents
            WHERE doc_id = 'POL-01'
            ORDER BY version
            """
        ).fetchall()
    finally:
        conn.close()

    assert integrity == "ok", integrity
    assert document_count == 8, document_count
    assert chunk_count == 22, chunk_count
    assert active_fts_count == 20, active_fts_count
    assert all_fts_count == 22, all_fts_count
    assert pol01 == [("1.0", 0), ("2.0", 1)], pol01

    kb = KnowledgeBase(DB_PATH)
    backup_results = kb.search("Backup được lưu giữ bao nhiêu ngày?", top_k=3)
    assert backup_results[0]["doc_id"] == "POL-01"
    assert backup_results[0]["version"] == "2.0"
    assert all(result["version"] != "1.0" for result in backup_results)

    report = run_evaluation(DB_PATH, EVAL_PATH)
    assert report["passed"] == report["total"], report

    print("Smoke test passed.")
    print(f"- documents: {document_count}")
    print(f"- chunks: {chunk_count} ({active_fts_count} active-indexed)")
    print("- POL-01 v1 inactive, v2 active")
    print(
        f"- evaluation: {report['passed']}/{report['total']} "
        f"passed, MRR={report['mrr']:.3f}"
    )


if __name__ == "__main__":
    main()
