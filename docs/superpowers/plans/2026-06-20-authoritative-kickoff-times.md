# Authoritative Kickoff Times Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the feed display each match's authoritative kickoff time from the football-data.org provider whenever the match is confidently matched, instead of relying solely on hand-typed scaffold constants.

**Architecture:** `_assign()` attaches the provider's UTC kickoff (`ov["utc"]`) to an override **only** when a non-time signal (team-name overlap or venue/city match) identified the slot. `build()` then derives `DTSTART`, the ET label, and the local-time label from that provider UTC when present, falling back to the scaffold constant otherwise. Tests run against a committed JSON fixture — no network or token.

**Tech Stack:** Python 3 standard library only (the project is intentionally zero-dependency). Tests are a plain `assert`-based script run with `python3 tests/test_feed.py`.

---

## File Structure

- `wc2026_feed.py` (modify) — extract `_fd_to_fixtures()`, update `_assign()` and `build()`.
- `tests/fixtures/wc_matches_sample.json` (create) — small football-data-shaped fixture.
- `tests/test_feed.py` (create) — zero-dependency test runner.
- `.github/workflows/world-cup-feed.yml` (modify) — run tests before building.

Key facts the implementer needs:
- `g(...)` calls build the group stage; `Mexico vs South Africa` is `seq=1`, venue `AZT` (Mexico City, ET offset `-2`), scaffold kickoff 15:00 ET → `utc_of` = `2026-06-11T19:00:00Z`. Its UID is `wc2026-001-AZT@worldcup2026`.
- `Türkiye vs Paraguay` is `seq=22`, venue `LEV` (ET offset `-3`), UID `wc2026-022-LEV@worldcup2026`.
- The first knockout (`ko(...)` num 73) is `seq=73`, venue `SOF` (offset `-3`), scaffold 15:00 ET → `2026-06-28T19:00:00Z`, UID `wc2026-073-SOF@worldcup2026`.
- Provider fixtures use football-data spellings; `canon()` maps `"Turkey"`→`"Türkiye"`, etc.
- `fx["utc"]` is a **naive** `datetime` representing UTC. The tournament is entirely EDT, so UTC→ET is `−4h` (consistent with the existing `utc_of`).

---

## Task 1: Extract `_fd_to_fixtures()` helper (refactor for testability)

**Files:**
- Modify: `wc2026_feed.py` (function `provider_footballdata`, around lines 258-274)
- Create: `tests/fixtures/wc_matches_sample.json`
- Create: `tests/test_feed.py`

- [ ] **Step 1: Create the test fixture**

Create `tests/fixtures/wc_matches_sample.json`:

```json
{
  "matches": [
    {"utcDate": "2026-06-11T20:00:00Z", "status": "FINISHED", "stage": "GROUP_STAGE", "group": "GROUP_A",
     "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
     "score": {"fullTime": {"home": 2, "away": 0}}},
    {"utcDate": "2026-06-20T03:00:00Z", "status": "FINISHED", "stage": "GROUP_STAGE", "group": "GROUP_D",
     "homeTeam": {"name": "Turkey"}, "awayTeam": {"name": "Paraguay"},
     "score": {"fullTime": {"home": 0, "away": 1}}},
    {"utcDate": "2026-06-28T19:30:00Z", "status": "TIMED", "stage": "LAST_32", "group": null,
     "homeTeam": null, "awayTeam": null,
     "score": {"fullTime": {"home": null, "away": null}}}
  ]
}
```

Note: the Mexico fixture time (`20:00Z`) is deliberately one hour off the scaffold (`19:00Z`) to prove the provider time wins.

- [ ] **Step 2: Write the failing test**

Create `tests/test_feed.py`:

```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 tests/test_feed.py`
Expected: `FAIL test_fd_to_fixtures_parses_sample` (AttributeError: module has no attribute `_fd_to_fixtures`).

- [ ] **Step 4: Implement `_fd_to_fixtures` and call it from `provider_footballdata`**

In `wc2026_feed.py`, add this function immediately above `provider_footballdata`:

```python
def _fd_to_fixtures(data):
    """Convert a football-data.org /matches payload into internal fixture dicts."""
    fx=[]
    for m in data.get("matches",[]):
        try: utc=datetime.strptime(m["utcDate"],"%Y-%m-%dT%H:%M:%SZ")
        except Exception: continue
        ft=(m.get("score") or {}).get("fullTime") or {}
        fx.append(dict(utc=utc, home=(m.get("homeTeam") or {}).get("name"),
                       away=(m.get("awayTeam") or {}).get("name"),
                       hs=ft.get("home"),
                       **{"as":ft.get("away")}, status=m.get("status"),
                       city=None))
    return fx
```

Replace the body of `provider_footballdata` (the `fx=[] ... for m in data.get("matches",[]): ...` loop) so it reads:

```python
def provider_footballdata(args, log):
    if not args.token:
        sys.exit("football-data provider needs --token (free key from football-data.org).")
    url="https://api.football-data.org/v4/competitions/WC/matches"
    data=_fd_get(url, args.token, log)
    fx=_fd_to_fixtures(data)
    log.append(f"  football-data: {len(fx)} fixtures fetched")
    return _assign(fx, log)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_feed.py`
Expected: `PASS test_fd_to_fixtures_parses_sample`, exit code 0.

- [ ] **Step 6: Sanity-check the scaffold still generates**

Run: `python3 wc2026_feed.py --provider none --out /tmp/none.ics && grep -c BEGIN:VEVENT /tmp/none.ics`
Expected: `104`.

- [ ] **Step 7: Commit**

```bash
git add wc2026_feed.py tests/test_feed.py tests/fixtures/wc_matches_sample.json
git commit -m "refactor: extract _fd_to_fixtures for testability"
```

---

## Task 2: `_assign()` attaches provider UTC only when confident

**Files:**
- Modify: `wc2026_feed.py` (function `_assign`, lines 203-230)
- Test: `tests/test_feed.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed.py` (above the `if __name__` runner):

```python
def test_assign_attaches_utc_for_group_match():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    # Mexico vs South Africa is seq 1 (confident: team-name overlap) -> utc attached
    assert ov[1].get("utc") == __import__("datetime").datetime(2026, 6, 11, 20, 0), ov.get(1)

def test_assign_no_utc_for_tbd_knockout():
    ov = wc._assign(wc._fd_to_fixtures(load_fixture()), [])
    # The null-team LAST_32 fixture matches scaffold seq 73 by time only -> NO utc
    assert "utc" not in ov.get(73, {}), ov.get(73)
    assert ov.get(73, {}).get("status") == "TIMED", ov.get(73)  # still overlays status
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_feed.py`
Expected: `FAIL test_assign_attaches_utc_for_group_match` (KeyError/None — `utc` not set).

- [ ] **Step 3: Implement the `_assign` change**

In `wc2026_feed.py`, replace the `_assign` loop body. The new version tracks whether a non-time signal identified the winning slot and attaches `utc` only then:

```python
def _assign(fixtures, log):
    """fixtures: list of dicts with utc(datetime), home, away, hs, as, status, city(optional)."""
    out={}
    for fx in fixtures:
        best=None;best_score=-1;best_confident=False
        for m in S:
            mu=utc_of(m)
            dt=abs((mu-fx["utc"]).total_seconds())/60.0
            if dt>180: continue                      # must be same kickoff window
            sc=100-dt                                 # closer time = better
            confident=False
            if fx.get("city") and fx["city"].lower() in V[m["vk"]][1].lower():
                sc+=200; confident=True                # venue/city match is decisive
            # team-name overlap (helps disambiguate simultaneous group games)
            names={canon(fx.get("home")),canon(fx.get("away"))}-{None}
            if names & {m["home"],m["away"]}: sc+=120; confident=True
            if sc>best_score: best_score=sc;best=m;best_confident=confident
        if best is None:
            log.append(f"  ! no scaffold slot for {fx.get('home')} v {fx.get('away')} @ {fx['utc']}")
            continue
        ov={}
        h,a=canon(fx.get("home")),canon(fx.get("away"))
        if h and not h.lower().startswith(("winner","runner","best","loser","group")): ov["home"]=h
        if a and not a.lower().startswith(("winner","runner","best","loser","group")): ov["away"]=a
        if fx.get("hs") is not None: ov["home_score"]=fx["hs"]
        if fx.get("as") is not None: ov["away_score"]=fx["as"]
        if fx.get("status"): ov["status"]=fx["status"]
        # authoritative kickoff: only when a non-time signal confirmed the slot
        if best_confident: ov["utc"]=fx["utc"]
        if ov: out[best["seq"]]=ov
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_feed.py`
Expected: all tests `PASS`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add wc2026_feed.py tests/test_feed.py
git commit -m "feat: _assign attaches provider kickoff time for confident matches"
```

---

## Task 3: `build()` derives times from provider UTC when present

**Files:**
- Modify: `wc2026_feed.py` (function `build`, lines 327-334)
- Test: `tests/test_feed.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed.py` (above the runner):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_feed.py`
Expected: `FAIL test_build_uses_provider_utc` (DTSTART is `20260611T190000Z`, the scaffold time).

- [ ] **Step 3: Implement the `build` change**

In `wc2026_feed.py` `build()`, replace these lines:

```python
        utc=utc_of(m); dtstart=utc.strftime("%Y%m%dT%H%M%SZ")
        dtend=(utc+timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
        et=fmt12(m["h"],m["mi"])
        loc_dt=datetime(2026,m["mo"],m["d"],m["h"],m["mi"])+timedelta(hours=off)
        local=fmt12(loc_dt.hour,loc_dt.minute)
```

with:

```python
        if ov.get("utc") is not None:
            utc=ov["utc"]
            et_dt=utc-timedelta(hours=4)              # provider UTC -> ET (EDT)
        else:
            utc=utc_of(m)
            et_dt=datetime(2026,m["mo"],m["d"],m["h"],m["mi"])  # scaffold ET wall-clock
        dtstart=utc.strftime("%Y%m%dT%H%M%SZ")
        dtend=(utc+timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
        et=fmt12(et_dt.hour,et_dt.minute)
        loc_dt=et_dt+timedelta(hours=off)
        local=fmt12(loc_dt.hour,loc_dt.minute)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_feed.py`
Expected: all tests `PASS`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add wc2026_feed.py tests/test_feed.py
git commit -m "feat: build derives DTSTART/ET/local from provider kickoff when present"
```

---

## Task 4: End-to-end regression test

**Files:**
- Test: `tests/test_feed.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feed.py` (above the runner):

```python
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
```

- [ ] **Step 2: Run the test**

Run: `python3 tests/test_feed.py`
Expected: `PASS` (the build logic already supports this after Task 3). If it fails, the assertion message names the offending match.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feed.py
git commit -m "test: end-to-end group kickoff times match provider"
```

---

## Task 5: Run tests in CI before building the feed

**Files:**
- Modify: `.github/workflows/world-cup-feed.yml`

- [ ] **Step 1: Add a test step before the "Build feed" step**

In `.github/workflows/world-cup-feed.yml`, insert this step immediately before the `- name: Build feed` step (same indentation as the other steps):

```yaml
      - name: Run tests
        run: python3 tests/test_feed.py
```

- [ ] **Step 2: Verify the workflow still parses locally**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/world-cup-feed.yml')); print('yaml ok')"`
Expected: `yaml ok` (if `yaml` is unavailable, instead run `python3 tests/test_feed.py` and confirm exit 0; the indentation matches the surrounding steps).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/world-cup-feed.yml
git commit -m "ci: run feed tests before building"
```

---

## Final verification

- [ ] **Run the full test suite:** `python3 tests/test_feed.py` → all `PASS`, exit 0.
- [ ] **Regenerate against the live provider** (needs `FD_TOKEN`; do not commit the token):
  `python3 wc2026_feed.py --provider footballdata --token "$FD_TOKEN" --out public/fifa-world-cup-2026.ics`
  then confirm the Türkiye/Paraguay event shows `DTSTART:20260620T030000Z` and "11:00 PM ET".
- [ ] **Confirm scaffold-only output is unchanged in count:** `python3 wc2026_feed.py --provider none --out /tmp/none.ics && grep -c BEGIN:VEVENT /tmp/none.ics` → `104`.
- [ ] **Commit the regenerated `.ics`** if it changed.

## Self-Review notes (completed)

- **Spec coverage:** `_assign` confidence gate → Task 2; `build` provider-UTC derivation → Task 3; fixture-driven tests (provider wins / weak-match fallback / e2e) → Tasks 1,3,4; CI without network/token → fixture (Task 1) + Task 5. All spec sections covered.
- **Type consistency:** `ov["utc"]` is a naive `datetime` everywhere (set in `_assign`, read in `build`); `_fd_to_fixtures` returns the same fixture dict shape `_assign` already consumes.
- **No placeholders:** every code step contains complete code; commands include expected output.
