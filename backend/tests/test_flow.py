from app.agents.planner import InterviewPlan, Segment
from app.services.flow import adjust_plan
from app.services.retriever import PoolItem


def item(i, topic, diff, text=None):
    return PoolItem(i, topic, text or f"Question {i} about {topic}", "dataset", diff, True)


POOL = [
    item(1, "Caching", 2), item(2, "Caching", 3), item(3, "Caching", 4), item(4, "Caching", 1),
    item(5, "Kafka", 3, "How do you size Kafka partitions?"),
    item(6, "Databases", 3, "How does Redis persistence work?"),
    item(7, "Databases", 4), item(8, "System Design", 4), item(9, "System Design", 5),
]


def seg(item_, link=""):
    return Segment(theme=item_.topic, topic=item_.topic, difficulty=item_.difficulty,
                   seed_question_id=item_.id, link_from_previous=link)


def make_plan(*ids):
    by_id = {p.id: p for p in POOL}
    return InterviewPlan(segments=[seg(by_id[i]) for i in ids])


def keyword_search(terms, pool):
    words = terms.lower().split()
    return [p for p in pool if any(w in p.text.lower() for w in words)]


def run(plan, idx=0, score=70, terms=(), asked=(1,)):
    return adjust_plan(plan, idx, score, list(terms), POOL, set(asked), keyword_search)


def test_neutral_score_leaves_plan_unchanged():
    plan = make_plan(1, 2, 7, 8, 9)
    new, bridge = run(plan, score=70)
    assert new == plan and bridge is None


def test_high_score_makes_next_question_harder_same_theme():
    plan = make_plan(4, 1, 7, 8, 9)  # next is Caching diff 2
    new, bridge = run(plan, idx=0, score=90, asked=(4,))
    nxt = new.segments[1]
    assert nxt.topic == "Caching" and nxt.difficulty > 2 and nxt.difficulty <= 1 + 2
    assert nxt.seed_question_id != 1 and bridge is None


def test_low_score_makes_next_question_easier_same_theme():
    plan = make_plan(3, 2, 7, 8, 9)  # next is Caching diff 3
    new, _ = run(plan, idx=0, score=40, asked=(3,))
    nxt = new.segments[1]
    assert nxt.topic == "Caching" and nxt.difficulty < 3


def test_no_harder_alternative_keeps_plan():
    plan = make_plan(8, 9, 7, 2, 1)  # next already the hardest System Design
    new, _ = run(plan, idx=0, score=95, asked=(8,))
    assert new == plan


def test_mentioned_term_pulls_matching_upcoming_question_to_next_with_bridge():
    plan = make_plan(1, 2, 3, 6, 8)  # Redis question (6) is upcoming at index 3
    new, bridge = run(plan, idx=0, score=70, terms=["redis"])
    assert new.segments[1].seed_question_id == 6
    assert bridge and "redis" in bridge.lower()
    assert sorted(s.seed_question_id for s in new.segments) == [1, 2, 3, 6, 8]  # nothing lost or duplicated


def test_mentioned_term_with_pool_match_outside_plan_swaps_it_in():
    plan = make_plan(1, 2, 3, 7, 8)
    new, bridge = run(plan, idx=0, score=70, terms=["kafka"])
    assert new.segments[1].seed_question_id == 5 and bridge


def test_never_changes_history_or_beyond_next_and_swap_target():
    plan = make_plan(1, 2, 3, 7, 8)
    new, _ = run(plan, idx=1, score=90, asked=(1, 2))
    assert new.segments[:2] == plan.segments[:2]
    assert new.segments[3:] == plan.segments[3:]


def test_never_picks_already_asked_question():
    plan = make_plan(4, 1, 7, 8, 9)
    new, _ = run(plan, idx=0, score=90, asked=(4, 2, 3))
    assert new.segments[1].seed_question_id not in (2, 3, 4)


def test_unmatched_terms_leave_plan_unchanged():
    plan = make_plan(1, 2, 3, 7, 8)
    new, bridge = run(plan, idx=0, score=70, terms=["zzzz"])
    assert new == plan and bridge is None


def test_last_segment_has_no_next_to_adjust():
    plan = make_plan(1, 2, 3, 7, 8)
    new, bridge = run(plan, idx=4, score=95, terms=["redis"], asked=(1, 2, 3, 7, 8))
    assert new == plan and bridge is None


def test_difficulty_jump_stays_within_limit():
    plan = make_plan(4, 1, 7, 8, 9)
    new, _ = run(plan, idx=0, score=90, asked=(4,))
    assert new.segments[1].difficulty - new.segments[0].difficulty <= 2
