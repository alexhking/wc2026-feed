#!/usr/bin/env python3
import os, sys, json, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("wc2026_feed", os.path.join(ROOT, "wc2026_feed.py"))
wc = importlib.util.module_from_spec(spec); spec.loader.exec_module(wc)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "wc_matches_sample.json")
OVERRIDES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "overrides_sample.json")
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


def test_build_uses_provider_utc():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    ev = parse_ics(wc.build(ov))
    mex = event(ev, "wc2026-001-AZT")          # Mexico, provider 20:00Z (off=-2)
    assert mex["DTSTART"] == "20260611T200000Z", mex["DTSTART"]
    assert "4:00 PM ET" in mex["DESCRIPTION"], mex["DESCRIPTION"]
    assert "2:00 PM local" in mex["DESCRIPTION"], mex["DESCRIPTION"]
    tur = event(ev, "wc2026-022-LEV")          # Türkiye, provider 03:00Z (off=-3)
    assert tur["DTSTART"] == "20260620T030000Z", tur["DTSTART"]
    assert "11:00 PM ET" in tur["DESCRIPTION"], tur["DESCRIPTION"]
    assert "8:00 PM local" in tur["DESCRIPTION"], tur["DESCRIPTION"]

def test_build_falls_back_to_scaffold_for_weak_match():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    ev = parse_ics(wc.build(ov))
    ko = event(ev, "wc2026-073-SOF")           # provider 19:30Z but not confident
    assert ko["DTSTART"] == "20260628T190000Z", ko["DTSTART"]   # scaffold 19:00Z wins

def test_build_scaffold_unchanged_with_no_overrides():
    ev = parse_ics(wc.build({}))
    mex = event(ev, "wc2026-001-AZT")
    assert mex["DTSTART"] == "20260611T190000Z", mex["DTSTART"]  # scaffold 15:00 ET
    assert "3:00 PM ET" in mex["DESCRIPTION"], mex["DESCRIPTION"]


def test_group_events_match_provider_utc_end_to_end():
    data = load_fixture()
    ov = wc._assign(wc._fd_to_fixtures(data), [])
    ev = parse_ics(wc.build(ov))
    want = {"20260611T200000Z", "20260620T030000Z"}   # the two group fixtures
    got = set()
    for m in data["matches"]:
        if m["stage"] != "GROUP_STAGE": continue
        compact = m["utcDate"].replace("-", "").replace(":", "")
        # find the event whose teams match and confirm DTSTART == provider time
        hit = [e for e in ev.values()
               if wc.canon(m["homeTeam"]["name"]) in e.get("SUMMARY", "")
               and e["DTSTART"] == compact]
        assert hit, (m["homeTeam"]["name"], compact)
        got.add(compact)
    assert got == want, got


def test_manual_overrides_parses_match_number():
    out = wc._manual_overrides(OVERRIDES, [])
    # Match 79 ("Winner Group A") -> its scaffold seq -> {"home": "Mexico"}
    by_num = {m["num"]: m for m in wc.S if m["num"]}
    seq79 = by_num[79]["seq"]
    assert out == {seq79: {"home": "Mexico"}}, out

def test_merge_overrides_manual_wins_per_field():
    dt = __import__("datetime").datetime(2026, 6, 30, 21, 0)
    base = {79: {"away": "Best 3rd", "utc": dt}}
    merged = wc._merge_overrides(base, {79: {"home": "Mexico"}})
    assert merged[79] == {"away": "Best 3rd", "utc": dt, "home": "Mexico"}, merged[79]

def test_merge_overrides_manual_overwrites_conflicting_field():
    merged = wc._merge_overrides({79: {"home": "Stale"}}, {79: {"home": "Mexico"}})
    assert merged[79]["home"] == "Mexico", merged[79]

def test_manual_layer_resolves_match_79_end_to_end():
    merged = wc._merge_overrides({}, wc._manual_overrides(OVERRIDES, []))
    ev = parse_ics(wc.build(merged))
    m79 = next(e for e in ev.values() if "(Match 79)" in e.get("SUMMARY", ""))
    assert "Mexico" in m79["SUMMARY"], m79["SUMMARY"]


def test_clinched_layer_below_overrides_hand_wins():
    # clinched asserts Brazil for match 79; hand override asserts Mexico -> hand wins
    base = {}
    wc._merge_overrides(base, wc._manual_overrides_from_dict({"79": {"home": "Brazil"}}, []))
    wc._merge_overrides(base, wc._manual_overrides_from_dict({"79": {"home": "Mexico"}}, []))
    by_num = {m["num"]: m for m in wc.S if m["num"]}
    seq79 = by_num[79]["seq"]
    assert base[seq79]["home"] == "Mexico", base[seq79]

def test_clinched_layer_fills_when_no_hand_override():
    base = {}
    wc._merge_overrides(base, wc._manual_overrides_from_dict({"76": {"home": "Brazil"}}, []))
    by_num = {m["num"]: m for m in wc.S if m["num"]}
    seq76 = by_num[76]["seq"]
    assert base[seq76]["home"] == "Brazil", base[seq76]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for t in tests:
        try:
            t(); print("PASS", t.__name__)
        except AssertionError as e:
            fails += 1; print("FAIL", t.__name__, repr(e))
    sys.exit(1 if fails else 0)
