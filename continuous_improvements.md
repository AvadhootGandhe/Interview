# Continuous Improvements

> The operating loop every Claude session (local or cloud) follows once a phase in `plan.md` is done, or whenever it is asked to "improve" something. **One improvement per loop. Tests first. Measure before and after. Log everything.**

## Before you start (every session)
1. Read `goal.md`, which wins every conflict. Then `plan.md`, which has the current phase and status boxes. Then the **Improvement Log** at the bottom of this file, which shows what was tried and what's next.
2. Run the baseline:
   ```bash
   cd backend && pytest -m "not local" -q          # must be green before you change anything
   python scripts/run_evals.py --json > /tmp/before.json   # if ANTHROPIC_API_KEY is set
   ```
   🖥 On the Mac, also run `pytest -q` (including local tests) and `python scripts/bench_latency.py`.
3. If the baseline is red, **fixing it is the improvement for this loop.**

## The loop

### 1. Observe
Collect evidence. Don't guess. Sources:
- failing or flaky tests;
- eval metrics (below);
- latency numbers;
- interview transcripts in the DB and `data/followup_train.jsonl`;
- screenshots compared against the minimalism checklist;
- the "Next ideas" column of the last log entry.

### 2. Generate
Write **3–5 candidate improvements**. Give each one:
- **Idea:** what to change.
- **Hypothesis:** why it should help.
- **Metric:** which number from the table below should move, and in which direction.
- **Effort:** S, M or L.
- **Risk:** what could get worse.

Think like a product owner and a staff engineer together. Look for the weakest point in the candidate's experience.

### 3. Validate (pick one)
Reject an idea if it:
- breaks a constraint in `goal.md` (8 GB RAM, no Docker, Apple-minimal UI, the training prompt format, and so on);
- adds UI elements without removing at least as many;
- can't be measured.

Pick the idea with the **best impact for its effort**. Write down in one line why you chose it.

### 4. Test first
Before any implementation, write the test or eval case that defines success, and run it so you **see it fail**:
- Logic change → a unit test in `backend/tests/` or `frontend/__tests__/`.
- Quality change (prompts, rubric, follow-ups) → new labeled cases in `evals/answers.jsonl` or `evals/followups.jsonl`, plus a threshold check in `run_evals.py`.
- Latency change → a benchmark assertion in `bench_latency.py` 🖥.
- UI change → a component test, plus a before/after screenshot.

### 5. Implement
Write the **smallest change** that turns the new test green. Don't add unrelated refactors. Follow the existing patterns and interfaces (`Agent`, `local_client`, `claude_client`, the speech interfaces).

### 6. Verify
- The full suite is green: `pytest -m "not local"`, plus `pytest` 🖥 and the frontend tests.
- Re-run evals and latency, then compare with the baseline.
- **If the target metric didn't improve, or any other metric got worse by more than the noise band (±3 points on eval metrics, ±10% on latency), revert.** Log the attempt anyway; a failed experiment is still useful.

### 7. Log
Add a row to the Improvement Log below. Tick or update `plan.md` if a phase item changed. Commit with the message `improve: <idea> (<metric> before→after)`.

Then start the loop again from step 1.

## Metrics to track
| Metric | Target | Source |
|--------|--------|--------|
| Unit test suite | 100% green | `pytest`, `vitest` |
| **Evaluator agreement:** satisfaction within ±10 of the label | ≥ 80% (G3) | `run_evals.py` on `evals/answers.jsonl` |
| **Follow-up trigger accuracy:** follows up exactly when the label says the answer is weak | ≥ 90% | `run_evals.py` |
| **Follow-up relevance:** a Claude judge rates whether the follow-up targets the actual gap (1–5) | ≥ 4.0 average | `run_evals.py` on `evals/followups.jsonl` |
| **Generated question quality:** single question, on-topic, right level (judge 1–5) | ≥ 4.0 average | `run_evals.py --generator` 🖥 |
| **Plan validity:** plans that pass checks without needing the fallback | 100% after fallback; ≥ 90% first try | `tests/test_planner.py`, `run_evals.py --flow` |
| **Flow coherence:** a Claude judge rates whether the questions build naturally (1–5) | ≥ 4.0 average (G9) | `run_evals.py --flow` on `evals/sessions.jsonl` |
| **Abrupt topic jumps** per interview | ≤ 1 (G9) | `run_evals.py --flow` |
| **Company relevance:** a Claude judge rates whether the questions feel like this company (1–5) | ≥ 4.0 average (G10) | `run_evals.py --flow` |
| **Pool hit rate:** mentioned terms that found a matching pool question for a bridge | Track it; if low, consider embeddings (Phase 7) | orchestrator logs |
| Turn latency p50 / p95 | < 4 s / < 6 s (G4) | `bench_latency.py` 🖥 |
| Claude cost per interview | Track it and don't let it creep up | API usage logs |
| UI minimalism checklist | All pass | Screenshot review |

## UI minimalism checklist (Apple-like)
Every screen, in light **and** dark mode, at 1440 px and 390 px:
- [ ] Exactly **one** primary action is visible.
- [ ] Nothing on screen can be removed without losing something the user needs right now.
- [ ] Secondary controls are hidden: in "•••", progressive disclosure, or the next step.
- [ ] Only the system font; at most 3 text sizes on the screen.
- [ ] Only the neutral palette plus the single accent `#0071e3`, and the accent is used only for the primary action and active states.
- [ ] Generous whitespace; the content never feels crowded at 390 px.
- [ ] Motion is soft springs or fades, and `prefers-reduced-motion` is respected.
- [ ] Every state (loading, error, empty) is calm, says one line, and offers one action.
- [ ] No horizontal scroll, and tap targets are at least 44 px.

## Rules
1. **Never skip tests-first.** No test means no change.
2. **One improvement per loop.** Small and measurable beats big and vague.
3. **`goal.md` is law.** To change a goal or constraint, propose it in the log and wait for the owner to approve it.
4. **Don't break the training prompt** in `question_generator.py`. Changing it requires retraining the LoRA.
5. **No made-up questions in plans.** The planner and flow controller only pick ids from the retrieved pool. Keep the flow controller rule-based (no LLM) unless a measured improvement justifies the added latency.
6. **Cloud sessions** can't reach 🖥 items (the full dataset, GGUF, mic, Metal). Use `data/sample_questions.json` and fakes, and mark anything that needs the Mac with `@pytest.mark.local`.
7. **Never commit** the 914 MB dataset, model weights, `.env` or API keys.
8. Keep this file and `plan.md` current. The next session only knows what is written down.

## Improvement Log
| # | Date | Idea (one line) | Hypothesis → metric | Result (before → after) | Kept? | Next ideas |
|---|------|-----------------|---------------------|-------------------------|-------|------------|
| 0 | 2026-10-24 | Project docs created | — | — | — | Start Phase 0 skeleton → Phase 1 |
| 1 | 2026-10-24 | Design: retrieval context pack + planner + flow controller (docs only) | Company-style, flowing interviews → G9, G10 | — (not built yet) | — | Build in Phase 2–3, tests first |
| 2 | 2026-10-23 | Phase 0 backend skeleton + Phase 1 question generator (cloud-safe part) | Tests first → G8 | 0 → 13 tests green, 1 local test deselected | Yes | 🖥 GGUF export + live test; then Phase 2 ingest/retriever |
| 3 | 2026-10-24 | Phase 2: ingest + FTS5, retriever with widening, company profile, context pack, catalog API (cloud-safe part) | Tests first → G5, G8, G10 | 13 → 119 tests green, 3 local tests deselected; sample ingest 0.2 s; packs ~1.5–2.4K tokens | Yes | 🖥 full ingest + `test_ingest_full_live.py`; Phase 3 planner/flow; watch pool size for companies with few exact matches |
| 4 | 2026-10-24 | Phase 3: planner + rule-based flow controller, evaluator, interviewer, reporter, DB-backed orchestrator, sessions API, text interview, eval sets (cloud-safe part, FakeLLM/DemoLLM) | Tests first -> G2, G6, G8, G9 (plan validity, flow) | 119 -> 223 tests green; fallback plan valid on all sampled pools; dry-run flow eval: plan validity 100%, 1.1 abrupt jumps (fallback plans) | Yes | Run `run_evals.py` (G3) and `--flow` (G9/G10) with a real key and the full DB; tune prompts from the misses; check the structured-output schema live; consider streaming + a filler line for G4 in Phase 6 |
| 5 | 2026-10-24 | Mac verification of Phases 1-2: full ingest, LoRA served via llama-server | Real data + model match the plan → G5 | Ingest 34 s (<15 min); 131K q / 3.86M maps; generator 1.6–2.0 s per question; 121 tests green (+3 local) | Yes | Phase 3 (cloud session in progress); Phase 4 speech; merge LoRA into a single GGUF if base+adapter proves flaky |
| 7 | 2026-10-24 | Phase 4 speech: ffmpeg to 16 kHz wav, mlx-whisper STT with silence gate, Kokoro TTS with sentence split + hash cache, `/audio/{file}` | Local voice in/out fast enough for a live interview → G3 | 119 → 145 tests green (+5 local); STT WER 0.0 on hello.wav; TTS 0.44 s per sentence after warm-up | Yes | Wire into answer endpoint (Phase 3 agent); stream TTS per sentence to cut time to first audio; measure WER on real mic/webm audio and accented speech; try whisper small.en if WER is poor |
| 6 | 2026-10-24 | Phase 5 frontend: design system + setup / interview / report screens against the plan.md API shapes | Tests first → G7, G8; one primary action per screen | 0 → 37 Vitest tests green; `npm run build` + `lint` clean | Yes | Screenshot review vs. minimalism checklist (light/dark, 1440/390); Playwright E2E with `FAKE_LLM=1` once Phase 3 API exists; align `lib/api.ts` to the real response shapes |
| 9 | 2026-10-24 | Connect frontend to the real API: types and screens use the real response shapes; Playwright E2E (typed answers, weak answer -> follow-up, report) and screenshot review light/dark at 1440/390 | Tests first -> G1 (typed), G6, G7 | 37 -> 38 Vitest + 4 Playwright runs green; build + lint clean; fixed report card double padding, overlapping placeholder text, topic list too long (12 -> 8 chips); all 9 checklist items pass in review | Yes | G1 voice run once multipart audio lands (confirm form field name `audio` and `transcript` in the reply); more rows on the topic step via the filter only; real-Claude e2e on the Mac |
| 8 | 2026-10-24 | Phase 4 voice loop: multipart audio answers, `audio_url` on every interviewer reply (TTS failure tolerated), injected STT/TTS (`SPEECH` setting), `Server-Timing` stage timings, `backend/API.md`, `scripts/bench_latency.py` | Spoken interview works end to end → G1, G4 | 249 → 261 cloud tests green (+1 local E2E passes); fake-LLM bench with real speech: p50 2.85 s, p95 4.16 s; TTS (2.4 s p50) dominates, STT 0.27 s | Yes | Run bench with real Claude (G4 unproven); cut time to first audio by synthesizing/streaming the first sentence first and shorter spoken replies; warm up Kokoro/Whisper at server start; browser webm E2E |
| 10 | 2026-10-24 | Latency: warm Whisper + Kokoro in a background task in the FastAPI lifespan (`app/speech/warmup.py`, `warm_up()` on STT/TTS; failure-tolerant, `/health` immediate). Also bench honesty: `TTS_CACHE=0` (the fake LLM repeats texts, so the TTS cache flattered earlier numbers) and `--pause` (default 8 s listen + think) in `bench_latency.py` | Models load while the user fills the setup screen -> first turn after restart | First real turn after restart 19.1 s -> 3.7 s (warm-up needs ~25-40 s after start); steady state unchanged. Honest steady-state baseline with cache off: p50 3.88 s, p95 8.32 s (TTS 3.6 s p50; the old 2.85 s included cache hits) | Yes | A user who answers in the first ~40 s after a cold start still waits |
| 11 | 2026-10-24 | Latency: time to first audio. `TextToSpeech.synthesize_stream` renders sentence 1 and returns at once; remaining clips + the joined whole render in a background thread. Response gains `audio_urls` (per sentence); `audio_url` is still the whole text; `GET /audio` waits for a clip still rendering. Documented in `backend/API.md` | G4: audio starts after one short sentence, not the whole reply | p50 3.88 s -> 0.65 / 0.77 s (two runs, 15 audio turns, 8 s pause, fake LLM, real STT/TTS); TTS stage 3.6 s -> 0.36-0.48 s. Back to back (no pause) it is 4.33 s because the next turn queues behind the previous background render; a real user is listening for longer than that. One p95 outlier of 7 s in one run, unexplained (n=15). Not valid for G4: fake LLM | Yes | Frontend must play `audio_urls` in order (other agent); with real Claude add the LLM time (see budget) |
| 12 | 2026-10-24 | Shorter spoken replies (`speech_max_words` 60 -> ~40, tighter `max_tokens`) | Fewer Claude output tokens and fewer sentences -> less LLM time | NOT MEASURABLE here: the fake LLM ignores the word limit and there is no `ANTHROPIC_API_KEY`. After #11 TTS time depends only on the first sentence, so the gain is Claude generation time only (est. 0.2-0.3 s) | No (not applied; cannot be measured) | Try on the Mac with a key and `bench_latency.py`; keep if p50 improves > 10% and the interviewer still sounds natural |
| 13 | 2026-10-24 | Overlap independent work: greeting and first question at session start run with `asyncio.gather` (test: peak concurrency 2). A per-turn overlap is not possible: the flow controller needs the evaluation (harder / easier / bridge), and nothing report-free is left after the interviewer reply (the DB commit takes ms) | Start of session saves one Haiku round trip | Test-verified overlap only; est. -1.0 to -1.5 s on `POST /sessions` with real Claude, not measured. Per-turn p50 unchanged by construction. `Server-Timing` `interviewer` now sums both calls at start | Yes (cheap, safe) | Stream Claude tokens into TTS: synthesize sentence 1 while the interviewer still writes sentence 2 (est. -0.7 s); a short spoken acknowledgement while the evaluator runs |

### Stage budget, one turn with REAL Claude (ESTIMATE, not measured: no API key in this session)
STT, flow and TTS-first-clip are measured in the fake-LLM bench above. The Claude stages are assumptions from typical Sonnet / Haiku latencies with the current settings.

| Stage | Source | Estimate (s) |
|-------|--------|--------------|
| Upload + ffmpeg + Whisper base.en | measured, p50 | 0.3 |
| Evaluator (Sonnet, structured JSON, up to 1500 tokens) | ASSUMED | 2.0 - 4.0 |
| Flow controller (rules) | measured | 0.0 |
| Interviewer (Haiku, ~60 words, effort low) | ASSUMED | 0.8 - 1.5 |
| TTS first sentence (Kokoro, warm) | measured, p50 | 0.4 - 0.5 |
| Fetch first clip + network | measured | 0.05 |
| **Total** | | **3.6 - 6.4 (mid ~5)** |

Reading: G4 (p50 < 4 s) is NOT safe yet with real Claude; the evaluator is now the biggest stage. Next steps in order: (1) measure with a real key; (2) shrink the evaluator (Haiku for scoring, fewer output tokens) or speak a short acknowledgement immediately while it runs, which brings perceived latency to ~0.8 s; (3) stream interviewer tokens into TTS (about -0.7 s).
