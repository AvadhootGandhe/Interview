"""Run an interview in the terminal (text only).

From backend/ (needs ANTHROPIC_API_KEY, or FAKE_LLM=1 for the offline demo model):
  python -m scripts.text_interview --profile Backend --level SDE-2/3 --company Amazon [--topic Caching]
Type an answer and press Enter. /end finishes early. Add --debug to see scores and flow decisions.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.orm import Session

from app.agents.orchestrator import Orchestrator, Reply
from app.agents.reporter import Report
from app.config import settings
from app.db.session import make_engine
from app.llm.factory import get_llm
from app.services.retriever import Filters


def show(reply: Reply, debug: bool) -> None:
    print(f"\nInterviewer: {reply.text}")
    if debug and reply.evaluation:
        ev = reply.evaluation
        print(f"  [satisfaction {ev.satisfaction} | missing {ev.missing_points} | mentioned {ev.mentioned_terms}]")


def show_report(report: Report) -> None:
    print(f"\n=== Report: {report.overall_score}/100 ===\n{report.verdict}")
    for q in report.questions:
        print(f"  {q.final_score:>3}  {q.text}  ({q.follow_ups} follow-ups)")
    print("Strengths:\n  - " + "\n  - ".join(report.strengths or ["-"]))
    print("Gaps:\n  - " + "\n  - ".join(report.gaps or ["-"]))


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default="Backend")
    p.add_argument("--level", default="SDE-2/3")
    p.add_argument("--company")
    p.add_argument("--topic")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    engine = make_engine(settings.database_url)
    with Session(engine) as db:
        orch = Orchestrator(db, get_llm())
        reply = await orch.start(Filters(args.profile, args.level, args.company, args.topic))
        show(reply, args.debug)
        while not reply.done:
            try:
                text = input("\nYou: ").strip()
            except EOFError:
                text = "/end"
            if not text:
                continue
            reply = await (orch.end(reply.session_id) if text == "/end" else orch.answer(reply.session_id, text))
            show(reply, args.debug)
        show_report(await orch.report(reply.session_id))


if __name__ == "__main__":
    asyncio.run(main())
