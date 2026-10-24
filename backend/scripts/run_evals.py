"""Evals that need a real model (so they are not part of the unit suite).

From backend/:
  python -m scripts.run_evals                 # G3: evaluator accuracy on evals/answers.jsonl (needs ANTHROPIC_API_KEY)
  python -m scripts.run_evals --flow          # G9/G10: scripted sessions on evals/sessions.jsonl (needs the ingested DB)
  python -m scripts.run_evals --dry-run ...   # same, with the offline DemoLLM: checks the harness, not the models

G3  = share of answers whose satisfaction is within +/-10 of the labeled score (target >= 80%).
G9  = plan validity 100%, flow coherence >= 4/5, <= 1 abrupt topic jump per interview.
G10 = company relevance (judge) >= 4/5.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Msg, extract_json
from app.agents.evaluator import EvalInput, Evaluator
from app.agents.orchestrator import Orchestrator
from app.agents.planner import validate_plan
from app.agents.schemas import InterviewPlan
from app.config import settings
from app.db.models import Plan
from app.services.retriever import Filters, PoolItem

EVALS = Path(__file__).resolve().parents[1] / "evals"
G3_TOLERANCE, G3_TARGET = 10, 0.8
COHERENCE_TARGET, RELEVANCE_TARGET, ABRUPT_MAX = 4.0, 4.0, 1.0


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- G3: evaluator accuracy -------------------------------------------------------

def g3_summary(results: list[dict]) -> dict:
    within = sum(1 for r in results if abs(r["predicted"] - r["label_score"]) <= G3_TOLERANCE)
    total = len(results)
    rate = within / total if total else 0.0
    return {
        "total": total, "within_10": within, "rate": round(rate, 3), "passed": rate >= G3_TARGET,
        "mean_abs_error": round(statistics.mean(abs(r["predicted"] - r["label_score"]) for r in results), 1) if results else 0,
    }


async def run_answers(llm, limit: int | None = None, path: Path = EVALS / "answers.jsonl") -> dict:
    rows = read_jsonl(path)[:limit]
    evaluator = Evaluator(llm)
    sem = asyncio.Semaphore(4)

    async def one(r: dict) -> dict:
        async with sem:
            ev = await evaluator.run(EvalInput(
                question=r["question"], thread=[Msg("interviewer", r["question"]), Msg("candidate", r["answer"])],
                profile=r["profile"], level=r["level"], topic=r["topic"]))
        return {"id": r["id"], "label": r["label"], "label_score": r["score"], "predicted": ev.satisfaction}

    results = await asyncio.gather(*(one(r) for r in rows))
    return {**g3_summary(results), "misses": [r for r in results if abs(r["predicted"] - r["label_score"]) > G3_TOLERANCE]}


# --- G9 / G10: interview flow ------------------------------------------------------

def _topic_words(topic: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 3}


def abrupt_jumps(topics: list[str], bridged: list[bool]) -> int:
    """Topic changes with no shared word and no bridge between neighbouring questions."""
    count = 0
    for i in range(1, len(topics)):
        if topics[i] == topics[i - 1] or (i < len(bridged) and bridged[i]):
            continue
        if not _topic_words(topics[i]) & _topic_words(topics[i - 1]):
            count += 1
    return count


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def flow_summary(rows: list[dict]) -> dict:
    n = len(rows)
    coherence, relevance = _mean([r["coherence"] for r in rows]), _mean([r["company_relevance"] for r in rows if r.get("company_relevance") is not None])
    abrupt = round(statistics.mean(r["abrupt"] for r in rows), 2) if rows else 0
    plan_valid = sum(r["plan_valid"] for r in rows) / n if n else 0
    return {
        "sessions": n, "plan_valid_rate": round(plan_valid, 3),
        "first_try_rate": round(sum(r["first_try"] for r in rows) / n, 3) if n else 0,
        "coherence": coherence, "company_relevance": relevance, "abrupt_per_interview": abrupt,
        "bridged": sum(r["bridged"] for r in rows),
        "passed": bool(n) and plan_valid == 1.0 and (coherence or 0) >= COHERENCE_TARGET
                  and (relevance is None or relevance >= RELEVANCE_TARGET) and abrupt <= ABRUPT_MAX,
    }


JUDGE = """You are grading a mock technical interview. $what

$context

Questions asked, in order (with the planner's note on how each follows the previous one):
$questions

Reply with JSON only: {"score": <integer 1-5>, "reason": "<one sentence>"}. 5 = excellent, 3 = mixed, 1 = poor."""
COHERENCE_Q = "Rate FLOW COHERENCE: do the questions build naturally from warm-up to a stretch, with related topics next to each other and no abrupt jumps?"
RELEVANCE_Q = "Rate COMPANY RELEVANCE: do these questions feel like questions this company really asks, given its profile?"


async def judge(llm, what: str, context: str, questions: str) -> float | None:
    from string import Template
    raw = await llm.complete(Template(JUDGE).safe_substitute(what=what, context=context, questions=questions),
                             task="judge", model=settings.evaluator_model, max_tokens=300)
    try:
        return float(extract_json(raw)["score"])
    except (ValueError, KeyError, TypeError):
        return None


async def play(orch: Orchestrator, llm, spec: dict) -> str:
    """Run one scripted interview: a Claude-played candidate with the persona and the technologies to mention."""
    reply = await orch.start(Filters(spec["profile"], spec["level"], spec.get("company"), spec.get("topic")))
    asked, mentions = 0, list(spec.get("mentions", []))
    for _ in range(60):
        if reply.done:
            break
        persona = {"strong": "strong", "weak": "weak"}.get(spec["persona"], "strong" if asked % 2 == 0 else "weak")
        mention = f"Naturally mention {mentions.pop(0)} in your answer." if mentions and asked == 0 else ""
        text = await llm.complete(
            f"You are role-playing a candidate in a mock {spec['level']} {spec['profile']} interview.\n"
            f"Persona: {persona} ({'a detailed, correct, trade-off aware answer' if persona == 'strong' else 'a vague, partly wrong answer'}).\n"
            f"Interviewer said: {reply.text}\n{mention}\nAnswer in 2-5 spoken sentences, no markdown.",
            task="candidate", model=settings.cheap_model, max_tokens=300)
        reply = await orch.answer(reply.session_id, text.strip() or "I'm not sure.")
        asked += reply.kind == "ask"
    if not reply.done:
        await orch.end(reply.session_id)
    return reply.session_id


async def run_flow(llm, db: Session, limit: int | None = None, followup_log: Path | str | None = None,
                   path: Path = EVALS / "sessions.jsonl") -> dict:
    out = []
    for spec in read_jsonl(path)[:limit]:
        orch = Orchestrator(db, llm, followup_log=followup_log)
        sid = await play(orch, llm, spec)
        state = orch.load(sid)
        first_plan = InterviewPlan.model_validate_json(
            db.scalar(select(Plan.plan_json).where(Plan.session_id == sid).order_by(Plan.id)))
        filters = Filters(spec["profile"], spec["level"], spec.get("company"), spec.get("topic"))
        valid = not validate_plan(first_plan, [PoolItem(**p) for p in state.pool], filters)
        segs = state.plan.segments
        bridged = [s.link_from_previous.startswith("candidate mentioned") for s in segs]
        questions = "\n".join(f"{i + 1}. [{r.topic}] {r.text} (note: {segs[i].link_from_previous or 'start'})"
                              for i, r in enumerate(state.results))
        coherence = await judge(llm, COHERENCE_Q, f"Level: {spec['level']}, role: {spec['profile']}.", questions)
        relevance = None
        if spec.get("company"):
            relevance = await judge(llm, RELEVANCE_Q, f"Company: {spec['company']}. Profile: {state.company_summary}", questions)
        out.append({
            "id": spec["id"], "plan_valid": valid, "first_try": first_plan.source == "llm" and first_plan.attempts == 1,
            "coherence": coherence, "company_relevance": relevance,
            "abrupt": abrupt_jumps([r.topic for r in state.results], bridged), "bridged": sum(bridged),
        })
    return {**flow_summary(out), "detail": out}


# --- CLI -------------------------------------------------------------------------------

async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--flow", action="store_true", help="run the session evals (G9/G10) instead of the answer evals (G3)")
    p.add_argument("--dry-run", action="store_true", help="use the offline DemoLLM (no API key)")
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    from app.llm.claude_client import ClaudeClient
    from app.llm.fake import DemoLLM
    llm = DemoLLM() if args.dry_run else ClaudeClient()

    if args.flow:
        from app.db.session import make_engine
        with Session(make_engine(settings.database_url)) as db:
            result = await run_flow(llm, db, args.limit, followup_log=EVALS / "flow_followups.jsonl")
    else:
        result = await run_answers(llm, args.limit)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
