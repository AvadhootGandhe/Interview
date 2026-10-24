# Backend API

Base URL `http://localhost:8000`. JSON unless noted. Errors are `{"detail": "<short message>"}`; voice errors also carry `"code"`.
Every session endpoint returns a `Server-Timing` header (`stt, evaluate, flow, interviewer, tts, total`, ms).

## Settings that matter to the UI
`SPEECH=auto|real|fake|off` (default `auto`: real STT/TTS unless `FAKE_LLM=1`, then off). When speech is off, `audio_url` is `null` and audio answers get 503; use text.

## POST /sessions
Request: `{"profile": "Backend", "level": "SDE-2/3", "company": null, "topic": null, "user_id": null}` (`company`, `topic`, `user_id` optional).

Response 200 (`SessionReply`, shared by `/answer` and `/end`):
```json
{
  "session_id": "…", "text": "greeting + question, one string", "kind": "ask|follow_up|closing",
  "state": "asking|done", "done": false, "question_index": 0, "total_questions": 5,
  "messages": [{"kind": "greeting", "text": "…"}, {"kind": "ask", "text": "…"}],
  "audio_url": "/audio/<hash>.wav",
  "audio_urls": ["/audio/<s1>.wav", "/audio/<s2>.wav"],
  "transcript": null,
  "evaluation": null
}
```
- `audio_url` speaks the whole `text` (for start: greeting + first question as one clip). It is `null` if speech is off or TTS failed; always show `text` regardless. Fetch it from the same origin as the API (`GET /audio/{file}`, `audio/wav`).
- `audio_urls` (time to first audio): one clip per sentence, in speaking order. Only `audio_urls[0]` is rendered when the response arrives; the rest render in the background (~0.3-0.5 s each). **To start speaking as early as possible, play `audio_urls[0]`, then the next ones in order.** Fetching a clip that is still rendering simply waits for it (up to 30 s), so you can request them all at once and queue them. `audio_url` is unchanged (the whole text as one clip) and also waits until the background render finishes; clients that ignore `audio_urls` keep working but start later. A one-sentence reply has `audio_urls == [audio_url]`; speech off or TTS failed gives `[]` and `null`.
- For single-message replies `messages[0].audio_url` equals `audio_url`.
- Errors: 422 bad filters / empty pool, 502 Claude unavailable.

## POST /sessions/{id}/answer
Two request forms:
1. Voice: `multipart/form-data` with file field `audio` (any browser format: webm, ogg, mp4, wav; converted by ffmpeg).
2. Text: `application/json` `{"text": "…"}` (non-empty).

Response 200: `SessionReply` as above, plus `transcript` (what the candidate said, or the typed text) and `evaluation`
`{"satisfaction": 0-100, "missing_points": [], "mentioned_terms": []}`. `kind` is `follow_up` (probe the same question), `ask` (next question; `question_index` advanced) or `closing` (`done: true`, then GET the report).

Voice errors (the interview does not advance; the candidate can simply try again):
| status | `code` | when | `detail` |
|---|---|---|---|
| 422 | `no_speech` | empty or silent recording, or nothing transcribed | "I didn't catch that. Could you say it again?" |
| 503 | `speech_unavailable` | STT is off on the server | "Voice answers are not available. Please type your answer." |
| 502 | `stt_failed` | the STT engine crashed | "I couldn't process that recording. Please try again." |

Other errors: 404 unknown session, 409 interview already over, 422 missing `audio` field or empty `text`, 502 Claude unavailable.

## POST /sessions/{id}/end
No body. Closes early. Response: `SessionReply` with `kind: "closing"`, `done: true`, `audio_url` for the closing line. 409 if already over.

## GET /sessions/{id}/report
Only when `done`. Response: `{"overall_score", "strengths", "gaps", "verdict", "questions": [{"thread": [{"role", "text"}], …}], …}` (see `app/agents/reporter.py`). 409 if the interview is not finished.

## GET /audio/{file}
Cached interviewer audio (`audio/wav`). A clip that is still rendering in the background is awaited (up to 30 s); 404 for unknown or unsafe names, or a clip whose rendering failed.

On server start the speech models are warmed in a background task (`/health` answers at once). `TTS_CACHE=0` disables the audio cache (for honest benchmarks only).

## Catalog and health
`GET /health` returns `{"status": "ok"}`. Catalog routes (profiles, levels, companies, topics) live in `app/api/catalog.py`.
