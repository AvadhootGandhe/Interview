# AI Mock Interview Platform

Read these first, in order:
1. `goal.md`: what we're building, the success criteria and the constraints. It wins every conflict.
2. `plan.md`: phased plan with status boxes. Work on the first unticked item.
3. `continuous_improvements.md`: the improve → validate → test → implement → verify → log loop. Follow it once a phase is done.

## Standing rules
- **Tests first, always.** Write a failing test or eval, then the smallest code that makes it pass.
- **UI is Apple-like and minimal:** one primary action per screen, system font, neutral palette plus `#0071e3`, auto dark mode. When in doubt, remove it.
- **Never change the question generator's prompt string.** It must match the LoRA's training format (see `plan.md` Phase 1).
- **Cloud sessions:** the full dataset (`by_company_profile_level_topic.json`), the LoRA weights and the GGUF are local-only and git-ignored. Use `data/sample_questions.json` and the fake LLM/STT/TTS fixtures, and run `pytest -m "not local"`.
- Never commit data dumps, model weights, `.env` or keys.
- Update the `plan.md` status boxes and the `continuous_improvements.md` log before you finish.

## Commands (once scaffolded)
```bash
cd backend && pytest -m "not local" -q            # cloud-safe tests
cd backend && uvicorn app.main:app --reload        # API on :8000
cd frontend && npm run dev                         # UI on :3000
llama-server -m models/interviewer-q4_k_m.gguf --port 8081 -c 2048 -ngl 99   # local only
```
