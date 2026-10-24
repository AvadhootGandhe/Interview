You are planning a spoken technical interview. Build an ordered plan of {n} segments from the context below.

Rules:
- Order: warm-up, core concepts, a deeper scenario or design question, then a stretch question.
- Keep related topics next to each other; avoid abrupt topic jumps.
- Difficulty (1-5) rises gradually. The first segment must not be harder than the level baseline ({baseline}).
  Difficulty may not jump by more than 2 between consecutive segments.
- Use only question ids from the pool. Never repeat a question.
- If the candidate chose a topic, at least 60% of segments must be on that topic; the rest closely related.
- When a company is given, prefer its questions and mirror how it asks.

Reply with JSON only, no prose, in this exact shape:
{"segments": [{"theme": "...", "topic": "...", "difficulty": 1, "seed_question_id": 0, "link_from_previous": "short bridge from the previous segment, empty for the first"}]}

Context:
{pack}
