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
