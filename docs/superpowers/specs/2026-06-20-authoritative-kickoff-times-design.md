# Authoritative kickoff times from the provider

**Date:** 2026-06-20
**Status:** Approved (design)
**File touched:** `wc2026_feed.py` (+ a new test)

## Problem

Every kickoff time in the feed is hand-typed into the `g(mo,d,h,mi,...)` / `ko(...)`
scaffold calls and interpreted as Eastern Time (`utc_of()` adds 4h to reach UTC).
The football-data.org provider knows each match's true `utcDate`, but `_assign()`
overlays **only team names and scores** — it discards the provider's kickoff times.

Consequently a mistyped scaffold time is invisible to the pipeline and can never
self-correct. This caused two missed kickoffs in June 2026:

- Brazil vs Haiti — scaffold 30 min late.
- Türkiye vs Paraguay — scaffold typed as midnight ET; true kickoff 11:00 PM ET
  (one hour earlier). Fixed in commit `06909e9`.

A full diff of all 104 scaffold times against the provider (group stage aligned by
group + team-set; knockouts by per-stage multiset) confirmed those were the only
errors, but hand-verification is exactly the method that let them slip.

## Goal

When the live provider **confidently** identifies a match, the feed uses the
provider's authoritative UTC kickoff for everything it displays. A wrong hand-typed
scaffold time can no longer affect a confidently-matched fixture. Scaffold times
remain the fallback for anything not confidently matched.

## Design

All changes are contained in `wc2026_feed.py`.

### 1. `_assign()` — attach provider UTC only when confident

`_assign()` already scores each candidate scaffold slot per provider fixture and
keeps the best. Today the score combines:

- time proximity (always, up to ~100),
- venue/city match (+200),
- team-name overlap (+120).

Change: while selecting the best slot, remember whether a **non-time signal**
(team-name overlap **or** venue/city match) contributed to the *winning* slot's
score. Only when such a signal contributed, write the provider's kickoff into the
override: `ov["utc"] = fx["utc"]`.

If the best slot won on **time proximity alone** (the knockout case: provider
`homeTeam`/`awayTeam` are `null` until groups resolve), do **not** attach `utc` —
attaching a time chosen purely by nearness to a possibly-wrong scaffold time is
circular and could bind a real time to the wrong slot.

This implements the approved "only confident matches" rule and is self-healing:
a knockout begins receiving its authoritative time the moment its teams resolve in
the provider (then team-name overlap makes the match confident).

### 2. `build()` — prefer `ov["utc"]` when present

Currently `build()` derives display from the scaffold:

```python
utc = utc_of(m)
et = fmt12(m["h"], m["mi"])
loc_dt = datetime(2026, m["mo"], m["d"], m["h"], m["mi"]) + timedelta(hours=off)
```

Change: if the override carries a provider UTC, derive **all** times from it:

- `utc = ov["utc"]`  (naive UTC datetime, as the provider parses it)
- `DTSTART = utc`, `DTEND = utc + 2h` (unchanged end logic)
- ET wall-clock: `et_dt = utc - timedelta(hours=4)` (EDT); `et = fmt12(et_dt.hour, et_dt.minute)`
- local: `loc_dt = et_dt + timedelta(hours=off)`; `local = fmt12(loc_dt.hour, loc_dt.minute)`

Otherwise the existing scaffold-based behavior is used unchanged.

This keeps the ET and local labels consistent with the real kickoff. Example:
Türkiye/Paraguay provider `03:00Z` → "11:00 PM ET / 8:00 PM local (San Francisco
Bay Area)" automatically, even if the scaffold constant were wrong.

### 3. Tests

No test suite exists today. Add a lightweight test driven by a **saved JSON
fixture** committed under the repo (e.g. `tests/fixtures/wc_matches_sample.json`)
so CI needs no network or token:

- **Provider time wins:** a group-stage fixture whose scaffold constant is
  deliberately wrong → generated `DTSTART` equals the provider's `utcDate`, and the
  ET/local description strings are derived from it.
- **Fallback on weak match:** a fixture representing a knockout with `null` teams
  (time-proximity-only) → `DTSTART` falls back to the scaffold time (no `utc`
  attached).
- **End-to-end sanity:** every group-stage event's `DTSTART` equals the matching
  provider `utcDate`.

## Out of scope (YAGNI)

- No separate CI warning/guard (auto-use makes the displayed time provider-driven
  for confident matches; "both" was explicitly not chosen).
- No DST handling — the tournament (June 11 – July 19) is entirely in EDT, matching
  the existing `utc_of` assumption.
- No manual-override layering and no knockout team assertion — the feed continues to
  trust the provider for team resolution (it never computes group standings itself).
- `manual` and `none` providers are untouched; they supply no `utc`, so they keep
  scaffold times.

## Residual risk (accepted)

Matches absent from the provider, or runs with `--provider none`/`manual`, still
rely on the scaffold constant. That is unavoidable without a provider and is the
minority case.
