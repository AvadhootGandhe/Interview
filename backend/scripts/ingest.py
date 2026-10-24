"""Stream the company/profile/level/topic question dump into SQLite.

    python scripts/ingest.py --source ../by_company_profile_level_topic.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

import ijson
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.models import Base  # noqa: E402
from app.services.levels import LEVEL_RANK  # noqa: E402

GENERAL = "General"
SLUG_ID = re.compile(r"-(d?\d+)$")
BATCH = 5000


def topic_category(name: str) -> str:
    if name.startswith("Behavioral"):
        return "behavioral"
    if name.startswith("Data Structures"):
        return "dsa"
    return "technical"


def canonical_company(name: str, aliases: dict[str, str]) -> str:
    name = name.strip()
    if not name or name.startswith(("(", "<")):
        return GENERAL
    return aliases.get(name, name)


class _Lookup:
    """Get-or-create ids for a small dimension table, cached in memory."""

    def __init__(self, conn, table: str, extra=None):
        self.conn, self.table, self.extra, self.cache = conn, table, extra or (lambda n: {}), {}
        self.cache.update({r[1]: r[0] for r in conn.execute(text(f"select id, name from {table}"))})

    def get(self, name: str) -> int:
        if name not in self.cache:
            cols = {"name": name, **self.extra(name)}
            if self.table == "companies":
                cols["is_general"] = int(name == GENERAL)
            keys = ", ".join(cols)
            vals = ", ".join(f":{k}" for k in cols)
            self.cache[name] = self.conn.execute(
                text(f"insert into {self.table} ({keys}) values ({vals})"), cols
            ).lastrowid
        return self.cache[name]


def ingest(source: Path, engine: Engine, aliases_path: Path | None = None) -> None:
    aliases = json.loads(Path(aliases_path).read_text()) if aliases_path else {}
    with engine.begin() as conn:
        companies = _Lookup(conn, "companies")
        profiles = _Lookup(conn, "profiles")
        levels = _Lookup(conn, "levels", lambda n: {"rank": LEVEL_RANK.get(n, 3)})
        topics = _Lookup(conn, "topics", lambda n: {"category": topic_category(n)})
        qids: dict[str, int] = {}
        for qid, slug in conn.execute(text("select id, slug from questions")):
            qids[slug] = qid
        maps: list[dict] = []

        def flush():
            if maps:
                conn.execute(text(
                    "insert or ignore into question_map "
                    "(question_id, company_id, profile_id, level_id, topic_id) "
                    "values (:q, :c, :p, :l, :t)"), maps)
                maps.clear()

        with open(source, "rb") as f:
            for company, by_profile in ijson.kvitems(f, ""):
                cid = companies.get(canonical_company(company, aliases))
                for profile, by_level in by_profile.items():
                    pid = profiles.get(profile)
                    for level, by_topic in by_level.items():
                        lid = levels.get(level)
                        for topic, body in by_topic.items():
                            tid = topics.get(topic)
                            for q in body["questions"]:
                                slug = q["slug"]
                                if slug not in qids:
                                    qid = conn.execute(
                                        text("insert into questions (slug, ext_id, text) values (:s, :e, :t)"),
                                        {"s": slug, "e": SLUG_ID.search(slug).group(1), "t": q["question"]},
                                    ).lastrowid
                                    conn.execute(
                                        text("insert into questions_fts (rowid, text) values (:i, :t)"),
                                        {"i": qid, "t": q["question"]})
                                    qids[slug] = qid
                                maps.append({"q": qids[slug], "c": cid, "p": pid, "l": lid, "t": tid})
                            if len(maps) >= BATCH:
                                flush()
        flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--db", default="sqlite:///./data/app.db")
    ap.add_argument("--aliases", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "company_aliases.json")
    args = ap.parse_args()
    engine = create_engine(args.db)
    Base.metadata.create_all(engine)
    ingest(args.source, engine, args.aliases)
    print("done")


if __name__ == "__main__":
    main()
