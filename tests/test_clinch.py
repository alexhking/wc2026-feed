#!/usr/bin/env python3
import os, sys, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, name + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
cl = _load("wc2026_clinch")

def test_slot_map_winner_and_runner_slots():
    sm = cl.slot_map()
    assert sm[("A", "W")] == (79, "home"), sm[("A", "W")]
    assert sm[("D", "W")] == (81, "home"), sm[("D", "W")]
    assert sm[("A", "R")] == (73, "home"), sm[("A", "R")]
    assert sm[("B", "R")] == (73, "away"), sm[("B", "R")]
    assert sm[("C", "R")] == (75, "away"), sm[("C", "R")]
    # 12 winner + 12 runner-up placements exist
    assert sum(1 for k in sm if k[1] == "W") == 12, sm
    assert sum(1 for k in sm if k[1] == "R") == 12, sm

def test_build_group_results_shape_and_played_flag():
    # seq 1 = Mexico v South Africa (Group A, MD1); mark it FINISHED 2-0
    assigned = {1: {"home_score": 2, "away_score": 0, "status": "FINISHED"}}
    groups = cl.build_group_results(assigned)
    assert set(groups) == set(cl.GROUPS), set(groups)
    assert len(groups["A"]) == 6, len(groups["A"])
    mex = groups["A"][0]
    assert mex["home"] == "Mexico" and mex["away"] == "South Africa"
    assert mex["hs"] == 2 and mex["as"] == 0 and mex["played"] is True, mex
    # an untouched match is not played
    assert groups["A"][1]["played"] is False, groups["A"][1]

def _M(home, away, hs=None, as_=None, played=False):
    return {"home": home, "away": away, "hs": hs, "as": as_, "played": played}

def test_points_counts_wins_draws():
    decided = [{"home": "A", "away": "B", "outcome": "H"},
               {"home": "A", "away": "C", "outcome": "D"}]
    pts = cl._points(["A", "B", "C"], decided)
    assert pts == {"A": 4, "B": 0, "C": 1}, pts

def test_h2h_first_beats_goal_difference():
    # Finished group. Mexico & South Korea both 6 pts; Mexico won H2H but South
    # Korea has the bigger overall GD. 2026 rule -> Mexico ranks above.
    M = [
        _M("Mexico", "South Africa", 1, 0, True),     # MEX +3
        _M("South Korea", "Czechia", 5, 0, True),     # SK  +3 (big GD)
        _M("Czechia", "South Africa", 0, 1, True),    # SA  +3
        _M("Mexico", "South Korea", 1, 0, True),      # MEX +3 (H2H over SK)
        _M("Czechia", "Mexico", 1, 0, True),          # CZE +3, MEX loss
        _M("South Africa", "South Korea", 0, 3, True),# SK  +3 (big GD)
    ]
    bw = cl.best_worst(M, {})
    # Mexico 6 (GD +1), South Korea 6 (GD +7) -> Mexico above on H2H
    assert bw["Mexico"] == (1, 1), bw
    assert bw["South Korea"] == (2, 2), bw

def test_finished_group_resolves_runner_up_on_overall_gd():
    # A and B tie on 4 pts, drew head-to-head (equal H2H goals); A has better
    # overall GD -> A is 2nd, B is 3rd. D wins the group.
    M = [
        _M("A", "B", 1, 1, True),   # draw
        _M("A", "C", 3, 0, True),   # A +3, GD+3
        _M("D", "A", 1, 0, True),   # A loss
        _M("B", "C", 1, 0, True),   # B +3, GD+1
        _M("B", "D", 0, 1, True),   # B loss
        _M("C", "D", 0, 1, True),   # D win
    ]
    bw = cl.best_worst(M, {})
    # D: 9, A: 4 (GD +2), B: 4 (GD 0), C: 0
    assert bw["D"] == (1, 1), bw
    assert bw["A"] == (2, 2), bw
    assert bw["B"] == (3, 3), bw

def test_pending_match_makes_tie_ambiguous_block():
    # In a given branch, D and {A,B} land tied; A has an UNPLAYED match, so the
    # A/B order would fall to overall GD which is unknown -> one ambiguous block.
    M = [
        _M("A", "B", 1, 1, True),   # draw, h2h equal
        _M("A", "C", 2, 0, True),   # A +3
        _M("D", "A", played=False), # PENDING (index 2)
        _M("B", "C", 1, 0, True),   # B +3
        _M("D", "B", 1, 0, True),   # B loss, D +3
        _M("C", "D", 0, 0, True),   # draw
    ]
    # branch: D beats A in the pending match
    bw = cl.best_worst(M, {2: "H"})
    # pts: D = 3(vs B)+1(vs C draw? C-D draw)+3(vs A) ; A = 1+3+0 = 4 ; B = 1+3 = 4
    # A and B tie at 4, h2h draw, A has a None-score match -> ambiguous {A,B}
    assert bw["A"][0] != bw["A"][1], bw          # spread, not pinned
    assert bw["A"] == bw["B"], (bw["A"], bw["B"])

def test_clinched_winner_when_rival_cannot_catch_or_loses_h2h():
    # Group D, pre-matchday-3 (USA already 6 pts, beat both rivals it played).
    # USA's last match (vs Türkiye) and Paraguay-Australia are pending.
    M = [
        _M("USA", "Paraguay", 2, 0, True),       # USA +3
        _M("Australia", "Türkiye", 1, 0, True),  # AUS +3
        _M("USA", "Australia", 1, 0, True),      # USA +3 (=6), beat AUS (H2H)
        _M("Türkiye", "Paraguay", 0, 0, True),   # draw: TUR 1, PRY 1
        _M("Türkiye", "USA", played=False), # PENDING (index 4)
        _M("Paraguay", "Australia", played=False),    # PENDING (index 5)
    ]
    pins = cl.clinched_positions(M)
    # USA guaranteed 1st: TUR max = 1+3 = 4 < 6; AUS max = 3+3 = 6 but USA won H2H.
    assert pins.get("USA") == 1, pins
    # Nobody else is pinned to an exact placement yet.
    assert set(pins) == {"USA"}, pins

def test_clinched_both_places_in_finished_group():
    M = [
        _M("Mexico", "South Africa", 2, 0, True),
        _M("South Korea", "Czechia", 1, 0, True),
        _M("Czechia", "South Africa", 0, 1, True),
        _M("Mexico", "South Korea", 1, 0, True),
        _M("Czechia", "Mexico", 0, 1, True),
        _M("South Africa", "South Korea", 1, 0, True),
    ]
    # Mexico 9, South Africa 6, South Korea 3, Czechia 0
    pins = cl.clinched_positions(M)
    assert pins == {"Mexico": 1, "South Africa": 2}, pins

def test_no_clinch_when_placement_hangs_on_pending_goal_difference():
    # Leader not yet separable from a rival because the deciding rung is GD and a
    # contributing match is still pending -> emit nothing.
    M = [
        _M("A", "B", 1, 1, True),
        _M("A", "C", 1, 0, True),
        _M("D", "A", played=False),   # PENDING
        _M("B", "C", 1, 0, True),
        _M("D", "B", played=False),   # PENDING
        _M("C", "D", played=False),   # PENDING
    ]
    pins = cl.clinched_positions(M)
    assert pins == {}, pins

def test_resolve_maps_pins_to_clinched_json_dict():
    # Group A finished -> Mexico winner (79 home), South Africa runner-up (73 home)
    assigned = {}
    # seq -> override; use scaffold seqs for Group A's six matches (seq 1..6)
    scores = {1: (2, 0), 2: (1, 0), 3: (0, 1), 4: (1, 0), 5: (0, 1), 6: (1, 0)}
    for seq, (h, a) in scores.items():
        assigned[seq] = {"home_score": h, "away_score": a, "status": "FINISHED"}
    out = cl.resolve(assigned)
    assert out.get("79") == {"home": "Mexico"}, out.get("79")
    assert out.get("73", {}).get("home") == "South Africa", out.get("73")

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for t in tests:
        try:
            t(); print("PASS", t.__name__)
        except AssertionError as e:
            fails += 1; print("FAIL", t.__name__, repr(e))
    sys.exit(1 if fails else 0)
