"""Phase 3: the flow controller. Pure functions, no LLM, only ids from the pool."""
from __future__ import annotations

from types import SimpleNamespace

from helpers import make_pool, seg

from app.agents.planner import InterviewPlan
from app.services.flow import Outcome, apply_next, next_segment

# pool ids: q1 Caching1 q2 Caching2 q3 Caching4 q4 Caching5 | q5 DB1 q6 DB3 q7 DB4 | q8 Msg2 q9 Msg3 q10 Msg5 | q11-14 APIs
PLAN = InterviewPlan.model_validate({"segments": [
    seg("q1", "Caching", 1, ""), seg("q2", "Caching", 2), seg("q6", "Databases", 3),
    seg("q7", "Databases", 4), seg("q9", "Messaging", 3),
]})
NO_TERMS = SimpleNamespace(mentioned_terms=[])


def test_high_score_picks_a_harder_question_on_the_same_theme(pool):
    s, bridge = next_segment(PLAN, [Outcome("q1", 90)], NO_TERMS, pool)
    assert bridge is None
    assert s.topic == "Caching" and s.seed_question_id == "q3"  # d4: the smallest step up from q2 (d2)
    assert s.difficulty == 4


def test_low_score_picks_an_easier_question(pool):
    history = [Outcome("q1", 80), Outcome("q2", 40)]  # next is q6 (Databases d3)
    s, bridge = next_segment(PLAN, history, NO_TERMS, pool)
    assert s.topic == "Databases" and s.seed_question_id == "q5" and s.difficulty == 1 and bridge is None


def test_middle_scores_keep_the_plan(pool):
    for score in (51, 70, 84):
        s, bridge = next_segment(PLAN, [Outcome("q1", score)], NO_TERMS, pool)
        assert s == PLAN.segments[1] and bridge is None


def test_no_alternative_leaves_the_plan_as_it_was(pool):
    # after q1 (asked) the next is q2 (Caching d2): no easier unasked, unplanned Caching question exists
    s, _ = next_segment(PLAN, [Outcome("q1", 10)], NO_TERMS, pool)
    assert s == PLAN.segments[1]
    # the hardest Caching question is d5; once q4 is the plan's, nothing harder exists
    plan = InterviewPlan.model_validate({"segments": [seg("q1", "Caching", 1, ""), seg("q4", "Caching", 5)]})
    s, _ = next_segment(plan, [Outcome("q1", 99)], NO_TERMS, pool)
    assert s == plan.segments[1]


def test_never_picks_an_already_asked_or_already_planned_question(pool):
    # q3 (d4) was already asked, q4 is another segment's seed -> no harder Caching question is left
    plan = InterviewPlan.model_validate({"segments": [
        seg("q1", "Caching", 1, ""), seg("q2", "Caching", 2), seg("q4", "Messaging", 4, theme="x"),
    ]})
    s, _ = next_segment(plan, [Outcome("q1", 95), ], NO_TERMS, [p for p in pool if p.id != "q3"])
    assert s.seed_question_id not in {"q1", "q4"}
    s, _ = next_segment(plan, [Outcome("q3", 95)], NO_TERMS, pool)
    assert s.seed_question_id != "q3"


def test_every_chosen_id_comes_from_the_pool(pool):
    ids = {p.id for p in pool}
    for score in (0, 40, 60, 90, 100):
        for n in range(1, 5):
            history = [Outcome(PLAN.segments[i].seed_question_id, score) for i in range(n)]
            s, _ = next_segment(PLAN, history, NO_TERMS, pool)
            assert s.seed_question_id in ids


def test_mentioned_term_pulls_a_matching_upcoming_question_forward_with_a_bridge():
    pool = make_pool()
    pool[8].text = "How would you use Redis to rate limit a public API?"  # q9, last segment
    terms = SimpleNamespace(mentioned_terms=["redis"])
    s, bridge = next_segment(PLAN, [Outcome("q1", 70)], terms, pool)
    assert s.seed_question_id == "q9"
    assert bridge == "candidate mentioned Redis"
    assert s.bridge == bridge

    plan = apply_next(PLAN, 1, s)
    ids = [x.seed_question_id for x in plan.segments]
    assert ids[1] == "q9" and sorted(ids) == sorted(["q1", "q2", "q6", "q7", "q9"])  # swapped, no duplicates
    assert plan.segments[0] == PLAN.segments[0] and plan.segments[2] == PLAN.segments[2]
    assert plan.segments[4].seed_question_id == "q2"  # the displaced question took the vacated slot


def test_search_function_is_injectable_and_used_for_matching():
    pool = make_pool()
    calls = []

    def search(terms, items):
        calls.append((terms, [i.id for i in items]))
        return [i for i in items if i.id == "q7"]

    s, bridge = next_segment(PLAN, [Outcome("q1", 70)], SimpleNamespace(mentioned_terms=["Kafka"]), pool, search=search)
    assert s.seed_question_id == "q7" and bridge == "candidate mentioned Kafka"
    assert calls and set(calls[0][1]) == {"q2", "q6", "q7", "q9"}  # only upcoming segments' questions are searched


def test_mention_that_matches_the_next_question_only_adds_a_bridge():
    pool = make_pool()
    pool[1].text = "Explain Redis eviction policies."  # q2 is already the next question
    s, bridge = next_segment(PLAN, [Outcome("q1", 70)], SimpleNamespace(mentioned_terms=["redis"]), pool)
    assert s.seed_question_id == "q2" and bridge == "candidate mentioned Redis"


def test_asked_questions_are_never_bridged_back_in():
    pool = make_pool()
    pool[0].text = "Redis basics?"  # q1 was asked already
    s, bridge = next_segment(PLAN, [Outcome("q1", 70)], SimpleNamespace(mentioned_terms=["redis"]), pool)
    assert s == PLAN.segments[1] and bridge is None


def test_flow_changes_at_most_the_next_segment_and_never_mutates_the_plan(pool):
    before = PLAN.model_dump()
    next_segment(PLAN, [Outcome("q1", 95)], NO_TERMS, pool)
    assert PLAN.model_dump() == before
    s, _ = next_segment(PLAN, [Outcome("q1", 95)], NO_TERMS, pool)
    changed = apply_next(PLAN, 1, s)
    diff = [i for i, (a, b) in enumerate(zip(PLAN.segments, changed.segments)) if a != b]
    assert diff == [1]


def test_end_of_plan_returns_none(pool):
    history = [Outcome(x.seed_question_id, 70) for x in PLAN.segments]
    assert next_segment(PLAN, history, NO_TERMS, pool) == (None, None)


def test_flow_module_never_touches_an_llm():
    import app.services.flow as flow

    source = open(flow.__file__).read()
    assert "anthropic" not in source and "complete(" not in source and "app.llm" not in source
