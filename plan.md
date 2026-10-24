# Plan

> **How** to build what `goal.md` describes, in phases. Each phase follows the same order: **write tests → implement → check "done when" → tick the status box**. Update this file as you go: tick boxes, add notes, and never delete history. For improvements after a phase is done, follow `continuous_improvements.md`.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done · 🖥 local-only (needs the Mac, the model, the mic or the full dataset; skipped in cloud sessions via `@pytest.mark.local`)

---

## Reference: what already exists
- `by_company_profile_level_topic.json` 🖥 (914 MB, git-ignored). Structure: `company → profile → level → topic → {"questions": [{"question", "slug"}]}`. It is pretty-printed with 2-space indentation: company keys are at 2 spaces, profiles at 4, levels at 6, topics at 8.
  - 3,825 company keys. Some are junk: `"(base list empty)"`, `"(none provided)"`, `"<<<FIELD:companies>>>"`, and other keys starting with `(`. Some are near-duplicates: `AI21`/`AI21 Labs`, `37signals`/`37signals/Basecamp`.
  - 8 profiles: Backend, DevOps, Fullstack, AI Engineer, ML Engineer, Database Developer, Data Engineer, AIOps.
  - 5 levels: Fresher, SDE-1, SDE-1/2, SDE-2/3, Architect/Principal.
  - 402 topics. "Data Structures & Algorithms" is by far the largest; "Behavioral & Leadership Principles (STAR)" also exists.
  - About 131K unique questions (unique slugs), referenced about 3.86M times. Questions are text only, with no answers or rubrics. A slug ends with a numeric id (`...-21847`).
- `data/sample_questions.json`: the same structure, a small subset for tests. It is committed.
- `output_/final-lora/` 🖥: PEFT LoRA r=16/α=16 on `unsloth/Qwen3-4B-unsloth-bnb-4bit` (bnb-4bit runs only on CUDA, so it must be exported).
- `finetune_qwen3_interviewer_t4.ipynb`: the training notebook. **The LoRA learned one task: Profile + Level + Topic → one question.** It never saw company, conversation history or follow-ups.

## Architecture
```
Browser (Next.js)                        Backend (FastAPI)
 ├ /            setup (step by step) ─▶ GET  /catalog/*            ── SQLite
 ├ /interview/[id]  orb + mic      ─▶  POST /sessions               (retrieve → plan → greeting)
 │                                        ├ Retriever      SQLite filters + FTS5 → question pool (≤40)
 │                                        ├ CompanyProfile topic mix (SQL) + focus summary (Claude Haiku, cached)
 │                                        ├ QuestionGenerator → llama-server (fine-tuned Qwen3-4B) 🖥 → extra pool items
 │                                        └ Planner        → Claude: ordered interview plan (4–6 segments)
 │                                      POST /sessions/{id}/answer   audio|text
 │                                        ├ STT        mlx-whisper              🖥
 │                                        ├ Orchestrator (state machine, DB-backed)
 │                                        │   ├ Evaluator          → Claude (structured JSON)
 │                                        │   ├ FlowController     rules only: harder/easier/bridge (no LLM)
 │                                        │   └ Interviewer        → Claude + context pack (greeting / ask / follow-up / close)
 │  ◀── transcript, text, audio_url ──    └ TTS        Kokoro-82M               🖥
 └ /report/[id] ◀───────────────────── GET  /sessions/{id}/report  → Reporter (Claude)
```

**Interview loop:**
1. **RETRIEVE.** Build the **context pack**:
   - company profile;
   - profile and level expectations;
   - question pool: up to 40 dataset questions plus fine-tuned generated questions for the likely topics;
   - each item tagged with id, topic and difficulty estimate.
2. **PLAN.** The planner turns the pack into 4–6 ordered segments: warm-up → core concepts → deeper scenario/design → stretch. Related topics sit next to each other, and difficulty rises with level. This runs while the greeting plays.
3. GREETING.
4. For each segment, ASK. The interviewer gets the segment theme, its question, 3 similar retrieved questions as style examples, the company profile, and the bridge note, then speaks a natural transition followed by the question.
5. The user answers. EVALUATE produces `{satisfaction 0–100, scores{correctness, depth, clarity, communication}, covered_points[], missing_points[], follow_up_focus, mentioned_terms[], red_flags[]}`.
6. If `satisfaction < THRESHOLD (70)` and `follow_ups < MAX_FOLLOWUPS (2)`, ask a FOLLOW_UP on `follow_up_focus` and go back to step 5.
7. **FLOW.** When a question is finished, the flow controller adjusts the *next* segment (rules only, no LLM call):
   - score ≥ 85 → harder question on the same theme from the pool;
   - score ≤ 50 → easier one;
   - a `mentioned_terms` FTS match against an upcoming pool question → swap that question in and add a **bridge** note ("they mentioned Redis").
8. After the last segment or the time limit: CLOSING, then REPORT.

The final score for a question is its last satisfaction score minus `FOLLOWUP_PENALTY (5)` for each follow-up it needed. All numbers live in `backend/app/config.py` and can be overridden from `.env`.

## Repo layout (the repo root is this folder)
```
goal.md  plan.md  continuous_improvements.md  CLAUDE.md  .gitignore
data/sample_questions.json
backend/
  app/main.py  app/config.py
  app/api/{catalog,sessions}.py
  app/agents/{base,question_generator,planner,interviewer,evaluator,reporter,orchestrator}.py
  app/llm/{local_client,claude_client}.py
  app/speech/{stt,tts}.py
  app/services/{retriever,company_profile,context_pack,flow}.py
  app/db/{models,session}.py
  app/prompts/{planner,interviewer,evaluator,reporter,company_profile}.md
  scripts/{ingest,check_model,text_interview,run_evals,bench_latency}.py
  evals/answers.jsonl
  tests/  (conftest.py has fake LLM, STT and TTS fixtures, plus the `local` marker)
  requirements.txt  .env.example  pytest.ini
frontend/  (Next.js app router)
models/    🖥 git-ignored (GGUF)
```

---

## Phase 0: Setup and docs
**Goal:** a repo that any Claude session can pick up.
- [x] `goal.md`, `plan.md`, `continuous_improvements.md`, `CLAUDE.md`, `.gitignore`
- [x] `data/sample_questions.json` (subset of the big file, for tests)
- [x] `git init` and push to GitHub → https://github.com/AvadhootGandhe/Interview
- [x] `backend/` skeleton: `requirements.txt`, `pytest.ini` (with the `local` marker; cloud runs use `-m "not local"`), `.env.example`, `tests/conftest.py`
  - Note: in cloud sessions run `python3 -m pytest`; the bare `pytest` on PATH may be a separate install without `pytest-asyncio`.

**Done when:** `cd backend && pytest -m "not local"` runs (0 tests is fine) in a fresh clone.

---

## Phase 1: Model serving (fine-tuned question generator)
**Goal:** the LoRA runs on the Mac and generates questions in its trained style.

**Tests first:**
- `tests/test_question_generator.py`
  - `build_prompt()` returns **exactly** the training string, compared byte for byte against a fixture.
  - The client sends `stop=["<|im_end|>"]`, `temperature=0.8`, `top_p=0.9`, `n_predict=100`.
  - Output cleanup: strip whitespace, drop leftover `<think>` blocks, reject empty or over-long output (more than 400 chars), and dedupe against questions already asked.
  - If llama-server is down, it raises `GeneratorUnavailable`. The picker then falls back to dataset questions (tested in Phase 2).
- 🖥 `tests/test_question_generator_live.py`: 3 real generations for `Backend / Architect/Principal / gRPC`, each a single question.

**Implement:**
- 🖥 Colab: uncomment notebook cell 11 → `model.save_pretrained_gguf(f"{OUT_DIR}/gguf", tok, quantization_method="q4_k_m")` → copy the result to `models/interviewer-q4_k_m.gguf`.
- 🖥 `brew install llama.cpp` → `llama-server -m models/interviewer-q4_k_m.gguf --port 8081 -c 2048 -ngl 99`.
- `app/llm/local_client.py`: async httpx client for `POST /completion`.
- `app/agents/question_generator.py`. Its exact prompt, which must not be changed without retraining:
  ```
  <|im_start|>system\nYou are a technical interviewer. Ask exactly one interview question that matches the requested profile, experience level and topic.<|im_end|>\n<|im_start|>user\nProfile: {profile}\nLevel: {level}\nTopic: {topic}\n\nAsk one interview question.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n
  ```
- `scripts/check_model.py`: prints 3 questions.
- ⚠ Training used `by_profile_level_topic.json`, which is not in the repo. Confirm its profile, level and topic names match the company file.

**Done when:** the unit tests are green. 🖥 `check_model.py` prints sensible single questions in under 2 s each.

**Status:**
- [x] Unit tests written first, then `app/config.py`, `app/llm/local_client.py`, `app/agents/question_generator.py` (13 tests green). Prompt checked against the notebook and a byte-exact fixture.
- [x] `scripts/check_model.py` (run with `python -m scripts.check_model` from `backend/`)
- [x] 🖥 Serve the model on the Mac (2026-10-24): no Colab export. Base `Qwen3-4B-Q4_K_M.gguf` (from `Qwen/Qwen3-4B-GGUF`) plus the LoRA converted with llama.cpp `convert_lora_to_gguf.py --base-model-id Qwen/Qwen3-4B --outtype f16` → `models/interviewer-lora-f16.gguf`. Run: `llama-server -m models/Qwen3-4B-Q4_K_M.gguf --lora models/interviewer-lora-f16.gguf --port 8081 -c 2048 -ngl 99`. `pytest -m local` live test passes; `check_model.py` gives single on-topic questions in ~1.6–2.0 s each. Note: the LoRA was trained on the bnb-4bit base; it runs here on the standard Qwen3-4B Q4_K_M base, which looks fine in spot checks but is not a merged GGUF.
- [ ] 🖥 Confirm `by_profile_level_topic.json` profile/level/topic names match the company file

---

## Phase 2: Data ingest, retrieval (RAG) and company profiles
**Goal:** fast, filterable access to the questions, and a **context pack** that gives Claude the company's real question style.

**Tests first** (all run on `data/sample_questions.json`):
- `tests/test_ingest.py`
  - Row counts match the sample.
  - Junk company keys are merged into one `General` company with `is_general=1`.
  - Aliases are merged (`AI21 Labs` becomes `AI21`).
  - Question ids are parsed from the slug suffix.
  - Duplicate slugs are stored once.
  - Re-running ingest is idempotent.
- `tests/test_retriever.py`
  - All filters are optional; any combination returns a pool of up to `POOL_SIZE (40)` distinct questions.
  - The pool covers several topics when no topic is given; no single topic exceeds 40% of it.
  - **Widening order:** drop company → General → drop level. It never returns an empty pool when the profile has any questions.
  - Excludes questions from the user's recent sessions.
  - **FTS5:** `search("redis cache eviction", pool)` ranks caching questions first; `search("kafka")` finds queue/streaming questions; it returns `[]` (and doesn't crash) on stop-words or empty input.
  - Each pool item carries `id, topic, text, source(dataset|generated), difficulty`. Difficulty is estimated from the level the question came from (Fresher = 1 … Architect = 5).
- `tests/test_company_profile.py`
  - The topic mix for `Amazon` on the sample data matches a hand-computed fixture, with percentages adding to 100.
  - The summary is generated once (with a fake LLM) and then served from the `company_profiles` cache; a second call makes no LLM call.
  - "General" or no company gives a neutral profile with no LLM call.
- `tests/test_context_pack.py`
  - The pack has company profile + level expectations + pool, and serializes under `MAX_CONTEXT_TOKENS (~3K)`, trimming the pool if needed.
  - Generated items come from the generator (mocked); if the generator is down, the pack is dataset-only and still valid.
  - A company with matches has ≥ 70% company-specific dataset items.
- `tests/test_api_catalog.py`: `/catalog/companies?q=ama` finds Amazon; profiles, levels and topics are listed and sorted.

**Implement:**
- `app/db/models.py`: `companies`, `profiles`, `levels`, `topics(category: technical|behavioral|dsa)`, `questions`, `question_map` (indexed on the filter combinations), **`questions_fts` (FTS5 virtual table over question text)**, **`company_profiles(company_id, profile_id, level_id, topic_mix_json, summary, updated_at)`**, `sessions`, `turns`, `evaluations`, `plans`.
- `scripts/ingest.py`: streams with `ijson`, takes a `--source` path, batches inserts, and builds the FTS index. Includes `company_aliases.json` and the topic category list.
- `app/services/retriever.py`: `build_pool(filters, user_id) -> list[PoolItem]`, `search(terms, pool) -> list[PoolItem]`.
- `app/services/company_profile.py`: topic mix by SQL, plus a 3–4 line focus/style summary from about 30 sample questions (Claude Haiku via `claude_client`), cached in the DB.
- `app/services/context_pack.py`: builds the pack the planner and interviewer receive.
- `app/api/catalog.py`.

**Done when:** tests are green. 🖥 Full ingest finishes in under 15 min with about 131K questions and about 3.86M mappings. `Amazon / AI Engineer / Architect/Principal / AI Agents & Tool Calling` returns the expected pool, and FTS for "idempotency" returns relevant questions in under 50 ms.

**Status:**
- [x] Tests written first, then `app/db/{models,session,names}.py`, `scripts/ingest.py`, `app/services/{retriever,company_profile,context_pack}.py`, `app/api/catalog.py`, `app/main.py`, `app/prompts/company_profile.md` (106 new tests; suite 119 green).
- [x] Ingest: ijson streams one company at a time, `--source`/`--db`/`--batch-size`, `INSERT OR IGNORE` (idempotent), FTS5 with the porter tokenizer. Aliases live in `app/db/company_aliases.json`; the topic category list in `app/db/names.py`.
- [x] Retriever: widening `exact → drop_company → general → drop_level → drop_topic → profile_only`; never empty; recent-session exclusion; ≤ 40% per topic; behavioral topics only when asked for.
- [x] Company profile (topic mix by SQL, summary via an injected LLM client, cached in `company_profiles`) and context pack (≤ 3K tokens, generator fallback).
- [ ] 🖥 Run the full ingest and `pytest -m local tests/test_ingest_full_live.py` (< 15 min, ~131K questions, ~3.86M mappings, FTS "idempotency" < 50 ms).
- [x] Company-profile summary wired to `claude_client` (Phase 3): it calls `complete(task="company_profile", model=settings.cheap_model)` (Haiku); tests use the fakes.
- [x] 🖥 Full ingest and `pytest -m local tests/test_ingest_full_live.py` (2026-10-24): 34 s, 130,998 questions, 3,855,261 mappings, 3,815 companies, 402 topics; FTS "idempotency" ≈ 1 ms; both live tests pass. Run: `python -m scripts.ingest --source ../by_company_profile_level_topic.json --db sqlite:///./data_full.db` (the db is git-ignored).
- [ ] Wire the company-profile summary to `claude_client` (Claude Haiku) once it exists in Phase 3; tests use the FakeLLM.

---

## Phase 3: Agents, interview flow and orchestrator (text only)
**Goal:** a complete interview in the terminal that **flows like a real interviewer**: questions build on each other, react to the candidate, and include real follow-ups.

**Tests first** (LLMs faked with deterministic fixtures):
- `tests/test_planner.py`
  - A valid plan parses into the `InterviewPlan` Pydantic model: 4–6 segments, each with `theme, topic, difficulty 1–5, seed_question_id, link_from_previous`.
  - **Rejects made-up ids:** every `seed_question_id` must exist in the pool.
  - No repeated questions; segment 1 is a warm-up (difficulty ≤ level baseline); difficulty never jumps by more than 2 between segments.
  - When a topic is given, ≥ 60% of segments use that topic, and the others are closely related topics.
  - Invalid output → one retry → **fixed fallback plan** (sort the pool by topic group, then difficulty). The fallback itself always passes validation.
  - The planner prompt contains the full context pack.
- `tests/test_flow.py` (pure functions, no LLM)
  - Final score ≥ 85 → the next segment's question becomes a harder pool question on the same theme (if one exists).
  - Score ≤ 50 → an easier one.
  - `mentioned_terms=["redis"]` with an FTS match on an upcoming segment → that question moves up to next, with `bridge="candidate mentioned Redis"`.
  - It never picks an already-asked question and never changes more than the next segment.
  - With no matching alternative, the plan stays as it was.
- `tests/test_evaluator.py`
  - Parses valid structured output into the `Evaluation` Pydantic model.
  - Retries once on invalid output, then raises.
  - The rubric text changes by level (Fresher vs Architect).
  - The whole question thread is sent: the main answer plus earlier follow-ups.
- `tests/test_interviewer.py`
  - Each mode (greeting, ask, follow_up, transition, closing) builds the right prompt.
  - The **ask** prompt includes the segment theme, the seed question, 3 similar retrieved questions as style examples, the company profile summary, the bridge note when there is one, and a one-line summary of the last answer.
  - The follow-up prompt includes `follow_up_focus` and the missing points.
  - The interviewer keeps the seed question's intent: a fake judge checks that the rephrased question is about the same thing.
  - Output is cleaned to plain speakable text: no markdown or lists, and at most about 60 words.
- `tests/test_orchestrator.py` (core)
  - Session start runs RETRIEVE → PLAN, saves the plan in `plans`, and greets.
  - Satisfaction 40 → follow-up. Satisfaction 85 → next segment, with the flow controller applied.
  - The follow-up cap is respected (2), then it moves on.
  - The final score applies the penalty.
  - After N questions → CLOSING → state `done`.
  - State survives a "restart": a new orchestrator instance loads from the DB mid-interview.
  - Every follow-up is appended to `data/followup_train.jsonl`.
- `tests/test_reporter.py`: the report has an overall score, a per-question list, strengths and gaps.
- `tests/test_api_sessions.py`: create session → answer in text → … → report, through the FastAPI TestClient.
- Eval set `evals/answers.jsonl`: about 30 labeled answers (strong, partial, weak, off-topic) across levels. `scripts/run_evals.py` reports the G3 metric. It needs the API key, so it is not part of the unit suite.
- Eval set `evals/sessions.jsonl`: about 10 scripted candidate sessions across company, profile and level. `run_evals.py --flow` reports G9: plan validity, flow coherence (Claude judge, 1–5), company relevance (judge, 1–5) and abrupt topic jumps per interview.

**Implement:**
- `app/agents/base.py`: `Agent` protocol `async run(ctx) -> result`.
- `app/llm/claude_client.py`: `anthropic` SDK. Model ids come from config: `claude-sonnet-5-5` by default for the evaluator, with `claude-haiku-5-5` as the cheaper option. Uses structured outputs for the evaluator. Check current SDK usage with the `claude-api` skill before writing it.
- `app/agents/planner.py` (Claude, structured output into `InterviewPlan`, validated in code, with the fallback plan) and `app/prompts/planner.md`.
- `app/services/flow.py`: `next_segment(plan, history, last_eval, pool) -> (segment, bridge|None)`. Pure function.
- The evaluator also returns `mentioned_terms[]` (technologies and concepts the candidate brought up).
- `evaluator.py`, `interviewer.py`, `reporter.py`, `orchestrator.py`, and prompts in `app/prompts/*.md`.
- `app/api/sessions.py`: `POST /sessions`, `POST /sessions/{id}/answer` (`text` for now), `POST /sessions/{id}/end`, `GET /sessions/{id}/report`.
- `scripts/text_interview.py`: an interview in the terminal.

**Done when:** tests are green, G3 is at least 80% on the eval set, G9 passes on `evals/sessions.jsonl`, and in a terminal interview:
- one deliberately weak answer triggers a relevant follow-up;
- mentioning a technology (for example, Redis) leads to a bridged next question;
- the questions clearly build from warm-up to stretch.

**Status:**
- [x] Tests written first for every item below, then the code (suite: 119 -> 223 green with `-m "not local"`).
- [x] `app/llm/claude_client.py` (SDK wrapper: structured output via `output_config.format`, `effort`, refusal handling, no sampling params), `app/llm/fake.py` (offline `DemoLLM` for `FAKE_LLM=1`), `app/llm/factory.py`.
- [x] `app/agents/{base,schemas,planner,evaluator,interviewer,reporter,orchestrator}.py`, `app/services/flow.py` (pure rules), prompts in `app/prompts/{planner,evaluator,interviewer,reporter}.md`.
- [x] `app/api/sessions.py` (`POST /sessions`, `/answer`, `/end`, `GET /report`), `scripts/text_interview.py`.
- [x] Planner copes with small pools (segments = min(4..6, pool size); the fallback plan is valid on every pool in the sample, including tiny companies such as AI21).
- [x] Eval sets `backend/evals/answers.jsonl` (34 labeled answers) and `backend/evals/sessions.jsonl` (10 scripted sessions); `scripts/run_evals.py` (G3, and `--flow` for G9/G10; `--dry-run` runs the harness on the DemoLLM).
- [ ] Run `python -m scripts.run_evals` with a real `ANTHROPIC_API_KEY`: G3 >= 80% on `answers.jsonl`.
- [ ] Run `python -m scripts.run_evals --flow` on the full ingested DB: G9 (coherence >= 4, <= 1 abrupt jump) and G10 (company relevance >= 4).
- [ ] Terminal acceptance run with real Claude (`python -m scripts.text_interview`): a weak answer triggers a relevant follow-up, mentioning Redis leads to a bridged question, questions build from warm-up to stretch.

---

## Phase 4: Speech 🖥
**Goal:** speak and listen locally.

**Tests first:**
- `tests/test_stt.py`
  - Audio conversion builds the right ffmpeg command (16 kHz mono wav).
  - The engine interface is called; the real engine is faked.
  - Empty or silent audio returns `""` and does not crash.
- `tests/test_tts.py`: text goes to the engine and comes back as a wav file whose URL is returned. Long text is split into sentences.
- 🖥 Live tests: transcribe `tests/fixtures/hello.wav` (word error rate under 15%), and synthesize a sentence in under 1 s.
- `tests/test_api_sessions.py`: the answer endpoint accepts multipart audio.

**Implement:** `app/speech/stt.py` (mlx-whisper `base.en`), `app/speech/tts.py` (Kokoro, one voice, cached), and audio served at `/audio/{file}`.

**Done when:** tests are green. 🖥 A recorded answer goes in and spoken interviewer audio comes out.

**Status:**
- [x] `tests/test_stt.py`, `tests/test_tts.py`, `tests/test_api_audio.py` written first (26 tests), then `app/speech/stt.py`, `app/speech/tts.py`, `app/api/audio.py` (registered in `app/main.py`). Cloud suite: 145 green.
- [x] 🖥 Live: `tests/test_speech_live.py` (marked local). mlx-whisper `whisper-base.en-mlx` on `tests/fixtures/hello.wav` (made with `say` + ffmpeg, 139 KB): WER 0.0 (limit 15%). Kokoro-82M voice `af_heart`: 0.44 s for one sentence after warm-up (limit 1 s). Mac-only deps in `backend/requirements-local.txt`.
- [ ] `tests/test_api_sessions.py`: the answer endpoint accepts multipart audio (owned by the Phase 3 sessions API; wire `SpeechToText` and `TextToSpeech` into it, same interface as `FakeSTT`/`FakeTTS`).
- [ ] 🖥 End to end: a recorded browser answer (webm) in, spoken interviewer audio out (needs the sessions API and frontend; ffmpeg conversion of webm is only unit-tested with a fake).

---

## Phase 5: Frontend (Apple-minimal)
**Goal:** the three screens from `goal.md`, each with one clear action.

**Tests first:**
- Vitest + React Testing Library:
  - The setup flow moves step by step, and Skip works for company and topic.
  - The Start button's enabled/disabled logic.
  - The mic button: holding and pressing Space start and stop recording (MediaRecorder mocked).
  - The "•••" menu shows the transcript, the typed-answer box and End.
  - The report renders scores from a fixture.
- Playwright (🖥 or a cloud session with a browser): a full flow against the backend in typed-answer mode with fake LLMs (`FAKE_LLM=1`).

**Design system first** (`frontend/styles/tokens.css`, `tailwind.config.ts`, `components/ui/`):
- Tokens and `Button`, `SegmentedControl`, `SearchField`, `Chip`, `Card`, `Orb`.
- System font, the neutral palette plus `#0071e3`, auto dark mode, springs, and `prefers-reduced-motion`.

**Screens:**
- `/`: headline "Practice your next interview." Then one step per screen: Role (chips) → Level (segmented) → Company (search, Skip) → Topic (chips, "Any topic"). Then one blue pill: **Start**.
- `/interview/[id]`: a centre orb (idle breathing, pulses while the interviewer speaks, blue while the user speaks), the current question as one calm line, one round mic button (hold, or Space), progress dots at the top, and everything else behind "•••".
- `/report/[id]`: a score ring and a one-line verdict, one card per question (tap to expand the thread), strengths and gaps, then "Practice again".

**Done when:** tests are green, every screen passes the minimalism checklist (`continuous_improvements.md`) in light and dark mode at 1440 px and 390 px, and G1 passes manually.

**Status:**
- [x] Scaffold `frontend/`: Next.js 15.5 (app router) + React 19 + TypeScript + Tailwind 3 + Framer Motion, exact versions pinned, npm scripts `dev` (:3000), `build`, `test` (`vitest run`), `lint`
- [x] Design system: `styles/tokens.css`, `tailwind.config.ts` (3 text sizes: display/body/caption, 14–20px radii, hairlines, 44px tap targets, auto dark mode), `components/ui/` `Button`, `SegmentedControl`, `SearchField`, `Chip`, `Card`, `Orb` (+ `StatusLine` for one-line states). `MotionConfig reducedMotion="user"` plus a CSS reduced-motion guard
- [x] `lib/api.ts`: every backend call, typed, base URL from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`); small normalisers absorb shape drift (`greeting`/`text`, `["a"]`/`[{name}]`/`{items}`, numeric `progress`)
- [x] `/` setup flow: Role chips → Level segmented → Company search (Skip) → Topic chips ("Any topic") → one blue **Start** pill; Back link; calm loading/error/empty lines
- [x] `/interview/[id]`: orb (idle/speaking/listening/thinking), one-line question, hold-to-talk mic + Space, progress dots, "•••" sheet with transcript, typed answer and End; mic-denied → "Type instead"; send failure → one retry; `done` swaps the mic for "See your report"
- [x] `/report/[id]`: score ring + verdict, per-question cards (tap for feedback), strengths, gaps, full conversation collapsed, "Practice again"
- [x] Vitest + RTL tests written first (37 green): setup flow incl. Skip/Any topic, Start enabled/disabled, mic hold + Space with mocked MediaRecorder, "•••" menu, report from fixture, `lib/api`
- [x] Playwright E2E (`npm run e2e`, 4 projects: light/dark x 1440/390) against the real backend with `FAKE_LLM=1` on a temp SQLite DB ingested from the sample data; frontend aligned to the real API shapes
- [x] Minimalism checklist screenshot review, light + dark, 1440 px + 390 px (e2e/screenshots, git-ignored); fixes: report card double padding, overlapping placeholder line, dev badge, fewer topic chips
- [ ] G1 manual voice run (needs Phases 3–4)
- Notes: the greeting is handed from `/` to `/interview/[id]` via `sessionStorage` (per-tab convenience only); a reload shows a neutral prompt until the next answer. Topics are requested as `/catalog/topics?profile=…`; with more than 12 topics a filter field appears. Remaining `npm audit` items are build-time only (Next's vendored postcss, Tailwind 3's postcss-selector-parser) and need major upgrades.

---

## Phase 6: Polish
- Latency (G4): start TTS on the first sentence while the rest generates; play a short pre-generated filler line ("Got it.") while the evaluator runs; keep models warm.
- Error states: mic denied, model server down, API errors. Each gets a calm one-line message with a single retry.
- `scripts/bench_latency.py` 🖥 records p50 and p95.

**Done when:** G1–G10 are all met. **That completes the MVP.**

---

## Phase 7: Next (after the MVP)
- [ ] **Behavioral track:** STAR rubric in the evaluator (situation, task, action, result, ownership, impact), behavioral topic set, follow-ups like "What was *your* specific role?"
- [ ] **LoRA v2:** a new Colab notebook trained on multi-turn data (context + question + answer + evaluator gaps → follow-up), from `data/followup_train.jsonl` plus synthetic Claude conversations, `MAX_LEN` about 1024. Swap `interviewer.py` to it and A/B it against Claude on logged sessions.
- [ ] **Semantic retrieval:** add small local embeddings (for example, bge-small, about 130 MB) with a numpy/sqlite-vec index, used together with FTS5. Only do this if the pool hit rate or the company relevance metric shows FTS is not enough.
- [ ] Planner aware of the candidate's history: use earlier sessions' weak areas to shape new plans.
- [ ] WebSocket streaming, a DSA code editor, auth, a history dashboard.

---

## Notes and decisions log
| Date | Decision | Why |
|------|----------|-----|
| 2026-10-24 | Hybrid: the LoRA generates questions; Claude handles conversation and follow-ups | The LoRA was trained only on single-turn question generation |
| 2026-10-24 | Claude for the evaluator | A 4B model on 8 GB RAM is too weak and slow for reliable scoring |
| 2026-10-24 | Local Whisper + Kokoro | Free, good quality, fits in RAM alongside the LLM |
| 2026-10-24 | Technical screening before behavioral | Owner's choice |
| 2026-10-24 | REST, not WebSocket, for the MVP | Simpler; streaming comes later |
| 2026-10-24 | Retrieval (RAG) context pack: company profile + filtered question pool, given to the planner and interviewer | Claude asks in the company's real style instead of rewording one random question |
| 2026-10-24 | FTS5 keyword search before embeddings | Built into SQLite, uses no extra RAM on the 8 GB Mac; embeddings only if the metrics need them |
| 2026-10-24 | Planner (one Claude call at start) + rule-based flow controller between questions | Interview flows warm-up → stretch and reacts to answers, with no extra latency per turn |
| 2026-10-24 | Generator prompt unchanged; company flavour comes from retrieval + Claude | The LoRA was trained without company input |
| 2026-10-24 | Question id = slug suffix as a string (`"21834"`, DSA `"d1743"`) | DSA slugs end in `-d<n>`; the suffixes are unique in the sample |
| 2026-10-24 | A company with ≥ 12 exact matches caps the widened share of its pool so ≥ 70% stays company-specific (pool can be < 40) | G10 (goal.md) wins; keeps the plan's widening order intact. Sparse companies widen freely (G5) |
| 2026-10-24 | Behavioral topics (STAR, leadership) are left out of pools and the topic catalog unless chosen explicitly | MVP is technical screening only (goal.md Scope) |
| 2026-10-24 | Company profile LLM failure → a one-line topic summary, not cached | The profile is optional context and must never block an interview |
| 2026-10-24 | Phase 3 models: planner/evaluator/reporter = `claude-sonnet-5-5`, interviewer/company profile = `claude-haiku-5-5`, all in `config.py` | Evaluator accuracy matters most; the interviewer speaks every turn so latency wins. No sampling params are sent (removed on current models) |
| 2026-10-24 | The flow controller takes the retriever's FTS `search` as an injected function (default: in-memory keyword match) | Keeps `next_segment` a pure function while the orchestrator still uses FTS5 |
| 2026-10-24 | A bridge swaps the matched later question with the next one (two segments change, no id lost or repeated) | "Move it up" must not duplicate the question left in its old slot |
| 2026-10-24 | Orchestrator does its LLM work first, then saves a whole step in one commit; extra `session_states` table instead of new columns | No SQLite write lock held across API calls; existing ingested DBs need no migration |
| 2026-10-24 | The interviewer checks that a reworded question keeps the seed's meaning with a cheap word-overlap rule and falls back to the seed text; the LLM judge is only used in evals | An extra judge call per turn would cost latency (G4) |
| 2026-10-24 | The fallback plan uses at most two topic groups (the chosen or largest first) | Five questions from five topics scored 3+ abrupt jumps in the dry run |
| 2026-10-24 | Frontend: Tailwind 3 (JS config) + Next 15.5.28 patched backport; all API calls in `lib/api.ts` with normalisers | `tailwind.config.ts` holds the design tokens; 15.5.28 fixes a critical Next advisory; backend shapes may still drift |
