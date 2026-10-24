import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

GENERAL = "General"
SAMPLE_QUESTIONS = 30
PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "company_profile.md").read_text()


@dataclass
class CompanyProfileData:
    topic_mix: dict[str, int] = field(default_factory=dict)  # topic -> percent, sums to 100
    summary: str = ""


def _percentages(counts: dict[str, int]) -> dict[str, int]:
    """Largest-remainder rounding so the percentages add up to exactly 100."""
    total = sum(counts.values())
    raw = {k: 100 * v / total for k, v in counts.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: 100 - sum(out.values())]:
        out[k] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


_BASE = """
    from question_map m
    join companies c on c.id = m.company_id
    join profiles p on p.id = m.profile_id
    join levels l on l.id = m.level_id
    join topics t on t.id = m.topic_id
    join questions q on q.id = m.question_id
    where c.name = :company and p.name = :profile and (:level is null or l.name = :level)"""


async def get_company_profile(engine: Engine, llm, company: str | None, profile: str,
                              level: str | None = None) -> CompanyProfileData:
    if not company or company == GENERAL:
        return CompanyProfileData()
    params = {"company": company, "profile": profile, "level": level}
    with engine.connect() as conn:
        counts = dict(conn.execute(text(
            "select t.name, count(distinct q.id)" + _BASE + " group by t.name"), params).all())
        if not counts:
            return CompanyProfileData()
        mix = _percentages(counts)
        cached = conn.execute(text(
            "select cp.summary from company_profiles cp "
            "join companies c on c.id = cp.company_id join profiles p on p.id = cp.profile_id "
            "left join levels l on l.id = cp.level_id "
            "where c.name = :company and p.name = :profile and l.name is :level and cp.summary is not null"),
            params).scalar()
        if cached:
            return CompanyProfileData(mix, cached)
        sample = [r[0] for r in conn.execute(text(
            "select distinct q.text" + _BASE + " order by (q.id * 7919) % 1000003 limit :n"),
            {**params, "n": SAMPLE_QUESTIONS})]

    prompt = PROMPT.format(company=company, profile=profile,
                           level_clause=f" at {level} level" if level else "",
                           questions="\n".join(f"- {s}" for s in sample))
    try:
        summary = (await llm.complete(prompt, max_tokens=250)).strip()
    except Exception:
        return CompanyProfileData(mix, "")  # degrade to the SQL mix; retry next time
    if summary:
        with engine.begin() as conn:
            conn.execute(text(
                "insert into company_profiles (company_id, profile_id, level_id, topic_mix_json, summary) "
                "select c.id, p.id, (select id from levels where name = :level), :mix, :summary "
                "from companies c, profiles p where c.name = :company and p.name = :profile"),
                {**params, "mix": json.dumps(mix), "summary": summary})
    return CompanyProfileData(mix, summary)
