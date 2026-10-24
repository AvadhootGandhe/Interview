"""Phase 3: the flow controller is pure rules (no LLM): harder / easier / bridge."""
from __future__ import annotations

import copy

from app.config import settings
from app.services.flow import keyword_search, next_segment
from tests.factories import evaluation, plan_of, standard_pool

POOL = standard_pool()
IDS = ["c1", "c2", "m1", "r2", "m2"]  # warm-up -> stretch, caching -> messaging -> databases


def plan():
    return plan_of(POOL, IDS)


def seeds(p):
    return [s.seed_question_id for s in p.segments]


def run(position, score, terms=None, history=None, p=None):
    p = p or plan()
    return next_segment(p, position, history or IDS[: position + 1], evaluation(score, terms), score, POOL)


def test_strong_score_swaps_in_a_harder_question_on_the_same_theme():
    d = run(0, 90)  # next is c2 (Caching, 3); c3 is the harder Caching question
    assert d.reason == "harder" and d.bridge is None
    assert d.segment.seed_question_id == "c3" and d.segment.topic == "Caching"
    assert d.segment.difficulty == 4  # +1 and within 2 of the previous segment (2)
    assert seeds(d.plan) == ["c1", "c3", "m1", "r2", "m2"]


def test_weak_score_swaps_in_an_easier_question():
    d = run(2, 30)  # next is r2 (Databases, 4); r1 (3) is the closest easier one
    assert d.reason == "easier"
    assert d.segment.seed_question_id == "r1"
    assert seeds(d.plan) == ["c1", "c2", "m1", "r1", "m2"]


def test_boundary_scores_use_the_configured_thresholds():
    assert run(0, settings.flow_harder_at).reason == "harder"
    assert run(0, settings.flow_harder_at - 1).reason == "unchanged"
    assert run(2, settings.flow_easier_at).reason == "easier"
    assert run(2, settings.flow_easier_at + 1).reason == "unchanged"


def test_no_matching_alternative_leaves_the_plan_unchanged():
    d = run(3, 95)  # next is m2 (Messaging, 4): nothing harder in Messaging
    assert d.reason == "unchanged" and d.segment.seed_question_id == "m2"
    assert d.plan == plan()


def test_mentioned_term_moves_a_matching_upcoming_question_up_with_a_bridge():
    d = run(0, 70, terms=["redis"])
    assert d.reason == "bridge" and d.bridge == "candidate mentioned Redis"
    assert d.segment.seed_question_id == "r2"
    assert seeds(d.plan) == ["c1", "r2", "m1", "c2", "m2"]  # swapped, nothing lost or duplicated
    assert d.segment.link_from_previous == "candidate mentioned Redis"


def test_bridge_wins_over_harder():
    d = run(0, 92, terms=["redis"])
    assert d.reason == "bridge"


def test_bridge_only_considers_upcoming_questions_and_never_asked_ones():
    assert run(0, 70, terms=["kafka"]).segment.seed_question_id == "m2"  # a later segment moves up
    d = run(3, 70, terms=["redis"], history=["c1", "c2", "m1", "r2"])  # r2 already asked
    assert d.reason == "unchanged" and d.bridge is None


def test_term_that_matches_the_next_question_itself_gives_a_bridge_without_moving():
    d = run(2, 70, terms=["redis"])  # next IS r2
    assert d.bridge == "candidate mentioned Redis"
    assert seeds(d.plan) == IDS


def test_stop_words_and_unknown_terms_do_nothing():
    assert run(0, 70, terms=["the", ""]).reason == "unchanged"
    assert run(0, 70, terms=["blockchain"]).reason == "unchanged"


def test_never_touches_finished_segments_or_repeats_and_input_is_not_mutated():
    p = plan()
    before = copy.deepcopy(p)
    for pos, score, terms in [(0, 90, None), (1, 20, None), (0, 70, ["redis"]), (2, 88, ["kafka"])]:
        d = next_segment(p, pos, IDS[: pos + 1], evaluation(score, terms), score, POOL)
        assert d.plan.segments[: pos + 1] == p.segments[: pos + 1]
        assert len(set(seeds(d.plan))) == len(IDS)
        assert not set(seeds(d.plan)[pos + 1:]) & set(IDS[: pos + 1])
        diffs = [i for i in range(len(IDS)) if d.plan.segments[i].seed_question_id != IDS[i]]
        assert diffs == [] or min(diffs) == pos + 1  # the change always starts at the next segment
    assert p == before


def test_difficulty_stays_within_two_of_the_previous_segment():
    for pos, score in [(0, 95), (2, 10), (1, 90)]:
        d = run(pos, score)
        ds = [s.difficulty for s in d.plan.segments]
        assert all(abs(a - b) <= 2 for a, b in zip(ds[pos:], ds[pos + 1:]))


def test_after_the_last_segment_there_is_no_next():
    d = run(4, 90)
    assert d.segment is None and d.reason == "end" and d.plan == plan()


def test_keyword_search_is_case_insensitive_and_ranks_by_matches():
    hits = keyword_search(["REDIS persistence"], POOL)
    assert hits[0].id == "r2"
    assert keyword_search(["the"], POOL) == []
