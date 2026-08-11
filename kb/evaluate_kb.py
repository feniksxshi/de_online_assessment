from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from search_kb import KnowledgeBase, normalize_text


def evaluate_case(kb: KnowledgeBase, case: dict[str, Any], top_k: int) -> dict[str, Any]:
    results = kb.search(case["question"], top_k=top_k)
    if case.get("expect_no_results"):
        passed = not results
        return {
            "id": case["id"],
            "passed": passed,
            "rank": None,
            "reason": "no results" if passed else f"unexpected source {results[0]['doc_id']}",
        }

    expected_docs = set(case["expected_doc_ids"])
    matching_ranks = [
        rank
        for rank, result in enumerate(results, start=1)
        if result["doc_id"] in expected_docs
        and (
            case.get("expected_version") is None
            or result["version"] == case["expected_version"]
        )
    ]
    rank = min(matching_ranks) if matching_ranks else None
    max_rank = int(case.get("max_rank", top_k))
    source_ok = rank is not None and rank <= max_rank

    matching_content = "\n".join(
        result["content"]
        for result in results
        if result["doc_id"] in expected_docs
        and (
            case.get("expected_version") is None
            or result["version"] == case["expected_version"]
        )
    )
    normalized_content = normalize_text(matching_content)
    terms_ok = all(
        normalize_text(term) in normalized_content for term in case.get("expected_terms", [])
    )
    forbidden = set(case.get("forbidden_versions", []))
    freshness_ok = not any(result["version"] in forbidden for result in results)
    passed = source_ok and terms_ok and freshness_ok
    reasons = []
    if not source_ok:
        reasons.append(f"expected source not within rank {max_rank}")
    if not terms_ok:
        reasons.append("expected answer terms missing")
    if not freshness_ok:
        reasons.append("inactive/forbidden version leaked")
    return {
        "id": case["id"],
        "passed": passed,
        "rank": rank,
        "reason": "; ".join(reasons) if reasons else "ok",
    }


def run_evaluation(db_path: Path, eval_path: Path, top_k: int = 5) -> dict[str, Any]:
    cases = json.loads(eval_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation file must contain a non-empty JSON list")
    kb = KnowledgeBase(db_path)
    results = [evaluate_case(kb, case, top_k) for case in cases]
    answerable_results = [
        result
        for case, result in zip(cases, results)
        if not case.get("expect_no_results")
    ]
    reciprocal_rank = sum(
        1 / result["rank"] if result["rank"] is not None else 0
        for result in answerable_results
    ) / max(1, len(answerable_results))
    return {
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
        "pass_rate": sum(result["passed"] for result in results) / len(results),
        "mrr": reciprocal_rank,
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KB retrieval regression evaluation.")
    parser.add_argument("--db", type=Path, default=Path("kb/artifacts/knowledge_base.db"))
    parser.add_argument(
        "--eval", type=Path, default=Path("kb/eval_questions.json")
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    report = run_evaluation(args.db, args.eval, top_k=args.top_k)
    for case in report["cases"]:
        marker = "PASS" if case["passed"] else "FAIL"
        rank = f" rank={case['rank']}" if case["rank"] is not None else ""
        print(f"[{marker}] {case['id']}{rank}: {case['reason']}")
    print(
        f"\nPassed {report['passed']}/{report['total']} "
        f"({report['pass_rate']:.1%}); MRR={report['mrr']:.3f}"
    )
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
