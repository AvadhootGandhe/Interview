You are planning a mock technical interview. Turn the context pack below into an ordered plan that flows like a real interview.

Level expectations: __EXPECTATIONS__

Plan rules:
- Return exactly __TARGET__ segments (never fewer than __MIN__, never more than 6).
- Order: warm-up first, then core concepts, then a deeper scenario or design question, then a stretch question.
- Put related topics next to each other. Never jump between unrelated topics without a reason; say the reason in link_from_previous.
- Segment 1 is a warm-up: its difficulty must be at most __BASELINE__ (the level baseline). Difficulty then rises, never by more than 2 between consecutive segments.
- Every seed_question_id must be copied exactly from the pool in the context pack. Never invent ids. Never use the same id twice.
- __TOPIC_RULE__
- theme is a short phrase for the segment, topic is the topic of the seed question, difficulty is 1 (easiest) to 5 (hardest).
- link_from_previous is one short sentence saying how this segment builds on the previous one. It is empty for segment 1.
- Prefer company-specific questions when the company profile shows a clear focus.

Context pack (JSON):
__CONTEXT__

Return only JSON: {"segments": [{"theme": "...", "topic": "...", "difficulty": 1, "seed_question_id": "...", "link_from_previous": "..."}]}
