# Clinch Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically resolve mathematically-clinched group winners and runners-up into the World Cup feed, replacing hand-typed `overrides.json` entries for those slots.

**Architecture:** A new standalone script `wc2026_clinch.py` imports and reuses `wc2026_feed.py` (fetch, scaffold, `_assign`), adds a standings engine + conservative clinch prover, and writes a machine-owned `clinched.json` using the same schema as `overrides.json`. The feed gains a `--clinched` layer applied between the live provider and the hand-owned `overrides.json` (hand wins over machine wins over provider). No third-place-slot logic.

**Tech Stack:** Python 3.12+ standard library only (no third-party deps). Tests are plain-assert functions run by a `__main__` runner, matching `tests/test_feed.py`.

## Global Constraints

- **Standard library only** — no new dependencies (matches the existing project).
- **Never a false positive** — the prover asserts a placement only when guaranteed across every remaining-result combination; when uncertain, emit nothing.
- **`clinched.json` schema is identical to `overrides.json`** — `{ "<match_num>": { "home"|"away": "<Team>" } }`, keys are stringified official match numbers.
- **Layer precedence:** live provider → `clinched.json` → `overrides.json` (later wins per field).
- **Reuse, don't duplicate** — import `S`, `V`, `canon`, `utc_of`, `_fd_get`, `_fd_to_fixtures`, `_assign` from `wc2026_feed`.
- **Team names** are the scaffold's canonical labels (already canonical); use `canon()` only on provider-sourced strings.
- Scope: **group winners + runners-up only.** No `Best 3rd (…)`, no Round of 16+.

---

## Task 1: Add `--clinched` layer to the feed

**Files:**
- Modify: `wc2026_feed.py` (the `main()` argparse + merge block, ~`wc2026_feed.py:390-403`)
- Test: `tests/test_feed.py` (append tests + they run via existing `__main__` runner)

**Interfaces:**
- Consumes: existing `_manual_overrides(path, log)` and `_merge_overrides(base, layer)`.
- Produces: a `--clinched PATH` CLI flag layered below `--overrides`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_feed.py` before the `if __name__` block:

```python
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
```

This requires a small refactor: extract the dict-parsing core of `_manual_overrides` into `_manual_overrides_from_dict(raw, log)` so both a file and an in-memory dict can be parsed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_feed.py`
Expected: FAIL — `AttributeError: module 'wc2026_feed' has no attribute '_manual_overrides_from_dict'`

- [ ] **Step 3: Refactor `_manual_overrides` to expose a dict parser**

In `wc2026_feed.py`, replace the body of `_manual_overrides` so the file loader delegates to a new dict-based function:

```python
def _manual_overrides_from_dict(raw, log):
    """Parse a {key: override} dict into {seq: override}. Keyed by official match
    number (str/int) or 'YYYY-MM-DD@City'."""
    by_num={m["num"]:m for m in S if m["num"]}
    out={}
    for k,v in raw.items():
        target=None
        if str(k).isdigit() and int(k) in by_num:
            target=by_num[int(k)]
        elif "@" in str(k):
            ds,city=k.split("@",1)
            for m in S:
                if utc_of(m).date().isoformat()==ds and city.lower() in V[m["vk"]][1].lower():
                    target=m;break
        if not target:
            log.append(f"  ! manual key {k} matched no match"); continue
        ov={}
        if v.get("home"): ov["home"]=canon(v["home"])
        if v.get("away"): ov["away"]=canon(v["away"])
        for f1 in ("home_score","away_score","status"):
            if v.get(f1) is not None: ov[f1]=v[f1]
        out[target["seq"]]=ov
    return out

def _manual_overrides(path, log):
    """Parse an overrides.json file into {seq: override}."""
    raw=json.load(open(path,encoding="utf-8"))
    return _manual_overrides_from_dict(raw, log)
```

- [ ] **Step 4: Add the `--clinched` flag and merge ordering in `main()`**

Add the argument next to `--overrides`:

```python
    ap.add_argument("--clinched",help="machine-generated clinched.json layer "
                    "(applied below --overrides; hand overrides win)")
```

Replace the override-merge block in `main()` with:

```python
    overrides=PROVIDERS[args.provider](args,log)
    if args.clinched and args.provider!="manual":
        clinched=_manual_overrides(args.clinched, log)
        _merge_overrides(overrides, clinched)
        log.append(f"  clinched layer: {len(clinched)} overrides merged on top of {args.provider}")
    if args.overrides and args.provider!="manual":
        manual=_manual_overrides(args.overrides, log)
        _merge_overrides(overrides, manual)
        log.append(f"  manual layer: {len(manual)} overrides merged on top of {args.provider}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_feed.py`
Expected: PASS for all tests (existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add wc2026_feed.py tests/test_feed.py
git commit -m "feat: --clinched override layer below --overrides"
```

---

## Task 2: Clinch module scaffolding — group results + slot map

**Files:**
- Create: `wc2026_clinch.py`
- Create: `tests/test_clinch.py`

**Interfaces:**
- Consumes: `S`, `V`, `canon`, `utc_of`, `_fd_get`, `_fd_to_fixtures`, `_assign` from `wc2026_feed`.
- Produces:
  - `GROUPS = "ABCDEFGHIJKL"`
  - `build_group_results(assigned) -> {grp: [ {home,away,hs,as,played}, ... ]}`
  - `slot_map() -> {(grp, 'W'|'R'): (num, 'home'|'away')}`

- [ ] **Step 1: Write the failing tests** — create `tests/test_clinch.py`:

```python
#!/usr/bin/env python3
import os, sys, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_clinch.py`
Expected: FAIL — `ModuleNotFoundError`/load error: `wc2026_clinch.py` does not exist.

- [ ] **Step 3: Create `wc2026_clinch.py` with imports + the two functions**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wc2026_clinch.py - compute mathematically-clinched group winners/runners-up
from football-data.org results and emit them as a clinched.json override layer.

Only asserts a placement when it is guaranteed across EVERY remaining-result
combination (conservative: never a false positive). Group winners and runners-up
only; third-place slots are left to the official provider / hand overrides.
"""
import argparse, itertools, json, re, sys
from wc2026_feed import (S, V, canon, utc_of, _fd_get, _fd_to_fixtures, _assign)

GROUPS = "ABCDEFGHIJKL"

def build_group_results(assigned):
    """assigned: {seq: override} from _assign. Returns {grp: [match,...]} where
    each match is {home, away, hs, as, played}. Teams come from the scaffold
    (already canonical); scores/status come from the provider overlay."""
    groups = {g: [] for g in GROUPS}
    for m in S:
        if m["kind"] != "G":
            continue
        ov = assigned.get(m["seq"], {})
        hs = ov.get("home_score"); as_ = ov.get("away_score")
        played = ov.get("status") == "FINISHED" and hs is not None and as_ is not None
        groups[m["grp"]].append({"home": m["home"], "away": m["away"],
                                 "hs": hs, "as": as_, "played": played})
    return groups

_SLOT_RE = re.compile(r"^(Winner|Runner-up) Group ([A-L])$")

def slot_map():
    """Scan the R32 scaffold for 'Winner Group X' / 'Runner-up Group X' labels.
    Returns {(grp, 'W'|'R'): (official_match_num, 'home'|'away')}."""
    out = {}
    for m in S:
        if m["rnd"] != "Round of 32":
            continue
        for side in ("home", "away"):
            mm = _SLOT_RE.match(m[side])
            if mm:
                placement = "W" if mm.group(1) == "Winner" else "R"
                out[(mm.group(2), placement)] = (m["num"], side)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_clinch.py`
Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
git add wc2026_clinch.py tests/test_clinch.py
git commit -m "feat: clinch module scaffolding (group results + slot map)"
```

---

## Task 3: Standings engine — points, tiebreaks, rank blocks

**Files:**
- Modify: `wc2026_clinch.py` (add functions)
- Test: `tests/test_clinch.py` (append tests)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `_points(teams, decided) -> {team: pts}` where `decided` is a list of `{home,away,outcome}` (`outcome` in `'H'/'D'/'A'`).
  - `rank_blocks(matches, branch) -> [[team,...], ...]` ordered best-to-worst; a block with >1 team is an undecidable tie.
  - `best_worst(matches, branch) -> {team: (best_rank, worst_rank)}` (1-based).
  - `matches` items are group-result dicts `{home,away,hs,as,played}`; `branch` is `{match_index: 'H'|'D'|'A'}` giving outcomes for the pending (`played is False`) matches.

Conservative tiebreak rule (2026 order): points → head-to-head points → head-to-head GD → head-to-head goals → overall GD → overall goals. A goal-based rung is used **only if every match it depends on is played**; otherwise the still-tied teams stay in one ambiguous block.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_clinch.py` (before the `__main__` block):

```python
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
    assert bw["A"] == bw["B"], (bw["A"], bw["B"]) # share the block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_clinch.py`
Expected: FAIL — `_points` / `best_worst` not defined.

- [ ] **Step 3: Implement the standings engine** — append to `wc2026_clinch.py`:

```python
def _outcome(hs, as_):
    return "H" if hs > as_ else "A" if as_ > hs else "D"

def _decide(matches, branch):
    """Return list of {home,away,outcome,hs,as} with outcomes from real scores
    (played) or from the branch (pending; hs/as stay None)."""
    out = []
    for i, m in enumerate(matches):
        if m["played"]:
            out.append({**m, "outcome": _outcome(m["hs"], m["as"])})
        else:
            out.append({**m, "outcome": branch[i], "hs": None, "as": None})
    return out

def _points(teams, decided):
    pts = {t: 0 for t in teams}
    for d in decided:
        if d["outcome"] == "H": pts[d["home"]] += 3
        elif d["outcome"] == "A": pts[d["away"]] += 3
        else: pts[d["home"]] += 1; pts[d["away"]] += 1
    return pts

def _teams(matches):
    return sorted({m["home"] for m in matches} | {m["away"] for m in matches})

def _gd_gf(subset, decided):
    """Goal difference & goals-for over the given decided matches, restricted to
    teams in `subset`. Only matches with real scores contribute."""
    gd = {t: 0 for t in subset}; gf = {t: 0 for t in subset}
    for d in decided:
        if d["hs"] is None: continue
        if d["home"] in subset: gd[d["home"]] += d["hs"] - d["as"]; gf[d["home"]] += d["hs"]
        if d["away"] in subset: gd[d["away"]] += d["as"] - d["hs"]; gf[d["away"]] += d["as"]
    return gd, gf

def _resolve_subtie(sub, decided):
    """sub: teams tied on points AND head-to-head points. Resolve via H2H GD,
    H2H goals, overall GD, overall goals -- but only using rungs whose matches
    are all played. Returns ordered list of blocks (ambiguous ties stay grouped)."""
    if len(sub) == 1:
        return [list(sub)]
    internal = [d for d in decided if d["home"] in sub and d["away"] in sub]
    if any(d["hs"] is None for d in internal):
        return [list(sub)]                       # H2H GD undecidable -> ambiguous
    overall_known = all(d["hs"] is not None for t in sub for d in decided
                        if t in (d["home"], d["away"]))
    hgd, hgf = _gd_gf(sub, internal)
    ogd, ogf = _gd_gf(sub, decided)
    def key(t):
        k = [hgd[t], hgf[t]]
        if overall_known: k += [ogd[t], ogf[t]]
        return tuple(k)
    blocks = []
    for kv in sorted({key(t) for t in sub}, reverse=True):
        grp = sorted(t for t in sub if key(t) == kv)
        if len(grp) == 1:
            blocks.append(grp)
        else:
            blocks.append(grp)                   # equal key (or unknown overall) -> ambiguous
    return blocks

def _resolve_tie(tied, decided):
    """tied: teams equal on points. Split by head-to-head points, then subtie."""
    if len(tied) == 1:
        return [list(tied)]
    internal = [d for d in decided if d["home"] in tied and d["away"] in tied]
    h2h = _points(tied, internal)
    blocks = []
    for hv in sorted(set(h2h.values()), reverse=True):
        sub = sorted(t for t in tied if h2h[t] == hv)
        blocks.extend(_resolve_subtie(sub, decided))
    return blocks

def rank_blocks(matches, branch):
    decided = _decide(matches, branch)
    teams = _teams(matches)
    pts = _points(teams, decided)
    order = []
    for pv in sorted(set(pts.values()), reverse=True):
        tied = sorted(t for t in teams if pts[t] == pv)
        order.extend(_resolve_tie(tied, decided))
    return order

def best_worst(matches, branch):
    res = {}; idx = 0
    for block in rank_blocks(matches, branch):
        best, worst = idx + 1, idx + len(block)
        for t in block:
            res[t] = (best, worst)
        idx += len(block)
    return res
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_clinch.py`
Expected: PASS for all tests.

- [ ] **Step 5: Commit**

```bash
git add wc2026_clinch.py tests/test_clinch.py
git commit -m "feat: standings engine with conservative 2026 tiebreaks"
```

---

## Task 4: Clinch prover + resolve to override dict

**Files:**
- Modify: `wc2026_clinch.py` (add functions)
- Test: `tests/test_clinch.py` (append tests)

**Interfaces:**
- Consumes: `best_worst`, `build_group_results`, `slot_map`, `_teams`, `GROUPS`.
- Produces:
  - `clinched_positions(matches) -> {team: 1|2}` — teams guaranteed exactly 1st / exactly 2nd across all completions.
  - `resolve(assigned) -> {str(num): {'home'|'away': team}}` — ready to serialize as `clinched.json`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_clinch.py`:

```python
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
```

Note: the `seq 1..6` mapping in the last test assumes Group A occupies scaffold seqs 1-6; verify against `wc2026_feed.S` (Group A is defined first). The scores above produce Mexico 9, South Africa 6.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_clinch.py`
Expected: FAIL — `clinched_positions` / `resolve` not defined.

- [ ] **Step 3: Implement the prover + resolver** — append to `wc2026_clinch.py`:

```python
def clinched_positions(matches):
    """Return {team: 1 or 2} for teams guaranteed exactly 1st / exactly 2nd
    across every Win/Draw/Loss completion of the pending matches."""
    teams = _teams(matches)
    pending = [i for i, m in enumerate(matches) if not m["played"]]
    g1 = {t: True for t in teams}     # still possibly-guaranteed 1st
    g2 = {t: True for t in teams}     # still possibly-guaranteed exactly 2nd
    for combo in itertools.product("HDA", repeat=len(pending)):
        branch = dict(zip(pending, combo))
        bw = best_worst(matches, branch)
        for t in teams:
            b, w = bw[t]
            if not (b == 1 and w == 1): g1[t] = False
            if not (b == 2 and w == 2): g2[t] = False
    out = {}
    for t in teams:
        if g1[t]: out[t] = 1
        elif g2[t]: out[t] = 2
    return out

def resolve(assigned):
    """assigned: {seq: override} from _assign. Returns {str(num): {side: team}}
    suitable for clinched.json. Winners and runners-up only."""
    groups = build_group_results(assigned)
    smap = slot_map()
    out = {}
    for grp in GROUPS:
        pins = clinched_positions(groups[grp])
        for team, pos in pins.items():
            placement = "W" if pos == 1 else "R"
            slot = smap.get((grp, placement))
            if not slot:
                continue
            num, side = slot
            out.setdefault(str(num), {})[side] = team
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_clinch.py`
Expected: PASS for all tests.

- [ ] **Step 5: Commit**

```bash
git add wc2026_clinch.py tests/test_clinch.py
git commit -m "feat: conservative clinch prover + resolve to clinched.json dict"
```

---

## Task 5: CLI entry point + live fetch + golden screenshot test

**Files:**
- Modify: `wc2026_clinch.py` (add `fetch_and_resolve` + `main`)
- Test: `tests/test_clinch.py` (append golden test)

**Interfaces:**
- Consumes: `_fd_get`, `_fd_to_fixtures`, `_assign`, `resolve`.
- Produces:
  - `fetch_and_resolve(token, log) -> {str(num): {side: team}}`
  - `main()` CLI: `--token` (required), `--out` (default `clinched.json`). Writes the JSON only on success.

- [ ] **Step 1: Write the failing golden test** — append to `tests/test_clinch.py`:

```python
def test_golden_resolve_three_representative_groups():
    # Group A finished -> Winner A (Mexico, 79h) + Runner-up A (South Africa, 73h).
    # Group D early -> Winner D only (USA, 81h), no runner-up.
    # Group F all pending -> nothing.
    by_grp = {}
    for m in cl.S:
        if m["kind"] == "G":
            by_grp.setdefault(m["grp"], []).append(m["seq"])
    assigned = {}
    def fin(seq, h, a):
        assigned[seq] = {"home_score": h, "away_score": a, "status": "FINISHED"}
    # Group A (Mexico 9, South Africa 6, South Korea 3, Czechia 0)
    a = by_grp["A"]
    fin(a[0], 2, 0); fin(a[1], 1, 0); fin(a[2], 0, 1)
    fin(a[3], 1, 0); fin(a[4], 0, 1); fin(a[5], 1, 0)
    # Group D (USA 6 and clinched; Türkiye-USA + Paraguay-Australia pending)
    d = by_grp["D"]
    # d order: USA-PRY, AUS-TUR, USA-AUS, TUR-PRY, TUR-USA, PRY-AUS
    fin(d[0], 2, 0); fin(d[1], 1, 0); fin(d[2], 1, 0); fin(d[3], 0, 0)
    # d[4], d[5] left pending (no entry)
    out = cl.resolve(assigned)
    assert out.get("79") == {"home": "Mexico"}, out.get("79")
    assert out.get("73", {}).get("home") == "South Africa", out.get("73")
    assert out.get("81") == {"home": "USA"}, out.get("81")
    # Group F untouched -> no F slots. F winner slot is 76? No: assert no spurious
    # USA/Mexico-style false positives appear for groups we left empty.
    assert "82" not in out or "home" not in out.get("82", {}), out  # Winner G slot empty
```

(`cl.S` is re-exported because `wc2026_clinch` imports `S` from the feed.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_clinch.py`
Expected: FAIL — golden test references behavior already implemented by `resolve`; it should actually PASS if Tasks 2-4 are correct. If it fails, the failure pinpoints a resolver bug to fix before continuing. (This task's *new* code is `main`/`fetch_and_resolve`, which the test does not exercise; treat a green golden test as the gate to proceed.)

- [ ] **Step 3: Add `fetch_and_resolve` + `main`** — append to `wc2026_clinch.py`:

```python
def fetch_and_resolve(token, log):
    url = "https://api.football-data.org/v4/competitions/WC/matches"
    data = _fd_get(url, token, log)
    fx = _fd_to_fixtures(data)
    assigned = _assign(fx, log)
    return resolve(assigned)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True, help="football-data.org API token")
    ap.add_argument("--out", default="clinched.json")
    args = ap.parse_args()
    log = []
    # _fd_get sys.exit()s on hard failure -> we never overwrite a good file.
    result = fetch_and_resolve(args.token, log)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print(f"clinched: {len(result)} match slots resolved -> {args.out}")
    for line in log:
        print(line)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests + a smoke check of the CLI arg parser**

Run: `python3 tests/test_clinch.py`
Expected: PASS for all tests.

Run: `python3 wc2026_clinch.py --help`
Expected: usage text listing `--token` and `--out` (exit 0).

- [ ] **Step 5: Commit**

```bash
git add wc2026_clinch.py tests/test_clinch.py
git commit -m "feat: clinch resolver CLI + live fetch + golden test"
```

---

## Task 6: Wire the resolver into CI

**Files:**
- Modify: `.github/workflows/world-cup-feed.yml`

**Interfaces:**
- Consumes: `wc2026_clinch.py` CLI, `FD_TOKEN` secret.
- Produces: a committed `clinched.json` and a build that layers it.

- [ ] **Step 1: Add a test step for the clinch suite**

In the `Run tests` step, run both suites:

```yaml
      - name: Run tests
        run: |
          python3 tests/test_feed.py
          python3 tests/test_clinch.py
```

- [ ] **Step 2: Regenerate `clinched.json` before the build (token-gated)**

Add a step before `Build feed`:

```yaml
      - name: Resolve clinched slots
        env:
          FD_TOKEN: ${{ secrets.FD_TOKEN }}
        run: |
          if [ -n "$FD_TOKEN" ]; then
            python3 wc2026_clinch.py --token "$FD_TOKEN" --out clinched.json || \
              echo "clinch resolver failed; keeping existing clinched.json"
          fi
```

- [ ] **Step 3: Layer `clinched.json` in the build**

In the `Build feed` step's `footballdata` branch, add the clinched layer:

```bash
          if [ -n "$FD_TOKEN" ]; then
            OVR=""; [ -f overrides.json ] && OVR="--overrides overrides.json"
            CLN=""; [ -f clinched.json ] && CLN="--clinched clinched.json"
            python wc2026_feed.py --provider footballdata --token "$FD_TOKEN" \
              $CLN $OVR --out public/fifa-world-cup-2026.ics
```

- [ ] **Step 4: Commit `clinched.json` when it changes**

In the `Commit if changed` step, add `clinched.json` to the staged paths:

```bash
          git add public/fifa-world-cup-2026.ics public/_headers clinched.json 2>/dev/null || true
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/world-cup-feed.yml
git commit -m "ci: regenerate + layer clinched.json before feed build"
```

---

## Final verification (after all tasks)

- [ ] Run the full test suite:

```bash
python3 tests/test_feed.py && python3 tests/test_clinch.py
```
Expected: every line `PASS`, exit 0.

- [ ] **Live check against ground truth** (needs a real `FD_TOKEN`):

```bash
python3 wc2026_clinch.py --token "$FD_TOKEN" --out /tmp/clinched_live.json
cat /tmp/clinched_live.json
```
Confirm the resolved slots match the confirmed Round-of-32 screenshot — at minimum Mexico→79h, USA→81h, South Africa→73h, Canada→73a, Brazil→76h, Morocco→75a, Germany→74h, Switzerland→85h, Argentina→86h — and that **no** slot is resolved for a team that has not actually clinched (no false positives). Investigate any discrepancy before declaring done.
```
```
