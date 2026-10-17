"""Evaluate retrieval quality: Recall@3 on data/eval/test-queries.json.

Run from the repository root (Qdrant must be running and the collection loaded):

    uv run --project services/api python -m data.eval.evaluate_retrieval

It also reads data/eval/out-of-scope-queries.json to show how high irrelevant questions
score, which is the evidence used to choose ``min_score`` (see docs/rag/rag-design.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from data.pipelines.rag import DEFAULT_MIN_SCORE, DEFAULT_TOP_K, retrieve

EVAL_DIR = Path(__file__).resolve().parent
TARGET_RECALL = 0.8


def _load(file_name: str) -> list[dict]:
    return json.loads((EVAL_DIR / file_name).read_text(encoding="utf-8"))


def _is_expected(chunk: dict, item: dict) -> bool:
    return (
        chunk["source_document"] == item["expected_source_document"]
        and chunk["chunk_index"] == item["expected_chunk_index"]
    )


def main() -> int:
    questions = _load("test-queries.json")
    out_of_scope = _load("out-of-scope-queries.json")

    # --- 1. Recall@3 -----------------------------------------------------------
    # Retrieve WITHOUT a score filter so the metric measures ranking quality only;
    # the min_score filter is applied afterwards on the same results (one embedding
    # call per question).
    hits = 0
    hits_after_filter = 0
    expected_scores: list[float] = []
    print(f"Recall@{DEFAULT_TOP_K} (ranking only, no score filter)\n")
    for item in questions:
        results = retrieve(item["question"], k=DEFAULT_TOP_K, min_score=-1.0)
        match = next((chunk for chunk in results if _is_expected(chunk, item)), None)
        if match:
            hits += 1
            expected_scores.append(match["score"])
            if match["score"] >= DEFAULT_MIN_SCORE:
                hits_after_filter += 1
        status = "HIT " if match else "MISS"
        found = f"{match['score']:.4f}" if match else "  -   "
        top = results[0]
        print(
            f"  {status} {item['id']}  expected {item['expected_source_document']}#{item['expected_chunk_index']}"
            f" score {found} | top1 {top['source_document']}#{top['chunk_index']} {top['score']:.4f}"
        )

    total = len(questions)
    recall = hits / total
    recall_filtered = hits_after_filter / total
    print(f"\nRecall@{DEFAULT_TOP_K} = {hits}/{total} = {recall:.0%}   (target >= {TARGET_RECALL:.0%})")
    print(f"Recall@{DEFAULT_TOP_K} with min_score={DEFAULT_MIN_SCORE} = {hits_after_filter}/{total} = {recall_filtered:.0%}")
    print(f"Lowest score of a correct chunk: {min(expected_scores):.4f}")

    # --- 2. Out-of-scope questions ---------------------------------------------
    print("\nOut-of-scope questions (best score of any chunk)\n")
    best_by_kind: dict[str, float] = {}
    refused = 0
    for item in out_of_scope:
        top = retrieve(item["question"], k=1, min_score=-1.0)[0]
        best_by_kind[item["kind"]] = max(best_by_kind.get(item["kind"], -1.0), top["score"])
        rejected = top["score"] < DEFAULT_MIN_SCORE
        refused += rejected
        print(f"  {top['score']:.4f}  {item['kind']:<11}  {'refused' if rejected else 'ANSWERED'}  {item['question']}")
    print(f"\nRefused at min_score={DEFAULT_MIN_SCORE}: {refused}/{len(out_of_scope)}")
    for kind, score in best_by_kind.items():
        print(f"Highest {kind} score: {score:.4f}")

    return 0 if recall_filtered >= TARGET_RECALL else 1


if __name__ == "__main__":
    sys.exit(main())