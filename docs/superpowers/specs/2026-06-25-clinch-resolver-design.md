# Clinch Resolver — Design

**Date:** 2026-06-25
**Status:** Approved (design); pending implementation plan

## Problem

`football-data.org` (the feed's live provider) only fills knockout-match team
identities once a slot is *officially* assigned — after the group stage ends and
the four best third-place teams are ranked. It will not surface a team that has
*mathematically* clinched a knockout position early (e.g. USA as Winner Group D
before its matchday-3 game). News outlets show these early; the feed lags them.

Today we patch this by hand-editing `overrides.json`. This spec replaces the
hand-typing for **group winners and runners-up** with an automatic resolver that
computes clinched placements from results and emits them as a layered override.

Scope of this spec: **group winners + runners-up only.** `Best 3rd (…)` slots are
explicitly out of scope (they cannot finalize until all groups end and depend on
FIFA's third-place allocation table) and remain hand-owned in `overrides.json`.

## Principles

- **Never a false positive.** The resolver asserts a placement only when the math
  guarantees it. When in doubt, it emits nothing and the scaffold label stands.
  "Late but never wrong" is the accepted bias.
- **Provider-agnostic core stays untouched in spirit.** `wc2026_feed.py` keeps its
  "never compute standings" stance for *resolution*; the new standings logic lives
  in a separate module and feeds in only as an override layer.
- **Machine output and hand edits never collide.** Separate files; hand wins.

## Architecture

New standalone script **`wc2026_clinch.py`** that imports and reuses
`wc2026_feed.py`:

- Reused from the feed: `_fd_get`, `_fd_to_fixtures` (fetch), `_assign` (map
  results onto scaffold slots), the scaffold `S`, venue table `V`, `utc_of`,
  and `canon` (name canonicalization).
- New in the resolver:
  - **Standings engine** — points + the 2026 FIFA group tiebreakers.
  - **Clinch prover** — Approach A (below).
  - **Slot mapper** — `{group, placement}` → `(match_num, "home"|"away")`.
  - **Emitter** — writes `clinched.json`.

`clinched.json` uses the **same schema as `overrides.json`**:
`{"79": {"home": "Mexico"}, "73": {"away": "Canada"}, ...}`. It is machine-owned
and fully regenerated each run.

### Feed change

`wc2026_feed.py` gains a `--clinched PATH` argument: a second override layer
parsed with the existing `_manual_overrides` and merged with `_merge_overrides`.

**Layer order (each later layer wins per field):**

```
live provider  ->  clinched.json (machine)  ->  overrides.json (hand)
```

So a hand override always beats the machine, which always beats the raw provider.
When both the provider and the resolver eventually resolve the same slot, they
agree by construction.

## The clinch prover (Approach A)

Per group: 4 teams, 6 round-robin matches, each either **played** (has a final
score) or **pending**.

The resolver determines each team's **exact** final position and emits a slot
only when a team is pinned to **exactly 1st** (→ Winner slot) or **exactly 2nd**
(→ Runner-up slot). A team guaranteed top-2 but not *which* emits nothing.

### Proof procedure

Enumerate every pending match as Win / Draw / Loss (≤ 3⁶ = 729 branches). In each
branch, rank the four teams using the **2026 tiebreaker order**:

1. **Points** — exact in every branch.
2. **Head-to-head points** among teams tied on points — exact in every branch
   (the branch fixes who won each match). This is the 2026 *first* tiebreaker
   rung and is applied correctly here.
3. **Head-to-head goal difference**, then **head-to-head goals scored**, then
   **overall goal difference**, then **overall goals scored** — these require
   actual scorelines. A rung is evaluated **only if every match it depends on is
   already played**. If any contributing match is still **pending**, the rung is
   treated as **indeterminate and resolves against the team under test**
   (adversarial / conservative), because goal margins are unbounded.
4. Remaining FIFA rungs (fair play, drawing of lots) are likewise treated as
   indeterminate-against-the-team when not decidable from played results.

A team **clinches** a slot iff it holds that exact position in **every** branch.

### Consequences (both intended)

- **Finished group** (0 pending matches): a single branch with all scores known →
  the full 2026 ordering computes exactly, including GD rungs. Both the winner and
  the runner-up are pinned.
- **In-progress group**: a placement is asserted only when points and/or
  already-locked head-to-head settle it. A placement hanging on a *pending*
  match's goal difference is never asserted. This is the no-false-positive
  guarantee, and it naturally captures the 2026 head-to-head-first reality (a team
  that already won the direct meeting sits above a points-tied rival regardless of
  goals).

> Note: this can be a false *negative* in rare cases — e.g. a finished group
> position that hinges on GD will still resolve (all scores known), but an
> in-progress GD-only edge will be left for the official feed or a hand override.
> Accepted per the "late but never wrong" bias.

## Data flow

```
football-data /competitions/WC/matches
  -> _fd_to_fixtures
  -> _assign            (attach final score + status to each scaffold group slot)
  -> per-group results table (teams known from scaffold S; scores from _assign)
  -> standings engine + clinch prover
  -> {group, placement} pins
  -> slot mapper: find R32 scaffold match whose home/away label ==
       "Winner Group X" / "Runner-up Group X"  ->  (match_num, side)
  -> clinched.json
```

The slot map is built by scanning the R32 entries of scaffold `S` for labels
matching `^(Winner|Runner-up) Group ([A-L])$` and recording which `home`/`away`
side of which official match number each placement fills.

## Error handling

- **No token** → resolver no-ops cleanly; the feed builds without the clinched
  layer (unchanged behavior).
- **API / 429 / network failure** → reuse `_fd_get`'s retry. On hard failure the
  resolver **exits without writing** `clinched.json`, leaving the last
  good committed file intact. It never overwrites good data with an empty file.
- **Insufficient or ambiguous data** for a group → emit nothing for that group.
- By construction the resolver can never emit a placement contradicting a played
  result.

## Testing

- **Tiebreaker unit tests** covering the 2026 head-to-head-first order:
  - the Mexico-beat-South-Korea case (H2H wins over equal points);
  - a USA-style early points clinch (rival cannot reach the leader's points);
  - a **GD-only case** that must **not** clinch while a contributing match is
    pending, but **must** resolve once the group is finished.
- **Golden test against the current real state / screenshot**: feed the resolver
  group results consistent with today's confirmed spots and assert it produces
  **exactly** the clinched slots shown — Mexico→79 home, USA→81 home, South
  Africa→73 home, Canada→73 away, Brazil→76 home, Morocco→75 away, Germany→74
  home, Switzerland→85 home, Argentina→86 home, … — **and nothing more** (no
  false positives).
- **Layering test**: a hand `overrides.json` entry still wins over a conflicting
  `clinched.json` entry.
- **Live check before completion**: run the resolver against live football-data
  and confirm output matches the screenshot.

## CI

In `.github/workflows/world-cup-feed.yml`, before the build step and gated on
`FD_TOKEN`:

1. Run `python wc2026_clinch.py --token "$FD_TOKEN" --out clinched.json`.
2. Commit `clinched.json` if changed (so the machine's decisions are diffable).
3. Build with `--clinched clinched.json --overrides overrides.json`.

If the token is absent, skip the resolver and build as today.

## Out of scope

- `Best 3rd (…)` R32 slots and FIFA's third-place allocation table.
- Round of 16 and later (`Winner Match NN`) — already resolved by the provider
  once the feeding matches finish.
- Any change to kickoff-time handling.
