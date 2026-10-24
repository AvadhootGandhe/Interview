"""Evaluator consistency eval (goal G3): satisfaction within +/-10 of the labeled score for >= 80% of answers.

    ANTHROPIC_API_KEY=... python scripts/run_evals.py [--json]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVALS = Path(__file__).resolve().parents[1] / "evals" / "answers.jsonl"
TOLERANCE = 10
TARGET = 0.8


def load_answers(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def accuracy_within(pairs: list[tuple[int, int]], tol: int = TOLERANCE) -> float:
    """Share of (label, predicted) pairs whose scores differ by at most tol."""
    return sum(abs(a - b) <= tol for a, b in pairs) / len(pairs) if pairs else 0.0


async def run(path: Path) -> dict:
    from app.agents.evaluator import evaluate
    from app.llm.claude_client import ClaudeClient

    llm, rows, pairs, misses = ClaudeClient(), load_answers(path), [], []
    sem = asyncio.Semaphore(5)

    async def one(r):
        async with sem:
            ev = await evaluate(llm, r["profile"], r["level"], [(r["question"], r["answer"])])
            return r, ev.satisfaction

    for r, predicted in await asyncio.gather(*(one(r) for r in rows)):
        pairs.append((r["score"], predicted))
        if abs(r["score"] - predicted) > TOLERANCE:
            misses.append({"id": r["id"], "label": r["score"], "predicted": predicted})
    acc = accuracy_within(pairs)
    return {"g3_accuracy": round(acc, 3), "target": TARGET, "passed": acc >= TARGET, "n": len(pairs), "misses": misses}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", type=Path, default=EVALS)
    args = ap.parse_args()
    result = asyncio.run(run(args.path))
    print(json.dumps(result, indent=2) if args.json else
          f"G3 accuracy {result['g3_accuracy']:.0%} over {result['n']} answers (target {TARGET:.0%}): "
          f"{'PASS' if result['passed'] else 'FAIL'}")
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
