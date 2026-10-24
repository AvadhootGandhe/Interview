"""Run a full interview in the terminal.

    FAKE_LLM=1 python scripts/text_interview.py --profile Backend --level SDE-2/3 --company Amazon
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import create_app  # noqa: E402
from app.services.retriever import Filters  # noqa: E402
from app.agents.reporter import build_report  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--level")
    ap.add_argument("--company")
    ap.add_argument("--topic")
    args = ap.parse_args()
    app = create_app()
    orch = app.state.orchestrator
    started = await orch.start(Filters(args.profile, args.level, args.company, args.topic))
    for msg in started.messages:
        print(f"\nInterviewer: {msg}")
    while True:
        answer = input("\nYou (blank to end): ").strip()
        reply = await (orch.answer(started.session_id, answer) if answer else orch.end(started.session_id))
        for msg in reply.messages:
            print(f"\nInterviewer: {msg}")
        if reply.state == "done":
            break
    report = await build_report(app.state.engine, app.state.llm, started.session_id)
    print(f"\nScore: {report.overall_score}/100 — {report.verdict}")
    print("Strengths:", "; ".join(report.strengths))
    print("Gaps:", "; ".join(report.gaps))


asyncio.run(main())
