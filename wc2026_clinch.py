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
