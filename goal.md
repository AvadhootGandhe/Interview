# Goal

> This file is the source of truth for **what** we are building. `plan.md` says **how and in what order**. `continuous_improvements.md` says **how we keep making it better**. If anything conflicts, this file wins. Only the project owner changes the Goal or Constraints sections.

## Product goal (one paragraph)
A voice-first **AI mock interview platform**. A candidate picks a **profile** (role), **level**, and optionally a **company** and **topic**, then has a realistic spoken interview. A multi-agent system runs it. A **retrieval layer** pulls that company's, profile's and level's real questions from a 131K-question dataset and builds a **company profile** (what the company focuses on and how it asks). It gives both to the agents as context, RAG-style. Our fine-tuned Qwen3-4B **question generator** adds more candidate questions. A **planner** turns all of it into an interview that **flows**: warm-up → core concepts → deeper scenarios → stretch, with related topics next to each other. The plan **adapts** as the interview goes: harder after strong answers, easier after weak ones, and bridging to what the candidate just mentioned. Questions are never fired at the candidate at random. An **interviewer** agent speaks naturally, in the company's style. An **evaluator** agent scores every answer with a **satisfaction score**, and when the score is below a threshold the interviewer **asks a follow-up** on exactly what was missing. A **reporter** agent gives clear, honest feedback at the end. The experience should feel like a calm, Apple-quality product: minimal, fast, and effortless.

## MVP success criteria (all must be true)
| # | Criterion | How it is measured |
|---|-----------|--------------------|
| G1 | A full **voice** interview runs end to end in the browser: setup → greeting → 4–5 questions → closing → report | Manual E2E run + `tests/e2e` (local-only) |
| G2 | A weak answer triggers a follow-up aimed at the missing points; a strong answer moves on | `tests/test_orchestrator.py` (mocked LLMs) + eval set `evals/answers.jsonl` |
| G3 | The evaluator is consistent: on the fixed eval set, satisfaction is within ±10 of the labeled score for ≥ 80% of answers | `scripts/run_evals.py` |
| G4 | Turn latency (end of user speech → interviewer audio starts) is **p50 < 4 s** on the target Mac | `scripts/bench_latency.py` (local-only) |
| G5 | Questions match the chosen filters; with sparse filters the retriever widens gracefully and never returns an empty pool | `tests/test_retriever.py` |
| G6 | The report shows an overall score, a score per question, strengths, gaps and the full thread | `tests/test_reporter.py` + visual check |
| G7 | The UI passes the minimalism checklist in `continuous_improvements.md` on every screen, light and dark | Screenshot review |
| G8 | Every piece of backend logic has tests written **before** the code; the suite is green | `pytest` in CI or a cloud session |
| G9 | **Interview flow:** 100% of plans pass validation (no made-up ids, no repeats, difficulty ramps); flow coherence (Claude judge) ≥ 4/5 on average; at most 1 abrupt topic jump per interview; a mentioned technology that matches the pool leads to a bridged next question | `tests/test_planner.py`, `tests/test_flow.py`, `run_evals.py --flow` |
| G10 | **Company context:** when a company is chosen, ≥ 70% of the pool is company-specific and company relevance (Claude judge) is ≥ 4/5 on average | `tests/test_context_pack.py`, `run_evals.py --flow` |

## Scope
**In (MVP):** technical screening only, covering conceptual topics (System Design, Cloud, K8s, Databases, LLMs, etc.). DSA is asked verbally ("explain your approach and complexity").

**Out (for now):** behavioral track (that is the next phase), code editor, auth/accounts, payments, Docker, deployment, horizontal scaling, mobile apps.

**Built so scaling is easy later, not scaled now:** every model, speech engine and the database sit behind small interfaces; there is no in-memory session state; config lives in `.env`.

## Fixed constraints
- **Target machine:** Apple A18 Pro, **8 GB RAM**, macOS. Everything runs locally except the Claude API.
- **Retrieval:** SQLite filters + FTS5 keyword search for the MVP. No embedding model unless the metrics show it's needed, to protect RAM. The planner and flow controller may only use question ids that exist in the retrieved pool.
- **Flow:** the planner is one Claude call at session start; adjustments between questions are rule-based (no LLM call) so they add no turn delay.
- **Question generator:** the fine-tuned **Qwen3-4B LoRA** (`output_/final-lora`), exported to GGUF q4_k_m and served by `llama-server`. Its prompt must match the training format **exactly** (see `plan.md` → Phase 1).
- **Interviewer, evaluator and reporter:** Claude API (`anthropic` Python SDK) for the MVP. The interviewer is later replaceable by LoRA v2.
- **Speech:** `mlx-whisper` (STT) and Kokoro-82M (TTS), both local.
- **Stack:** Python 3.12 + FastAPI + SQLAlchemy/SQLite backend; Next.js + TypeScript + Tailwind + Framer Motion frontend.
- **No Docker.** No premature infrastructure.
- **Data:** `by_company_profile_level_topic.json` (914 MB, local-only, never committed). Tests use `data/sample_questions.json`.

## Design rule (permanent)
**Apple-like and as minimal as possible. Whatever is on screen must be the best possible experience.**
- One clear primary action per screen. Hide everything secondary.
- System font, neutral palette (`#ffffff` / `#f5f5f7` / `#1d1d1f`, dark `#000` / `#1c1c1e` / `#f5f5f7`), one accent `#0071e3`, secondary text `#86868b`.
- Large calm type, generous whitespace, 14–20px radii, hairline borders, soft spring motion, auto light/dark.
- When in doubt, remove it.

## Engineering rule (permanent)
**Tests first, always.** Write a failing test or eval case, then write the smallest code that makes it pass, then refactor. Never merge red tests.
