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
 ├ /interview/[id]  orb + mic      ─▶  POST /sessions               (pick questions, greeting)
 │                                      POST /sessions/{id}/answer   audio|text
 │                                        ├ STT        mlx-whisper              🖥
 │                                        ├ Orchestrator (state machine, DB-backed)
 │                                        │   ├ Evaluator          → Claude (structured JSON)
 │                                        │   ├ QuestionGenerator  → llama-server (fine-tuned Qwen3-4B) 🖥
 │                                        │   └ Interviewer        → Claude (greeting / ask / follow-up / close)
 │  ◀── transcript, text, audio_url ──    └ TTS        Kokoro-82M               🖥
 └ /report/[id] ◀───────────────────── GET  /sessions/{id}/report  → Reporter (Claude)
```

**Interview loop:**
1. GREETING.
2. For each question `q_i`, ASK.
3. The user answers. EVALUATE produces `{satisfaction 0–100, scores{correctness, depth, clarity, communication}, covered_points[], missing_points[], follow_up_focus, red_flags[]}`.
4. If `satisfaction < THRESHOLD (70)` and `follow_ups < MAX_FOLLOWUPS (2)`, ask a FOLLOW_UP on `follow_up_focus` and go back to step 3. Otherwise move to the next question.
5. After N questions (5) or the time limit: CLOSING, then REPORT.

The final score for a question is its last satisfaction score minus `FOLLOWUP_PENALTY (5)` for each follow-up it needed. All numbers live in `backend/app/config.py` and can be overridden from `.env`.

## Repo layout (the repo root is this folder)
```
goal.md  plan.md  continuous_improvements.md  CLAUDE.md  .gitignore
data/sample_questions.json
backend/
  app/main.py  app/config.py
  app/api/{catalog,sessions}.py
  app/agents/{base,question_generator,interviewer,evaluator,reporter,orchestrator}.py
  app/llm/{local_client,claude_client}.py
  app/speech/{stt,tts}.py
  app/services/question_picker.py
  app/db/{models,session}.py
  app/prompts/{interviewer,evaluator,reporter}.md
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
- [ ] `git init` and push to GitHub (owner does this or asks Claude to)
- [ ] `backend/` skeleton: `requirements.txt`, `pytest.ini` (with the `local` marker; cloud runs use `-m "not local"`), `.env.example`, `tests/conftest.py`

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

---

## Phase 2: Data ingest and question picker
**Goal:** fast, filterable access to the questions.

**Tests first** (all run on `data/sample_questions.json`):
- `tests/test_ingest.py`
  - Row counts match the sample.
  - Junk company keys are merged into one `General` company with `is_general=1`.
  - Aliases are merged (`AI21 Labs` becomes `AI21`).
  - Question ids are parsed from the slug suffix.
  - Duplicate slugs are stored once.
  - Re-running ingest is idempotent.
- `tests/test_question_picker.py`
  - All filters are optional, and any combination returns N distinct questions.
  - Questions are spread across topics when no topic is given.
  - **Widening order:** drop company → General → drop level. It never returns 0 questions when the profile has any.
  - It excludes questions from the user's recent sessions.
  - Source mix: a selected company with matches gives dataset questions only; otherwise about `GENERATED_RATIO` of slots are generated (with a mocked generator).
  - If the generator is unavailable, it falls back to the dataset.
- `tests/test_api_catalog.py`: `/catalog/companies?q=ama` finds Amazon; profiles, levels and topics are listed and sorted.

**Implement:**
- `app/db/models.py`: `companies`, `profiles`, `levels`, `topics(category: technical|behavioral|dsa)`, `questions`, `question_map` (indexed on the filter combinations), `sessions`, `turns`, `evaluations`.
- `scripts/ingest.py`: streams with `ijson`, takes a `--source` path, and batches inserts. Includes `company_aliases.json` and the topic category list.
- `app/services/question_picker.py` and `app/api/catalog.py`.

**Done when:** tests are green. 🖥 Full ingest finishes in under 15 min with about 131K questions and about 3.86M mappings. `Amazon / AI Engineer / Architect/Principal / AI Agents & Tool Calling` returns the expected questions.

---

## Phase 3: Agents and orchestrator (text only)
**Goal:** a complete interview in the terminal with real follow-up behaviour.

**Tests first** (LLMs faked with deterministic fixtures):
- `tests/test_evaluator.py`
  - Parses valid structured output into the `Evaluation` Pydantic model.
  - Retries once on invalid output, then raises.
  - The rubric text changes by level (Fresher vs Architect).
  - The whole question thread is sent: the main answer plus earlier follow-ups.
- `tests/test_interviewer.py`
  - Each mode (greeting, ask, follow_up, transition, closing) builds the right prompt.
  - The follow-up prompt includes `follow_up_focus` and the missing points.
  - Output is cleaned to plain speakable text: no markdown or lists, and at most about 60 words.
- `tests/test_orchestrator.py` (core)
  - Satisfaction 40 → follow-up. Satisfaction 85 → next question.
  - The follow-up cap is respected (2), then it moves on.
  - The final score applies the penalty.
  - After N questions → CLOSING → state `done`.
  - State survives a "restart": a new orchestrator instance loads from the DB mid-interview.
  - Every follow-up is appended to `data/followup_train.jsonl`.
- `tests/test_reporter.py`: the report has an overall score, a per-question list, strengths and gaps.
- `tests/test_api_sessions.py`: create session → answer in text → … → report, through the FastAPI TestClient.
- Eval set `evals/answers.jsonl`: about 30 labeled answers (strong, partial, weak, off-topic) across levels. `scripts/run_evals.py` reports the G3 metric. It needs the API key, so it is not part of the unit suite.

**Implement:**
- `app/agents/base.py`: `Agent` protocol `async run(ctx) -> result`.
- `app/llm/claude_client.py`: `anthropic` SDK. Model ids come from config: `claude-sonnet-5-5` by default for the evaluator, with `claude-haiku-5-5` as the cheaper option. Uses structured outputs for the evaluator. Check current SDK usage with the `claude-api` skill before writing it.
- `evaluator.py`, `interviewer.py`, `reporter.py`, `orchestrator.py`, and prompts in `app/prompts/*.md`.
- `app/api/sessions.py`: `POST /sessions`, `POST /sessions/{id}/answer` (`text` for now), `POST /sessions/{id}/end`, `GET /sessions/{id}/report`.
- `scripts/text_interview.py`: an interview in the terminal.

**Done when:** tests are green, G3 is at least 80% on the eval set, and a terminal interview with one deliberately weak answer triggers a relevant follow-up.

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

---

## Phase 6: Polish
- Latency (G4): start TTS on the first sentence while the rest generates; play a short pre-generated filler line ("Got it.") while the evaluator runs; keep models warm.
- Error states: mic denied, model server down, API errors. Each gets a calm one-line message with a single retry.
- `scripts/bench_latency.py` 🖥 records p50 and p95.

**Done when:** G1–G8 are all met. **That completes the MVP.**

---

## Phase 7: Next (after the MVP)
- [ ] **Behavioral track:** STAR rubric in the evaluator (situation, task, action, result, ownership, impact), behavioral topic set, follow-ups like "What was *your* specific role?"
- [ ] **LoRA v2:** a new Colab notebook trained on multi-turn data (context + question + answer + evaluator gaps → follow-up), from `data/followup_train.jsonl` plus synthetic Claude conversations, `MAX_LEN` about 1024. Swap `interviewer.py` to it and A/B it against Claude on logged sessions.
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
