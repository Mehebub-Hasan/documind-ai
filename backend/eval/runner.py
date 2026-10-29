"""
RAG Triad evaluation runner.

Runs benchmark cases through DocuMind's real pipeline (FastAPI app
exercised in-process via TestClient: auth, upload, retrieval gate, DeepSeek
generation, attribution verification), then scores each case with the
three LLM-as-a-Judge metrics from metrics.py:

  1. Context Relevance   (retrieval quality)
  2. Groundedness        (faithfulness / hallucination detection)
  3. Answer Relevance    (does the answer address the query)

Datasets (JSON, chosen with --dataset):
  - benchmark_data.json  — starter set against the soil-lab PDF document
  - golden_dataset.json  — 15-case golden set against the electronics-labs
    DOCX, with expected_facts, expected_citations (block ranges) and
    allow_refusal per case.

Deterministic per-case checks (independent of the judges):
  - refusal_ok     allow_refusal cases must refuse; others must not.
  - citations_ok   every expected block range must overlap the sources the
                   pipeline actually cited.
  - facts_matched  ratio of expected_facts covered by the answer (signal
                   only; paraphrase-tolerant token matching, not gated).

With --gate the runner enforces regression thresholds (average groundedness
/ answer relevance / context relevance, plus the deterministic refusal and
citation checks) and exits non-zero on any failure — this is what CI runs.

Outputs: a formatted scoring table on stdout and a detailed JSON report
(default backend/eval/eval_report.json, gitignored).

Usage (from backend/):
    python -m eval.runner
    python -m eval.runner --dataset eval/golden_dataset.json --gate

Requires DEEPSEEK_API_KEY (generation + judging) and requirements-dev.txt
(httpx for the TestClient transport). The benchmark documents and eval user
persist in the configured database and are reused across runs.
"""

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from chatbot import is_refusal_answer
from eval.benchmark_documents import build_document_bytes
from eval.metrics import (
    JUDGE_MODEL,
    JudgeError,
    score_answer_relevance,
    score_context_relevance,
    score_groundedness,
)
from main import app

EVAL_DIR = Path(__file__).resolve().parent

EVAL_USER = {
    "email": "eval@documind.ai",
    "password": "EvalRunner123!",
    "name": "Eval Runner",
}

# Default regression gates (used with --gate). The groundedness floor is the
# hallucination regression gate; context relevance guards retrieval drift.
DEFAULT_GATE = {
    "min_context_relevance": 0.50,
    "min_groundedness": 0.80,
    "min_answer_relevance": 0.70,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Deterministic checks (no judge involvement)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")

FACT_MATCH_THRESHOLD = 0.7  # share of a fact's tokens that must appear


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall(text.lower()))


def facts_matched_ratio(expected_facts: list, answer: str) -> float:
    """
    Share of expected_facts covered by the answer. A fact counts as matched
    when at least FACT_MATCH_THRESHOLD of its tokens appear in the answer
    (paraphrase-tolerant; substring matching would be too brittle).
    """

    if not expected_facts:
        return 1.0

    answer_tokens = _tokens(answer)
    matched = 0

    for fact in expected_facts:
        fact_tokens = _tokens(fact)
        if not fact_tokens:
            matched += 1
            continue

        covered = sum(1 for token in fact_tokens if token in answer_tokens)
        if covered / len(fact_tokens) >= FACT_MATCH_THRESHOLD:
            matched += 1

    return matched / len(expected_facts)


def _parse_range(text: str) -> tuple | None:
    """'Blocks 4-9' -> (4, 9); 'Page 3' -> (3, 3); unparsable -> None."""

    numbers = re.findall(r"\d+", text or "")
    if not numbers:
        return None
    return (int(numbers[0]), int(numbers[-1]))


def sources_to_ranges(sources: list) -> list:
    """Normalize /ask sources (page ints or 'blocks a-b' strings) to ranges."""

    ranges = []

    for source in sources:
        if isinstance(source, (int, float)):
            ranges.append((int(source), int(source)))
        elif isinstance(source, str):
            parsed = _parse_range(source)
            if parsed:
                ranges.append(parsed)

    return ranges


def _ranges_overlap(a: tuple, b: tuple) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def citations_ok(expected_citations: list, sources: list) -> bool | None:
    """
    True when every expected citation range overlaps a cited source range.
    None when the case declares no expected citations (not applicable).
    """

    if not expected_citations:
        return None

    source_ranges = sources_to_ranges(sources)

    for expected in expected_citations:
        expected_range = _parse_range(expected)
        if expected_range is None:
            return False
        if not any(
            _ranges_overlap(expected_range, source_range)
            for source_range in source_ranges
        ):
            return False

    return True


def _judge_confirmed_refusal(metrics: dict | None) -> bool:
    """
    Fallback refusal signal for allow_refusal cases: the model refused in
    its own words (not a standard refusal string) but the judges confirm
    nothing was hallucinated and the answer addresses the query. Only
    available after the judges have run.
    """

    if not metrics:
        return False

    groundedness = metrics.get("groundedness", {})
    relevance = metrics.get("answer_relevance", {})

    return (
        groundedness.get("score", 0.0) >= 0.99
        and not groundedness.get("hallucinated_claims")
        and relevance.get("score", 0.0) >= 0.7
    )


def case_checks(case: dict, pipeline: dict, metrics: dict | None = None) -> dict:
    """Per-case checks. refusal_ok prefers the deterministic string signal
    and falls back to judge confirmation for allow_refusal cases."""

    allow_refusal = case.get("allow_refusal", False)
    refusal_detected = pipeline["refusal_detected"]

    if allow_refusal:
        refusal_ok = refusal_detected or _judge_confirmed_refusal(metrics)
    else:
        refusal_ok = not refusal_detected

    return {
        "refusal_ok": refusal_ok,
        "citations_ok": citations_ok(
            case.get("expected_citations", []), pipeline["sources"]
        ),
        "facts_matched": facts_matched_ratio(
            case.get("expected_facts", []), pipeline["answer"]
        ),
    }


# ---------------------------------------------------------------------------
# Regression gates
# ---------------------------------------------------------------------------

def evaluate_gates(aggregates: dict, results: list, thresholds: dict) -> list:
    """
    Return a list of regression-gate failures (empty = pass). Pure function
    over the aggregates, per-case checks, and the configured thresholds.
    """

    failures = []

    label_by_metric = {
        "context_relevance": "min_context_relevance",
        "groundedness": "min_groundedness",
        "answer_relevance": "min_answer_relevance",
    }

    for metric, threshold_key in label_by_metric.items():
        floor = thresholds.get(threshold_key)
        average = aggregates.get(metric, {}).get("average_score")

        if floor is not None and average is not None and average < floor:
            failures.append(
                f"{threshold_key}: average {average:.2f} < floor {floor:.2f}"
            )

    for case in results:
        checks = case.get("checks", {})

        if checks.get("refusal_ok") is False:
            expected = "refusal" if case.get("allow_refusal") else "an answer"
            failures.append(
                f"{case['id']}: refusal check failed (expected {expected}, "
                f"got {'refusal' if case.get('refusal_detected') else 'an answer'})"
            )

        if checks.get("citations_ok") is False:
            failures.append(
                f"{case['id']}: citation check failed — expected citations "
                f"{case.get('expected_citations')} not covered by sources"
            )

    return failures


# ---------------------------------------------------------------------------
# Pipeline + judging
# ---------------------------------------------------------------------------

def ensure_session(client: TestClient) -> dict:
    """Log in as the eval user, registering the account on first run."""

    login = client.post("/auth/login", json=EVAL_USER)

    if login.status_code == 200:
        token = login.json()["token"]
    else:
        registered = client.post("/auth/register", json=EVAL_USER)
        registered.raise_for_status()
        token = registered.json()["token"]

    return {"Authorization": f"Bearer {token}"}


def ensure_document(client: TestClient, headers: dict, document_key: str) -> tuple:
    """
    Reuse the benchmark document if present; otherwise build and upload it.
    Returns (document_id, filename).
    """

    filename, content, content_type = build_document_bytes(document_key)

    listed = client.get("/documents", headers=headers).json()

    for document in listed.get("documents", []):
        if document["filename"] == filename:
            return document["document_id"], filename

    endpoint = "/upload-docx" if filename.lower().endswith(".docx") else "/upload-pdf"
    uploaded = client.post(
        endpoint,
        files={"file": (filename, content, content_type)},
        headers=headers,
    )
    uploaded.raise_for_status()

    return uploaded.json()["document_id"], filename


def run_pipeline(client: TestClient, headers: dict, document_id: str, case: dict) -> dict:
    """Drive one benchmark case through the real /ask pipeline."""

    response = client.post(
        "/ask",
        json={
            "document_id": document_id,
            "question": case["question"],
            "top_k": case.get("top_k", 6),
        },
        headers=headers,
    )
    response.raise_for_status()

    data = response.json()
    answer = data.get("answer", "")

    return {
        "answer": answer,
        "sources": data.get("sources", []),
        "retrieved_chunks": data.get("retrieved_chunks", []),
        "pipeline_grounded": data.get("grounded"),
        "verification": data.get("verification"),
        "top_retrieval_score": (
            data["retrieved_chunks"][0]["score"]
            if data.get("retrieved_chunks")
            else None
        ),
        "refusal_detected": is_refusal_answer(answer),
    }


def normalize_case(raw: dict) -> dict:
    """
    Accept both dataset schemas: golden entries use allow_refusal /
    expected_facts / expected_citations; the starter set uses expected_refusal.
    """

    return {
        "id": raw["id"],
        "category": raw.get("category", "uncategorized"),
        "question": raw["question"],
        "allow_refusal": bool(
            raw.get("allow_refusal", raw.get("expected_refusal", False))
        ),
        "expected_facts": raw.get("expected_facts", []),
        "expected_citations": raw.get("expected_citations", []),
        "top_k": raw.get("top_k", 6),
    }


def evaluate_case(case: dict, pipeline: dict) -> dict:
    """Run the three judges, then the per-case checks (the refusal fallback
    consults the judges, so checks run last)."""

    metric_specs = [
        (
            "context_relevance",
            lambda: score_context_relevance(
                case["question"], pipeline["retrieved_chunks"]
            ),
        ),
        (
            "groundedness",
            lambda: score_groundedness(
                pipeline["retrieved_chunks"], pipeline["answer"]
            ),
        ),
        (
            "answer_relevance",
            lambda: score_answer_relevance(
                case["question"],
                pipeline["answer"],
                expected_refusal=case["allow_refusal"],
            ),
        ),
    ]

    metrics = {}

    for name, judge in metric_specs:
        try:
            metrics[name] = judge()
        except JudgeError as exc:
            metrics[name] = {"error": str(exc)}

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "allow_refusal": case["allow_refusal"],
        "refusal_detected": pipeline["refusal_detected"],
        "top_retrieval_score": pipeline["top_retrieval_score"],
        "answer": pipeline["answer"],
        "checks": case_checks(case, pipeline, metrics),
        "expected_facts": case["expected_facts"],
        "expected_citations": case["expected_citations"],
        "metrics": metrics,
    }


def aggregate_results(results: list) -> dict:
    """Average each metric across cases where the judge produced a score."""

    aggregates = {}

    for metric in ("context_relevance", "groundedness", "answer_relevance"):
        scores = [
            case["metrics"][metric]["score"]
            for case in results
            if metric in case["metrics"]
            and "score" in case["metrics"][metric]
        ]

        aggregates[metric] = (
            {
                "average_score": round(statistics.mean(scores), 4),
                "cases_scored": len(scores),
            }
            if scores
            else {"average_score": None, "cases_scored": 0}
        )

    return aggregates


def render_table(results: list, aggregates: dict) -> str:
    """Plain-text scoring table (no external dependency)."""

    header = (
        f"{'ID':<16}{'Category':<24}{'CtxRel':>8}{'Ground':>8}"
        f"{'AnsRel':>8}{'Cit':>5}{'Facts':>7}{'Refusal':>9}"
    )
    lines = ["", "=" * 85, "RAG TRIAD EVALUATION REPORT", "=" * 85, header, "-" * 85]

    def check_cell(value):
        if value is None:
            return f"{'–':>5}"
        return f"{'ok' if value else 'FAIL':>5}"

    for case in results:
        cells = []

        for metric in ("context_relevance", "groundedness", "answer_relevance"):
            value = case["metrics"].get(metric, {})
            cells.append(f"{value['score']:>8.2f}" if "score" in value else f"{'ERR':>8}")

        checks = case.get("checks", {})
        facts = checks.get("facts_matched")

        lines.append(
            f"{case['id']:<16}{case['category']:<24}{cells[0]}{cells[1]}{cells[2]}"
            f"{check_cell(checks.get('citations_ok'))}"
            f"{f'{facts:>7.2f}' if isinstance(facts, float) else f'{chr(8211):>7}'}"
            f"{'yes' if case.get('refusal_detected') else '-':>9}"
        )

    lines.append("-" * 85)

    def avg(metric):
        value = aggregates[metric]["average_score"]
        return f"{value:>8.2f}" if value is not None else f"{'n/a':>8}"

    lines.append(
        f"{'AVERAGE':<40}{avg('context_relevance')}{avg('groundedness')}{avg('answer_relevance')}"
    )
    lines.append("=" * 85)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RAG Triad evaluation.")
    parser.add_argument(
        "--dataset",
        default=str(EVAL_DIR / "benchmark_data.json"),
        help="Path to a dataset JSON (benchmark_data.json or golden_dataset.json).",
    )
    parser.add_argument(
        "--output",
        default=str(EVAL_DIR / "eval_report.json"),
        help="Path for the detailed JSON report.",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Enforce regression gates and exit non-zero on failure.",
    )
    parser.add_argument("--min-context-relevance", type=float, default=None)
    parser.add_argument("--min-groundedness", type=float, default=None)
    parser.add_argument("--min-answer-relevance", type=float, default=None)
    args = parser.parse_args()

    thresholds = dict(DEFAULT_GATE)
    for key in ("min_context_relevance", "min_groundedness", "min_answer_relevance"):
        override = getattr(args, key)
        if override is not None:
            thresholds[key] = override

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    document_key = dataset.get("document", "soil_lab")
    cases = [normalize_case(raw) for raw in dataset["cases"]]

    started_at = _now_iso()
    print(f"RAG Triad evaluation — {len(cases)} cases, judge: {JUDGE_MODEL}")
    print(f"Dataset: {dataset_path.name} | document: {document_key}")

    with TestClient(app) as client:
        headers = ensure_session(client)
        document_id, filename = ensure_document(client, headers, document_key)
        print(f"Benchmark document: {filename} ({document_id})")

        results = []

        for index, case in enumerate(cases, start=1):
            print(
                f"[{index}/{len(cases)}] {case['id']}: {case['question'][:60]}…",
                flush=True,
            )
            pipeline = run_pipeline(client, headers, document_id, case)
            results.append(evaluate_case(case, pipeline))

    aggregates = aggregate_results(results)

    report = {
        "started_at": started_at,
        "finished_at": _now_iso(),
        "generator_model": "deepseek-chat",
        "judge_model": JUDGE_MODEL,
        "dataset": dataset_path.name,
        "benchmark_document": filename,
        "document_id": document_id,
        "num_cases": len(cases),
        "aggregate_scores": aggregates,
        "results": results,
    }

    gate_failures = evaluate_gates(aggregates, results, thresholds) if args.gate else []
    report["gate"] = {
        "enabled": args.gate,
        "thresholds": thresholds,
        "failures": gate_failures,
    }

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(render_table(results, aggregates))

    if gate_failures:
        print("\nREGRESSION GATE FAILURES:")
        for failure in gate_failures:
            print(f"  ✗ {failure}")
    else:
        print(f"\nDetailed report written to: {output_path}")

    failed_judges = sum(
        1
        for case in results
        for metric in case["metrics"].values()
        if "error" in metric
    )
    if failed_judges:
        print(f"WARNING: {failed_judges} judge call(s) failed — see report.")
        return 1

    if args.gate and gate_failures:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
