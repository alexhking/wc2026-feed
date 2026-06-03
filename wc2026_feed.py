#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wc2026_feed.py  -  Dynamic FIFA World Cup 2026 .ics generator

WHAT IT DOES
------------
Holds a fixed 104-match "scaffold" (kickoff time, venue, stage, bracket
structure) and overlays real team identities + scores from a data provider
as they become known. Knockout slots like "Winner Group A" / "Winner Match 73"
are replaced with actual nations the moment the provider resolves them.

It NEVER computes group standings / FIFA tiebreakers itself. It trusts the
provider's already-resolved matchups, so resolution is always correct and the
code stays provider-agnostic: a provider only has to emit, per match, the two
team names (and optionally a final score + status).

USAGE
-----
  # Automated (football-data.org, free token):
  python wc2026_feed.py --provider footballdata --token $FD_TOKEN \
        --out /path/to/fifa-world-cup-2026.ics

  # Zero-dependency manual overlay (hand-edit a JSON as teams clinch):
  python wc2026_feed.py --provider manual --overrides overrides.json \
        --out fifa-world-cup-2026.ics

  # No overlay at all (pure scaffold, same as the original file):
  python wc2026_feed.py --provider none --out fifa-world-cup-2026.ics

overrides.json schema (manual provider) -- key by official match number OR by
"YYYY-MM-DD@CITY"; values may include any subset:
  {
    "73": {"home": "Argentina", "away": "Morocco", "home_score": 2,
           "away_score": 1, "status": "FINISHED"}
  }
"""
import argparse, json, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------------
# VENUES: key -> (name, city, country, capacity, FIFA name, lat, lon, ET offset)
# ET (EDT)=UTC-4 in Jun/Jul 2026. offset = LOCAL - ET hours.
# ET venues 0 | US Central -1 | Mexico (CST,no DST) -2 | Pacific -3
# ----------------------------------------------------------------------------
V = {
 "AZT": ("Estadio Azteca","Mexico City","Mexico","~87,000","Mexico City Stadium",19.3029,-99.1505,-2),
 "AKR": ("Estadio Akron","Guadalajara","Mexico","~48,000","Guadalajara Stadium",20.6819,-103.4625,-2),
 "BBV": ("Estadio BBVA","Monterrey","Mexico","~53,500","Monterrey Stadium",25.6692,-100.2444,-2),
 "BMO": ("BMO Field","Toronto","Canada","~45,000","Toronto Stadium",43.6332,-79.4185,0),
 "BCP": ("BC Place","Vancouver","Canada","~54,500","Vancouver Stadium",49.2768,-123.1119,-3),
 "MBS": ("Mercedes-Benz Stadium","Atlanta","USA","~71,000","Atlanta Stadium",33.7553,-84.4006,0),
 "LEV": ("Levi's Stadium","San Francisco Bay Area","USA","~71,000","San Francisco Bay Area Stadium",37.4030,-121.9698,-3),
 "SOF": ("SoFi Stadium","Los Angeles","USA","~70,000","Los Angeles Stadium",33.9535,-118.3392,-3),
 "LUM": ("Lumen Field","Seattle","USA","~69,000","Seattle Stadium",47.5952,-122.3316,-3),
 "MET": ("MetLife Stadium","New York/New Jersey","USA","~82,500","New York New Jersey Stadium",40.8135,-74.0745,0),
 "GIL": ("Gillette Stadium","Boston","USA","~65,000","Boston Stadium",42.0909,-71.2643,0),
 "LFF": ("Lincoln Financial Field","Philadelphia","USA","~69,000","Philadelphia Stadium",39.9008,-75.1675,0),
 "HRS": ("Hard Rock Stadium","Miami","USA","~65,000","Miami Stadium",25.9580,-80.2389,0),
 "NRG": ("NRG Stadium","Houston","USA","~72,000","Houston Stadium",29.6847,-95.4107,-1),
 "ARR": ("Arrowhead Stadium","Kansas City","USA","~76,000","Kansas City Stadium",39.0489,-94.4839,-1),
 "ATT": ("AT&T Stadium","Dallas","USA","~80,000","Dallas Stadium",32.7473,-97.0945,-1),
}

# ----------------------------------------------------------------------------
# FLAGS (regional-indicator + subdivision flags for England/Scotland)
# ----------------------------------------------------------------------------
F = {
 "Mexico":"\U0001F1F2\U0001F1FD","South Africa":"\U0001F1FF\U0001F1E6","South Korea":"\U0001F1F0\U0001F1F7",
 "Czechia":"\U0001F1E8\U0001F1FF","Canada":"\U0001F1E8\U0001F1E6","Bosnia & Herzegovina":"\U0001F1E7\U0001F1E6",
 "Qatar":"\U0001F1F6\U0001F1E6","Switzerland":"\U0001F1E8\U0001F1ED","Brazil":"\U0001F1E7\U0001F1F7",
 "Morocco":"\U0001F1F2\U0001F1E6","Haiti":"\U0001F1ED\U0001F1F9",
 "Scotland":"\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
 "USA":"\U0001F1FA\U0001F1F8","Paraguay":"\U0001F1F5\U0001F1FE","Australia":"\U0001F1E6\U0001F1FA",
 "T\u00fcrkiye":"\U0001F1F9\U0001F1F7","Germany":"\U0001F1E9\U0001F1EA","Cura\u00e7ao":"\U0001F1E8\U0001F1FC",
 "Ivory Coast":"\U0001F1E8\U0001F1EE","Ecuador":"\U0001F1EA\U0001F1E8","Netherlands":"\U0001F1F3\U0001F1F1",
 "Japan":"\U0001F1EF\U0001F1F5","Sweden":"\U0001F1F8\U0001F1EA","Tunisia":"\U0001F1F9\U0001F1F3",
 "Iran":"\U0001F1EE\U0001F1F7","New Zealand":"\U0001F1F3\U0001F1FF","Belgium":"\U0001F1E7\U0001F1EA",
 "Egypt":"\U0001F1EA\U0001F1EC","Spain":"\U0001F1EA\U0001F1F8","Cape Verde":"\U0001F1E8\U0001F1FB",
 "Saudi Arabia":"\U0001F1F8\U0001F1E6","Uruguay":"\U0001F1FA\U0001F1FE","France":"\U0001F1EB\U0001F1F7",
 "Senegal":"\U0001F1F8\U0001F1F3","Iraq":"\U0001F1EE\U0001F1F6","Norway":"\U0001F1F3\U0001F1F4",
 "Argentina":"\U0001F1E6\U0001F1F7","Algeria":"\U0001F1E9\U0001F1FF","Austria":"\U0001F1E6\U0001F1F9",
 "Jordan":"\U0001F1EF\U0001F1F4","Portugal":"\U0001F1F5\U0001F1F9","DR Congo":"\U0001F1E8\U0001F1E9",
 "Uzbekistan":"\U0001F1FA\U0001F1FF","Colombia":"\U0001F1E8\U0001F1F4",
 "England":"\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
 "Croatia":"\U0001F1ED\U0001F1F7","Ghana":"\U0001F1EC\U0001F1ED","Panama":"\U0001F1F5\U0001F1E6",
}
TROPHY="\U0001F3C6"

# Provider/team-name aliases -> our canonical display label (which keys F)
ALIAS = {
 "turkey":"T\u00fcrkiye","turkiye":"T\u00fcrkiye",
 "korea republic":"South Korea","republic of korea":"South Korea","south korea":"South Korea",
 "ir iran":"Iran","iran":"Iran",
 "united states":"USA","usa":"USA","united states of america":"USA",
 "cote d'ivoire":"Ivory Coast","c\u00f4te d'ivoire":"Ivory Coast","ivory coast":"Ivory Coast",
 "cabo verde":"Cape Verde","cape verde":"Cape Verde",
 "dr congo":"DR Congo","congo dr":"DR Congo","democratic republic of congo":"DR Congo",
 "democratic republic of the congo":"DR Congo",
 "czech republic":"Czechia","czechia":"Czechia",
 "bosnia and herzegovina":"Bosnia & Herzegovina","bosnia & herzegovina":"Bosnia & Herzegovina",
 "curacao":"Cura\u00e7ao","cura\u00e7ao":"Cura\u00e7ao",
}
def canon(name):
    if not name: return None
    return ALIAS.get(name.strip().lower(), name.strip())

# ----------------------------------------------------------------------------
# SCAFFOLD: list of dicts. (mo,d,h,mi) are ET; midnight games already rolled
# to the correct next calendar day. official_num set for knockouts (73-104).
# ----------------------------------------------------------------------------
S = []
def g(mo,d,h,mi,home,away,vk,grp,md):
    S.append(dict(seq=len(S)+1,mo=mo,d=d,h=h,mi=mi,home=home,away=away,vk=vk,
                  kind="G",grp=grp,md=md,num=None,rnd=None))
def ko(mo,d,h,mi,home,away,vk,rnd,num):
    S.append(dict(seq=len(S)+1,mo=mo,d=d,h=h,mi=mi,home=home,away=away,vk=vk,
                  kind="KO",grp=None,md=None,num=num,rnd=rnd))

# --- Group stage ---
g(6,11,15,0,"Mexico","South Africa","AZT","A",1); g(6,11,22,0,"South Korea","Czechia","AKR","A",1)
g(6,18,12,0,"Czechia","South Africa","MBS","A",2); g(6,18,21,0,"Mexico","South Korea","AKR","A",2)
g(6,24,21,0,"Czechia","Mexico","AZT","A",3); g(6,24,21,0,"South Africa","South Korea","BBV","A",3)
g(6,12,15,0,"Canada","Bosnia & Herzegovina","BMO","B",1); g(6,13,15,0,"Qatar","Switzerland","LEV","B",1)
g(6,18,15,0,"Switzerland","Bosnia & Herzegovina","SOF","B",2); g(6,18,18,0,"Canada","Qatar","BCP","B",2)
g(6,24,15,0,"Switzerland","Canada","BCP","B",3); g(6,24,15,0,"Bosnia & Herzegovina","Qatar","LUM","B",3)
g(6,13,18,0,"Brazil","Morocco","MET","C",1); g(6,13,21,0,"Haiti","Scotland","GIL","C",1)
g(6,19,18,0,"Scotland","Morocco","GIL","C",2); g(6,19,21,0,"Brazil","Haiti","LFF","C",2)
g(6,24,18,0,"Scotland","Brazil","HRS","C",3); g(6,24,18,0,"Morocco","Haiti","MBS","C",3)
g(6,12,21,0,"USA","Paraguay","SOF","D",1); g(6,14,0,0,"Australia","T\u00fcrkiye","BCP","D",1)
g(6,19,15,0,"USA","Australia","LUM","D",2); g(6,20,0,0,"T\u00fcrkiye","Paraguay","LEV","D",2)
g(6,25,22,0,"T\u00fcrkiye","USA","SOF","D",3); g(6,25,22,0,"Paraguay","Australia","LEV","D",3)
g(6,14,13,0,"Germany","Cura\u00e7ao","NRG","E",1); g(6,14,19,0,"Ivory Coast","Ecuador","LFF","E",1)
g(6,20,16,0,"Germany","Ivory Coast","BMO","E",2); g(6,20,20,0,"Ecuador","Cura\u00e7ao","ARR","E",2)
g(6,25,16,0,"Ecuador","Germany","MET","E",3); g(6,25,16,0,"Cura\u00e7ao","Ivory Coast","LFF","E",3)
g(6,14,16,0,"Netherlands","Japan","ATT","F",1); g(6,14,22,0,"Sweden","Tunisia","BBV","F",1)
g(6,20,13,0,"Netherlands","Sweden","NRG","F",2); g(6,21,0,0,"Tunisia","Japan","BBV","F",2)
g(6,25,19,0,"Japan","Sweden","ATT","F",3); g(6,25,19,0,"Tunisia","Netherlands","ARR","F",3)
g(6,15,21,0,"Iran","New Zealand","SOF","G",1); g(6,15,15,0,"Belgium","Egypt","LUM","G",1)
g(6,21,15,0,"Belgium","Iran","SOF","G",2); g(6,21,21,0,"New Zealand","Egypt","BCP","G",2)
g(6,26,23,0,"Egypt","Iran","LUM","G",3); g(6,26,23,0,"New Zealand","Belgium","BCP","G",3)
g(6,15,12,0,"Spain","Cape Verde","MBS","H",1); g(6,15,18,0,"Saudi Arabia","Uruguay","HRS","H",1)
g(6,21,12,0,"Spain","Saudi Arabia","MBS","H",2); g(6,21,18,0,"Uruguay","Cape Verde","HRS","H",2)
g(6,26,20,0,"Cape Verde","Saudi Arabia","NRG","H",3); g(6,26,20,0,"Uruguay","Spain","AKR","H",3)
g(6,16,15,0,"France","Senegal","MET","I",1); g(6,16,18,0,"Iraq","Norway","GIL","I",1)
g(6,22,17,0,"France","Iraq","LFF","I",2); g(6,22,20,0,"Norway","Senegal","MET","I",2)
g(6,26,15,0,"Norway","France","GIL","I",3); g(6,26,15,0,"Senegal","Iraq","BMO","I",3)
g(6,16,21,0,"Argentina","Algeria","ARR","J",1); g(6,17,0,0,"Austria","Jordan","LEV","J",1)
g(6,22,13,0,"Argentina","Austria","ATT","J",2); g(6,22,23,0,"Jordan","Algeria","LEV","J",2)
g(6,27,22,0,"Algeria","Austria","ARR","J",3); g(6,27,22,0,"Jordan","Argentina","ATT","J",3)
g(6,17,13,0,"Portugal","DR Congo","NRG","K",1); g(6,17,22,0,"Uzbekistan","Colombia","AZT","K",1)
g(6,23,13,0,"Portugal","Uzbekistan","NRG","K",2); g(6,23,22,0,"Colombia","DR Congo","AKR","K",2)
g(6,27,19,30,"Colombia","Portugal","HRS","K",3); g(6,27,19,30,"DR Congo","Uzbekistan","MBS","K",3)
g(6,17,16,0,"England","Croatia","ATT","L",1); g(6,17,19,0,"Ghana","Panama","BMO","L",1)
g(6,23,16,0,"England","Ghana","GIL","L",2); g(6,23,19,0,"Panama","Croatia","BMO","L",2)
g(6,27,17,0,"Panama","England","MET","L",3); g(6,27,17,0,"Croatia","Ghana","LFF","L",3)

# --- Knockouts (official match numbers) ---
R32="Round of 32";R16="Round of 16";QF="Quarter-final";SF="Semi-final";TP="Third-place play-off";FN="Final"
ko(6,28,15,0,"Runner-up Group A","Runner-up Group B","SOF",R32,73)
ko(6,29,13,0,"Winner Group C","Runner-up Group F","NRG",R32,76)
ko(6,29,16,30,"Winner Group E","Best 3rd (A/B/C/D/F)","GIL",R32,74)
ko(6,29,21,0,"Winner Group F","Runner-up Group C","BBV",R32,75)
ko(6,30,13,0,"Runner-up Group E","Runner-up Group I","ATT",R32,78)
ko(6,30,17,0,"Winner Group I","Best 3rd (C/D/F/G/H)","MET",R32,77)
ko(6,30,21,0,"Winner Group A","Best 3rd (C/E/F/H/I)","AZT",R32,79)
ko(7,1,12,0,"Winner Group L","Best 3rd (E/H/I/J/K)","MBS",R32,80)
ko(7,1,16,0,"Winner Group G","Best 3rd (A/E/H/I/J)","LUM",R32,82)
ko(7,1,20,0,"Winner Group D","Best 3rd (B/E/F/I/J)","LEV",R32,81)
ko(7,2,15,0,"Winner Group H","Runner-up Group J","SOF",R32,84)
ko(7,2,19,0,"Runner-up Group K","Runner-up Group L","BMO",R32,83)
ko(7,2,23,0,"Winner Group B","Best 3rd (E/F/G/I/J)","BCP",R32,85)
ko(7,3,14,0,"Runner-up Group D","Runner-up Group G","ATT",R32,88)
ko(7,3,18,0,"Winner Group J","Runner-up Group H","HRS",R32,86)
ko(7,3,21,30,"Winner Group K","Best 3rd (D/E/I/J/L)","ARR",R32,87)
ko(7,4,13,0,"Winner Match 73","Winner Match 75","NRG",R16,90)
ko(7,4,17,0,"Winner Match 74","Winner Match 77","LFF",R16,89)
ko(7,5,16,0,"Winner Match 76","Winner Match 78","MET",R16,91)
ko(7,5,20,0,"Winner Match 79","Winner Match 80","AZT",R16,92)
ko(7,6,15,0,"Winner Match 83","Winner Match 84","ATT",R16,93)
ko(7,6,20,0,"Winner Match 81","Winner Match 82","LUM",R16,94)
ko(7,7,12,0,"Winner Match 86","Winner Match 88","MBS",R16,95)
ko(7,7,16,0,"Winner Match 85","Winner Match 87","BCP",R16,96)
ko(7,9,16,0,"Winner Match 89","Winner Match 90","GIL",QF,97)
ko(7,10,15,0,"Winner Match 93","Winner Match 94","SOF",QF,98)
ko(7,11,17,0,"Winner Match 91","Winner Match 92","HRS",QF,99)
ko(7,11,21,0,"Winner Match 95","Winner Match 96","ARR",QF,100)
ko(7,14,15,0,"Winner Match 97","Winner Match 98","ATT",SF,101)
ko(7,15,15,0,"Winner Match 99","Winner Match 100","MBS",SF,102)
ko(7,18,17,0,"Loser Match 101","Loser Match 102","HRS",TP,103)
ko(7,19,15,0,"Winner Match 101","Winner Match 102","MET",FN,104)

def utc_of(m):
    return datetime(2026,m["mo"],m["d"],m["h"],m["mi"]) + timedelta(hours=4)  # ET->UTC

# ----------------------------------------------------------------------------
# PROVIDERS  -> each returns {seq: {home,away,home_score,away_score,status}}
# Only fields that are known need be present. Assignment to scaffold slots is
# by nearest kickoff time, disambiguated by venue then by team-name overlap.
# ----------------------------------------------------------------------------
def _assign(fixtures, log):
    """fixtures: list of dicts with utc(datetime), home, away, hs, as, status, city(optional)."""
    out={}
    for fx in fixtures:
        best=None;best_score=-1
        for m in S:
            mu=utc_of(m)
            dt=abs((mu-fx["utc"]).total_seconds())/60.0
            if dt>180: continue                      # must be same kickoff window
            sc=100-dt                                 # closer time = better
            if fx.get("city") and fx["city"].lower() in V[m["vk"]][1].lower():
                sc+=200                                # venue/city match is decisive
            # team-name overlap (helps disambiguate simultaneous group games)
            names={canon(fx.get("home")),canon(fx.get("away"))}-{None}
            if names & {m["home"],m["away"]}: sc+=120
            if sc>best_score: best_score=sc;best=m
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
        if ov: out[best["seq"]]=ov
    return out

def provider_none(args, log):
    return {}

def provider_footballdata(args, log):
    if not args.token:
        sys.exit("football-data provider needs --token (free key from football-data.org).")
    url="https://api.football-data.org/v4/competitions/WC/matches"
    req=urllib.request.Request(url, headers={"X-Auth-Token":args.token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data=json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"football-data error {e.code}: {e.read().decode()[:200]}")
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
    log.append(f"  football-data: {len(fx)} fixtures fetched")
    return _assign(fx, log)

def provider_manual(args, log):
    if not args.overrides: sys.exit("manual provider needs --overrides PATH")
    raw=json.load(open(args.overrides,encoding="utf-8"))
    # keyed by official match number (str/int) or "YYYY-MM-DD@City"
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
    log.append(f"  manual: {len(out)} overrides applied")
    return out

PROVIDERS={"none":provider_none,"footballdata":provider_footballdata,"manual":provider_manual}

# ----------------------------------------------------------------------------
# ICS BUILD
# ----------------------------------------------------------------------------
def esc(s): return s.replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")
def fmt12(h,mi):
    ap="AM" if h<12 else "PM";hh=h%12 or 12;return f"{hh}:{mi:02d} {ap}"
def fold(line):
    b=line.encode("utf-8")
    if len(b)<=73: return line
    out=[];start=0;limit=73
    while start<len(b):
        end=min(start+limit,len(b))
        while end<len(b) and (b[end]&0xC0)==0x80: end-=1
        out.append(b[start:end].decode("utf-8"));start=end;limit=72
    return "\r\n ".join(out)

def build(overrides):
    now=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//WC2026 Dynamic Feed//EN",
       "CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:FIFA World Cup 2026",
       "X-WR-CALDESC:All 104 matches\\, auto-updating as knockout teams are confirmed.",
       "X-WR-TIMEZONE:America/New_York","REFRESH-INTERVAL;VALUE=DURATION:PT12H",
       "X-PUBLISHED-TTL:PT12H"]
    for m in S:
        name,city,country,cap,fifaname,lat,lon,off=V[m["vk"]]
        ov=overrides.get(m["seq"],{})
        home=ov.get("home",m["home"]); away=ov.get("away",m["away"])
        utc=utc_of(m); dtstart=utc.strftime("%Y%m%dT%H%M%SZ")
        dtend=(utc+timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
        et=fmt12(m["h"],m["mi"])
        loc_dt=datetime(2026,m["mo"],m["d"],m["h"],m["mi"])+timedelta(hours=off)
        local=fmt12(loc_dt.hour,loc_dt.minute)
        # score string if finished
        hs,as_=ov.get("home_score"),ov.get("away_score")
        score=f" ({hs}\u2013{as_})" if hs is not None and as_ is not None else ""
        fh,fa=F.get(home,""),F.get(away,"")
        if m["kind"]=="G":
            summary=f"{fh} {home} vs {fa} {away}{score}".strip()
            roundlabel=f"Group {m['grp']} \u00b7 Matchday {m['md']}"
            cats=f"FIFA World Cup 2026,Group Stage,Group {m['grp']}"
        else:
            lead=(fh+" " if fh else "")+home; trail=(fa+" " if fa else "")+away
            summary=f"{TROPHY} {m['rnd']}: {lead} vs {trail}{score} (Match {m['num']})"
            roundlabel=f"{m['rnd']} \u00b7 Match {m['num']}"
            cats=f"FIFA World Cup 2026,Knockouts,{m['rnd']}"
        timeline=(f"Kickoff: {et} ET (local)" if off==0
                  else f"Kickoff: {local} local ({city}) / {et} ET")
        desc=(f"{roundlabel}\\n{timeline}\\nVenue: {esc(name)} ({esc(fifaname)})\\n"
              f"City: {esc(city)}\\, {esc(country)}\\nCapacity: {cap}\\n"
              f"US broadcast: FOX (English)\\, Telemundo/Universo (Spanish) \u00b7 stream Peacock/Fubo")
        L+= ["BEGIN:VEVENT", fold(f"UID:wc2026-{m['seq']:03d}-{m['vk']}@worldcup2026"),
             f"DTSTAMP:{now}", f"DTSTART:{dtstart}", f"DTEND:{dtend}",
             fold("SUMMARY:"+esc(summary)), fold("LOCATION:"+esc(f"{name}, {city}, {country}")),
             fold("DESCRIPTION:"+desc), fold("CATEGORIES:"+cats),
             f"GEO:{lat};{lon}", "STATUS:CONFIRMED", "TRANSP:OPAQUE", "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(L)+"\r\n"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--provider",choices=PROVIDERS,default="none")
    ap.add_argument("--token",help="football-data.org API token")
    ap.add_argument("--overrides",help="overrides.json for manual provider")
    ap.add_argument("--out",default="fifa-world-cup-2026.ics")
    args=ap.parse_args()
    log=[]
    overrides=PROVIDERS[args.provider](args,log)
    ics=build(overrides)
    open(args.out,"w",encoding="utf-8").write(ics)
    resolved=sum(1 for m in S if m["seq"] in overrides and ("home" in overrides[m["seq"]] or "away" in overrides[m["seq"]]))
    print(f"provider={args.provider}  events=104  team-overrides={resolved}  -> {args.out}")
    for line in log: print(line)

if __name__=="__main__":
    main()
