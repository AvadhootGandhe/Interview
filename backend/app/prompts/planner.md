You are planning a mock technical interview so that it flows like a real one: warm-up, then core concepts, then deeper scenarios or design, then a stretch. Related topics sit next to each other. The interview is for a $profile candidate at level $level$company_line.

Below is the context pack: the company profile, what is expected at this level, and the pool of candidate questions. Every question has an id, a topic, a difficulty (1 easiest to 5 hardest) and a source.

<context_pack>$pack</context_pack>

Return the plan as JSON: {"segments": [{"theme", "topic", "difficulty", "seed_question_id", "link_from_previous"}, ...]}.

Rules (a plan that breaks any of them is rejected):
- $count_rule
- Every seed_question_id must be an id from the pool above. Never invent one, and never use the same id twice.
- Segment 1 is a warm-up: its difficulty is at most $baseline.
- Difficulty rises overall but never changes by more than $max_jump between two neighbouring segments.
- Keep related topics next to each other; the topic of each segment must be the topic of its seed question.
- $topic_rule
- theme is a short phrase for what this segment explores (for example "Core concepts: cache eviction"). link_from_previous is one short sentence on how this segment follows the previous one (empty for the first).
- Prefer questions that match the company profile, but follow the rules above first.
