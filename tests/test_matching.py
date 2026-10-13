"""Unit tests for weigh-in attribution."""

import importlib.util
import pathlib
import sys

BASE = pathlib.Path(__file__).parents[1] / "custom_components" / "hume_pod"
spec = importlib.util.spec_from_file_location("hp_matching", BASE / "matching.py")
m = importlib.util.module_from_spec(spec)
sys.modules["hp_matching"] = m
spec.loader.exec_module(m)
C = m.Candidate


def run(weight, cands, wt=3.0, ft=4.0):
    return m.match_person(weight, cands, wt, ft)


def test_clear_weight_match():
    r = run(80.4, [C("dan", 80.0), C("sam", 62.0)])
    assert (r.person_id, r.reason) == ("dan", m.REASON_MATCHED)


def test_similar_weight_split_by_fat():
    # Same weight; reading's fat (as computed per profile) only fits sam.
    cands = [C("dan", 70.0, ref_fat=18.0, fat_now=27.5), C("sam", 70.5, ref_fat=28.0, fat_now=28.2)]
    r = run(70.2, cands)
    assert r.person_id == "sam"


def test_similar_weight_without_fat_is_ambiguous():
    r = run(70.2, [C("dan", 70.0), C("sam", 70.4)])
    assert (r.person_id, r.reason) == (None, m.REASON_AMBIGUOUS)


def test_guest_not_matched():
    r = run(105.0, [C("dan", 80.0), C("sam", 62.0)])
    assert (r.person_id, r.reason) == (None, m.REASON_NO_MATCH)


def test_first_weigh_in_goes_to_only_new_person():
    r = run(62.0, [C("dan", 80.0), C("sam", None)])
    assert (r.person_id, r.reason) == ("sam", m.REASON_ONLY_NEW_PERSON)


def test_two_new_people_unassigned():
    r = run(62.0, [C("dan", None), C("sam", None)])
    assert r.person_id is None


def test_single_person_bootstrap():
    assert run(93.0, [C("dan", None)]).person_id == "dan"


def test_known_person_beats_new_person():
    r = run(80.5, [C("dan", 80.0), C("sam", None)])
    assert r.person_id == "dan"


def test_no_people():
    assert run(80.0, []).reason == m.REASON_NO_PEOPLE


def test_tolerance_option_respected():
    assert run(84.0, [C("dan", 80.0)], wt=3.0).person_id is None
    assert run(84.0, [C("dan", 80.0)], wt=5.0).person_id == "dan"


def test_single_person_estimate_far_off_still_assigned():
    r = run(63.5, [C("dan", 75.0, ref_is_estimate=True)])
    assert (r.person_id, r.reason) == ("dan", m.REASON_ONLY_NEW_PERSON)
    assert r.distances["dan"] > 1  # reported for diagnostics


def test_estimates_get_wider_tolerance():
    # 6 kg from the estimate is within 3x3 kg; still beats a measured person 10 kg away
    cands = [C("dan", 69.5, ref_is_estimate=True), C("sam", 53.5)]
    r = run(63.5, cands)
    assert (r.person_id, r.reason) == ("dan", m.REASON_MATCHED)


def test_measured_single_person_still_rejects_guests():
    r = run(63.5, [C("dan", 75.0)])
    assert (r.person_id, r.reason) == (None, m.REASON_NO_MATCH)
    assert r.distances == {"dan": round(11.5 / 3, 3)}
