import json
from pathlib import Path

from scripts.run_evals import accuracy_within, load_answers

EVALS = Path(__file__).resolve().parents[1] / "evals" / "answers.jsonl"


def test_accuracy_within_tolerance():
    pairs = [(80, 85), (50, 75), (10, 0), (90, 70)]
    assert accuracy_within(pairs, tol=10) == 0.5
    assert accuracy_within([], tol=10) == 0.0


def test_answers_file_is_well_formed_and_balanced():
    rows = load_answers(EVALS)
    assert len(rows) >= 30
    assert {r["label"] for r in rows} == {"strong", "partial", "weak"}
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(0 <= r["score"] <= 100 and r["answer"] and r["question"] for r in rows)
    assert len({r["level"] for r in rows}) >= 4
