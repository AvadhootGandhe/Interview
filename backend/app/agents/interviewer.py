import re
from pathlib import Path

from app.agents.planner import Segment

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "interviewer.md").read_text()
MAX_WORDS = 60


def clean_speech(text: str) -> str:
    """Make model output speakable: no markdown or bullets, one line, at most ~60 words."""
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*`#]", "", text)
    text = " ".join(text.split())
    if len(text.split()) <= MAX_WORDS:
        return text
    out: list[str] = []
    for sentence in re.findall(r"[^.!?]+[.!?]?", text):
        if len(" ".join(out + [sentence.strip()]).split()) > MAX_WORDS:
            break
        out.append(sentence.strip())
    return " ".join(out) if out else " ".join(text.split()[:MAX_WORDS])


class Interviewer:
    def __init__(self, llm, check_intent: bool = False):
        self.llm, self.check_intent = llm, check_intent

    async def _say(self, mode: str, details: str, company: str | None = None) -> str:
        prompt = (PROMPT.replace("{company_clause}", f" at {company}" if company else "")
                  .replace("{mode}", mode).replace("{details}", details))
        return clean_speech(await self.llm.complete(prompt, max_tokens=200, temperature=0.7))

    async def greeting(self, profile: str, level: str, company: str | None = None) -> str:
        return await self._say(
            "greeting",
            f"Greet the candidate warmly in one or two sentences. They are interviewing for a {profile} role "
            f"at {level} level. Say you will ask a few questions, then invite them to start. Do not ask a question yet.",
            company)

    async def ask(self, segment: Segment, seed_question: str, style_examples: list[str],
                  company_summary: str, last_answer_summary: str, company: str | None = None) -> str:
        lines = [f"Segment theme: {segment.theme}", f"Question to ask (keep its intent): {seed_question}"]
        if style_examples:
            lines.append("Similar questions, for tone and style only:\n" + "\n".join(f"- {e}" for e in style_examples))
        if company_summary:
            lines.append(f"How this company interviews: {company_summary}")
        if segment.link_from_previous:
            lines.append(f"Bridge: {segment.link_from_previous}")
        if last_answer_summary:
            lines.append(f"Last answer: {last_answer_summary}")
        lines.append("Start with a short natural transition (acknowledge the last answer if any), "
                     "then ask the question in your own words.")
        spoken = await self._say("ask", "\n".join(lines), company)
        if self.check_intent and not await self._same_intent(seed_question, spoken):
            return seed_question
        return spoken

    async def follow_up(self, question: str, answer: str, focus: str, missing_points: list[str],
                        company: str | None = None) -> str:
        details = (f"Original question: {question}\nCandidate's answer: {answer}\n"
                   f"Follow-up focus: {focus}\nMissing points: {', '.join(missing_points)}\n"
                   "Ask one short follow-up that probes exactly what was missing. Do not reveal the answer.")
        return await self._say("follow_up", details, company)

    async def closing(self, profile: str, company: str | None = None) -> str:
        return await self._say(
            "closing", f"Close the {profile} interview in one or two warm sentences. Thank the candidate "
                       "and say their feedback report is ready. Do not give scores.", company)

    async def _same_intent(self, seed: str, spoken: str) -> bool:
        verdict = await self.llm.complete(
            f"Original question: {seed}\nRephrased: {spoken}\n"
            "Does the rephrased version ask about the same thing as the original? Answer YES or NO only.",
            max_tokens=3, temperature=0)
        return verdict.strip().upper().startswith("YES")
