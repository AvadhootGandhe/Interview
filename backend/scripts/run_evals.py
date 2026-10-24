"""Run the quality evals.

    python scripts/run_evals.py                 # G3: evaluator agreement on evals/answers.jsonl (needs ANTHROPIC_API_KEY)
    python scripts/run_evals.py --flow          # G9/G10: plan validity, flow coherence, company relevance, abrupt jumps
    python scripts/run_evals.py --fake --flow   # same plumbing on the offline fake (no key, judges skipped)
    python scripts/run_evals.py --json          # machine-readable output

Exit code 0 only when every check that could be computed passes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.base import complete_validated  # noqa: E402
from app.agents.evaluator import EvalContext, Evaluator, ThreadTurn  # noqa: E402
from app.agents.orchestrator import Orchestrator  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.retriever import Filters  # noqa: E402

EVALS = Path(__file__).resolve().parents[1] / "evals"
AGREEMENT_BAND = 10  # G3: satisfaction within +-10 of the label


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- G3: evaluator agreement --------------------------------------------------

async def eval_answers(llm, rows: list[dict]) -> dict:
    evaluator = Evaluator(llm)
    per_label: dict[str, list[bool]] = {}
    agree, follow, failures = [], [], 0
    for r in rows:
        ctx = EvalContext(r["question"], [ThreadTurn("candidate", r["answer"])], r["level"], r.get("profile"), r.get("topic"))
        try:
            ev = await evaluator.run(ctx)
        except Exception:
            failures += 1
            agree.append(False)
            follow.append(False)
            per_label.setdefault(r["label"], []).append(False)
            continue
        ok = abs(ev.satisfaction - r["satisfaction"]) <= AGREEMENT_BAND
        agree.append(ok)
        follow.append((ev.satisfaction < settings.satisfaction_threshold) == r["should_follow_up"])
        per_label.setdefault(r["label"], []).append(ok)
    n = len(rows)
    return {
        "n": n, "failures": failures,
        "g3_agreement": sum(agree) / n if n else 0.0,
        "followup_accuracy": sum(follow) / n if n else 0.0,
        "by_label": {k: {"n": len(v), "agreement": sum(v) / len(v)} for k, v in per_label.items()},
    }


def check_answers(m: dict) -> dict[str, bool]:
    return {"g3_agreement >= 0.8": m["g3_agreement"] >= 0.8, "followup_accuracy >= 0.9": m["followup_accuracy"] >= 0.9}


# --- G9 / G10: interview flow ---------------------------------------------------

class Judgement(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = ""


CANNED = {
    "strong": "I would explain the core idea, then the trade-offs, failure modes and how I would measure and monitor it in production. " * 3,
    "partial": "I think it works by keeping the main data close to where it is used, which should make things faster in most cases.",
    "weak": "I am not sure about this one.",
}


async def candidate_answer(llm, quality: str, question: str, mention: str | None, offline: bool) -> str:
    if offline:
        text = CANNED[quality]
    else:
        style = {
            "strong": "a strong, complete, specific answer with trade-offs",
            "partial": "a partial answer that gets the basics right but misses important depth",
            "weak": "a weak, vague answer that shows the candidate does not really know",
        }[quality]
        text = await llm.complete(
            f"You are role-playing a job candidate in a spoken interview. Question: {question}\n"
            f"Reply in 2 to 5 sentences with {style}. Plain spoken text only.",
            task="candidate", max_tokens=400,
        )
    return f"{text} I would use {mention} for that." if mention else text


async def _judge(judge, kind: str, transcript: str, company: str | None) -> int | None:
    if judge is None:
        return None
    what = (
        "Do the questions build naturally from one to the next, like a real interview that goes from warm-up to harder "
        "material with related topics next to each other? (1 = random jumps, 5 = flows very well)"
        if kind == "coherence" else
        f"Do these questions feel like what {company or 'a typical tech company'} would really ask, in its style and "
        "focus? (1 = generic or off, 5 = very characteristic)"
    )
    j = await complete_validated(
        judge, f"You are judging a mock interview.\n{what}\n\nInterview questions in order:\n{transcript}\n\n"
        'Return only JSON: {"score": 1-5, "reason": "one sentence"}', Judgement, task="judge",
    )
    return j.score


async def run_session(db: Session, llm, s: dict, offline: bool) -> dict:
    o = Orchestrator(db, llm)
    start = await o.start(Filters(profile=s["profile"], level=s["level"], company=s["company"], topic=s["topic"]))
    sid, script, asked, i = start.session_id, s["script"], 0, 0
    first_try = not o.planner.used_fallback
    result = None
    while True:
        snap = o.snapshot(sid)
        step = script[min(i, len(script) - 1)]
        answer = await candidate_answer(llm, step["quality"], snap["current_question"]["text"], step.get("mention"), offline)
        result = await o.answer(sid, answer)
        if result.kind != "follow_up":
            i += 1
        asked += 1
        if result.done or asked > 60:
            break
    snap = o.snapshot(sid)
    segs = snap["plan"]["segments"][: len(snap["finals"])]
    pool = {p["id"]: p for p in snap["pool"]}
    jumps = sum(
        1 for a, b in zip(segs, segs[1:])
        if a["topic"] != b["topic"] and not b["link_from_previous"] and not b.get("bridge")
    )
    return {
        "id": s["id"], "company": s["company"], "questions": len(snap["finals"]), "first_try": first_try,
        "abrupt_jumps": jumps, "bridges": sum(1 for g in segs if g.get("bridge")),
        "questions_text": [pool[g["seed_question_id"]]["text"] for g in segs],
        "topics": [g["topic"] for g in segs],
    }


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


async def eval_flow(db: Session, llm, sessions: list[dict], judge=None, offline: bool = True) -> dict:
    out, coherence, relevance = [], [], []
    for s in sessions:
        r = await run_session(db, llm, s, offline)
        transcript = "\n".join(f"{n}. [{t}] {q}" for n, (t, q) in enumerate(zip(r["topics"], r["questions_text"]), 1))
        coherence.append(await _judge(judge, "coherence", transcript, s["company"]))
        relevance.append(await _judge(judge, "relevance", transcript, s["company"]))
        r["coherence"], r["company_relevance"] = coherence[-1], relevance[-1]
        out.append(r)
    n = len(out)
    return {
        "n": n,
        "plan_first_try": sum(r["first_try"] for r in out) / n if n else 0.0,
        "plan_valid_after_fallback": 1.0 if n else 0.0,  # every session got a validated plan, else start() raised
        "abrupt_jumps_avg": round(sum(r["abrupt_jumps"] for r in out) / n, 2) if n else 0.0,
        "coherence_avg": _avg(coherence), "company_relevance_avg": _avg(relevance),
        "pool_hit_rate_bridges": sum(r["bridges"] for r in out),
        "sessions": out,
    }


def check_flow(m: dict) -> dict[str, bool]:
    checks = {
        "plan_first_try >= 0.9": m["plan_first_try"] >= 0.9,
        "plan_valid_after_fallback == 1.0": m["plan_valid_after_fallback"] == 1.0,
        "abrupt_jumps_avg <= 1": m["abrupt_jumps_avg"] <= 1,
    }
    if m["coherence_avg"] is not None:
        checks["coherence_avg >= 4.0"] = m["coherence_avg"] >= 4.0
    if m["company_relevance_avg"] is not None:
        checks["company_relevance_avg >= 4.0"] = m["company_relevance_avg"] >= 4.0
    return checks


# --- CLI -------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flow", action="store_true", help="G9/G10 on evals/sessions.jsonl instead of G3")
    ap.add_argument("--fake", action="store_true", help="offline fake LLM; judges are skipped")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=settings.database_url)
    ap.add_argument("--limit", type=int, default=0, help="only the first N rows")
    args = ap.parse_args(argv)

    if args.fake:
        from app.llm.fake_llm import DeterministicFakeLLM

        llm, judge = DeterministicFakeLLM(), None
    else:
        from app.llm.claude_client import ClaudeClient

        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY is not set. Use --fake for an offline plumbing check.", file=sys.stderr)
            return 2
        llm = judge = ClaudeClient()

    if args.flow:
        from app.db.session import make_engine

        sessions = load_jsonl(EVALS / "sessions.jsonl")[: args.limit or None]
        with Session(make_engine(args.db)) as db:
            metrics = asyncio.run(eval_flow(db, llm, sessions, judge=judge, offline=args.fake))
        checks = check_flow(metrics)
    else:
        rows = load_jsonl(EVALS / "answers.jsonl")[: args.limit or None]
        metrics = asyncio.run(eval_answers(llm, rows))
        checks = check_answers(metrics)

    if args.json:
        print(json.dumps({"metrics": metrics, "checks": checks}, indent=2))
    else:
        for k, v in metrics.items():
            if k != "sessions":
                print(f"{k}: {v}")
        for name, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
