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

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for t in tests:
        try:
            t(); print("PASS", t.__name__)
        except AssertionError as e:
            fails += 1; print("FAIL", t.__name__, repr(e))
    sys.exit(1 if fails else 0)
