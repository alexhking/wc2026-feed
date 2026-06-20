#!/usr/bin/env python3
import os, sys, json, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("wc2026_feed", os.path.join(ROOT, "wc2026_feed.py"))
wc = importlib.util.module_from_spec(spec); spec.loader.exec_module(wc)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "wc_matches_sample.json")
def load_fixture(): return json.load(open(FIXTURE, encoding="utf-8"))

def parse_ics(ics):
    ics = ics.replace("\r\n ", "")            # unfold continuation lines
    events = {}; cur = None
    for line in ics.split("\r\n"):
        if line == "BEGIN:VEVENT": cur = {}
        elif line == "END:VEVENT": events[cur.get("UID", "")] = cur; cur = None
        elif cur is not None and ":" in line:
            k, v = line.split(":", 1); cur[k.split(";")[0]] = v
    return events

def event(events, uid_prefix):
    return next(e for u, e in events.items() if u.startswith(uid_prefix))

def test_fd_to_fixtures_parses_sample():
    fx = wc._fd_to_fixtures(load_fixture())
    assert len(fx) == 3, fx
    mex = next(f for f in fx if f["home"] == "Mexico")
    assert mex["utc"] == __import__("datetime").datetime(2026, 6, 11, 20, 0), mex["utc"]
    assert mex["away"] == "South Africa" and mex["hs"] == 2 and mex["as"] == 0
    ko = next(f for f in fx if f["home"] is None)
    assert ko["away"] is None and ko["hs"] is None


def test_assign_attaches_utc_for_group_match():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    # Mexico vs South Africa is seq 1 (confident: team-name overlap) -> utc attached
    assert ov[1].get("utc") == __import__("datetime").datetime(2026, 6, 11, 20, 0), ov.get(1)

def test_assign_no_utc_for_tbd_knockout():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    # The null-team LAST_32 fixture matches scaffold seq 73 by time only -> NO utc
    assert "utc" not in ov.get(73, {}), ov.get(73)
    assert ov.get(73, {}).get("status") == "TIMED", ov.get(73)  # still overlays status


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for t in tests:
        try:
            t(); print("PASS", t.__name__)
        except AssertionError as e:
            fails += 1; print("FAIL", t.__name__, repr(e))
    sys.exit(1 if fails else 0)
