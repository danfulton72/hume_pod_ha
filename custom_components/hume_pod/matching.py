"""Decide which person stepped on the scale.

Pure Python (no Home Assistant imports) so it can be unit tested directly.

Each person has a reference weight (their last weigh-in, or the approximate
weight entered at setup) and, once they have had a barefoot weigh-in, a
reference body-fat %. For a new reading we compute every person's body fat
with *their own* profile and score how far the reading is from their
references, in units of the configured tolerances:

    score = (Δweight / weight_tolerance)² + (Δfat / fat_tolerance)²

A person is only a candidate if their weight is within tolerance. The lowest
score wins, unless the runner-up is too close to call, in which case the
weigh-in is left unassigned for manual assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# How much closer (in tolerance units) the best match must be than the runner-up.
AMBIGUITY_MARGIN = 0.25

REASON_MATCHED = "matched"
REASON_ONLY_NEW_PERSON = "only_new_person"
REASON_NO_MATCH = "no_match"
REASON_AMBIGUOUS = "ambiguous"
REASON_NO_PEOPLE = "no_people"


@dataclass(frozen=True)
class Candidate:
    person_id: str
    ref_weight: float | None
    ref_fat: float | None = None
    # Body fat % for *this* reading computed with this person's profile
    # (None when the reading had no usable impedance).
    fat_now: float | None = None


@dataclass(frozen=True)
class MatchResult:
    person_id: str | None
    reason: str
    # person_id -> distance in tolerance units (sqrt of score), for diagnostics
    distances: dict[str, float]


def match_person(
    weight: float,
    candidates: list[Candidate],
    weight_tolerance: float,
    fat_tolerance: float,
) -> MatchResult:
    if not candidates:
        return MatchResult(None, REASON_NO_PEOPLE, {})

    distances: dict[str, float] = {}
    for cand in candidates:
        if cand.ref_weight is None:
            continue
        dw = (weight - cand.ref_weight) / weight_tolerance
        if abs(dw) > 1:
            continue
        score = dw * dw
        if cand.ref_fat is not None and cand.fat_now is not None:
            df = (cand.fat_now - cand.ref_fat) / fat_tolerance
            score += df * df
        distances[cand.person_id] = round(math.sqrt(score), 3)

    if distances:
        ranked = sorted(distances.items(), key=lambda kv: kv[1])
        best_id, best = ranked[0]
        if len(ranked) > 1 and ranked[1][1] - best < AMBIGUITY_MARGIN:
            return MatchResult(None, REASON_AMBIGUOUS, distances)
        return MatchResult(best_id, REASON_MATCHED, distances)

    # Nobody with history is close. If exactly one person has no history yet,
    # this is most likely their first weigh-in.
    new_people = [c.person_id for c in candidates if c.ref_weight is None]
    if len(new_people) == 1:
        return MatchResult(new_people[0], REASON_ONLY_NEW_PERSON, distances)
    return MatchResult(None, REASON_NO_MATCH, distances)
