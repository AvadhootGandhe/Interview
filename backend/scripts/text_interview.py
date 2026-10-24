"""A mock interview in the terminal (text answers).

    python scripts/text_interview.py --profile Backend --level SDE-2/3 --company Amazon
    python scripts/text_interview.py --profile Backend --level SDE-1 --fake     # offline, no API key

Type your answer and press Enter. Type /end to finish early.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.agents.orchestrator import Orchestrator  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.retriever import Filters  # noqa: E402


async def run(args, input_fn: Callable[[str], str], out: Callable[[str], None]) -> int:
    from app.db.session import make_engine
    from app.llm.claude_client import LLMError
    from app.llm.factory import make_llm

    if args.fake:
        settings.fake_llm = True
    engine = make_engine(args.db)
    generator = None
    if not settings.fake_llm:
        from app.api.sessions import get_generator

        generator = get_generator()
    with Session(engine) as db:
        o = Orchestrator(db, make_llm(), generator=generator)
        try:
            start = await o.start(Filters(args.profile, args.level, args.company, args.topic))
        except (ValueError, LLMError) as exc:
            out(f"Could not start: {exc}")
            return 1
        for m in start.messages:
            out(f"\nInterviewer: {m.text}")
        sid, done = start.session_id, False
        while not done:
            try:
                text = input_fn("\nYou: ").strip()
            except EOFError:
                text = "/end"
            try:
                turn = await (o.end(sid) if text == "/end" else o.answer(sid, text))
            except Exception as exc:  # one calm line, then let the candidate try again
                out(f"(Something went wrong: {exc}. Please answer again.)")
                continue
            out(f"\nInterviewer: {turn.text}")
            done = turn.done
        report = await o.report(sid)
    out("\n--- Report ---")
    out(f"Overall: {report.overall_score}/100. {report.verdict}")
    for q in report.questions:
        out(f"  {q.final_score:>3}  [{q.topic}] {q.question}" + (f"  ({q.followups} follow-up)" if q.followups else ""))
    out("Strengths: " + "; ".join(report.strengths))
    out("Gaps: " + "; ".join(report.gaps))
    return 0


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input, out: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--level")
    ap.add_argument("--company")
    ap.add_argument("--topic")
    ap.add_argument("--db", default=settings.database_url)
    ap.add_argument("--fake", action="store_true", help="offline fake LLM (no API key)")
    return asyncio.run(run(ap.parse_args(argv), input_fn, out))


if __name__ == "__main__":
    sys.exit(main())
