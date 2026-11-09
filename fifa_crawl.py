"""Crawl match metadata from FIFA (the public JSON API behind www.fifa.com) into CSV files for the
"no event" / INFO commentary flow.

Input : season (e.g. 2023 or 2023/2024), team A, team B (club or national team)
Output: one folder per match between A and B in that season, with
    match_info.csv        competition, stage, date, stadium, city, attendance, referee, score, possession...
    lineups.csv           both teams: shirt number, name, position, starter/substitute, captain
    staff.csv             coaches and match officials
    events.csv            minute-by-minute timeline (goals, cards, substitutions, shots, fouls...) with half/second
    standings_before.csv  table of the stage computed from the matches played BEFORE kick-off
    form.csv              last 5 results of each team before the match (all competitions)
    head_to_head.csv      previous meetings of the two teams
    facts.csv             ready-to-say sentences with priority and the time from which each may be said
    raw/*.json            the API answers, for checking

Usage (terminal):
    python fifa_crawl.py                                   # asks for season and teams
    python fifa_crawl.py --season 2023 --team_a Arsenal --team_b Liverpool
    python fifa_crawl.py --season 2022 --team_a Argentina --team_b France --competition "World Cup"

Season: "2023/2024" or "2023" = the 2023/2024 club season; for national-team tournaments named with one
year (World Cup 2022) "2022" = that year. Coverage depends on FIFA: e.g. the Premier League starts in 2020/2021.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API = "https://api.fifa.com/api/v3"
USER_AGENT = "Mozilla/5.0 (research crawler)"
POSITIONS = {0: "GK", 1: "DF", 2: "MF", 3: "FW"}
# period code -> (half number, minute at which that period starts)
PERIODS = {3: (1, 0), 5: (2, 45), 7: (3, 90), 9: (4, 105), 11: (5, 120)}
MINUTE_RE = re.compile(r"(\d+)'?\s*(?:\+\s*(\d+))?")
FIELD_STATUS_STARTER = 1


# ----------------------------------------------------------------------------- API
def get(path, **params):
    params.setdefault("language", "en")
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            time.sleep(0.2)  # be polite
            return json.loads(body) if body.strip() not in ("", "null") else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))


def txt(localized):
    """[{"Locale": "en-gb", "Description": "Arsenal"}] -> "Arsenal"."""
    return localized[0]["Description"] if localized else ""


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def pretty(name):
    """'Virgil VAN DIJK' -> 'Virgil Van Dijk', 'Trent ALEXANDER-ARNOLD' -> 'Trent Alexander-Arnold'."""
    return " ".join(w.title() if w.isupper() and len(w) > 1 else w for w in (name or "").split())


def minute_phrase(minute):
    """"38'" -> "in the 38th minute", "45'+3'" -> "in the 3rd minute of stoppage time"."""
    m = MINUTE_RE.search(minute or "")
    if m is None:
        return ""
    base, extra = int(m.group(1)), m.group(2)
    if extra:
        return f"in the {ordinal(int(extra))} minute of stoppage time"
    return f"in the {ordinal(base)} minute"


def team_name(t):
    return txt(t.get("TeamName") or t.get("Name")) or t.get("ShortClubName") or ""


# ----------------------------------------------------------------------------- inputs
def find_team(name, women=False):
    res = (get("teams/search", name=name, count=50) or {}).get("Results", [])
    if not res:
        sys.exit(f"Không tìm thấy đội '{name}' trên FIFA")
    q, gender = name.strip().lower(), 2 if women else 1

    def rank(t):
        names = {txt(t["Name"]).lower(), (t.get("ShortClubName") or "").lower()}
        return (t.get("Gender") == gender, t.get("AgeType") in (4, 7), q in names,
                t.get("FoundationYear") is not None, -len(txt(t["Name"])))
    best = max(res, key=rank)
    return {"id": best["IdTeam"], "name": txt(best["Name"]), "country": best.get("IdCountry"),
            "founded": best.get("FoundationYear"), "city": best.get("City")}


def parse_season(s):
    years = re.findall(r"\d{4}|\d{2}", s)
    if not years or len(years[0]) != 4:
        sys.exit(f"Season không hợp lệ: '{s}' (ví dụ 2023 hoặc 2023/2024)")
    return int(years[0])


def season_matches(season_name, year):
    """'Premier League 2023/2024' or 'FIFA World Cup Qatar 2022': is it the season starting in `year`?"""
    years = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", season_name)]
    return bool(years) and years[0] == year


def team_matches(team_id, start, end):
    """All matches of a team between two dates (any competition), in 2-year windows."""
    out, a = {}, start
    while a < end:
        b = min(a + timedelta(days=730), end)
        for m in (get("calendar/matches", idTeam=team_id, **{"from": iso(a), "to": iso(b)}, count=500) or {}).get("Results", []):
            out[m["IdMatch"]] = m
        a = b
    return sorted(out.values(), key=lambda m: m["Date"])


def finished(m):
    return m.get("HomeTeamScore") is not None and m.get("AwayTeamScore") is not None and m.get("Home") and m.get("Away")


# ----------------------------------------------------------------------------- time helpers
def event_time(minute, period=None):
    """("61'", 5) -> (2, 960): half number and seconds since the start of that half."""
    m = MINUTE_RE.search(minute or "")
    if m is None:
        return None
    base, extra = int(m.group(1)), int(m.group(2) or 0)
    if period in PERIODS:
        half, start = PERIODS[period]
    else:
        half, start = (1, 0) if base <= 45 else (2, 45)
    return half, max(base - start + extra, 0) * 60


def game_time(t):
    return f"{t[0]} - {t[1] // 60:02d}:{t[1] % 60:02d}" if t else ""


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def name_list(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ----------------------------------------------------------------------------- tables
def standings_before(stage_matches, kickoff, group):
    table = defaultdict(lambda: {"team": "", "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0})
    for m in stage_matches:
        if not finished(m) or parse_date(m["Date"]) >= kickoff or m.get("IdGroup") != group:
            continue
        hs, as_ = m["HomeTeamScore"], m["AwayTeamScore"]
        for side, gf, ga in (("Home", hs, as_), ("Away", as_, hs)):
            r = table[m[side]["IdTeam"]]
            r["team"] = team_name(m[side])
            r["P"] += 1
            r["GF"] += gf
            r["GA"] += ga
            r["W" if gf > ga else "D" if gf == ga else "L"] += 1
    rows = []
    for tid, r in table.items():
        rows.append({"id_team": tid, **r, "GD": r["GF"] - r["GA"], "Pts": 3 * r["W"] + r["D"]})
    rows.sort(key=lambda r: (-r["Pts"], -r["GD"], -r["GF"], r["team"]))
    for i, r in enumerate(rows, 1):
        r["position"] = i
    return rows


def result_row(m, team_id):
    home = m["Home"]["IdTeam"] == team_id
    gf, ga = (m["HomeTeamScore"], m["AwayTeamScore"]) if home else (m["AwayTeamScore"], m["HomeTeamScore"])
    opp = m["Away"] if home else m["Home"]
    return {"date": m["Date"][:10], "competition": txt(m["CompetitionName"]), "season": txt(m["SeasonName"]),
            "venue": "home" if home else "away", "opponent": team_name(opp), "goals_for": gf, "goals_against": ga,
            "result": "W" if gf > ga else "D" if gf == ga else "L", "id_match": m["IdMatch"]}


def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0].keys()) if rows else ["empty"])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ----------------------------------------------------------------------------- one match
def crawl_match(m, args):
    ids = "/".join([m["IdCompetition"], m["IdSeason"], m["IdStage"], m["IdMatch"]])
    live = get(f"live/football/{ids}") or {}
    timeline = (get(f"timelines/{ids}") or {}).get("Event", []) or []
    stage = (get("calendar/matches", idCompetition=m["IdCompetition"], idSeason=m["IdSeason"], count=500) or {}).get("Results", [])
    kickoff = parse_date(m["Date"])
    home_t, away_t = live.get("HomeTeam") or m["Home"], live.get("AwayTeam") or m["Away"]
    home, away = team_name(home_t), team_name(away_t)
    competition, season = txt(m["CompetitionName"]), txt(m["SeasonName"])
    folder = f"{m['Date'][:10]} - {home} {m.get('HomeTeamScore', '')} - {m.get('AwayTeamScore', '')} {away}"
    out = os.path.join(args.out, re.sub(r'[<>:"/\\|?*]', "_", folder))
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    for name, data in (("match", m), ("live", live), ("timeline", timeline)):
        json.dump(data, open(os.path.join(out, "raw", f"{name}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # --- people
    players, names = [], {}
    for side, t in (("home", home_t), ("away", away_t)):
        for p in t.get("Players") or []:
            names[p["IdPlayer"]] = pretty(txt(p["PlayerName"]))
            players.append({"side": side, "team": team_name(t), "shirt_number": p.get("ShirtNumber"),
                            "name": pretty(txt(p["PlayerName"])), "name_fifa": txt(p["PlayerName"]),
                            "short_name": txt(p.get("ShortName")),
                            "position": POSITIONS.get(p.get("Position"), ""), "position_code": p.get("Position"),
                            "role": "starter" if p.get("Status") == FIELD_STATUS_STARTER else "substitute",
                            "captain": bool(p.get("Captain")), "id_player": p["IdPlayer"]})
    staff = [{"side": side, "team": team_name(t), "role": {0: "head_coach", 1: "assistant_coach"}.get(c.get("Role"), f"coach_role_{c.get('Role')}"),
              "name": pretty(txt(c["Name"])), "country": c.get("IdCountry")}
             for side, t in (("home", home_t), ("away", away_t)) for c in t.get("Coaches") or []]
    staff += [{"side": "", "team": "", "role": txt(o.get("TypeLocalized")), "name": pretty(txt(o["Name"])), "country": o.get("IdCountry")}
              for o in live.get("Officials") or m.get("Officials") or []]

    # --- timeline
    events = []
    for e in timeline:
        t = event_time(e.get("MatchMinute"), e.get("Period"))
        events.append({"game_time": game_time(t), "half": t[0] if t else "", "second": t[1] if t else "",
                       "minute": e.get("MatchMinute"), "period": e.get("Period"), "type": e.get("Type"),
                       "type_name": txt(e.get("TypeLocalized")), "team": team_name(home_t) if e.get("IdTeam") == home_t.get("IdTeam")
                       else team_name(away_t) if e.get("IdTeam") == away_t.get("IdTeam") else "",
                       "player": names.get(e.get("IdPlayer"), ""), "home_goals": e.get("HomeGoals"),
                       "away_goals": e.get("AwayGoals"), "description": txt(e.get("EventDescription")),
                       "player_off": names.get(e.get("IdSubPlayer"), "") if e.get("Type") == 5 else "",
                       "_time": t, "_type": e.get("Type"), "_id_team": e.get("IdTeam")})

    # --- context before kick-off
    table = standings_before([s for s in stage if s["IdStage"] == m["IdStage"]], kickoff, m.get("IdGroup"))
    form = {}
    for t in (home_t, away_t):
        past = [x for x in team_matches(t["IdTeam"], kickoff - timedelta(days=365), kickoff)
                if finished(x) and parse_date(x["Date"]) < kickoff]
        form[t["IdTeam"]] = [result_row(x, t["IdTeam"]) for x in past[-args.form:]]
    h2h = [result_row(x, home_t["IdTeam"]) for x in team_matches(home_t["IdTeam"], kickoff - timedelta(days=365 * args.h2h_years), kickoff)
           if finished(x) and parse_date(x["Date"]) < kickoff and away_t["IdTeam"] in (x["Home"]["IdTeam"], x["Away"]["IdTeam"])]

    # --- match info
    stadium = live.get("Stadium") or m.get("Stadium") or {}
    referee = next((pretty(txt(o["Name"])) for o in live.get("Officials") or m.get("Officials") or [] if o.get("OfficialType") == 1), "")
    ht = next(((e["home_goals"], e["away_goals"]) for e in events if e["_type"] == 8 and e["period"] == 3), None)
    poss = live.get("BallPossession") or m.get("BallPossession") or {}
    weather = live.get("Weather") or m.get("Weather") or {}
    info = {"id_match": m["IdMatch"], "competition": competition, "season": season, "stage": txt(m.get("StageName")),
            "group": txt(m.get("GroupName")), "matchday": m.get("MatchDay"), "date_utc": m["Date"], "date_local": m.get("LocalDate"),
            "stadium": txt(stadium.get("Name")), "city": txt(stadium.get("CityName")), "country": stadium.get("IdCountry"),
            "capacity": stadium.get("Capacity"), "stadium_built": (stadium.get("Built") or "")[:4],
            "attendance": live.get("Attendance") or m.get("Attendance"), "referee": referee,
            "home_team": home, "away_team": away, "home_tactics": home_t.get("Tactics"), "away_tactics": away_t.get("Tactics"),
            "home_score": m.get("HomeTeamScore"), "away_score": m.get("AwayTeamScore"),
            "half_time_score": f"{ht[0]}-{ht[1]}" if ht else "",
            "home_penalties": m.get("HomeTeamPenaltyScore"), "away_penalties": m.get("AwayTeamPenaltyScore"),
            "home_possession": poss.get("OverallHome"), "away_possession": poss.get("OverallAway"),
            "temperature": weather.get("Temperature") if isinstance(weather, dict) else "",
            "humidity": weather.get("Humidity") if isinstance(weather, dict) else "",
            "weather": txt(weather.get("TypeLocalized")) if isinstance(weather, dict) else ""}

    facts = build_facts(info, players, staff, events, table, form, h2h, home_t, away_t)

    write_csv(os.path.join(out, "match_info.csv"), [{"field": k, "value": v} for k, v in info.items()])
    write_csv(os.path.join(out, "lineups.csv"), players)
    write_csv(os.path.join(out, "staff.csv"), staff)
    write_csv(os.path.join(out, "events.csv"), [{k: v for k, v in e.items() if not k.startswith("_")} for e in events])
    write_csv(os.path.join(out, "standings_before.csv"), table,
              ["position", "team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts", "id_team"])
    write_csv(os.path.join(out, "form.csv"), [{"team": team_name(t), **r} for t in (home_t, away_t) for r in form[t["IdTeam"]]])
    write_csv(os.path.join(out, "head_to_head.csv"), [{"team": home, **r} for r in h2h])
    write_csv(os.path.join(out, "facts.csv"), facts)
    print(f"  {len(players)} cầu thủ, {len(events)} sự kiện, bảng xếp hạng {len(table)} đội, "
          f"đối đầu {len(h2h)} trận, {len(facts)} câu -> {out}")
    return out


# ----------------------------------------------------------------------------- facts for the INFO flow
def fact(topic, text, priority, valid_from=(1, 0), valid_until=None, live=False, repeat_every="", repeat_text=""):
    return {"topic": topic, "priority": priority, "live": live,
            "valid_from": game_time(valid_from), "valid_from_half": valid_from[0], "valid_from_second": valid_from[1],
            "valid_until": game_time(valid_until), "valid_until_half": valid_until[0] if valid_until else "",
            "valid_until_second": valid_until[1] if valid_until else "",
            "repeat_every": repeat_every, "text": text, "repeat_text": repeat_text or text}


def build_facts(info, players, staff, events, table, form, h2h, home_t, away_t):
    home, away = info["home_team"], info["away_team"]
    second_half = (2, 0)
    f = []
    where = f"{info['stadium']} ({info['city']})" if info["city"] else info["stadium"]
    league_stage = info["stage"] in ("", "Regular Season") or info["stage"].lower().startswith("group")
    if info["group"]:
        stage = f", {info['group']}"
    elif league_stage and info["matchday"]:
        stage = f", matchday {info['matchday']}"
    else:
        stage = f", {info['stage']}" if info["stage"] else ""
    f.append(fact("intro", f"Welcome to {where} for this {info['competition']} match between {home} and {away}{stage}, "
                  f"{info['season']}.", 100, valid_until=second_half))
    if info["referee"]:
        f.append(fact("referee", f"{info['referee']} is the referee today.", 60))
    if info["attendance"]:
        f.append(fact("attendance", f"The attendance today is {int(info['attendance']):,}.", 55))
    if info["capacity"] and info["stadium_built"]:
        f.append(fact("stadium", f"{info['stadium']}, built in {info['stadium_built']}, holds {int(info['capacity']):,} people.", 45))
    if info["temperature"]:
        f.append(fact("weather", f"It is {info['temperature']} degrees here{', ' + info['weather'].lower() if info['weather'] else ''}.", 45))
    coaches = {s["side"]: s["name"] for s in staff if s["role"] == "head_coach"}
    if len(coaches) == 2:
        f.append(fact("coaches", f"It is {coaches['home']}'s {home} against {coaches['away']}'s {away} today.", 70))
    for side, t, tactic in (("home", home, info["home_tactics"]), ("away", away, info["away_tactics"])):
        if tactic:
            f.append(fact("tactic", f"{t} are set up in a {tactic} formation.", 65))
        team_players = [p for p in players if p["side"] == side]
        starters = [p for p in team_players if p["role"] == "starter"]
        keeper = next((p for p in starters if p["position"] == "GK"), None)
        if keeper and len(starters) > 1:
            f.append(fact("lineup", f"{t} line up with {keeper['name']} in goal, and "
                          f"{name_list([p['name'] for p in starters if p is not keeper])} in front of him.", 64))
        for p in starters:
            if p["captain"]:
                f.append(fact("captain", f"{p['name']} wears the captain's armband for {t}.", 62))
        bench = [p["name"] for p in team_players if p["role"] == "substitute"]
        if bench:
            f.append(fact("bench", f"On the {t} bench: {name_list(bench)}.", 40))
        for p in starters:
            if p["shirt_number"] is not None:
                f.append(fact("player", f"{p['name']} wears number {p['shirt_number']} for {t}.", 35))

    # before kick-off: table, form, head-to-head
    pos = {r["id_team"]: r for r in table}
    rh, ra = pos.get(home_t.get("IdTeam")), pos.get(away_t.get("IdTeam"))
    if rh and ra:
        f.append(fact("standings", f"Before kick-off, {home} were {ordinal(rh['position'])} in the table with {rh['Pts']} points "
                      f"from {rh['P']} games, and {away} {ordinal(ra['position'])} with {ra['Pts']} points.", 75))
        for name, r in ((home, rh), (away, ra)):
            f.append(fact("season_goals", f"{name} have scored {r['GF']} and conceded {r['GA']} in {r['P']} games of this "
                          f"competition so far.", 45))
    for t in (home_t, away_t):
        rows = form.get(t.get("IdTeam")) or []
        if rows:
            last = rows[-1]
            verb = {"W": "beat", "D": "drew with", "L": "lost to"}[last["result"]]
            f.append(fact("form", f"{team_name(t)}'s last {len(rows)} results: {' '.join(r['result'] for r in rows)}. Most recently they "
                          f"{verb} {last['opponent']} {last['goals_for']}-{last['goals_against']} ({last['competition']}).", 58))
    if h2h:
        w = sum(r["result"] == "W" for r in h2h)
        d = sum(r["result"] == "D" for r in h2h)
        last = h2h[-1]
        result = f"{home} {last['goals_for']}-{last['goals_against']} {away}"
        if len(h2h) == 1:
            text = f"These two teams last met on {last['date']} ({last['competition']}): it finished {result}."
        else:
            text = (f"In their last {len(h2h)} meetings, {home} won {w}, {away} won {len(h2h) - w - d}, and {d} ended level. "
                    f"The last one, on {last['date']}, finished {result}.")
        f.append(fact("head_to_head", text, 68))

    # live: goals, cards, substitutions, score and half-time, only valid from the minute they happen
    # a goal = the first event where the running score changes (normal goals, penalties, own goals);
    # the penalty shoot-out does not change it
    score, since = (0, 0), (1, 0)
    for e in events:
        new = (e["home_goals"] or 0, e["away_goals"] or 0)
        if not e["_time"] or new == score or e["period"] == 11:
            continue
        f.append(fact("score", score_text(home, away, score), 30, valid_from=since, valid_until=e["_time"], repeat_every=600))
        scorer_side = home if new[0] > score[0] else away
        score, since = new, e["_time"]
        kind = e["type_name"].lower()
        if "own" in kind and e["player"]:
            who = f"an own goal by {e['player']} ({e['team']}) gives {scorer_side} a goal"
        elif e["player"]:
            who = f"{e['player']} scores for {scorer_side}" + (" from the penalty spot" if "penalty" in kind else "")
        else:
            who = f"{scorer_side} score"
        f.append(fact("goal", f"Goal! {who[0].upper() + who[1:]} {minute_phrase(e['minute'])}. "
                      f"{home} {score[0]}, {away} {score[1]}.", 98, valid_from=e["_time"], live=True))
    f.append(fact("score", score_text(home, away, score), 30, valid_from=since, repeat_every=600))
    for e in events:
        if e["_time"] and ("card" in e["type_name"].lower() or "sent off" in e["description"].lower()):
            red = "red" in e["type_name"].lower() or "sent off" in e["description"].lower()
            text = (f"{e['player']} ({e['team']}) {'is sent off' if red else 'is shown a yellow card'} {minute_phrase(e['minute'])}."
                    if e["player"] else e["description"])
            f.append(fact("card", text, 85, valid_from=e["_time"], live=True))
    subs = defaultdict(list)
    for e in events:
        if e["_type"] == 5 and e["_time"]:
            subs[(e["_time"], e["_id_team"])].append(e)
    for (t, _), group in sorted(subs.items()):
        changes = [f"{g['player']} comes on for {g['player_off']}" if g["player"] and g["player_off"] else g["description"]
                   for g in group]
        label = {2: "Double change", 3: "Triple change"}.get(len(group), "Change")
        f.append(fact("substitution", f"{label} for {group[0]['team']} {minute_phrase(group[0]['minute'])}: {name_list(changes)}.", 88,
                      valid_from=t, live=True))
    ht = info["half_time_score"]
    if ht:
        h, a = ht.split("-")
        f.append(fact("half_time", f"At half-time it was {home} {h}, {away} {a}.", 95, valid_from=second_half, valid_until=(2, 600)))
    return sorted(f, key=lambda x: (x["valid_from_half"], x["valid_from_second"], -x["priority"]))


def score_text(home, away, score):
    if score == (0, 0):
        return f"Still goalless here between {home} and {away}."
    return f"The score is {home} {score[0]}, {away} {score[1]}."


# ----------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", help="ví dụ 2023 hoặc 2023/2024")
    p.add_argument("--team_a", help="đội bóng A, ví dụ Arsenal")
    p.add_argument("--team_b", help="đội bóng B, ví dụ Liverpool")
    p.add_argument("--competition", default=None, help="chỉ lấy giải có tên chứa chuỗi này, ví dụ 'Premier League'")
    p.add_argument("--match", type=int, default=None, help="chỉ lấy trận thứ N trong danh sách (mặc định: tất cả)")
    p.add_argument("--women", action="store_true", help="đội nữ")
    p.add_argument("--form", type=int, default=5, help="số trận gần nhất cho phong độ")
    p.add_argument("--h2h_years", type=int, default=10, help="số năm lấy lịch sử đối đầu")
    p.add_argument("--out", default="metadata/fifa", help="thư mục kết quả")
    args = p.parse_args()

    args.season = args.season or input("Season (năm, ví dụ 2023 hoặc 2023/2024): ").strip()
    args.team_a = args.team_a or input("Đội bóng A: ").strip()
    args.team_b = args.team_b or input("Đội bóng B: ").strip()
    year = parse_season(args.season)

    a, b = find_team(args.team_a, args.women), find_team(args.team_b, args.women)
    print(f"Đội A: {a['name']} (id {a['id']}, {a['country']}) | Đội B: {b['name']} (id {b['id']}, {b['country']})")
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    matches = [m for m in team_matches(a["id"], start, datetime(year + 1, 12, 31, tzinfo=timezone.utc))
               if m.get("Home") and m.get("Away") and b["id"] in (m["Home"]["IdTeam"], m["Away"]["IdTeam"])
               and season_matches(txt(m["SeasonName"]), year)
               and (not args.competition or args.competition.lower() in txt(m["CompetitionName"]).lower())]
    if not matches:
        sys.exit(f"Không có trận {a['name']} - {b['name']} trong mùa {args.season} trên FIFA "
                 f"(FIFA chỉ có dữ liệu một số giải/mùa, ví dụ Premier League từ 2020/2021).")
    print(f"{len(matches)} trận:")
    for i, m in enumerate(matches, 1):
        print(f"  [{i}] {m['Date'][:10]} {txt(m['CompetitionName'])} ({txt(m['SeasonName'])}): "
              f"{team_name(m['Home'])} {m.get('HomeTeamScore')} - {m.get('AwayTeamScore')} {team_name(m['Away'])}")
    chosen = [matches[args.match - 1]] if args.match else matches
    for m in chosen:
        print(f"Crawl {m['Date'][:10]} {team_name(m['Home'])} - {team_name(m['Away'])}")
        crawl_match(m, args)


if __name__ == "__main__":
    main()
