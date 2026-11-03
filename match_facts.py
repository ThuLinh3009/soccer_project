"""Facts that can be commented on when nothing happens on the pitch (the "no event" flow).

Every fact has a time window (valid_from / valid_until, as (half, second) tuples) so a fact
is never used before it is known: the live score, cards and substitutions come from the
lineup "facts" of Labels-caption.json and only become valid after the minute they happened.
The final "score" field of the label file is never used.
"""
import json
import os
import re
from datetime import datetime
from itertools import zip_longest

from football_data import LeagueHistory, match_team

LEAGUES = {
    "england_epl": "Premier League",
    "spain_laliga": "La Liga",
    "italy_serie-a": "Serie A",
    "germany_bundesliga": "Bundesliga",
    "france_ligue-1": "Ligue 1",
    "europe_uefa-champions-league": "Champions League",
}
KICKOFF = (1, 0)
REPEAT_SCORE = 10 * 60
FACT_TYPES = {"1": "yellow", "2": "red", "3": "goal", "4": "own_goal", "6": "sub_out", "7": "sub_in", "8": "assist"}
MINUTE_RE = re.compile(r"(\d+)(?:\+(\d+))?'")


def minute_to_time(minute_str):
    """"30'" -> (1, 1800), "90+5'" -> (2, 3000): the end of that minute, when the event is surely over."""
    m = MINUTE_RE.search(minute_str)
    if m is None:
        return None
    base, extra = int(m.group(1)), int(m.group(2) or 0)
    if base <= 45:
        return 1, (base + extra) * 60
    return 2, (base - 45 + extra) * 60


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def minute_phrase(minute):
    """"30" -> "in the 30th minute", "90+5" -> "in the 5th minute of stoppage time"."""
    if "+" in minute:
        return f"in the {ordinal(int(minute.split('+')[1]))} minute of stoppage time"
    return f"in the {ordinal(int(minute))} minute"


def name_list(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def player_name(p):
    return p.get("long_name") or p.get("name")


def outfield_shape(tactic):
    """"1-4-1-4-1" -> "4-1-4-1" (the leading 1 is the goalkeeper)."""
    parts = tactic.split("-")
    return "-".join(parts[1:]) if parts and parts[0] == "1" else tactic


class Fact:
    def __init__(self, topic, text, priority, valid_from=KICKOFF, valid_until=None, repeat_every=None, repeat_text=None):
        self.topic = topic
        self.text = text
        self.priority = priority
        self.valid_from = valid_from
        self.valid_until = valid_until
        # seconds after which the fact may be said again (e.g. the score), with repeat_text from then on
        self.repeat_every = repeat_every
        self.repeat_text = repeat_text or text

    def valid_at(self, t):
        return self.valid_from <= t and (self.valid_until is None or t < self.valid_until)


def _game_date(game):
    m = re.match(r"(\d{4}-\d{2}-\d{2}) - (\d{2})-(\d{2})", game.split("/")[-1])
    return datetime.strptime(m.group(1), "%Y-%m-%d") if m else None


def match_events(labels):
    """Goals, cards and substitutions from the lineup facts, sorted by time."""
    events = []
    names = {p["hash"]: player_name(p) for side in ("home", "away") for p in labels["lineup"][side]["players"]}
    for side in ("home", "away"):
        team = labels[side]["name"]
        for p in labels["lineup"][side]["players"]:
            for f in p["facts"]:
                kind = FACT_TYPES.get(f["type"])
                when = minute_to_time(f["time"])
                if kind is None or when is None:
                    continue
                minute = MINUTE_RE.search(f["time"]).group(0).rstrip("'")
                events.append({"kind": kind, "time": when, "minute": minute, "side": side,
                               "team": team, "player": player_name(p),
                               "other": names.get(f.get("linked_player_hash"), f.get("description", ""))})
    return sorted(events, key=lambda e: e["time"])


def soccernet_facts(game, labels):
    league_folder, season, _ = game.split("/")
    league = LEAGUES.get(league_folder, league_folder)
    home, away = labels["home"]["name"], labels["away"]["name"]
    venue = (labels.get("venue") or [""])[0]
    referee = (labels.get("referee_matched") or labels.get("referee") or [""])[0]
    attendance = (labels.get("attendance") or [""])[0].replace(" ", ",")
    coaches = labels.get("coach_matched") or []
    lineup = labels["lineup"]
    first_half_end = (1, 15 * 60)
    facts = []

    intro = f"Welcome to {venue} for this {league} game between {home} and {away}" if venue \
        else f"Welcome to this {league} game between {home} and {away}"
    if labels.get("round"):
        intro += f", round {labels['round']} of the {season} season"
    facts.append(Fact("intro", intro + ".", 100, valid_until=first_half_end))
    if referee:
        facts.append(Fact("referee", f"{referee} is the man in the middle today.", 60))
    if attendance:
        facts.append(Fact("attendance", f"The attendance today is {attendance}.", 55))

    if len(coaches) == 2:
        facts.append(Fact("coaches", f"It is {coaches[0]}'s {home} against {coaches[1]}'s {away} today.", 70))
    player_facts = []
    for side, team in (("home", home), ("away", away)):
        tactic = lineup[side].get("tactic")
        if tactic:
            facts.append(Fact("tactic", f"{team} are set up in a {outfield_shape(tactic)} formation.", 65))
        starters = sorted((p for p in lineup[side]["players"] if p["starting"]), key=lambda p: p["lineup"] or 99)
        bench = [p for p in lineup[side]["players"] if not p["starting"]]
        if starters:
            keeper, outfield = starters[0], starters[1:]
            facts.append(Fact("lineup", f"{team} line up with {player_name(keeper)} in goal, and "
                                        f"{name_list([player_name(p) for p in outfield])} in front of him.", 75))
        for p in starters:
            if p.get("captain"):
                facts.append(Fact("captain", f"{player_name(p)} wears the captain's armband for {team}.", 62))
        if bench:
            facts.append(Fact("bench", f"On the {team} bench: {name_list([player_name(p) for p in bench])}.", 40))
        player_facts.append([Fact("player", f"{player_name(p)}, number {p['shirt_number']} for {team}, "
                                            f"is from {p['country']}.", 20)
                             for p in starters[1:] if p.get("country") and p.get("shirt_number")])
    # alternate home and away players
    for pair in zip_longest(*player_facts):
        facts += [f for f in pair if f is not None]

    # live state: only valid after it happened
    score = {"home": 0, "away": 0}
    goal_facts = [Fact("score", f"Still goalless here between {home} and {away}.", 30,
                       valid_from=(1, 10 * 60), repeat_every=REPEAT_SCORE)]
    for e in match_events(labels):
        t = e["time"]
        if e["kind"] in ("goal", "own_goal"):
            scoring_side = e["side"] if e["kind"] == "goal" else ("away" if e["side"] == "home" else "home")
            score[scoring_side] += 1
            how = f"{e['player']}'s goal" if e["kind"] == "goal" else f"an own goal by {e['player']}"
            goal_facts[-1].valid_until = t
            goal_facts.append(Fact("score", f"A reminder of the score: {home} {score['home']}, {away} {score['away']}, "
                                            f"after {how} {minute_phrase(e['minute'])}.", 90, valid_from=t,
                                   repeat_every=REPEAT_SCORE,
                                   repeat_text=f"The score remains {home} {score['home']}, {away} {score['away']}."))
        elif e["kind"] in ("yellow", "red"):
            colour = "a yellow card" if e["kind"] == "yellow" else "a red card"
            facts.append(Fact("card", f"{e['player']} ({e['team']}) has already seen {colour}, "
                                      f"{minute_phrase(e['minute'])}.", 50, valid_from=t))
        elif e["kind"] == "sub_in":
            facts.append(Fact("substitution", f"{e['player']} came on for {e['other']} for {e['team']} "
                                              f"{minute_phrase(e['minute'])}.", 45, valid_from=t))
    facts += goal_facts

    ht = {"home": 0, "away": 0}
    for e in match_events(labels):
        if e["time"][0] == 1 and e["kind"] in ("goal", "own_goal"):
            side = e["side"] if e["kind"] == "goal" else ("away" if e["side"] == "home" else "home")
            ht[side] += 1
    facts.append(Fact("half_time", f"At half-time it was {home} {ht['home']}, {away} {ht['away']}.", 95,
                      valid_from=(2, 0), valid_until=(2, 10 * 60)))
    return facts


def football_data_facts(game, labels, cache_dir):
    """Standings, form and head-to-head before the game date, from football-data.co.uk."""
    league_folder, season, _ = game.split("/")
    date = _game_date(game)
    history = LeagueHistory(league_folder, season, cache_dir)
    if not history.available or date is None:
        return []
    candidates = history.teams()
    home_name, away_name = labels["home"]["name"], labels["away"]["name"]
    home = match_team(labels["home"].get("names", []) + [home_name], candidates)
    away = match_team(labels["away"].get("names", []) + [away_name], candidates)
    if home is None or away is None:
        print(f"football-data: could not match teams for {game}: {home_name} -> {home}, {away_name} -> {away}")
        return []
    facts = []

    table = history.standings(before=date)
    rh, ra = table[home], table[away]
    if rh["played"] and ra["played"]:
        facts.append(Fact("standings", f"Before kick-off, {home_name} were {ordinal(rh['position'])} in the table "
                                       f"with {rh['points']} points from {rh['played']} games, and {away_name} "
                                       f"{ordinal(ra['position'])} with {ra['points']} points.", 85))
        for name, r in ((home_name, rh), (away_name, ra)):
            facts.append(Fact("season_goals", f"{name} have scored {r['gf']} and conceded {r['ga']} "
                                              f"in {r['played']} league games this season.", 35))

    for name, team in ((home_name, home), (away_name, away)):
        form = history.form(team, before=date)
        if len(form) >= 3:
            results = " ".join(g["result"] for g in form)
            last = form[-1]
            verb = {"W": "beat", "D": "drew with", "L": "lost to"}[last["result"]]
            place = "at home" if last["home"] else "away from home"
            facts.append(Fact("form", f"{name}'s last {len(form)} league results: {results}. Most recently they "
                                      f"{verb} {last['opponent']} {last['gf']}-{last['ga']} {place}.", 80))

    h2h = history.head_to_head(home, away, before=date)
    if h2h:
        wins = {home: 0, away: 0}
        for m in h2h:
            if m["hg"] != m["ag"]:
                wins[m["home"] if m["hg"] > m["ag"] else m["away"]] += 1
        draws = len(h2h) - wins[home] - wins[away]
        last = h2h[-1]
        facts.append(Fact("head_to_head", f"In their last {len(h2h)} league meetings, {home_name} won {wins[home]}, "
                                          f"{away_name} won {wins[away]}, and {draws} ended level. The last one, on "
                                          f"{last['date']:%d %B %Y}, finished {last['home']} {last['hg']}-{last['ag']} "
                                          f"{last['away']}.", 88))
    return facts


def build_facts(soccernet_path, game, labels_file="Labels-caption.json", cache_dir="metadata/football-data", crawl=True):
    labels = json.load(open(os.path.join(soccernet_path, game, labels_file)))
    facts = soccernet_facts(game, labels)
    if crawl:
        try:
            facts += football_data_facts(game, labels, cache_dir)
        except Exception as e:
            print(f"football-data: skipped for {game}: {e}")
    return labels, facts
