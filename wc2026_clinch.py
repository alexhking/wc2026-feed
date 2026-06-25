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

def _split_by(teams, score):
    """Group teams by `score(team)` (higher is better); return groups ordered
    best-to-worst, each group a sorted list of teams sharing that score."""
    buckets = {}
    for t in teams:
        buckets.setdefault(score(t), []).append(t)
    return [sorted(buckets[k]) for k in sorted(buckets, reverse=True)]

def _rank_tied(teams, decided):
    """Rank a set of teams level on the criterion that grouped them, applying the
    2026 FIFA tiebreakers: head-to-head points, head-to-head GD, head-to-head
    goals -- RE-APPLIED recursively to any still-level subset -- then overall GD
    and overall goals. A goal-based rung is used only when every contributing
    match is played; otherwise the still-tied teams stay in one ambiguous block."""
    teams = sorted(teams)
    if len(teams) <= 1:
        return [teams]
    internal = [d for d in decided if d["home"] in teams and d["away"] in teams]
    # Head-to-head points (always determined within a branch)
    h2hp = _points(teams, internal)
    groups = _split_by(teams, lambda t: h2hp[t])
    if len(groups) > 1:
        return [blk for g in groups for blk in _rank_tied(g, decided)]
    # All level on H2H points; H2H GD/goals need the internal matches played
    if any(d["hs"] is None for d in internal):
        return [teams]                       # H2H GD undecidable -> ambiguous block
    hgd, hgf = _gd_gf(teams, internal)
    groups = _split_by(teams, lambda t: (hgd[t], hgf[t]))
    if len(groups) > 1:
        return [blk for g in groups for blk in _rank_tied(g, decided)]
    # Fully level on every head-to-head criterion -> overall GD / goals
    overall_known = all(d["hs"] is not None for t in teams for d in decided
                        if t in (d["home"], d["away"]))
    if not overall_known:
        return [teams]                       # overall GD undecidable -> ambiguous block
    ogd, ogf = _gd_gf(teams, decided)
    return _split_by(teams, lambda t: (ogd[t], ogf[t]))

def rank_blocks(matches, branch):
    decided = _decide(matches, branch)
    teams = _teams(matches)
    pts = _points(teams, decided)
    order = []
    for pv in sorted(set(pts.values()), reverse=True):
        tied = sorted(t for t in teams if pts[t] == pv)
        order.extend(_rank_tied(tied, decided))
    return order

def best_worst(matches, branch):
    res = {}; idx = 0
    for block in rank_blocks(matches, branch):
        best, worst = idx + 1, idx + len(block)
        for t in block:
            res[t] = (best, worst)
        idx += len(block)
    return res

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
