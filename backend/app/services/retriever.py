import math
import random
import re
from dataclasses import dataclass, replace

from sqlalchemy import text
from sqlalchemy.engine import Engine

GENERAL = "General"
MAX_TOPIC_SHARE = 0.4
CANDIDATE_LIMIT = 3000
STOPWORDS = frozenset(
    "a an and are as at be by for from how i in is it of on or that the this to was what when where "
    "which who why with you your do does did can could would should".split()
)


@dataclass(frozen=True)
class Filters:
    profile: str
    level: str | None = None
    company: str | None = None
    topic: str | None = None


@dataclass(frozen=True)
class PoolItem:
    id: int
    topic: str
    text: str
    source: str  # dataset | generated
    difficulty: int  # 1 (Fresher) .. 5 (Architect/Principal)
    company_specific: bool = False


def _stages(f: Filters) -> list[tuple[str | None, bool, bool, bool]]:
    """(company, use_level, use_topic, company_specific) in widening order.

    A chosen company is kept as long as possible so the pool stays company-specific
    (G10); then company is dropped, then General, then level, then topic.
    """
    has_company = bool(f.company) and f.company != GENERAL
    raw: list[tuple[str | None, bool, bool, bool]] = []
    if has_company:
        raw += [(f.company, True, True, True), (f.company, True, False, True),
                (f.company, False, True, True), (f.company, False, False, True)]
        raw += [(GENERAL, True, True, False)]
    raw += [(None, True, True, False), (None, False, True, False),
            (None, True, False, False), (None, False, False, False)]
    seen, stages = set(), []
    for company, use_level, use_topic, specific in raw:
        key = (company, use_level and bool(f.level), use_topic and bool(f.topic))
        if key not in seen:
            seen.add(key)
            stages.append((company, use_level and bool(f.level), use_topic and bool(f.topic), specific))
    return stages


def _candidates(conn, f: Filters, company, use_level, use_topic, exclude, salt) -> list[dict]:
    where = ["p.name = :profile", "t.category != 'behavioral'"]  # behavioral is a later track
    params: dict = {"profile": f.profile, "limit": CANDIDATE_LIMIT, "salt": salt}
    if company:
        where.append("c.name = :company")
        params["company"] = company
    if use_level:
        where.append("l.name = :level")
        params["level"] = f.level
    if use_topic:
        where.append("t.name = :topic")
        params["topic"] = f.topic
    sql = f"""
        select distinct q.id, q.text, t.name as topic, l.rank as rank
        from question_map m
        join questions q on q.id = m.question_id
        join companies c on c.id = m.company_id
        join profiles p on p.id = m.profile_id
        join levels l on l.id = m.level_id
        join topics t on t.id = m.topic_id
        where {' and '.join(where)}
        order by (q.id * :salt) % 1000003 limit :limit"""
    rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows if r["id"] not in exclude]


def _target_rank(conn, level: str | None) -> int | None:
    if not level:
        return None
    return conn.execute(text("select rank from levels where name = :n"), {"n": level}).scalar()


def build_pool(engine: Engine, filters: Filters, size: int = 40, seed: int | None = None,
               exclude_ids=frozenset()) -> list[PoolItem]:
    """Up to `size` distinct questions; widens until filled and never returns [] for a known profile."""
    rng = random.Random(seed)
    cap = math.ceil(MAX_TOPIC_SHARE * size) if not filters.topic else size
    exclude = set(exclude_ids)
    salt = rng.randrange(1, 1_000_000) * 2 + 1
    chosen: dict[int, PoolItem] = {}
    topic_counts: dict[str, int] = {}
    leftovers: list[tuple[dict, bool]] = []

    with engine.connect() as conn:
        target = _target_rank(conn, filters.level)
        for company, use_level, use_topic, specific in _stages(filters):
            if len(chosen) >= size:
                break
            rows = [r for r in _candidates(conn, filters, company, use_level, use_topic, exclude, salt)
                    if r["id"] not in chosen]
            rng.shuffle(rows)
            if target is not None:
                rows.sort(key=lambda r: abs(r["rank"] - target))
            rows = list({r["id"]: r for r in reversed(rows)}.values())[::-1]  # one row per question, best level match
            by_topic: dict[str, list[dict]] = {}
            for r in rows:
                by_topic.setdefault(r["topic"], []).append(r)
            order = list(by_topic)
            rng.shuffle(order)
            while len(chosen) < size and any(by_topic.values()):
                for topic in order:
                    if len(chosen) >= size:
                        break
                    queue = by_topic[topic]
                    if not queue:
                        continue
                    if topic_counts.get(topic, 0) >= cap:
                        leftovers.extend((r, specific) for r in queue)
                        queue.clear()
                        continue
                    r = queue.pop(0)
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
                    chosen[r["id"]] = PoolItem(r["id"], r["topic"], r["text"], "dataset", r["rank"], specific)

        # Relax the topic cap only if every stage still left the pool short.
        for r, specific in leftovers:
            if len(chosen) >= size:
                break
            chosen.setdefault(r["id"], PoolItem(r["id"], r["topic"], r["text"], "dataset", r["rank"], specific))
    return list(chosen.values())


def _fts_query(raw: str) -> str | None:
    terms = [t for t in re.findall(r"[a-z0-9]+", raw.lower()) if len(t) > 1 and t not in STOPWORDS]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms)) or None


def search(engine: Engine, query: str, pool: list[PoolItem], limit: int = 20) -> list[PoolItem]:
    """Rank pool items by BM25 keyword match; [] for empty or stop-word-only queries."""
    match = _fts_query(query)
    if not match or not pool:
        return []
    by_id = {p.id: p for p in pool}
    with engine.connect() as conn:
        rows = conn.execute(
            text("select rowid from questions_fts where questions_fts match :q "
                 "order by bm25(questions_fts) limit 500"), {"q": match}).all()
    return [by_id[r[0]] for r in rows if r[0] in by_id][:limit]
