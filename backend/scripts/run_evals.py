"""Evals (need ANTHROPIC_API_KEY).

    python scripts/run_evals.py [--json]          G3: evaluator within +/-10 of the labeled score for >= 80%
    python scripts/run_evals.py --flow [--json]   G9/G10: plan validity, flow coherence, company relevance, topic jumps
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVALS = Path(__file__).resolve().parents[1] / "evals" / "answers.jsonl"
SESSIONS = Path(__file__).resolve().parents[1] / "evals" / "sessions.jsonl"
TOLERANCE = 10
TARGET = 0.8


def load_answers(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def accuracy_within(pairs: list[tuple[int, int]], tol: int = TOLERANCE) -> float:
    """Share of (label, predicted) pairs whose scores differ by at most tol."""
    return sum(abs(a - b) <= tol for a, b in pairs) / len(pairs) if pairs else 0.0


def count_topic_jumps(topics: list[str]) -> int:
    return sum(a != b for a, b in zip(topics, topics[1:]))


CANDIDATE = ("You are role-playing a job candidate in a spoken interview. Answer as a {quality} candidate would "
             "in 2-4 sentences, plain speech.\nStrong = accurate, specific, mentions trade-offs. Weak = vague or "
             "partly wrong. Mixed = correct basics, little depth.\nQuestion: {question}")
COHERENCE = ("Rate 1-5 how naturally these interview questions build on each other (warm-up to harder, related "
             "topics adjacent, no abrupt jumps). Reply with one digit only.\n{questions}")
RELEVANCE = ("Rate 1-5 how much these interview questions feel like what {company} asks {profile} candidates "
             "at {level} level. Reply with one digit only.\n{questions}")


def _digit(text: str, default: int = 1) -> int:
    return next((int(c) for c in text if c in "12345"), default)


async def run_flow(engine, llm, generator, judge, sessions: list[dict]) -> dict:
    """Run scripted candidate sessions end to end and measure plan validity, flow and company relevance."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.agents.orchestrator import Orchestrator
    from app.agents.planner import InterviewPlan, validate_plan
    from app.db import models as m
    from app.services.context_pack import ContextPack
    from app.services.retriever import Filters, PoolItem

    orch = Orchestrator(engine, llm, generator, followup_log=None)
    valid, jumps, coherence, relevance, shares = [], [], [], [], []
    for sc in sessions:
        f = Filters(sc["profile"], sc["level"], sc.get("company"), sc.get("topic"))
        started = await orch.start(f, seed=1)
        question, reply_state, turn = started.messages[-1], "active", 0
        while reply_state != "done" and turn < 12:
            quality = sc["quality"][turn % len(sc["quality"])]
            answer = await llm.complete(CANDIDATE.format(quality=quality, question=question), max_tokens=200)
            reply = await orch.answer(started.session_id, answer)
            question, reply_state, turn = reply.messages[-1], reply.state, turn + 1
        with Session(engine) as db:
            s = db.get(m.InterviewSession, started.session_id)
            pool = [PoolItem(**p) for p in __import__("json").loads(s.pool_json)]
            plan = InterviewPlan.model_validate_json(db.scalars(
                select(m.Plan).where(m.Plan.session_id == s.id).order_by(m.Plan.version.desc())).first().plan_json)
            asked = [t.text for t in db.scalars(select(m.Turn).where(
                m.Turn.session_id == s.id, m.Turn.kind == "ask").order_by(m.Turn.id))]
        pack = ContextPack(f, None, "", pool)  # type: ignore[arg-type]
        valid.append(not validate_plan(plan, pack))
        jumps.append(count_topic_jumps([seg.topic for seg in plan.segments]))
        shares.append(sum(p.company_specific for p in pool) / len(pool) if pool and f.company else 1.0)
        numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(asked))
        coherence.append(_digit(await judge.complete(COHERENCE.format(questions=numbered), max_tokens=5)))
        if f.company:
            relevance.append(_digit(await judge.complete(RELEVANCE.format(
                company=f.company, profile=f.profile, level=f.level, questions=numbered), max_tokens=5)))

    mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else 0.0  # noqa: E731
    result = {"n": len(sessions), "plan_validity": mean([float(v) for v in valid]),
              "flow_coherence": mean(coherence), "company_relevance": mean(relevance),
              "avg_topic_jumps": mean(jumps), "g10_company_pool_share": mean(shares)}
    # avg_topic_jumps is informational: "abrupt" needs topic relatedness, which the coherence judge covers.
    result["passed"] = (result["plan_validity"] == 1.0 and result["flow_coherence"] >= 4.0
                        and result["company_relevance"] >= 4.0 and result["g10_company_pool_share"] >= 0.7)
    return result


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


def main_flow(as_json: bool) -> None:
    from app.agents.question_generator import QuestionGenerator
    from app.config import settings
    from app.db.session import make_engine
    from app.llm.claude_client import ClaudeClient
    from app.llm.local_client import LocalClient

    llm = ClaudeClient()
    result = asyncio.run(run_flow(make_engine(), llm, QuestionGenerator(LocalClient(settings.llama_server_url)),
                                  llm, load_answers(SESSIONS)))
    print(json.dumps(result, indent=2) if as_json else result)
    sys.exit(0 if result["passed"] else 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", type=Path, default=EVALS)
    args = ap.parse_args()
    if args.flow:
        return main_flow(args.json)
    result = asyncio.run(run(args.path))
    print(json.dumps(result, indent=2) if args.json else
          f"G3 accuracy {result['g3_accuracy']:.0%} over {result['n']} answers (target {TARGET:.0%}): "
          f"{'PASS' if result['passed'] else 'FAIL'}")
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
