"""Name rules shared by ingest and retrieval: companies, question ids, topic categories."""
from __future__ import annotations

import json
from pathlib import Path

GENERAL = "General"
ALIASES: dict[str, str] = json.loads((Path(__file__).parent / "company_aliases.json").read_text())

# Topic category list. Everything not matched here is "technical".
DSA_TOPICS = {"Data Structures & Algorithms", "Time & Space Complexity", "Aptitude & Logical Reasoning"}
BEHAVIORAL_KEYWORDS = ("Behavioral", "Leadership", "STAR", "Team & Org", "Mentoring", "Stakeholder")


def canonical_company(raw: str) -> str:
    """Junk keys ("(none provided)", "<<<FIELD:companies>>>", "") become General; aliases merge."""
    name = raw.strip()
    if not name or name.startswith(("(", "<")):
        return GENERAL
    return ALIASES.get(name, name)


def parse_question_id(slug: str) -> str:
    """`...-tech-lead-on-an--21834` -> "21834"; DSA slugs end in `-d1743` -> "d1743"."""
    return slug.rsplit("-", 1)[-1]


def topic_category(topic: str) -> str:
    if topic in DSA_TOPICS:
        return "dsa"
    if any(k in topic for k in BEHAVIORAL_KEYWORDS):
        return "behavioral"
    return "technical"
